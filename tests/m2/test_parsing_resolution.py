"""Resource identity, source missingness and explicit search selection."""

from datetime import date
import json

import pytest

from risk_intelligence.domain.enums import AvailabilityStatus
from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient, Response, ParseError
from risk_intelligence.ingestion.companies_house.parsing import observations, subject_identity, page_items
from risk_intelligence.ingestion.companies_house.policy import Resource
from risk_intelligence.ingestion.companies_house.resolution import search_companies
from risk_intelligence.persistence.connection import Database
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.storage.objects import checksum
from conftest import NOW, NUMBER


def test_pre_1992_appointment_is_not_fabricated_and_identity_is_not_name() -> None:
    item = {'name':'SYNTHETIC SAME NAME', 'officer_role':'director', 'appointed_before':'1992-01-01',
            'is_pre_1992_appointment':True, 'links':{'officer':{'appointments':'/officers/synthetic/appointments'}}}
    facts = {o.concept:o for o in observations(Resource.OFFICERS,item,NUMBER)}
    assert facts['OFFICERS_APPOINTED_ON'].value.value is None
    assert facts['OFFICERS_APPOINTED_BEFORE'].value.value=='1992-01-01'
    assert facts['OFFICERS_IS_PRE_1992_APPOINTMENT'].value.value is True
    first=subject_identity(Resource.OFFICERS,item,NUMBER)
    item['name']='CHANGED DISPLAY NAME'; item['resigned_on']='2000-01-01'
    assert subject_identity(Resource.OFFICERS,item,NUMBER)==first
    item['appointed_before']='1991-01-01'
    assert subject_identity(Resource.OFFICERS,item,NUMBER)!=first


def test_psc_kinds_and_ceased_history_preserve_source_semantics() -> None:
    individual={'kind':'individual-person-with-significant-control', 'name':'SYNTHETIC',
                'notified_on':'2016-04-06','ceased_on':'2025-01-01','links':{'self':'/psc/a'}}
    facts={o.concept:o for o in observations(Resource.PSC,individual,NUMBER)}
    assert facts['PSC_CEASED_ON'].value.value==date(2025,1,1)
    assert facts['PSC_IDENTIFICATION_LEGAL_FORM'].status==AvailabilityStatus.NOT_APPLICABLE
    corporate=individual|{'kind':'corporate-entity-person-with-significant-control','links':{'self':'/psc/b'},
                         'identification':{'legal_form':'limited company','registration_number':'SYNTHETIC123'}}
    facts={o.concept:o for o in observations(Resource.PSC,corporate,NUMBER)}
    assert facts['PSC_IDENTIFICATION_LEGAL_FORM'].value.value=='limited company'
    assert all(o.subject=='/psc/b' for o in facts.values())


@pytest.mark.parametrize('data,index', [({'items':[],'total_results':2,'start_index':0},0),
    ({'items':[{}],'total_results':1,'start_index':0},1),
    ({'items':[{}],'total_results':True,'start_index':0},0),
    ({'items':{},'total_results':0,'start_index':0},0)])
def test_inconsistent_pagination_is_never_complete(data: dict, index: int) -> None:
    with pytest.raises(ParseError):
        page_items(data,index)


def test_search_preserves_exact_bytes_before_explicit_selection(database: Database, storage: LocalStorage) -> None:
    body=json.dumps({'items':[{'company_number':NUMBER,'title':'SYNTHETIC A'},
                              {'company_number':'ZZ000003','title':'SYNTHETIC B'}],
                     'total_results':2,'start_index':0},indent=4).encode()+b'\n'
    client=CompaniesHouseClient(lambda p:Response(p,body,200,NOW))
    result=search_companies(database,storage,client,'SYNTHETIC','search-test')
    with pytest.raises(ValueError,match='Explicit'):
        result.select()
    assert result.select(NUMBER).company_number==NUMBER
    with pytest.raises(ValueError):
        result.select('ZZ999999')
    row=database.query('SELECT * FROM company_search_evidence')[0]
    assert storage.read(row['object_path'])==body and row['checksum']==checksum(body)
    assert not database.query('SELECT * FROM company')


def test_bad_search_json_is_preserved_but_never_fabricates_candidates(database: Database, storage: LocalStorage) -> None:
    client=CompaniesHouseClient(lambda p:Response(p,b'not json',200,NOW))
    with pytest.raises(ParseError):
        search_companies(database,storage,client,'SYNTHETIC','bad-search')
    assert len(database.query('SELECT * FROM company_search_evidence'))==1


def test_profile_optional_fields_preserve_null_and_current_overdue_boolean() -> None:
    items=observations(Resource.PROFILE,{'company_number':NUMBER,'company_name':'SYNTHETIC',
                       'confirmation_statement':{'overdue':True},
                       'accounts':{'accounting_reference_date':{'day':'31','month':'03'}}},NUMBER)
    by_concept={o.concept:o for o in items}
    assert by_concept['PROFILE_DATE_OF_CESSATION'].value.value is None
    assert by_concept['PROFILE_CONFIRMATION_STATEMENT_OVERDUE'].value.value is True
    assert by_concept['PROFILE_ACCOUNTS_ACCOUNTING_REFERENCE_DATE_DAY'].value.value=='31'


@pytest.mark.parametrize('field,value', [('appointed_on','2020-99-01'), ('appointed_on','2020-01'),
                                        ('is_pre_1992_appointment',1), ('name',17)])
def test_malformed_types_are_explicit_not_sentinel_facts(field: str, value: object) -> None:
    item={'name':'SYNTHETIC','officer_role':'secretary','links':{'self':'/synthetic/a'},field:value}
    with pytest.raises(ParseError):
        observations(Resource.OFFICERS,item,NUMBER)
