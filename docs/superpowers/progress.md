# Execution ledger — plan: docs/superpowers/plans/2026-11-05-bolipost.md

- Design approved by user. Technical plan and implementation already authorized.
- Ruling: reuse initially empty supplied workspace; there is no Git repository to isolate.
- Ruling: independent agents implement data/UI; primary owns Django integration, auth, jobs, AI, PDF and docs.
- Pre-flight: data stream/catalog and frontend HTTP contracts defined in plan; no shared file ownership.
- Real integration prerequisite: existing PostgreSQL service requires credentials; OpenRouter key not supplied. Do not claim real backup/chat verified without these.

## Delivered 2026-11-05

- Tasks 1–5: implementation complete. Django, metadata, authorized data layer, jobs/session boundaries, tracking, dashboards, PDF and responsive browser-local history integrated.
- Ruling: use packaged Geist Unicode font for PDF and UI, avoiding a second font download/dependency.
- Ruling: AI plans may not supply projected literal data or graph values. Recorded AI filters are extracted from executed SQL predicates and sources, not trusted model descriptions.
- Ruling: queries have no fixed total row cap or 10-second statement deadline. Results spool to private SQLite files in batches, with 100-row presentation pages. Presence polling keeps active work alive; abandonment after 120 seconds cancels the connection.
- Ruling: completed results expire 24 hours after completion/update; automatic maintenance and cleanup_results remove expired temporary records/files. Active queries do not expire merely by duration.
- Data integration: isolated PostgreSQL on 55439, actual backup schema (122 tables, 159 FK) plus fixtures; restricted role and 16 projected views. Existing service on 5432 and backup untouched. Isolated cluster stopped after tests.
- Final full suite: `.venv/Scripts/python.exe manage.py test --verbosity 1` with POSTAL_INTEGRATION_URL: **47 tests passed, zero skipped, zero failures**. Cluster stopped in finally.
- Django check: no issues. makemigrations --check --dry-run: no changes. JavaScript syntax check: passed.
- Real Edge browser: `scripts/browser_smoke.py`: **20 checks passed, zero failures**, including login, candidate-service tracking, four verified datasets/charts, PDF/copy, catalog privacy, metadata chat, missing-key error, IndexedDB history lifecycle, late cancellation, mobile390/light+dark, cross-tab account isolation, JS and console errors.
- PDF: downloaded through authenticated endpoint, text/accents verified and first page rendered with Poppler; legible and explicitly demo-marked.
- Independent review: fixed all important findings: invented projected values, stale-account history mixing, lost follow-up context, abandoned creation, non-string service input and stale-process concurrency quota. Regression test observed RED then GREEN for final restart recovery.
- UI QA corrections: malformed EMS option fixed; deleting/resetting a conversation now destroys only charts in that conversation, preserving dashboard graphs.
- Local server: http://127.0.0.1:8000 in explicit demonstration mode. Initial randomized account is in ignored `.runtime/local-access.txt`; no secrets printed.

## Not verified with real services

- Full 15.4GB business-data restore into the existing PostgreSQL installation: requires user-supplied local administrative credentials. Only schema extraction and isolated fixture-backed integration were performed.
- Actual OpenRouter response using the user's API key/account: key not supplied. Provider request/response boundaries are tested with HTTP transport fixtures; missing-key/error behavior is tested in browser.
- Production/shared deployment is outside this local delivery. Use README for prerequisites and deployment settings before shared hosting.

## Correction: AI assistant reports, 2026-11-05

- User clarified that the assistant itself must generate answers, summaries, reports and database dashboards. Expanded the original scope's implementation from one SQL/template to multi-query AI plans and evidence-selected narrative.
- Query plans distinguish answer/summary/report/dashboard and select up to six analyses (not a total-row cap). Every SQL is validated before execution; all panels spool independently and retain session ownership.
- A second OpenRouter call selects and organizes factual findings from verified data. The final IR accepts only value/comparison/maximum/minimum plus cell references; the server renders facts and verifies arithmetic/extrema. Free-text factual claims, invented multipliers/units and extrema from incomplete samples are rejected.
- The UI renders all panels, independent charts/pages, sources, summary, copy and complete/individual PDF exports. History retains the entire report; restored data remain explicitly historical.
- Added local interactive configure_services with hidden input and a read-only PostgreSQL connectivity check before saving .env. Preserves existing config and secret redaction. User confirmed they know the PostgreSQL password; they have not yet run configuration during this work.
- Fixed SQLite timestamp affinity producing Julian dates with PostgreSQL casts; regression covers timestamp/timestamptz/nesting/NULL. Fixed single-point line marker and PDF orphan headings.
- Final full Django suite with isolated PostgreSQL enabled: **66 tests passed, zero skipped, zero failures**, system check clean; isolated cluster stopped afterwards. makemigrations check clean, JavaScript syntax valid.
- AI report browser QA: **11 checks passed**, including five panels/three charts, two viewports, real owned-result PDF endpoints, independent pagination, history/copy and composer failure. Provider was explicitly simulated; no live API key used. Screenshots/PDF in `.runtime/qa/ai-dashboard-*` and report-smoke.json.
- Independent final review of factual IR: earlier invented-unit finding closed; 15 AI/report tests passed. Live OpenRouter and full backup integration still require local credentials.
