# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Ira, please report it responsibly.

**Do not open a public GitHub issue.**

Instead, email **rushabh@machinecraft.org** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge receipt within 48 hours and aim to provide a fix or
mitigation plan within 7 business days.

## Supported Versions

| Version | Supported |
|:--------|:----------|
| 3.x     | Yes       |
| < 3.0   | No        |

## Security Practices

- All secrets are loaded from environment variables (`.env`), never committed to source.
- API endpoints are protected by `API_SECRET_KEY` when set.
- Email mode defaults to `TRAINING` — live sending requires explicit opt-in.
- PII redaction is available via Google Cloud DLP integration.
- The Docker image runs as a non-root user (`ira`, uid 1000).
