"""Verify recorded v1.2 results or deliberately run the three configured pilot companies."""
import argparse
from datetime import UTC, date, datetime
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from risk_intelligence.config import load_settings
from risk_intelligence.services.application import AssessmentApplication, error_message
from risk_intelligence.services.application_runtime import application_database, ingestion_services
from risk_intelligence.services.model_config import load_model_configuration, RuntimeConfigurationError
from run_company_assessment import environment

PILOTS = (('LODI', '05127466'), ('Westpoint', 'SC137690'), ('Pip & Nut', '08624397'))


def main() -> int:
    """Never migrate, overwrite assessments, or claim a missing company was verified."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path('.env'))
    parser.add_argument('--database', type=Path)
    parser.add_argument('--reporting-year', type=int, default=2025)
    parser.add_argument('--assessment-date', type=date.fromisoformat, default=date.today())
    parser.add_argument('--live', action='store_true', help='Explicitly permit bounded source and optional extraction calls')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new report path')
    values = environment(args.env_file)
    if args.database:
        values['RISK_UI_DATABASE_PATH'] = str(args.database)
    rows = []
    try:
        settings = load_settings(values)
        config = load_model_configuration(values)
        if args.live and not config.download_hosts:
            raise RuntimeConfigurationError('Live preflight requires verified exact download_hosts in model YAML')
        with application_database(values, write=args.live) as db:
            app = AssessmentApplication(db)
            for name, number in PILOTS:
                row = {'company': name, 'company_number': number, 'reporting_year': args.reporting_year,
                       'mode': 'LIVE' if args.live else 'RECORDED', 'verified': False}
                try:
                    if args.live:
                        m2, m3 = ingestion_services(db, settings, values, enable_llm=False)
                        view = app.create(number=number, assessment_date=args.assessment_date,
                            reporting_year=args.reporting_year, run_id='pilot-' + uuid4().hex,
                            calculated_at=datetime.now(UTC), m2=m2, m3=m3, max_documents=5)
                    else:
                        choice = next((c for c in app.choices() if c.assessment.company_number == number
                            and c.reporting_year == args.reporting_year and c.assessment.risk_model_version == '1.2'), None)
                        if choice is None:
                            row['issue'] = 'NO_RECORDED_ASSESSMENT'; rows.append(row); continue
                        view = app.load(choice.assessment.assessment_id)
                    ex = view.explanation
                    row.update(assessment_id=ex.assessment.assessment_id,
                        assessment_date=str(ex.assessment.assessment_date), assessment_status=ex.assessment.status.value,
                        overall=ex.overall.result.belief.model_dump(mode='json'),
                        indicators=[{'code': v.leaf.result.variable_code,
                                     'availability': v.leaf.result.availability_status.value,
                                     'raw_value': str(v.leaf.result.raw_value) if v.leaf.result.raw_value is not None else None,
                                     'supporting_inputs': len(v.inputs),
                                     'evidence_locators': sum(len(i.evidence) for i in v.inputs)} for v in ex.variables])
                    # A loaded tree is structural success. Retrieval/validation gaps still block full pilot acceptance.
                    row['verified'] = len(ex.variables) == 6 and all(v.leaf.result.raw_value is not None for v in ex.variables)
                    if not row['verified']: row['issue'] = 'UNRESOLVED_INDICATORS_REVIEW_REQUIRED'
                    row['document_diagnostics'] = db.query(
                        'SELECT d.processing_run_id, d.status, d.availability_status, d.reason '
                        'FROM accounts_run_document d JOIN processing_run r '
                        'ON r.processing_run_id=d.processing_run_id WHERE r.company_number=? '
                        'ORDER BY r.started_at DESC LIMIT 15', (number,))
                except Exception as error:
                    message = error_message(error)
                    row.update(issue=message.code, message=message.message)
                rows.append(row)
    except Exception as error:
        message = error_message(error)
        rows.append({'issue': message.code, 'message': message.message, 'verified': False})
    accepted = len(rows) == 3 and all(row['verified'] for row in rows)
    report = {'companies': rows, 'three_company_data_acceptance': accepted,
              'ui_human_acceptance': 'PENDING', 'm9_gate': 'PENDING_HUMAN_UI_REVIEW' if accepted else 'BLOCKED'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if accepted else 1


if __name__ == '__main__':
    raise SystemExit(main())
