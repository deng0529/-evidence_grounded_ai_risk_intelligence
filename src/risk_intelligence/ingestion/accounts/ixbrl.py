"""Bounded deterministic inline-XBRL monetary extraction, without taxonomy guessing."""

from datetime import date
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import re
from xml.etree import ElementTree as ET

from risk_intelligence.domain.enums import AvailabilityStatus, ComparabilityStatus, ExtractionMethod, PeriodType
from risk_intelligence.domain.facts import ReportingPeriod
from risk_intelligence.ingestion.companies_house.client import ParseError
from .models import ExtractionResult, SourceFinancialFact

PARSER_VERSION = "ixbrl-monetary-v1"
INSTANCE = "http://www.xbrl.org/2003/instance"
INLINE = {"http://www.xbrl.org/2013/inlineXBRL", "http://www.xbrl.org/2008/inlineXBRL"}
ISO = "http://www.xbrl.org/2003/iso4217"
TRANSFORMS = {
    "{http://www.xbrl.org/inlineXBRL/transformation/2010-04-20}numcommadot",
    "{http://www.xbrl.org/inlineXBRL/transformation/2011-07-31}numcommadot",
    "{http://www.xbrl.org/inlineXBRL/transformation/2015-02-26}numdotdecimal",
    "{http://www.xbrl.org/inlineXBRL/transformation/2020-02-12}num-dot-decimal",
}


def _qname(value: str, namespaces: dict[str, str]) -> str:
    prefix, separator, local = value.partition(":")
    if not separator:
        local, prefix = prefix, ""
    if prefix not in namespaces or not local:
        raise ParseError("Unresolved financial QName")
    return "{" + namespaces[prefix] + "}" + local


def _tree(content: bytes) -> tuple[ET.Element, dict[ET.Element, dict[str, str]]]:
    if len(content) > 32 * 1024 * 1024 or b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ParseError("Unsupported XML declarations or document size")
    # UTF-16 declarations must not bypass the lexical DTD guard.
    if b"\x00" in content:
        raise ParseError("Only UTF-8 compatible XML input is supported")
    scopes: dict[ET.Element, dict[str, str]] = {}
    stack: list[dict[str, str]] = [{}]
    pending: dict[str, str] = {}
    try:
        parser = ET.iterparse(BytesIO(content), events=("start-ns", "start", "end"))
        for event, element in parser:
            if event == "start-ns":
                pending[element[0]] = element[1]
            elif event == "start":
                scope = stack[-1] | pending
                pending = {}
                stack.append(scope)
                scopes[element] = scope
                if len(stack) > 128 or len(scopes) > 200000:
                    raise ParseError("XML complexity bound exceeded")
            else:
                stack.pop()
        return parser.root, scopes
    except ET.ParseError:
        raise ParseError("Accounts representation is not valid XML") from None


def _required_text(parent: ET.Element, path: str) -> str:
    element = parent.find(path)
    if element is None or not element.text or not element.text.strip():
        raise ParseError("Financial context lacks required metadata")
    return element.text.strip()


def _period(context: ET.Element) -> ReportingPeriod:
    prefix = "{" + INSTANCE + "}"
    period = context.find(prefix + "period")
    if period is None:
        raise ParseError("Missing financial period")
    instant = period.find(prefix + "instant")
    try:
        if instant is not None:
            if len(period) != 1:
                raise ValueError()
            return ReportingPeriod(period_type=PeriodType.INSTANT,
                period_end=date.fromisoformat(_required_text(period, prefix + "instant")),
                comparability_status=ComparabilityStatus.REVIEW_REQUIRED)
        if len(period) != 2:
            raise ValueError()
        return ReportingPeriod(period_type=PeriodType.DURATION,
            period_start=date.fromisoformat(_required_text(period, prefix + "startDate")),
            period_end=date.fromisoformat(_required_text(period, prefix + "endDate")),
            comparability_status=ComparabilityStatus.REVIEW_REQUIRED)
    except ValueError:
        raise ParseError("Invalid reporting period") from None


def _number(raw: str, scale: int, sign: str, transform: str | None) -> Decimal:
    if not -18 <= scale <= 18 or sign not in ("+", "-"):
        raise ParseError("Unsupported sign or scale")
    if transform is not None and transform not in TRANSFORMS:
        raise ParseError("Unsupported numeric transformation")
    token = raw.strip()
    pattern = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?" if transform else r"[+-]?[0-9]+(?:\.[0-9]+)?"
    if not re.fullmatch(pattern, token) or len(token) > 100:
        raise ParseError("Unsupported monetary lexical value")
    value = Decimal(token.replace(",", ""))
    # Manipulate the Decimal tuple so ambient context cannot round exact source digits.
    negative, digits, exponent = value.as_tuple()
    if sign == "-":
        if negative:
            raise ParseError("Ambiguous double negative")
        negative = 1
    return Decimal((negative, digits, exponent + scale))


def extract_ixbrl(content: bytes, document_id: str, company_number: str) -> ExtractionResult:
    """Extract supported monetary occurrences from already verified evidence bytes.

    Unknown transformations or contexts fail closed for the document; callers
    may route to another representation. Unknown taxonomy concepts remain source
    facts for later controlled mapping rather than being guessed here.
    """
    root, scopes = _tree(content)
    prefix = "{" + INSTANCE + "}"
    contexts: dict[str, ET.Element] = {}
    units: dict[str, str] = {}
    for element in root.iter():
        if element.tag == prefix + "context":
            identity = element.get("id")
            if not identity or identity in contexts:
                raise ParseError("Missing or duplicate context identity")
            contexts[identity] = element
        elif element.tag == prefix + "unit":
            identity = element.get("id")
            if not identity or identity in units:
                raise ParseError("Missing or duplicate unit identity")
            measures = list(element)
            # Ratios and shares are outside monetary extraction, not guessed units.
            units[identity] = (_qname(measures[0].text or "", scopes[measures[0]])
                               if len(measures) == 1 and measures[0].tag == prefix + "measure" else "unsupported")
    periods = {identity: _period(context) for identity, context in contexts.items()}
    latest = max((period.period_end for period in periods.values()), default=None)
    facts: list[SourceFinancialFact] = []
    for index, element in enumerate(root.iter()):
        if element.tag not in {"{" + namespace + "}nonFraction" for namespace in INLINE}:
            continue
        context_id, unit_id = element.get("contextRef"), element.get("unitRef")
        if context_id not in contexts or unit_id not in units:
            raise ParseError("Unresolved fact context/unit")
        unit = units[unit_id]
        if not unit.startswith("{" + ISO + "}"):
            continue
        currency = unit.split("}", 1)[1]
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ParseError("Unsupported currency")
        context = contexts[context_id]
        identifier = context.find(prefix + "entity/" + prefix + "identifier")
        if identifier is None or not identifier.get("scheme"):
            raise ParseError("Missing entity identity")
        entity = (identifier.text or "").strip()
        if entity != company_number:
            raise ParseError("Document context does not match selected company")
        dimensions: list[tuple[str, str]] = []
        for member in context.iter():
            if member.tag == "{http://xbrl.org/2006/xbrldi}explicitMember":
                dimensions.append((_qname(member.get("dimension", ""), scopes[member]),
                                   _qname((member.text or "").strip(), scopes[member])))
            elif member.tag == "{http://xbrl.org/2006/xbrldi}typedMember":
                raise ParseError("Typed financial dimensions are unsupported")
        if element.get("continuedAt") or any(child.tag.split("}")[-1] == "exclude" for child in element.iter()):
            raise ParseError("Unsupported inline continuation/exclusion")
        raw = "".join(element.itertext()).strip()
        transform = _qname(element.get("format"), scopes[element]) if element.get("format") else None
        try:
            scale = int(element.get("scale", "0"))
        except ValueError:
            raise ParseError("Invalid monetary scale") from None
        sign = element.get("sign", "+")
        nil = element.get("{http://www.w3.org/2001/XMLSchema-instance}nil") in ("true", "1")
        if nil and raw:
            raise ParseError("Nil monetary fact must not also contain a value")
        value = None if nil else _number(raw, scale, sign, transform)
        identity = sha256(f"{document_id}:{PARSER_VERSION}:{index}".encode()).hexdigest()
        facts.append(SourceFinancialFact(
            source_fact_id=identity, document_id=document_id, evidence_id="e-" + identity,
            source_concept=_qname(element.get("name", ""), scopes[element]),
            raw_value=raw or None, value=value,
            availability_status=AvailabilityStatus.NOT_DISCLOSED if nil else AvailabilityStatus.AVAILABLE,
            currency=currency, unit=currency, unit_ref=unit_id, context_ref=context_id,
            entity_identifier=entity, entity_scheme=identifier.get("scheme"),
            dimensions=tuple(sorted(dimensions)), period=periods[context_id],
            period_role="CURRENT" if periods[context_id].period_end == latest else "COMPARATIVE",
            scale=scale, sign=sign, decimals=element.get("decimals"), precision=element.get("precision"),
            transformation=transform, extraction_method=ExtractionMethod.IXBRL_DIRECT,
            parser_version=PARSER_VERSION,
        ))
    if not facts:
        raise ParseError("No supported inline monetary facts; route to another representation")
    unique_periods = {fact.period.model_dump_json(): fact.period for fact in facts}
    return ExtractionResult(facts=tuple(facts), periods=tuple(unique_periods.values()), complete=True)
