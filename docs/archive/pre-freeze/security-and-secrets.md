# Security and Secrets

## Never commit
- API keys
- access tokens
- passwords
- database credentials
- private certificates
- personal secrets

## Local configuration
Use environment variables and a local `.env` file where appropriate.

Commit only:
`.env.example`

## Logging
Do not log secrets. Avoid unnecessary personal data.

## Public data
The prototype uses public company information, but source terms, rate limits, robots policies, licensing, and applicable laws must be respected.

## Database
Use least-privilege credentials and separate development/test data from production data if the project later becomes production-grade.
