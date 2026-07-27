# Security

## Scope

ReOrch is a portfolio-grade decision-support MVP. The public repository uses
synthetic, digital-twin, benchmark, and public-source-derived data. It must not
be connected to production ERP, MES, APS, QMS, EAM, identity, or writeback
endpoints without an independent security and operational review.

## Reporting

Please report suspected vulnerabilities through GitHub's private vulnerability
reporting channel for this repository. Do not include credentials, customer
data, production payloads, or other sensitive evidence in a public issue.

## Operational Boundary

- Production writeback is disabled by default.
- Demo credentials are for local synthetic environments only.
- Secrets must be provided through environment variables or a managed secret
  store and must never be committed.
- Customer data requires a separate data agreement, retention policy, access
  review, and isolated deployment.
- Passing repository tests or digital-twin gates is not a production security
  certificate.
