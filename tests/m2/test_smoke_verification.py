"""The live smoke's documented 404 allowance must not relax other failure gates."""

from pathlib import Path
import runpy

import pytest

from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient
from risk_intelligence.ingestion.companies_house.service import CompaniesHouseIngestion
from risk_intelligence.persistence.connection import Database
from risk_intelligence.storage.local import LocalStorage
from conftest import NOW, NUMBER, FakeAPI


@pytest.mark.parametrize('failure', [404,401,503])
def test_observed_statements_not_found_is_explicit_not_fabricated_completeness(
    database: Database, storage: LocalStorage, api: FakeAPI, failure: int,
) -> None:
    api.failures['persons-with-significant-control-statements:0'] = failure
    CompaniesHouseIngestion(database,storage,CompaniesHouseClient(api,pause=lambda _:None),clock=lambda:NOW).ingest(NUMBER,NOW.date(),'verify')
    verify = runpy.run_path(str(Path(__file__).parents[2]/'examples'/'ingest_company.py'))['verify_run']
    with pytest.raises(RuntimeError):
        verify(database,storage,'verify')
    if failure==404:
        report = verify(database,storage,'verify',allow_statements_not_found=True)
        assert report['run_status']=='PARTIAL'
        missing = next(r for r in report['resources'] if r['resource']=='persons-with-significant-control-statements')
        assert missing['complete'] is False and missing['items'] is None
    else:
        with pytest.raises(RuntimeError):
            verify(database,storage,'verify',allow_statements_not_found=True)
