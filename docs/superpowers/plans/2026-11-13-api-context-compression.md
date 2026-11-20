# API context compression implementation plan

**Goal:** Implement approved plans 1 and 2 without extra model calls or changing SQL/data safety.

**Design:** Keep full results in the existing private spool. Persist a server-owned conversation state on each job (including clarification failures), with a request anchor, latest explicit corrections, unresolved notes, and three recent turns. The model receives this state and deduplicated verified query metadata; rows are included only when needed to resolve a result reference. Keep unrecognized user constraints verbatim rather than guessing. All ownership and expiration checks remain in the HTTP boundary.

The analyst receives compact JSON and bounded verified evidence, preserving row order, all panels, counts, completeness and citation indices. Small complete results remain complete; oversized samples are reduced transparently. Do not remove safety instructions or filter the authorized catalog (plan 3).

**Files:** `postal/context.py`, model + migration, `views.py`, `jobs.py`, `ai.py`, regression tests and README.

- [x] Write failing tests for smaller payloads, state corrections/clarifications, result references, evidence completeness and usage logging.
- [x] Implement compact serialization, query deduplication and server-owned state with legacy history fallback.
- [x] Bound analyst evidence and log only token counts/provider/stage/attempt, never prompts or results.
- [x] Run targeted and full Django tests; check migrations and verify the additive local migration is applied.
- [x] Document behavior and verification limits.

Ruling: User selected and authorized both previously described plans; implement directly without another approval cycle. Preserve unknown constraints even when this limits compression.

Review: fixed two independently identified cases with red/green regression tests: historical reports retain all panel metadata; complete aggregates over 20 rows remain available while within the evidence budget. Partial samples are reduced first.

Verification: full `manage.py test postal.tests` ran 191 tests, OK with 5 integration tests skipped. `manage.py check` clean; `makemigrations --check --dry-run` reports no changes; `showmigrations postal` confirms migration 0003 applied. Local accounts SQLite backup created without overwriting an existing backup. No live provider calls or measured token-saving claim; regression transport is mocked.
