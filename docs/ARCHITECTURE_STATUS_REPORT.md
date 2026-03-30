# CHIEFLY — ARCHITECTURE STATUS REPORT

**Date:** 2026-03-30
**Assessor:** Sisyphus (AI Architecture Review)
**Codebase:** `chiefly` — Personal task management system bridging Google Tasks ↔ LLM classification ↔ Telegram review UX
**Test Baseline:** 442 passed, 1 skipped, 0 failures

---

## 1. Executive Summary

Chiefly is a single-user personal task management system that:
1. **Syncs** tasks from a Google Tasks inbox list (read-only)
2. **Processes** them through a multi-step LLM pipeline (normalize → classify → describe → steps)
3. **Presents** proposals via Telegram for human review (confirm / edit / discard)
4. **Routes** confirmed tasks back to Google Tasks project lists
5. Provides a **FastAPI admin panel** (HTMX) for oversight, prompt management, and manual interventions

**Overall health: GOOD.** The core architecture contracts are obeyed. Sync is read-only. Processing is decoupled. Telegram is sequential. The data model correctly treats Google Tasks as source of truth with the DB as history + control plane. 442 tests pass clean.

**Key strengths:**
- Clean sync/processing decoupling via `task_processing_queue`
- Comprehensive admin panel with prompt versioning, aliases, reprocessing, rollback
- Full revision history / audit trail on every task decision
- Sequential Telegram UX with two-step discard confirmation

**Key weaknesses:**
- No end-to-end integration tests (inbox → classification → telegram → confirm → route)
- No dead letter queue or circuit breaker for permanently failed LLM calls
- Pause state is in-memory (lost on restart)
- `google_calendar_service.py` exists but is disconnected (dead code)
- No monitoring/metrics infrastructure

---

## 2. What Is Actually Implemented

| Capability | Status | Key Files |
|---|---|---|
| Google Tasks sync (read-only) | ✅ Complete | `sync_service.py`, `sync_worker.py` |
| Google Tasks project sync | ✅ Complete | `project_sync_service.py`, `project_sync_worker.py` |
| Multi-step LLM pipeline | ✅ Complete | `llm_service.py`, `prompts/pipeline.py` |
| Processing queue with claim/retry/fail | ✅ Complete | `processing_worker.py`, `processing_queue_repo.py` |
| Classification with project routing | ✅ Complete | `classification_service.py`, `project_routing_service.py` |
| Telegram proposal cards | ✅ Complete | `telegram_service.py`, `review_queue_service.py` |
| Confirm / Edit / Discard flows | ✅ Complete | `main.py` callback handlers |
| Two-step discard confirmation | ✅ Complete | `main.py` discard/discard_confirm/discard_cancel |
| Sequential review queue | ✅ Complete | `review_queue_service.py` |
| Queue position display | ✅ Complete | `telegram_service.py`, `review_queue_service.py` |
| /pause command | ✅ Complete | `review_pause.py` |
| Daily review generation | ✅ Complete | `llm_service.py` generate_daily_review |
| Sync summary emission | ✅ Complete | `sync_worker.py` |
| Admin dashboard | ✅ Complete | `admin_ui.py`, `admin_dashboard_service.py` |
| Admin task list/detail/filter | ✅ Complete | `admin_ui.py`, `admin_tasks_service.py` |
| Admin project management | ✅ Complete | `admin_ui.py`, `admin_projects_service.py` |
| Admin event log | ✅ Complete | `admin_ui.py`, `admin_logs_service.py` |
| Prompt versioning (create/edit/activate/rollback) | ✅ Complete | `prompt_versioning_service.py` |
| Project aliases | ✅ Complete | `project_alias_repo.py` |
| Admin reprocessing (retry/reclassify/resend/rewrite) | ✅ Complete | `admin_api.py` |
| Task rollback to previous revision | ✅ Complete | `admin_api.py` |
| Google Tasks import | ✅ Complete | `admin_api.py` |
| Token-based admin auth with signed cookies | ✅ Complete | `admin/auth.py` |
| HTMX admin UI (23 templates) | ✅ Complete | `templates/admin/` |
| Revision history / audit trail | ✅ Complete | `revision_service.py`, `task_revision_repo.py` |
| Change detection + alerts | ✅ Complete | `task_change_monitor.py`, `alert_service.py` |
| Idempotency locks | ✅ Complete | `idempotency_service.py` |
| Notes codec (metadata envelope in task notes) | ✅ Complete | Referenced in sync/processing |
| LLM fallback heuristics | ✅ Complete | `llm_service.py` fallback methods |

**Telegram Commands:** /start, /help, /pause, /inbox, /today, /projects, /review, /stats, /next, /backlog

**Telegram Callbacks:** confirm, discard, discard_confirm, discard_cancel, change_project, change_type, edit, show_steps, proj:{id}, kind:{value}

---

## 3. What Is Partially Implemented

| Capability | State | Gap |
|---|---|---|
| LLM disambiguation flow | Pipeline step exists | No Telegram UX for user to pick among ambiguity options — results shown in proposal card but no interactive selection |
| Edit flow | Works | Text-based only — user sends raw text after pressing "Edit" — no inline editing, no field-specific editing |
| Processing queue observability | Queue viewable in admin | No metrics, no alerting on queue depth or stuck items |
| Custom instructions per project | Prompt versions exist | Re-runs entire pipeline on project match — no partial pipeline override |

---

## 4. What Is Missing

| Capability | Impact | Notes |
|---|---|---|
| End-to-end integration tests | **HIGH** | No test covers full inbox → process → telegram → confirm → Google Tasks route |
| Dead letter queue | **MEDIUM** | Failed items after max retries just get FAILED status — no structured DLQ or alerting |
| Persistent pause state | **MEDIUM** | `review_pause.py` uses in-memory global — lost on restart |
| Circuit breaker for LLM | **MEDIUM** | No backoff pattern — if LLM provider is down, all items will exhaust retries |
| Monitoring/metrics | **MEDIUM** | No Prometheus, no structured metrics, no processing latency tracking |
| Google Calendar integration | **LOW** | `google_calendar_service.py` exists but is completely disconnected |
| Bulk operations in admin | **LOW** | No multi-select, no batch retry/reclassify |
| Exponential backoff on queue retries | **LOW** | Simple count-based retry — immediate re-attempt |

---

## 5. What Is Architecturally Wrong

| Issue | Severity | Details |
|---|---|---|
| In-memory pause state | **MEDIUM** | `review_pause.py` stores state in a module-level variable. Restart = unpause. Should be in DB or Redis. |
| Telegram send failure not handled in processing worker | **MEDIUM** | Processing worker creates review session then calls `send_next()`. If Telegram send fails, session exists but user never sees proposal. No retry mechanism for send failures. |
| `google_calendar_service.py` dead code | **LOW** | Not imported anywhere. Should be removed or clearly marked as roadmap. |
| Credentials in repo root | **LOW** | Google service account key and OAuth client secret appear to be in the repo root. Should be in `.gitignore`. |
| `source_tasks` dual-write | **LOW** | Sync writes to both `source_tasks` AND `task_records`+`task_snapshots`. The `source_tasks` table appears to be a backward-compatibility artifact. |

**No major architecture violations.** The three core contracts (sync read-only, sync/processing decoupled, Telegram sequential) are all properly enforced.

---

## 6. Current Data Model Assessment

**Tables (13 total):**

| Table | Purpose | Health |
|---|---|---|
| `task_records` | Primary task identity (stable_id PK, Google pointers, state, processing_status) | ✅ Clean |
| `task_revisions` | Full audit trail (proposals, decisions, before/after) | ✅ Clean |
| `task_snapshots` | Point-in-time Google Tasks state (content_hash dedup) | ✅ Clean |
| `telegram_review_sessions` | Active review state (queued/pending/awaiting_edit/resolved) | ✅ Clean |
| `projects` | Project definitions with Google tasklist mapping | ✅ Clean |
| `project_aliases` | Routing aliases | ✅ Clean |
| `project_prompt_versions` | Versioned prompts per project | ✅ Clean |
| `source_tasks` | Raw ingested data from Google Tasks | ⚠️ Possibly redundant with snapshots |
| `task_processing_queue` | Job queue with status, retries, locking | ✅ Clean |
| `task_processing_log` | LLM interaction logs (tokens, duration, prompts) | ✅ Clean |
| `processing_locks` | Distributed locks | ✅ Clean |
| `daily_review_snapshots` | Generated daily reviews | ✅ Clean |
| `system_events` | Structured event log | ✅ Clean |

**Source of Truth:** Correctly Google Tasks. DB stores history + control plane.

**Relationship Integrity:** All tables have clear FK relationships. No orphaned tables detected. All have corresponding repositories with proper query methods.

**Migration History:** 7 migrations, clean progression from initial schema through sync/processing decoupling to TaskItem removal.

---

## 7. Current Telegram UX Assessment

**Strengths:**
- Sequential review enforced (one active proposal at a time)
- Queue position shown on cards
- Confidence displayed with color emoji (🔴🟡🟢)
- Two-step discard flow prevents accidental data loss
- /pause prevents interruptions during focus time
- /backlog shows queue status
- /next lets user pull next item on demand

**Weaknesses:**
- **Edit flow is crude**: Press "Edit" → bot says "send me a new title" → user types raw text. No inline editing, no field selection, no undo.
- **Disambiguation is passive**: If LLM produces ambiguity options, they're shown in the proposal card text but the user can't interactively pick one.
- **No undo on confirm**: Once confirmed, task is moved in Google Tasks. No "oops, wrong project" shortcut.
- **No batch review**: Each task requires individual attention. High-volume days could be tedious.

**Overall Telegram UX: Functional and safe, but utilitarian.** The sequential model prevents spam and errors, but the interaction model is basic.

---

## 8. Current Admin Panel Assessment

**Strengths:**
- Full-featured dashboard with task counts, status breakdown, recent events, error counts
- Task list with filtering (status, kind, project, search) + detail with revision history
- Project management with prompt versioning, aliases, description generation
- Comprehensive task actions: retry, reclassify, resend, rewrite, rollback, manual edit
- Processing queue visibility
- HTMX-powered partial updates (responsive without full page reloads)
- 23 templates (5 pages, 18 partials/macros)
- Signed cookie auth with HTMX-aware error handling
- Event log with filtering by type/severity/subsystem

**Weaknesses:**
- No bulk operations (can't batch-retry 50 failed tasks)
- Admin token is static (`admin_token: "admin"` default) — no user management
- No admin UI tests (no Playwright/Selenium coverage)
- No CSRF protection visible
- No rate limiting on admin endpoints

**Overall Admin Panel: Surprisingly complete for a personal tool.** Covers all major administrative needs. The HTMX approach is clean.

---

## 9. Current Testing Assessment

**Baseline:** 442 passed, 1 skipped, 0 failures across 45 test files (~9,767 lines)

**Unit Tests (35 files):** Cover all core services, processing, LLM, Telegram, state management, auth, utilities.

**Integration Tests (9 files):** Cover admin actions, models, repositories, classification, daily review, edit flows, Telegram callbacks.

**Well-covered areas:**
- Processing worker flow (819 lines)
- Sync service (613 lines)
- LLM service + pipeline
- Admin actions + auth
- Telegram callback handling
- State machine transitions

**Coverage gaps:**

| Gap | Impact |
|---|---|
| No end-to-end workflow tests | **HIGH** — Full user journey never tested as integration |
| No external API resilience tests | **MEDIUM** — Google/Telegram API failures, rate limits, timeouts |
| No concurrent processing tests | **MEDIUM** — Race conditions in queue claiming untested |
| No admin UI tests | **LOW** — HTMX interactions untested |
| No performance/load tests | **LOW** — High-volume scenarios untested |

**Test infrastructure:** pytest + pytest-asyncio, factory-boy for fixtures, freezegun for time, shared conftest.py. SQLite in-memory with JSONB→JSON shim for integration tests.

---

## 10. Most Important Risks

1. **Telegram send failure creates orphaned review sessions** — Processing worker creates a review session, then calls `send_next()`. If Telegram API is down, the session exists in DB as `queued` but the user never sees it. No recovery mechanism retries the send.

2. **In-memory pause state** — Server restart silently unpauses. User thinks reviews are paused, but proposals start arriving.

3. **No circuit breaker on LLM provider** — If OpenAI is down, every queued task will burn through 3 retries and land in FAILED. When service recovers, all tasks require manual admin intervention (retry via admin panel).

4. **Credentials in repo root** — Google service account key and OAuth client secret appear to be in the repo root directory. If this repo is public or shared, this is a credential leak.

5. **No end-to-end test** — The most critical user path (sync → process → review → confirm → route) has never been tested as a single flow. Regressions in the handoff between stages would go undetected.

---

## 11. Recommended Next Debugging Targets

1. **Telegram send failure handling** — Trace what happens when `send_next()` fails after review session creation. Add retry or status correction.

2. **Orphaned review sessions** — Check if any existing review sessions are stuck in `queued` state with no corresponding Telegram message.

3. **Queue claiming under load** — Verify `SELECT FOR UPDATE SKIP LOCKED` behavior when multiple processing cycles overlap (APScheduler fires every 10s — what if a cycle takes >10s?).

4. **Fallback classification accuracy** — When LLM falls back to keyword heuristics, validate the `_TYPE_KEYWORDS` regex patterns against real task data for false positive/negative rates.

---

## 12. Recommended Next Implementation Targets

| Priority | Target | Effort | Rationale |
|---|---|---|---|
| **P0** | Persist pause state to DB | Small | Prevents silent unpause on restart |
| **P0** | Handle Telegram send failures in processing worker | Small | Prevents orphaned review sessions |
| **P0** | Add end-to-end integration test | Medium | Covers the most critical user path |
| **P1** | Remove `google_calendar_service.py` or mark as roadmap | Trivial | Dead code cleanup |
| **P1** | Add `.gitignore` entries for credential files | Trivial | Security hygiene |
| **P1** | Add circuit breaker / exponential backoff for LLM | Medium | Prevents mass failure on provider outage |
| **P2** | Interactive disambiguation in Telegram | Medium | Turns passive display into actionable UX |
| **P2** | Inline edit flow in Telegram | Medium | Better UX than raw text input |
| **P2** | Dead letter queue with alerting | Medium | Structured handling of permanently failed items |
| **P3** | Bulk admin operations | Medium | Quality-of-life for high-volume days |
| **P3** | Monitoring/metrics | Medium-Large | Observability |

---

## 13. Suggested Roadmap From Current State

### Phase 1 — Hardening (1-2 days)
- Persist pause state to DB
- Handle Telegram send failures
- Remove dead `google_calendar_service.py`
- Credential hygiene (.gitignore)
- Write end-to-end integration test

### Phase 2 — Resilience (2-3 days)
- LLM circuit breaker with exponential backoff
- Dead letter queue for permanently failed items
- External API failure tests (Google, Telegram, LLM)
- Concurrent processing race condition tests

### Phase 3 — UX Polish (3-5 days)
- Interactive disambiguation selection in Telegram
- Improved edit flow (field-specific, inline)
- Undo on confirm (within time window)
- Batch review mode for high-volume days
- Bulk admin operations

### Phase 4 — Observability (2-3 days)
- Structured metrics (processing latency, LLM success rate, queue depth)
- Alerting on stuck items / high failure rates
- Admin dashboard metrics visualization

---

## 14. File-Level Findings

| File | Finding |
|---|---|
| `apps/api/services/review_pause.py` | In-memory state — needs persistence |
| `apps/api/services/google_calendar_service.py` | Dead code — not imported anywhere |
| `apps/api/workers/processing_worker.py` | No Telegram send failure handling after review session creation |
| `apps/api/services/llm_service.py` | Fallback heuristics are simplistic — keyword matching may misclassify edge cases |
| `apps/api/services/llm_service.py` | Prompts are hardcoded strings — limited runtime dynamism beyond format() |
| `apps/api/config.py` | `admin_token` defaults to `"admin"` — insecure default |
| `apps/api/admin/auth.py` | No CSRF protection visible |
| `apps/api/routes/admin_api.py` | No rate limiting |
| `db/models/source_task.py` | Potentially redundant with `task_snapshots` — dual-write artifact |
| `apps/api/services/sync_service.py` | Dual-write to `source_tasks` + `task_records`/`task_snapshots` — cleanup candidate |
| Repo root | Credential JSON files should not be in working directory |
| `apps/api/workers/sync_worker.py` | Sync summary emission works but has no test for failure path |
| `tests/` | No end-to-end test covering full user journey |

---

## 15. Final Recommendation

**Chiefly is in solid working condition.** The core architecture is sound — contracts are obeyed, 442 tests pass, the data model is clean, and the admin panel is surprisingly complete. The recent audit/rewrite fixed all test failures and removed the major architecture violations (LLM in sync, dead IntakeService code, stale TaskItem references).

**What to do next depends on your intent:**

- **If deploying soon:** Do Phase 1 (Hardening) — persist pause state, handle Telegram send failures, credential hygiene, end-to-end test. This is 1-2 days and closes the highest-risk gaps.

- **If improving the product:** Skip to Phase 3 (UX Polish) — interactive disambiguation and better edit flow would make the Telegram UX significantly more pleasant.

- **If building for longevity:** Do Phases 1 → 2 → 4 in order — resilience and observability before features.

The codebase is disciplined enough to support any of these directions without architectural rework.
