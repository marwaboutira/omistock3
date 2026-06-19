# OMISTOCK — Comprehensive Review Report

**Repository:** https://github.com/sarahgacem/omistock
**Reviewed working tree:** local clone, branch `mainbr` (authoritative working state; the GitHub default branch is `master`/HEAD `2346ca6`)
**Review date:** 2026-06-17
**Reviewer:** independent code & architecture review (evidence-based, grounded in the actual workspace files)

> **Scope note / honesty disclaimer.** The clone in the workspace is in a *heavily-refactored, uncommitted* state on branch `mainbr`. The committed GitHub HEAD (`2346ca6`) is an academic ERP for a defence ("soutenance"); the working tree adds a large stock-theory + AI-agent-governance layer on top. This report reviews **the project as it currently exists in the working tree** (the latest intent), and explicitly flags where claims are documentation-only vs. verified in code. Every non-trivial claim below was checked against the actual files and, where possible, by running the code and the test suite.

---

## 1. Executive Summary

OMISTOCK is a multi-tenant inventory-management ("gestion de stock") web platform built with **FastAPI + SQLAlchemy + SQLite** on the backend and **vanilla JS + TailwindCSS (CDN) + Chart.js** on the frontend, plus a **PWA mobile/scanner** client and an **MCP server** for AI-agent access. The original project is an academic ERP; the current working tree elevates it substantially toward two explicit goals:

1. **Stock-management theory best practice** — WAC costing, ROP/safety-stock, EOQ, FEFO lots, cycle-count reconciliation, valuation at cost, per-branch inventory as the single source of truth.
2. **AI-agent-ready platform best practice** — a dedicated agent interface (`/api/agent/*`), graded autonomy levels, scoped least-privilege authorization, API-key issuance/rotation/expiry, hash-chained audit log, correlation IDs, human-in-the-loop proposals, and action-level rollback (sale reversal).

**Overall verdict:** This is an unusually mature student/POC project for the two target axes. The *backend domain logic and the agent-governance model are genuinely well-designed* and **verified working** (the app boots, seeds, and **25/25 tests pass**). The weakest areas are (a) the **frontend**, where the agent-governance refactor is only partially adopted, (b) **schema/migration maturity** (SQLite + best-effort `ALTER TABLE`, no Alembic), and (c) a handful of **correctness/consistency bugs** (naive datetimes, audit-chain verification that does not recompute the hash, dependency version drift). None of these are blockers for a demo, but several matter before any production use.

### Maturity ratings (1 = poor, 5 = excellent)

| Aspect | Rating | One-line justification |
|---|---|---|
| Project structure & layering | 4 | Clean 3-layer split (routers → repository/DAL → models); a few flat-import quirks. |
| Backend architecture | 4 | Repository pattern, transactional writes, centralized config. |
| Stock-management theory | 4.5 | WAC, ROP, EOQ, FEFO, cycle count, valuation-at-cost all present and tested. |
| AI-agent readiness | 4 | Separate interface, autonomy levels, scopes, audit chain, HITL — strong design; some gaps. |
| Security | 3.5 | Env-driven secret, key expiry, tenant isolation; tz bugs, version drift, partial hardening. |
| Frontend | 2.5 | Functional ERP/PWA, but shared client + governance UI barely adopted. |
| Data model / persistence | 3 | Good relational model; SQLite + best-effort migrations limit production readiness. |
| Testing | 3.5 | 25 passing tests at repo/service level; no HTTP/route or frontend tests. |
| Documentation | 4 | README, technical summary, walkthrough, migrations doc — thorough but partly aspirational. |

---

## 2. Project Intent

- **Stated intent (README / TECHNICAL_SUMMARY):** "plateforme web moderne de gestion d'inventaire multi-tenant" for multi-site businesses (e.g., Alger/Oran/Constantine), with real-time KPIs, multi-tenant isolation by `company_id`, financial reports, invoices/PDF export, and JWT auth. Sector-agnostic (electronics, pharma, food).
- **Evolved intent (Walkthrough.md + refactor):** harden into (1) a textbook-correct stock engine and (2) an "agent-ready" platform with a governed AI interface. This is the lens the task explicitly asks to evaluate against, and the working tree clearly targets it.

---

## 3. Project Structure & Architecture

### 3.1 Layout (working tree)
```
omistock/
├── backend/
│   ├── main.py            # FastAPI app, CORS, correlation middleware, additive migrations, auto-seed
│   ├── config.py          # 12-factor config (secret, CORS, env, destructive-restore flag)
│   ├── security.py        # JWT create/verify, bcrypt password hashing
│   ├── dependencies.py    # hybrid auth (JWT or X-API-Key) + RBAC role deps
│   ├── database.py        # engine/session, OMISTOCK_DB_PATH
│   ├── models.py          # SQLAlchemy ORM (Company/Branch/User/Product/Inventory/Lot/...)
│   ├── repository.py      # Data Access Layer (all SQL)
│   ├── stock.py           # stock-theory service (WAC/ROP/EOQ/FEFO/valuation/alerts)
│   ├── agent_policy.py    # autonomy levels + scopes + quantity caps
│   ├── audit.py           # hash-chained, tamper-evident audit log
│   ├── services.py        # auth, dashboard stats, MCP analysis
│   ├── schemas.py         # Pydantic v2 request/response models
│   ├── routers/           # auth, products, transfers, admin, agent
│   └── tests/             # conftest + 3 test modules (25 tests)
├── frontend/              # ERP pages, PWA, style.css, api.js, agent-governance.html
├── mcp/server.py          # MCP server (agent tools over /api/agent/*)
├── docs/                  # installation.md, migrations.md
└── README / TECHNICAL_SUMMARY / Walkthrough / Dockerfile / docker-compose.yml
```

### 3.2 Layering — **Good**
A clean three-layer separation is implemented and largely respected:
**Presentation (routers)** → **Data access (`repository.py`)** → **Persistence (`models.py` + SQLite)**, with **`stock.py`** as a domain-service layer and **`audit.py` / `agent_policy.py`** as cross-cutting governance services. Routers delegate to the repository and no longer embed raw SQL for the refactored paths (verified by reading `repository.py` and the routers).

### 3.3 Architectural observations / flaws
- **Mixed import strategy.** `main.py` injects *both* `backend/` and the project root onto `sys.path`, so modules import each other flatly (`import models`, `import stock`) **while** routers import the package form (`from backend import repository`). This works (app boots, tests pass) but is fragile and confusing; a single packaging convention (proper package + relative imports, or a `src/` layout) would be cleaner.
- **Startup side-effects.** `main.py` runs `create_all`, `run_db_migrations()`, and `auto_seed_if_empty()` at import time. Convenient for a demo, but import-time DB writes and seeding are an anti-pattern for testability and production startup (should move behind an explicit CLI / lifespan event).
- **Business logic still partly in `admin.py`.** The admin router is ~708 lines and contains inline aggregation SQL and the MCP-chat + proposal-execution logic, partly bypassing the DAL discipline applied elsewhere.

---

## 4. Backend Review

### 4.1 Data model — **Good**
`models.py` is well-structured: multi-tenant `company_id` on every business entity; `Inventory(product_id, branch_id)` with `UniqueConstraint` + `CheckConstraint(quantity >= 0)`; `Lot` with `expiry_date` for FEFO; `StockMovement` with `actor_id`, `correlation_id`, `reverses_movement_id`, `reversed`; `Sale`/`SaleItem` carrying `total_cost`/`unit_cost` (COGS); `AuditLog` with `prev_hash`/`entry_hash`; `AgentProposal` for HITL. The decision to make **`Inventory` the single source of truth** and treat **`Product.quantity` as a derived cache** (`hybrid_property total_quantity`, recomputed via `stock.recompute_product_quantity`) is the correct inventory-domain choice.

### 4.2 Transactions & integrity — **Good**
Write paths in `repository.py` (`create_sale`, `restock_product`, transfer approve/confirm, `reverse_sale`, `adjust_inventory`) consistently wrap mutations in `try/except` with `db.rollback()` and raise `ValueError` for business errors. Stock-insufficiency checks happen before decrementing. This is solid.

### 4.3 Authentication & authorization — **Mostly good**
- Hybrid auth in `dependencies.py`: JWT Bearer (humans) **or** `X-API-Key` (agents). The previous silent `company_id=1` fallback has been removed — missing/invalid credentials now correctly return 401 (verified).
- RBAC deps: `get_current_admin`, `get_current_human`, `get_current_agent`, `get_current_admin_or_agent`. API keys carry an **expiry** check (`api_key_expires_at`).
- `config.py` reads the JWT secret from env, **refuses to boot in prod without it**, and generates an ephemeral dev key with a clear warning (verified at runtime). Token lifetime reduced to 2h. CORS is an explicit allow-list (no wildcard-with-credentials).

### 4.4 Backend flaws found
1. **Naive `datetime.now()` in several places** (`admin.py` `deletion_deadline = datetime.now() + 30d` and `prop.reviewed_at`, `seed_data.py`, `backup_db.py`), while the rest of the codebase is timezone-aware (`datetime.now(timezone.utc)`). This is a real correctness bug: comparisons/serialization can be off by the server's UTC offset, and the soft-delete 30-day deadline is computed in naive local time. **Fix:** standardize on tz-aware UTC everywhere.
2. **Dependency version drift.** `passlib==1.7.4` + `bcrypt==4.1.2` triggers a `module 'bcrypt' has no attribute '__about__'` error at runtime (observed during seed). It is trapped and non-fatal, but it indicates an unpinned/incompatible combination. **Fix:** pin `bcrypt<4.1` or migrate to a maintained hashing path.
3. **`admin.py` size and responsibility creep** — see §3.3; the proposal-execution and MCP-chat logic should move into services/repository.
4. **Import-time seeding/migration** — see §3.3.

---

## 5. Stock-Management Theory Evaluation

**This is the strongest axis of the project.** Verified in `stock.py`, `repository.py`, and `backend/tests/test_stock_theory.py` (passing).

| Best practice | Implemented? | Evidence |
|---|---|---|
| Single source of truth for quantity | ✅ | `Inventory` per branch; `Product.quantity` is a recomputed cache. |
| Weighted Average Cost (WAC) on receipt | ✅ | `apply_weighted_average_cost()` recalculated before quantity increment in `restock_product`. |
| COGS captured per sale line | ✅ | `SaleItem.unit_cost` snapshot at sale time; `Sale.total_cost` aggregated. |
| Reorder point (ROP = demand×lead + safety stock) | ✅ | `Product.reorder_point` property; falls back to `min_threshold`. |
| Average daily demand from history | ✅ | `compute_avg_daily_demand()` (30-day rolling window, CONFIRMED sales). |
| Economic Order Quantity (Wilson) | ✅ | `economic_order_quantity()` with input guards. |
| FEFO lot consumption (pharma/food) | ✅ | `consume_lots_fefo()` ordered by `expiry_date NULLS LAST`, used in `create_sale`. |
| Expiry alerts | ✅ | `expiring_lots()` within horizon. |
| Inventory valuation **at cost** (not sale price) | ✅ | `stock_value_at_cost()` uses `cost_price`. |
| Low-stock alerting on real on-hand vs ROP | ✅ | `get_alerts()` compares `on_hand <= reorder_point`. |
| Cycle counting / physical reconciliation | ✅ | `adjust_inventory()` computes signed variance, posts an `ADJUST` movement, audited. |

### Stock-theory gaps / improvements
- **No multi-branch ROP per location** — ROP is computed at the product level using aggregated demand; per-branch demand/ROP would be more accurate for multi-site replenishment.
- **PurchaseOrder lifecycle is modeled but not driven** — `PurchaseOrder`/`OrderStatus` exist, but there is no "send → receive → auto-restock at received cost" workflow; receiving is done via the generic `restock_product`. This is acknowledged as deferred. Wiring EOQ/ROP → automatic PO generation would close the replenishment loop.
- **Demand model is a flat moving average** — no seasonality/trend/lead-time variability, so safety stock is essentially a static input rather than service-level-driven (e.g., `z·σ_LT`).
- **WAC keeps the existing cost when `incoming_unit_cost <= 0`** — reasonable, but silently; consider warning/auditing zero-cost receipts.

---

## 6. AI-Agent-Ready Platform Evaluation

**The second target axis, and also strong.** The project implements a coherent governance model rather than a buzzword. Verified in `agent.py`, `agent_policy.py`, `audit.py`, `auth.py`, `dependencies.py`, `mcp/server.py`.

### 6.1 Two separate interfaces (human vs agent) — ✅
- **Humans:** `/api/*` with JWT Bearer; `get_current_human` explicitly **rejects** agents.
- **Agents:** a dedicated `/api/agent/*` surface (10 agent-related routes confirmed via app introspection) authenticated by `X-API-Key`; `get_current_agent` rejects non-agents. The MCP server (`mcp/server.py`) calls **only** `/api/agent/*` with `X-API-Key`, never the human routes — verified in code.

### 6.2 Autonomy levels — ✅
`AutonomyLevel`: `READ_ONLY < SUGGEST < PROPOSE < AUTO`, enforced by `agent_policy.level_at_least`. Reads require READ_ONLY/SUGGEST; proposals require PROPOSE; direct execution requires AUTO. Default for new users/agents is the safest level (`READ_ONLY`).

### 6.3 Authorization model — ✅ (least privilege)
`agent_policy.authorize_agent_action()` checks **type = AGENT**, **autonomy level**, **scope** (fine-grained `domain:action`, wildcard support), and **quantity cap** (`max_action_quantity`; **0 ⇒ no autonomous quantitative action**, a safe default). Verified by `test_agent_readiness.py` (passing).

### 6.4 Human-in-the-loop (HITL) & Separation of Duties — ✅
- Agents at PROPOSE create an `AgentProposal` (`/api/agent/proposals/restock`) that is **pending human approval**.
- An **ADMIN** approves (`/api/agent/proposals/{id}/approve`) — the action is then **executed under the admin's identity** (`actor_id=current_user.id`), realizing SoD: the proposer is not the executor.
- Reject path and "already-processed" guards exist.
- Transfers similarly separate request/approve/confirm.

### 6.5 Audit & traceability — ✅ with one real caveat
- `audit.record()` writes a **hash-chained** entry per company: `entry_hash = sha256(prev_hash | company | user | actor_type | action | entity | old | new | ts)`. Each entry stores `actor_type`, structured `old/new` JSON deltas, `entity_type/id`, and a `correlation_id` linking intent→action→result. Agent reads *and* writes are audited.
- **Caveat / flaw:** `verify_chain()` only checks that `log.prev_hash == previous entry_hash` (link continuity); it **does not recompute `entry_hash`** to confirm the stored fields weren't altered. The stored hash mixes in a `ts` that is not persisted in replayable form (it relies on `func.now()` server default), so a full replay isn't currently possible. **Net effect:** insertion/deletion/reordering is detectable, but **in-place edits of an entry's fields are not.** This weakens the "tamper-evident" guarantee and should be fixed by persisting the canonical timestamp used in the hash and recomputing `entry_hash` during verification.

### 6.6 Credential lifecycle — ✅
Agent API keys are issued **ADMIN-only**, shown **once**, never re-listed in clear (`get_agents` returns a masked key), carry a **TTL/expiry**, and support **rotation** (`/api/agents/{id}/rotate-key`) with audit entries.

### 6.7 Rollback — ✅ (action-level)
`reverse_sale()` performs **compensating** stock movements (re-adds inventory, posts IN movements, marks the sale `REVERSED`) instead of deleting history; double-reversal is rejected. Verified by `test_repository.py`. This is the right "append-only + compensation" rollback model. (There is no generic time-travel/snapshot rollback, which is acceptable for this scope.)

### Agent-readiness gaps / improvements
- **`reviewed_at = datetime.now()` (naive)** on proposal approve/reject — same tz bug as §4.4.
- **No rate limiting / quota** on agent endpoints beyond per-action quantity caps; a runaway AUTO agent is bounded per call but not per time window.
- **Proposal execution supports only `RESTOCK`** (`TRANSFER` etc. raise 400) — the model is generic but only one action type is wired.
- **No per-agent dry-run / simulation endpoint** and **no idempotency key** on agent writes (correlation IDs help trace but don't dedupe retries).

---

## 7. Frontend Review — **Weakest area**

- **Functional ERP UI exists:** `dashboard/inventory/sales/reports/suppliers/logs/settings/index/signup` pages, a shared `style.css`, a shared `erp-sidebar.js` (responsive sidebar), and a **PWA** (`manifest.json`, `sw.js` stale-while-revalidate, `app_mobile.html`, `mobile_scan.html` barcode scanner). These are legitimate and reasonably polished for a POC.
- **Shared API client (`api.js`) barely adopted — real gap.** `api.js` is a clean `window.OmiAPI` wrapper (token handling, 401-redirect, REST + business helpers). But it is referenced by **only one page: `agent-governance.html`**. The 7 core ERP pages still use raw inline `fetch()` (measured: dashboard 12, settings 13, sales 9, suppliers 8, inventory 7, logs 5, reports 4 inline `fetch(` calls; **zero** use `OmiAPI`). So the stated "eliminate duplicated fetch logic" refactor is **largely unrealized** in the human ERP.
- **Agent-governance UI is orphaned.** `agent-governance.html` (the human supervision screen for proposals + audit-chain verification — exactly the right idea) is **not linked from any other page** (no nav entry, no sidebar item). A reviewer/operator would have to know the URL. It should be wired into the ERP navigation and into the sidebar for admins.
- **Heavy reliance on CDNs** (Tailwind, Chart.js, html5-qrcode, Google Fonts) — fine for a demo, but a production build should self-host/bundle (also closes the "100% offline" gap the docs acknowledge).
- **No frontend tests** and large monolithic HTML files (dashboard/settings are ~50KB each) with embedded JS.

---

## 8. Data, Migrations & Persistence

- **SQLite** with `check_same_thread=False`. Fine for dev/POC; not suitable for concurrent multi-tenant production write loads.
- **`run_db_migrations()`** performs **additive, best-effort `ALTER TABLE ... ADD COLUMN`** guarded by try/except. `docs/migrations.md` honestly documents this as transitional and recommends Alembic. **Flaw:** no real versioned migrations; no down-migrations; SQLite can't alter/drop columns/constraints in place, so schema evolution beyond adding columns is unmanaged.
- **Backup/restore:** JSON backup/restore is company-scoped; destructive raw `.db`/`.sql` restore is **disabled by default** (`OMISTOCK_ALLOW_DESTRUCTIVE_RESTORE`), a good hardening over the earlier design described in the docs.

---

## 9. Testing & Verification (performed during this review)

Run with the project venv (`omistock/.venv`, SQLAlchemy 2.0.25):

- **`pytest backend/tests` → 25 passed, 0 failed** (verified; matches the claimed count).
- **App import/boot:** `import main` succeeds, runs additive migrations, auto-seeds dev data, and registers **62 routes** (claim was 63; close — the difference is incidental). Dedicated `/api/agent/*` surface and the proposal lifecycle endpoints are present.
- **Coverage shape:** tests cover the *domain/repository/service* layer well (WAC, COGS, sale reversal + double-reverse rejection, cycle-count variance, FEFO, ROP/alerts, valuation-at-cost, EOQ, agent authorization). **Gaps:** no HTTP/route-level tests (the in-repo note explains a `TestClient`/httpx/starlette version mismatch), no auth/RBAC integration tests, no audit-chain *tamper* test (which would have surfaced the §6.5 verify-chain limitation), no frontend tests.

---

## 10. Consolidated Findings

### Strengths
- Correct inventory domain model (per-branch source of truth; derived product cache).
- Genuinely textbook stock theory: WAC, COGS, ROP, EOQ, FEFO, valuation-at-cost, cycle count — all tested.
- Coherent, non-superficial **agent-governance** model: separate interface, autonomy levels, scoped least-privilege, key TTL/rotation, HITL proposals with SoD, correlation IDs, hash-chained audit, compensating rollback.
- Sensible security posture: env-driven secret with prod fail-fast, key expiry, explicit CORS, no silent tenant fallback.
- Clean layering and transactional DAL; honest, thorough documentation.

### Flaws / Errors (prioritized)
1. **(High) Audit `verify_chain` does not recompute `entry_hash`** — only link continuity is checked, so in-place field edits are undetectable; the persisted timestamp isn't replayable. Undermines the tamper-evident claim.
2. **(Med-High) Naive `datetime.now()`** for `deletion_deadline`, `reviewed_at`, seed/backup timestamps — tz-inconsistent with the rest of the code; affects the 30-day soft-delete logic.
3. **(Med) Frontend refactor unrealized** — `api.js` used by 1/8 pages; 7 ERP pages keep duplicated inline `fetch`; `agent-governance.html` is unlinked/orphaned.
4. **(Med) Dependency drift** — `passlib`/`bcrypt` mismatch throws a (trapped) error at runtime; unpinned combination.
5. **(Med) Persistence/migrations** — SQLite + best-effort `ALTER TABLE`, no Alembic, no real schema versioning; not production-grade.
6. **(Low-Med) `admin.py` responsibility creep** and **import-time migrations/seeding**.
7. **(Low) Proposal execution only supports `RESTOCK`**; PurchaseOrder lifecycle and per-branch ROP deferred.
8. **(Low) Branch metadata mismatch** between docs/reports (`main`/HEAD) and the authoritative working branch `mainbr`.

---

## 11. Recommended Improvements (roadmap)

**Correctness / security (do first)**
1. Make `verify_chain` recompute `entry_hash`: persist the exact canonical timestamp string used in `record()` (e.g., a dedicated `hash_ts` column) and replay it; add a tamper test.
2. Replace all naive `datetime.now()` with `datetime.now(timezone.utc)`.
3. Pin compatible `bcrypt`/`passlib` (or move to a maintained hasher) and re-pin `requirements.txt`.
4. Add rate limiting / time-windowed quotas to `/api/agent/*` (defense-in-depth beyond per-action caps); add idempotency keys for agent writes.

**Architecture / data**
5. Adopt **Alembic** and stop import-time `create_all`/migrate/seed; move seeding to an explicit CLI; move startup hooks to a lifespan handler.
6. Move aggregation/MCP/proposal-execution logic out of `admin.py` into services/repository.
7. Plan a Postgres path for production (SQLite is fine for the demo).

**Stock theory**
8. Compute demand/ROP **per branch**; introduce service-level safety stock (`z·σ_LT`).
9. Wire the **PurchaseOrder lifecycle** and EOQ/ROP → auto-PO generation; receive POs at recorded cost feeding WAC.

**Agent platform**
10. Support more proposal action types (transfer, price changes) with the same HITL/audit pattern; add a dry-run/simulation endpoint.

**Frontend**
11. Migrate all ERP pages to `OmiAPI` and remove duplicated `fetch` logic; add an admin nav entry to `agent-governance.html`.
12. Self-host/bundle CDN assets; add basic frontend tests; consider splitting the largest HTML files.

**Process**
13. Add HTTP/route + RBAC integration tests (resolve the `TestClient` version mismatch by pinning compatible `httpx`/`starlette`).
14. Reconcile branch/HEAD metadata in docs with the authoritative branch and commit the refactor.

---

## 12. Methodology & Evidence

This report is grounded in direct inspection and execution of the workspace files (not snippets): `models.py`, `database.py`, `config.py`, `security.py`, `dependencies.py`, `repository.py`, `stock.py`, `agent_policy.py`, `audit.py`, `main.py`, the routers (`auth.py`, `agent.py`, `admin.py`), `mcp/server.py`, frontend (`api.js`, `agent-governance.html`, ERP pages), `docs/migrations.md`, and the test suite. Verifications performed: `git` branch/diff inspection; `pytest backend/tests` (**25 passed**); app import + route enumeration (**62 routes**, agent surface + proposal lifecycle present); grep-based measurement of frontend `fetch`/`OmiAPI` adoption; runtime confirmation of the dev-secret warning and the passlib/bcrypt version error. Limitations: HTTP route-level behavior was not exercised end-to-end (known `TestClient`/httpx/starlette version mismatch in the env); review of the largest HTML pages was structural rather than line-by-line.
