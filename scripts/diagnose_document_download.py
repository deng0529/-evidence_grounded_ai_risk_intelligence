"""One metadata/content probe; report safe diagnostics without signed URLs or storage writes."""
import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from run_company_assessment import environment
from risk_intelligence.config import load_settings
from risk_intelligence.ingestion.accounts.client import DocumentClient, DocumentRetrievalError, representations
from risk_intelligence.ingestion.companies_house.client import json_object
from risk_intelligence.services.model_config import load_model_configuration
from risk_intelligence.services.application_runtime import application_database
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.accounts_repository import AccountsRepository


class ProbeClient(DocumentClient):
    """Capture only a bounded syntactically valid redirect hostname, never its signed path."""
    target_host: str | None = None

    def _request(self, host: str, path: str, accept: str, authenticated: bool):
        response, location = super()._request(host, path, accept, authenticated)
        if authenticated and response.status == 302 and location:
            try:
                target = urlsplit(location).hostname
            except ValueError:
                target = None
            if target and len(target) <= 253 and re.fullmatch(r'[a-z0-9.-]+', target):
                self.target_host = target
        return response, location


def main() -> int:
    """Probe one explicit M2 metadata link; never guess or automatically authorize hosts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path('.env'))
    parser.add_argument('--company-number', default='05127466')
    parser.add_argument('--metadata-url', help='The exact recorded M2 document metadata link')
    args = parser.parse_args()
    values = environment(args.env_file)
    try:
        settings = load_settings(values); config = load_model_configuration(values)
        if settings.companies_house_api_key is None:
            print(json.dumps({'code': 'CONFIGURATION_MISSING'})); return 1
        client = ProbeClient(settings.companies_house_api_key, download_hosts=config.download_hosts, attempts=1)
        metadata_url = args.metadata_url
        if metadata_url is None:
            with application_database(values) as database:
                company = SqlCompanyRepository(database).get_by_company_number(args.company_number)
                filings = AccountsRepository(database).filings(company.company_id) if company else ()
                if not filings:
                    print(json.dumps({'code': 'NO_RECORDED_M2_DOCUMENT_LINK'})); return 1
                metadata_url = filings[0].metadata_url
        metadata = client.get(metadata_url)
        supported = representations(json_object(metadata))
        if not supported:
            print(json.dumps({'code': 'NO_SUPPORTED_REPRESENTATION'})); return 1
        result = client.get(metadata_url, supported[0])
        print(json.dumps({'code': 'CONTENT_RETRIEVED', 'http': result.status, 'bytes': len(result.body),
                          'content_type': result.content_type, 'observed_target_host': client.target_host}))
        return 0
    except DocumentRetrievalError as error:
        print(json.dumps({'stage': error.stage, 'code': error.code, 'http': error.status,
                          'observed_target_host': client.target_host}))
    except Exception:
        print(json.dumps({'code': 'PROBE_FAILED', 'message': 'Check configuration and the recorded metadata link.'}))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
