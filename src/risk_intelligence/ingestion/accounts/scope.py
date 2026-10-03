"""Versioned source-heading classification, independent of financial admission."""

import re
from typing import Literal

SourceScope = Literal['COMPANY', 'GROUP', 'UNRESOLVED']
SCOPE_VERSION = 'pdf-heading-scope-v1'
SCOPE_PARSERS = frozenset(('pdf-table-v4', 'financial-statement-structure-v4', 'located-financial-admission-v4', 'located-financial-admission-v5',
                              'located-financial-admission-v6-year-column',
                              'located-financial-admission-final-three-v11',
                              'located-financial-admission-three-company-v18',
                              'located-financial-admission-three-company-v19',
                              'openai-pdf-semantic-v1',
                              'openai-pdf-semantic-v2-period-canonicalization',
                              'openai-pdf-semantic-v3-year-only-admission',
                              'openai-pdf-semantic-v30-closest-column'))
STATEMENT_HEADING = re.compile(
    r'(?:(company|group|consolidated) )?(?:balance sheet|statement of financial position)'
    r'(?:\s+as at .*)?', re.IGNORECASE)


def source_scope(statement_context: str | None, parser_version: str) -> SourceScope:
    """Classify one explicit heading; absent, competing or unknown context stays unresolved.

    Parser versions pin this interpretation of the persisted PDF section. Empty
    dimensions, canonical concepts and successful admission are never inputs.
    Multiple headings cannot establish which statement supplied a row.
    """
    if parser_version not in SCOPE_PARSERS or statement_context is None:
        return 'UNRESOLVED'
    headings = statement_context.splitlines()
    if len(headings) != 1:
        return 'UNRESOLVED'
    match = STATEMENT_HEADING.fullmatch(' '.join(headings[0].split()))
    if match is None or match[1] is None:
        return 'UNRESOLVED'
    return 'COMPANY' if match[1].lower() == 'company' else 'GROUP'
