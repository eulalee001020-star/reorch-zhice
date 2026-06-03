# CI Validation Summary

## 1. Validation Scope

This note records the internal engineering validation baseline for the ReOrch MVP. It covers backend tests, frontend build, and Docker Compose smoke validation in GitHub Actions.

It does not claim validation against a real customer ERP/MES/APS system. Digital-twin validation evidence covers the current lab-trial stage; customer integration remains a separate P0 workstream.

## 2. Commit Under Test

| Field | Value |
| --- | --- |
| Commit | `d58b6c5af28a03cd837ea785b906379afd2122cd` |
| Short SHA | `d58b6c5` |
| CI run | https://github.com/eulalee001020-star/reorch-zhice/actions/runs/25852548883 |
| Result | Success |
| Run created | 2026-05-14T09:26:51Z |
| Run completed | 2026-05-14T09:29:31Z |

## 3. Test Results

| Validation item | Result | Evidence |
| --- | --- | --- |
| Backend test suite | Passed | Local `pytest -q`: `717 passed` |
| GitHub backend job | Passed | CI job `backend` |
| Frontend build | Passed | CI job `frontend` |
| Docker Compose smoke | Passed | CI job `compose-smoke` |

## 4. Compose Smoke Results

The Compose stack was validated in GitHub Actions on a standard Linux runner. The job built and started the full stack, waited for backend health, checked backend readiness, checked integration health, checked frontend availability, verified no service exited unexpectedly, printed Compose status/logs, and tore the stack down.

Validated endpoints:

```text
GET http://localhost:8000/healthz
GET http://localhost:8000/readyz
GET http://localhost:8000/api/v1/health/integrations
GET http://localhost:3000
```

## 5. Known Non-Blocking Warnings

GitHub Actions emitted a Node.js 20 action runtime deprecation warning for GitHub-managed actions. The frontend job itself uses `node-version: "22"`, and the warning does not block the current PoC validation.

Maintenance item:

```text
chore(ci): verify GitHub Actions Node 24 runtime compatibility
```

## 6. Limitations

- Compose was validated in CI/Linux, not on the local machine.
- No claim is made that local Docker is available or locally validated.
- No customer sandbox, staging, or production ERP/MES/APS system has been validated in this note.
- Data-volume restart recovery should be captured again during customer-facing deployment validation.

## 7. Conclusion

Internal MVP engineering validation is closed for the referenced commit. The primary remaining risk has moved from "system can run" to "system can ingest real industrial data, preserve auditability, and execute human-approved writeback safely."
