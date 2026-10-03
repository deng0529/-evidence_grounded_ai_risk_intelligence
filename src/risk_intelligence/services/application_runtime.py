"""Explicit M8 runtime adapters; configuration is environment-based and never displayed."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from hashlib import sha256

from risk_intelligence.config import Settings, load_settings
from .model_config import load_model_configuration, RuntimeConfigurationError
from risk_intelligence.ingestion.accounts.client import DocumentClient
from risk_intelligence.ingestion.accounts.llm import OpenAIExtraction
from risk_intelligence.ingestion.accounts.service import AccountsIngestion
from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient, HttpTransport
from risk_intelligence.ingestion.companies_house.service import CompaniesHouseIngestion
from risk_intelligence.persistence.connection import Database, PersistenceError, open_database
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.storage.r2 import R2Storage


@contextmanager
def application_database(environ: Mapping[str, str], *, write: bool = False) -> Iterator[Database]:
    """Open the configured existing DB; viewing never creates it or applies migrations.

    Local viewing uses SQLite read-only mode. Turso uses the existing adapter with
    read-only services. The caller owns a fresh connection per operation/rerun.
    """
    settings = load_settings(environ)
    if settings.database_backend == 'sqlite':
        path = Path(environ.get('RISK_UI_DATABASE_PATH', str(settings.local_data_directory / 'metadata.sqlite3')))
        if not path.is_file():
            raise PersistenceError('Configured application database is absent')
        try:
            connection = sqlite3.connect(path.resolve().as_uri() + ('?mode=rw' if write else '?mode=ro'),
                                         uri=True, isolation_level=None)
        except sqlite3.Error:
            raise PersistenceError('Application database is unavailable') from None
        database = Database(connection)
    else:
        database = open_database(settings)
    with database:
        if write:
            from risk_intelligence.persistence.migrations import migrate
            migrate(database)
        yield database


def ingestion_services(database: Database, settings: Settings, environ: Mapping[str, str], *,
                       enable_llm: bool = False) -> tuple[CompaniesHouseIngestion, AccountsIngestion]:
    """Construct existing live adapters only after an explicit Run action.

    Optional OCR uses the existing fingerprint contract; LLM use is opt-in and
    configuration-driven. No clients are constructed merely to view an assessment.
    """
    if settings.companies_house_api_key is None:
        raise RuntimeConfigurationError('Live ingestion requires Companies House configuration')
    configuration = load_model_configuration(environ)
    model = None
    if enable_llm and settings.openai_api_key:
        model = OpenAIExtraction(settings.openai_api_key, configuration.extraction_model,
                                 config_version=configuration.version)
    tessdata = environ.get('RISK_OCR_TESSDATA') or None
    # The repository ships the bounded English OCR model under the configured
    # data directory.  Prefer an explicit override, otherwise use that local
    # resource when present.  This does not download models or discover secrets.
    if not tessdata:
        bundled = settings.local_data_directory / 'tessdata'
        if (bundled / 'eng.traineddata').is_file():
            tessdata = str(bundled)
    ocr_version = 'disabled'
    if tessdata:
        trained = Path(tessdata) / 'eng.traineddata'
        if not trained.is_file():
            raise RuntimeConfigurationError('Configured OCR tessdata is missing eng.traineddata')
        ocr_version = 'pymupdf-1.28.2-eng-' + sha256(trained.read_bytes()).hexdigest()
    storage = (R2Storage.from_settings(settings) if settings.evidence_storage_backend == 'r2'
               else LocalStorage(settings.local_data_directory / 'raw'))
    m2 = CompaniesHouseIngestion(database, storage, CompaniesHouseClient(HttpTransport(settings.companies_house_api_key)))
    m3 = AccountsIngestion(database, storage, DocumentClient(settings.companies_house_api_key, download_hosts=configuration.download_hosts),
                          tessdata=tessdata, ocr_version=ocr_version, llm=model)
    return m2, m3
