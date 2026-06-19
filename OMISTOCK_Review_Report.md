# OMISTOCK — Deep Code Review & Architecture Assessment

> **Repository:** https://github.com/sarahgacem/omistock (working branch `mainbr`; committed baseline HEAD `2346ca6`)
> **Note:** the *committed* baseline (`2346ca6`) is the original design; the review below was conducted against the **working tree** of `mainbr`, which carries a large, verified, not-yet-committed hardening refactor (see Addendum). Ratings in §1 describe the original baseline; the Addendum records the hardened state.
> **Reviewed:** 2026-06-17
> **Reviewer scope:** full source (backend, frontend, MCP layer, infra, docs)
> **Method:** repository cloned locally and read in full; routes, models, dependencies, MCP tools and committed artifacts inspected directly.

> ⚠️ **Branch note.** The default `master` branch is *behind* `main` and is missing the `routers/`, `repository.py`, `services.py`, RBAC, MCP and Docker work. This review targets **`main`**, which is the version referenced in the prompt and the one containing the complete feature set. A reader who clones the repo without specifying `--branch main` (or whose `git clone` resolves `master`) will see a much smaller, older project. *This branch divergence is itself a project-hygiene problem (see §9).*

---

## 1. Executive Summary

OMISTOCK is an academic / demonstration **multi-tenant inventory ERP** built for an oral defense (*soutenance*). The stack is **FastAPI + SQLAlchemy + SQLite** on the backend, **vanilla JS + TailwindCSS (CDN) + Chart.js** on the frontend, plus a small **Model Context Protocol (MCP) server** that exposes inventory "intelligence" tools to an AI agent. It supports multiple companies (tenants), multiple branches/depots per company, products, suppliers, sales/invoicing, inter-branch transfers, an audit log, soft-delete account lifecycle, and DB backup/restore.

The project is **genuinely ambitious for its category** and the *intent* is clear and well-documented (`Walkthrough.md`, `TECHNICAL_SUMMARY.md`): present a clean 3-layer architecture (routers → repository/DAL → models), demonstrate multi-tenant isolation, role-based access, and an "AI-ready" MCP integration.

However, against **production stock-management best practice** and **AI-agent-platform best practice**, the implementation has substantial gaps. It is best characterized as a **strong student/demo prototype** with real architectural intent but with security defects, a fragile data model, and an "agent layer" that is conceptually present but functionally shallow and partly dead code.

**Overall maturity rating (indicative):**

| Axis | Rating (/5) | One-line justification |
|------|:-----------:|------------------------|
| Project structure | 3.0 | Clean 3-layer intent, but stray files, committed secrets, branch divergence |
| Backend architecture | 3.0 | Good DAL refactor; SQLite + dual quantity model + weak transactions limit it |
| Frontend | 2.5 | Functional, consistent design system, but no build, CDN-only, logic duplicated, tokens in localStorage |
| Security | 1.5 | Hard-coded secret, `CORS *` + credentials, committed DB backups, weak agent auth |
| Stock-management theory | 2.0 | Movements/transfers exist; no reorder logic, no valuation method, no lead time, no costing |
| AI-agent readiness | 2.0 | MCP exists and 2-interface idea is present, but no autonomy model, weak authz, no rollback |

---

## 2. Project Structure

```
omistock/
├── backend/
│   ├── main.py                # app bootstrap, CORS, "tenant" middleware, migrations, autoseed
│   ├── database.py            # SQLite engine/session
│   ├── models.py              # SQLAlchemy ORM (Company, Branch, User, Product, Inventory, ...)
│   ├── schemas.py             # Pydantic v2 schemas
│   ├── security.py            # JWT + bcrypt helpers
│   ├── dependencies.py        # auth + RBAC dependencies
│   ├── mcp_auth.py            # ⚠ DEAD CODE: separate MCP auth, never imported by any route
│   ├── services.py            # business logic (dashboard stats, signup, login, MCP "analyze")
│   ├── repository.py          # Data Access Layer (DAL)
│   ├── seed_data.py / init_db.py  # two overlapping seeders
│   ├── backup_db.py
│   └── routers/{auth,products,transfers,admin}.py
├── frontend/                  # ~15 standalone HTML pages + style.css + erp-sidebar.js + PWA
├── mcp/server.py              # FastMCP server exposing 3 tools to an AI agent
├── docs/installation.md
├── Dockerfile / docker-compose.yml
├── README.md / TECHNICAL_SUMMARY.md / Walkthrough.md / CONTRIBUTING.md
├── backup_omistock_2026_05_18.zip / _2026_05_25.zip   # ⚠ committed DB backups (leak hashes)
├── ngrok_test_log.txt / mobile_qr.png
├── check_db.py / check_users.py                        # ad-hoc debug scripts
└── "s -ExecutionPolicy RemoteSigned) ; (& c...Activate.ps1)"  # ⚠ junk file from a broken shell paste
```

**Strengths**
- Clear separation backend / frontend / mcp / docs.
- The 3-layer pattern (routers → `repository.py` → models) is real and consistently applied for products, sales and transfers.
- Documentation is unusually thorough for a student project, with Mermaid ER and flow diagrams.

**Problems**
- **Committed artifacts that should never be in VCS:** two `backup_*.zip` files (each a full SQLite DB), `ngrok_test_log.txt`, `mobile_qr.png`, and a literal junk filename created by pasting a broken PowerShell command into the shell and `git add`-ing the result.
- **`.gitignore` ignores `*.db`** but the zipped DB backups bypass it — and the live DB was clearly committed at some point (the backups exist in-repo).
- **Two seeders** (`init_db.py` and `seed_data.py`) with overlapping but slightly different logic → maintenance hazard / drift.
- **Ad-hoc debug scripts** (`check_db.py`, `check_users.py`) committed at the repo root.
- **`master`/`main` divergence** (`main` is 34 ahead / 17 behind `master`): the canonical branch is ambiguous.

---

## 3. Backend Architecture

### 3.1 What's good
- **FastAPI** with Pydantic v2 schemas, dependency injection, and a tidy DAL (`repository.py`). Routers no longer issue raw SQL (mostly — see exceptions below), which is the explicit goal of the refactor and is largely achieved.
- **Transactional writes** in the DAL for sales and transfers use `try/except` + `db.rollback()` and raise `ValueError` for business errors (insufficient stock, invalid status) → translated to HTTP 400. This is the right shape.
- A **CHECK constraint** `quantity >= 0` exists on `Inventory`.
- **Transfer workflow** models a real two-step approval (`PENDING → APPROVED → CONFIRMED`), decrementing source on approve and incrementing destination on confirm, with `StockMovement` records on each leg.

### 3.2 Architectural flaws

1. **Dual, denormalized quantity (data-integrity time bomb).** Stock is stored in *two* places: `Product.quantity` (a global per-product total) **and** `Inventory.quantity` (per branch). The code tries to keep them in sync manually in several places (`repository.py` lines 119, 243, 354; `services.py` line 34 mutates `product.quantity` in memory). This is fragile:
   - `get_alerts()` filters on **`Product.quantity`** (the global field), while the branch dashboard recomputes alerts from **`Inventory.quantity`** → two different "alert" truths for the same product.
   - `restock` and `create_sale` both adjust the global counter with ad-hoc `max(0, ...)` arithmetic that can silently diverge from the sum of inventories.
   - **Recommendation:** make `Inventory` the single source of truth; derive product totals via a query/`hybrid_property`, never store them.

2. **SQLite for a multi-tenant ERP.** `check_same_thread=False` + SQLite file means: no real concurrency, table-level write locks, no migrations engine, and "restore" implemented by **overwriting the live DB file** (`admin.py` `restore_database`). Fine for a demo; unacceptable for production. There is no Alembic; schema evolution is done by best-effort `ALTER TABLE … ; except: pass` in `run_db_migrations()`.

3. **Tenant isolation is enforced by convention, not by the framework.** Every query manually `.filter(... company_id == cid)`. The `TenantIsolationMiddleware` in `main.py` is effectively a **no-op** — it decodes the JWT for PUT/DELETE and then literally `pass`es (`# Ici on pourrait ajouter une vérification`). So the "middleware de sécurité" advertised in `TECHNICAL_SUMMARY.md` does nothing. Several read endpoints also fall back to `company_id = 1` when `current_user` is `None`, which can leak tenant 1's data if auth is ever bypassed.

4. **Inconsistent layering.** `admin.py` still contains large amounts of **raw `db.query` / inline HTML invoice generation** (the `restock`, invoice and purchase-order HTML routes), contradicting the "routers contain no SQL" principle stated in the Walkthrough. `services.get_dashboard_stats_data` also queries directly. The refactor is partial.

5. **Two overlapping auth modules, with dead code.** `mcp_auth.py` (`get_mcp_agent`) and `dependencies.get_current_agent_by_api_key`/`get_current_agent_ai` are **never referenced by any route** (verified by grep). The actual hybrid JWT/API-key logic lives only in `get_current_user`. This is confusing and inflates the attack/maintenance surface.

6. **Doc/code contradiction on RBAC.** `TECHNICAL_SUMMARY.md` claims `get_current_agent_ai` "validates access for ADMIN and autonomous AGENT". The code does the opposite: `get_current_agent_ai` rejects everyone except `user_type == "AGENT"` — and is never used anyway.

7. **Error handling swallows context.** Many `except Exception: pass` blocks (JWT fallback, migrations) hide real failures. The login/JWT path catches *all* exceptions and silently falls through to API-key auth.

8. **No tests.** There is not a single automated test, despite the Walkthrough explicitly listing "unit tests on repository.py with in-memory SQLite" as a *future* item.

---

## 4. Security Review (high priority)

| # | Severity | Issue | Evidence |
|---|----------|-------|----------|
| S1 | **Critical** | **Hard-coded JWT secret** committed in source: `SECRET_KEY = "SUPER_SECRET_POUR_OMISTOCK_2026"`. Anyone can forge tokens for any tenant. | `backend/security.py` |
| S2 | **Critical** | **Committed DB backups leak data + bcrypt hashes.** The two `backup_*.zip` files unzip to full SQLite DBs; I confirmed they contain `users` rows with `hashed_password` (e.g. `admin@test.com`, `$2b$12$...`). | `backup_omistock_2026_05_25.zip` (verified) |
| S3 | **High** | **`CORS allow_origins=["*"]` together with `allow_credentials=True`.** This combination is invalid/insecure and lets any site drive the API. | `backend/main.py` |
| S4 | **High** | **Weak agent identity.** AI "agents" are auto-created with `hashed_password=None` and an API key; any read endpoint accepts the API key with the *same* power as a human via `get_current_user`. There is no scope limiting what an agent key can do. | `dependencies.get_current_user`, `auth.create_agent_route`, `products.analyze_product_mcp_post` |
| S5 | **High** | **Restore endpoint = arbitrary DB overwrite / `executescript`.** `POST /api/admin/restore` runs raw SQL via `raw_conn.executescript(sql_script)` and can overwrite the live `.db` file. An admin (or a forged admin token via S1) gets effectively arbitrary DB control. | `admin.py restore_database` |
| S6 | Medium | **JWT in `localStorage`** on every page → XSS-exfiltratable; tokens valid 24h with no refresh/rotation/revocation. | `frontend/index.html`, all pages |
| S7 | Medium | **Self-service privilege grant.** `get_current_agent_human` lets any `HUMAIN` user mint AGENT API keys (`POST /api/agents`); no admin gate, no per-agent scope. | `auth.py` |
| S8 | Medium | **No rate limiting / lockout** on `/token`; demo passwords (`password123`) and quick-login buttons hard-coded in the UI. | `index.html`, `seed_data.py` |
| S9 | Low | **Purge-on-login is destructive and unguarded.** A login attempt after the 30-day deadline triggers an irreversible cascade delete of the whole company inside `authenticate_user`. A side-effect this large in an auth path is dangerous (and runs before password re-confirmation logic in a way that couples deletion to login). | `services.authenticate_user` |
| S10 | Low | **ngrok tunnel + `ngrok-skip-browser-warning` headers** baked into the frontend; tunnel logs committed. | `index.html`, `ngrok_test_log.txt` |

---

## 5. Frontend Review

**Architecture:** ~15 standalone HTML pages, each shipping its own `<script>` block, sharing `style.css` (a real, centralized design system) and `erp-sidebar.js` (shared mobile menu). A separate **mobile PWA** (`app_mobile.html`, `mobile_scan.html`) with manifest + service worker (stale-while-revalidate, `/api/*` excluded from cache) and a barcode scanner (html5-qrcode).

**Strengths**
- Coherent, modern visual design; consistent components (`.glass`, `.card`, `.btn-premium`, status badges).
- The CSS centralization (Step 1) and responsive sidebar (Step 2) refactors are real and good pedagogy.
- PWA installability + offline UI shell is a nice "field" touch for warehouse scanning.
- Real data wiring (e.g., the branch-distribution chart was de-mocked to use API data).

**Problems**
- **No build pipeline / no bundler / no framework.** Tailwind via CDN (`cdn.tailwindcss.com`) is explicitly *not for production*. Google Fonts + CDNs are runtime dependencies.
- **Heavy logic duplication** across pages (auth headers, token handling, fetch boilerplate repeated in every file). `dashboard.html` alone is 788 lines, `settings.html` and `app_mobile.html` ~892 lines each.
- **Security coupling:** tokens read from `localStorage` and attached as `Bearer` on every fetch; no central API client; no CSRF/JWT-expiry handling beyond "redirect on 401".
- **No accessibility** considerations (ARIA, focus management) and no i18n (UI is French only, mixed with English code comments).
- **"MCP chat" in the UI is a fake.** `POST /api/mcp/chat` (used by `test-mcp.html` and dashboard) returns **hard-coded canned strings** (e.g. "hausse de 12% sur les produits Pharma… augmenter le stock d'Amoxicilline") regardless of real data. This is a mock masquerading as agent intelligence.

---

## 6. The "AI Agent" / MCP Layer

There are effectively **three** different "AI" surfaces, which is itself a sign of unfinished design:

1. **`mcp/server.py` (FastMCP)** — the *real* MCP server. Exposes 3 tools to an external agent/LLM: `get_stock_alerts`, `get_business_summary`, `predict_stockout`. These call the REST API over HTTP using an `X-API-Key`. This is the architecturally correct "agent talks to the platform through the same API" pattern. ✅
2. **`POST /api/mcp/analyze`** — server-side heuristic in `services.analyze_product_mcp`. Its "prediction" is **not real forecasting**: it counts audit-log rows matching `%OUT%/%Vente%/%SELL%` and computes `vitesse_vente_jour = (count*2)+1` — a meaningless formula that ignores per-product history, time windows and branch. ⚠
3. **`POST /api/mcp/chat`** — pure canned-text mock (see §5). ❌

**MCP correctness bugs**
- `mcp/server.py` `get_business_summary` and `predict_stockout` call `GET /api/audit_logs` / `/api/sales` / `/api/inventory` with an **API key for an AGENT user**, but `/api/audit_logs` is guarded by `get_current_admin_or_agent` (OK) while the *forecasting* logic in `predict_stockout` divides total sold by a fixed `30` days regardless of actual sales dates — inconsistent with the server-side `analyze` heuristic. Two different, both-wrong, stock-out models coexist.
- `mcp/requirements.txt` is **absent on `main`** (it exists only on `master`), so `mcp/server.py` has no pinned deps on the canonical branch.

---

## 7. Evaluation Axis A — Stock-Management Theory Best Practice

This is where the gap between "ERP" branding and reality is largest. Assessed against standard inventory-management theory:

| Concept | Status | Notes |
|---|---|---|
| Multi-warehouse / per-location stock | ✅ Partial | `Inventory` per `Branch` exists; but undermined by the redundant `Product.quantity` global field. |
| Stock movements / ledger | ✅ | `StockMovement` (IN/OUT) is recorded for sales, restock, transfers — a real movement ledger. |
| Inter-branch transfers | ✅ | Two-step approve/confirm workflow with movements. Good. |
| Min threshold / low-stock alert | ⚠ Basic | Single `min_threshold` per product/inventory; flat reorder point only. |
| **Reorder point with lead time** | ❌ | No supplier lead time anywhere; ROP = min_threshold only. No `ROP = demand × lead_time + safety_stock`. |
| **Safety stock** | ❌ | Not modeled. |
| **EOQ / economic order quantity** | ❌ | No order-quantity optimization; restock quantity is manual. |
| **Demand forecasting** | ❌ | The "predictions" are toy heuristics (`count*2+1`, or `total/30`), not statistical forecasts. |
| **Inventory valuation method (FIFO/LIFO/WAC)** | ❌ | Stock value = `quantity × Product.price` (a single sell/list price). No cost vs price separation, no costing method. Margin/profit ("calcul de bénéfices" in README) cannot be correct without cost. |
| **Cost vs. selling price** | ❌ | `Product.price` is overloaded; `RestockCreate.purchase_price` exists in schema but is **ignored** by the restock route. |
| **ABC / XYZ classification** | ❌ | Absent. |
| **Cycle counting / physical inventory / variance** | ❌ | No stock-take or adjustment-with-variance flow. |
| **Lot / batch / expiry tracking** | ❌ | Critical for the Pharma/Food sectors the demo targets (Doliprane, food oil) — no batch or expiry, no FEFO. |
| **Serial numbers / barcode→unit** | ⚠ | Barcode field exists; scanner exists; but no per-unit serialization. |
| **Backorder / reservation / allocation** | ❌ | Sales just hard-fail on insufficient stock; no reservation/allocation. |
| **Purchase orders** | ⚠ | `PurchaseOrder`/`PurchaseOrderItem` models exist but are barely wired; "purchase order" is generated as an HTML printout from a single restock movement, not a real PO lifecycle (draft→sent→received). |
| **Audit trail of stock changes** | ✅ Partial | `AuditLog` captures actions; but `old_value/new_value` are free-text strings, not structured deltas. |

**Verdict (Axis A): ~2/5.** The *transactional* core (movements + transfers + per-branch inventory) is present and is the project's strongest stock feature. But the project lacks essentially **all replenishment science** (ROP/safety stock/EOQ/lead time), **valuation/costing** (so financial reports are unreliable), and **regulatory-grade tracking** (lot/expiry/FEFO) that the chosen demo verticals (pharma, food) specifically require.

---

## 8. Evaluation Axis B — AI-Agent-Ready Platform Best Practice

Assessed against the criteria you specified: two separate interfaces (human vs agent), autonomy levels, authorization model, audit & traceability, rollback.

### B.1 Two separate interfaces (human vs agent)
- **Partially present, conceptually.** Humans use JWT (web UI); agents use `X-API-Key` (MCP). There is a distinct `AGENT` user type and a distinct MCP server.
- **But the separation is shallow and leaky:**
  - `get_current_user` accepts **both** JWT and API key and returns the same `User` with the same powers — there is *no separate, narrower API surface for agents*. An agent key can call the same human endpoints.
  - The "agent interface" the dashboard shows users (`/api/mcp/chat`, `/api/mcp/analyze`) is server-side mock/heuristic, not the MCP server.
  - Dead `mcp_auth.py` suggests a cleaner agent boundary was *intended* but never finished.
- **Best practice gap:** a real agent-ready platform exposes a **purpose-built, scoped, machine-friendly API** (idempotency keys, structured tool schemas, capability-limited tokens) distinct from the human session API. Here the two share the same routes and the same authority.

### B.2 Autonomy levels
- **Absent.** There is no notion of agent autonomy tiers (e.g. *read-only / suggest / propose-with-human-approval / auto-execute*). The MCP tools are **read-only** (`get_stock_alerts`, `get_business_summary`, `predict_stockout`) — which is *de facto* the safest level — but this is by omission, not by design. There is no policy/config that says "this agent may restock automatically up to N units" or "agent may propose but a human must approve."
- The transfer workflow *could* have modeled human-in-the-loop autonomy (agent proposes transfer → human approves), but agents have no write path at all, so the human-approval safety net is unused for agents.
- **Best practice gap:** define explicit autonomy levels per agent/per action, with guardrails (spend/quantity caps, allowed action lists, time windows).

### B.3 Authorization model
- **RBAC exists** (`ADMIN`, `HUMAIN`, `AGENT`) via FastAPI dependencies — a good foundation.
- **But weak in practice:**
  - Agents and humans collapse into `get_current_user` for most routes; agent scoping is not enforced.
  - Any `HUMAIN` can mint agent keys (privilege escalation surface).
  - API keys are **bearer secrets with no scopes, no expiry, no rotation, no per-tool permissions**.
  - The documented agent-AI dependency is dead code; the real authorization for agents is "whatever `get_current_user` allows."
- **Best practice gap:** capability-scoped agent credentials, least-privilege per tool, admin-gated issuance, key rotation/expiry, and an explicit allow-list of agent-permitted operations.

### B.4 Audit & traceability
- **Best-developed agent dimension.** There is an `AuditLog` table; sales, transfers, restocks and the `analyze` action are logged; the `logs.html` UI can **filter by `AGENT`** and shows old→new values; CSV export exists (`/api/audit/export`).
- **Gaps:**
  - `old_value`/`new_value` are unstructured free text (`"Qty:50"`, `"N/A"`), not machine-parseable diffs.
  - **No correlation / request ID** linking an agent decision to the resulting state change.
  - Read-only agent calls (alerts/summary) are **not** audited — only the server-side `analyze` is, and it logs against an auto-created synthetic agent account.
  - No tamper-evidence (no hash chaining / append-only guarantee); audit rows are deletable (`clean_database`, purge, restore all wipe them).

### B.5 Rollback / reversibility
- **Essentially absent at the action level.** There is:
  - **DB-level backup/restore** (`/api/admin/backup`, `/api/admin/restore`) — coarse, destructive, all-or-nothing, and itself a security risk (S5). This is *disaster recovery*, not *action rollback*.
  - **Transaction rollback** inside a single DAL call (`db.rollback()` on error) — protects atomicity of one operation, but is not user-facing undo.
- **No per-action undo / compensating transactions.** A confirmed sale or transfer cannot be reversed through a first-class "reverse this movement" operation; you'd have to hand-craft a counter-movement. For an agent platform this is a major gap: autonomous actions need cheap, auditable, reversible compensations.
- **Best practice gap:** model every state change as a reversible command with a compensating action, expose "undo last agent action," and keep rollback scoped (per movement/sale) rather than per-database.

**Verdict (Axis B): ~2/5.** The *vocabulary* of an agent-ready platform is present (MCP tools, AGENT role, audit log, RBAC scaffolding) and the team clearly understood the direction. But the *guarantees* that make a platform safe for autonomous agents — scoped credentials, explicit autonomy levels, structured/tamper-evident audit with correlation IDs, and action-level rollback — are missing or mocked.

---

## 9. Bugs, Errors & Inconsistencies (consolidated)

1. **Dual quantity divergence** — `Product.quantity` vs `Inventory.quantity` can desync; `get_alerts` (global) and dashboard branch alerts (per-branch) disagree. *(§3.2-1)*
2. **No-op tenant middleware** advertised as a security feature. *(§3.2-3)*
3. **Dead code:** `mcp_auth.py`, `get_current_agent_ai`, `get_current_agent_by_api_key` are never wired. *(§3.2-5)*
4. **Doc vs code contradiction** on `get_current_agent_ai` semantics. *(§3.2-6)*
5. **`/api/mcp/chat` returns hard-coded text**, including a fabricated "Amoxicilline" recommendation. *(§5)*
6. **`predict_stockout` (MCP)** and **`analyze_product_mcp` (server)** use two different, both invalid, stock-out formulas. *(§6)*
7. **`RestockCreate.purchase_price` is accepted but ignored** → cost never captured → margins/valuation wrong. *(§7)*
8. **`render.yaml` referenced in commit history is absent on `main`**, and `mcp/requirements.txt` is absent on `main` (present on `master`) → broken/ambiguous deploy artifacts. *(§1, §6)*
9. **Two seeders** (`seed_data.py`, `init_db.py`) that both wipe and repopulate, with divergent data. *(§2)*
10. **Auto-seed on startup** (`auto_seed_if_empty`) creates demo accounts with known password `password123` in any fresh/empty deployment. *(security + correctness)*
11. **Purge-in-login** side effect (irreversible cascade delete during authentication). *(§4-S9)*
12. **Frontend assumes server origin** but docs/`installation.md` tell users to "open `frontend/index.html` in a browser" (file://), which `index.html` itself warns against → contradictory instructions.
13. **Junk committed file** from a broken shell paste (`"s -ExecutionPolicy RemoteSigned)..."`).

---

## 10. Prioritized Recommendations

### P0 — Security / correctness (do first)
1. **Rotate & externalize the JWT secret** to an env var / secrets manager; never commit it. Invalidate all existing tokens.
2. **Purge the committed `backup_*.zip`, `ngrok_test_log.txt`, the live DB and the junk file from git history** (e.g. `git filter-repo`), and add them to `.gitignore`.
3. **Fix CORS:** replace `allow_origins=["*"]` + credentials with an explicit allow-list, or drop credentials.
4. **Lock down `/api/admin/restore`**: forbid raw `executescript` and live-file overwrite, or restrict to a controlled import format with validation; require re-authentication.
5. **Decouple purge from login**: move account purge to a scheduled job, not the auth path.

### P1 — Data model & stock correctness
6. **Eliminate `Product.quantity`**; make `Inventory` the single source of truth; expose totals via a computed query.
7. **Add cost vs price separation and a valuation method** (start with weighted-average cost); use `purchase_price` in restock; recompute reports/margins on cost.
8. **Add supplier lead time + reorder point + safety stock**; compute alerts as `on_hand ≤ ROP`.
9. **Add lot/batch + expiry + FEFO** for pharma/food verticals; add cycle-count/adjustment flow with variance logging.
10. **Promote PurchaseOrder to a real lifecycle** (draft→sent→received→stock-in) instead of an HTML printout.
11. **Move off SQLite to Postgres + Alembic migrations** before any multi-user deployment; remove `ALTER…except:pass` migrations.

### P2 — AI-agent platform hardening
12. **Define autonomy levels** per agent (read / suggest / propose-with-approval / auto-execute) and enforce them in dependencies.
13. **Give agents a dedicated, scoped API** distinct from human routes; issue **capability-scoped, expiring, rotatable** agent credentials; admin-gate issuance.
14. **Route agent write actions through human-in-the-loop approval** (reuse the transfer approve/confirm pattern) for medium/high autonomy.
15. **Make the audit log structured & tamper-evident**: JSON deltas, correlation/request IDs linking agent intent → action → result; append-only / hash-chained; protect it from `clean`/restore.
16. **Implement action-level rollback / compensating transactions** ("reverse this sale/transfer/restock"), separate from DB backup.
17. **Replace mock `analyze`/`chat`** with a real forecasting service (or clearly label them as demos) and consolidate the three "AI" surfaces into one.

### P3 — Engineering hygiene
18. **Add automated tests** (pytest + in-memory SQLite/Postgres test DB), starting with `repository.py`.
19. **Remove dead code** (`mcp_auth.py`, unused dependencies) and **the duplicate seeder**.
20. **Reconcile branches** — pick `main` as canonical, fast-forward or delete `master`; align deploy artifacts (`render.yaml`, `mcp/requirements.txt`).
21. **Frontend:** introduce a tiny shared `api.js` client (one place for base URL, auth header, 401 handling), self-host fonts, and pin a real Tailwind build for production.
22. **Fix contradictory install docs** (always run via the server, never `file://`).

---

## 11. Conclusion

OMISTOCK demonstrates **clear architectural intent and solid effort**: a working multi-tenant inventory app with a real DAL, an approve/confirm transfer workflow, an audit log, a polished UI, a PWA, and an MCP server — an impressive scope for an academic project. The *direction* on both evaluation axes is recognizable: the team understood that stock systems need movements/transfers/auditing, and that an AI-ready platform needs separate human/agent paths, roles, audit and recovery.

However, measured against the two required best-practice bars:

- **Stock-management theory (~2/5):** strong on the transactional ledger and multi-branch model, but missing the replenishment science (ROP/safety stock/EOQ/lead time), valuation/costing (making financial reports untrustworthy), and lot/expiry/FEFO tracking that its own pharma/food demo data demands.
- **AI-agent readiness (~2/5):** the building blocks exist (MCP tools, AGENT role, RBAC scaffold, audit log) but the *safety guarantees* do not — no autonomy levels, leaky and unscoped agent authorization, partly dead auth code, mock "intelligence," unstructured non-tamper-evident audit, and only coarse DB-level (not action-level) rollback.

Combined with concrete security defects (hard-coded secret, committed DB backups with password hashes, `CORS *`+credentials, dangerous restore endpoint), the project is **a good prototype and a strong learning artifact, but not production-grade and not yet a safe autonomous-agent platform.** The P0/P1/P2 actions above are the shortest path from "demo" to "credible."

---

### Appendix — Evidence index (files inspected)
`backend/`: `main.py`, `database.py`, `models.py`, `schemas.py`, `security.py`, `dependencies.py`, `mcp_auth.py`, `services.py`, `repository.py`, `seed_data.py`, `init_db.py`, `routers/{auth,products,transfers,admin}.py`. `mcp/server.py`. `frontend/`: `index.html`, `dashboard.html`, `inventory.html`, `logs.html`, `settings.html`, `test-mcp.html`, `app_mobile.html` (sections). Infra: `Dockerfile`, `docker-compose.yml`. Docs: `README.md`, `TECHNICAL_SUMMARY.md`, `Walkthrough.md`, `CONTRIBUTING.md`, `docs/installation.md`. Verified artifacts: `backup_omistock_2026_05_25.zip` (unzipped, inspected `users` table). Route inventory and dead-code references confirmed via `grep`.

---

## Addendum — Refactor Applied (Backend)

This section records the concrete code changes implemented to close the gaps raised above, plus the verification evidence. All work targets branch `main`; the app was re-booted and smoke-tested in a clean virtualenv after each phase.

### Phase 0 — Configuration, security, hygiene
- **`backend/config.py`** (new): 12-factor settings. `OMISTOCK_SECRET_KEY` is now mandatory in production (process refuses to boot without it) and falls back to an ephemeral dev key with a warning. Token lifetime cut from 24 h to 2 h. CORS origins read from env (explicit allow-list; **wildcard `*` + credentials removed**).
- **`backend/security.py`**: reads secret/expiry from `config`; no hardcoded secret.
- **`backend/main.py`**: real `CORSMiddleware` allow-list; the no-op `TenantIsolationMiddleware` replaced by a `CorrelationMiddleware` that stamps an `X-Correlation-Id` end-to-end (tenant isolation is now enforced in the DAL/dependencies, not faked in middleware). Additive, idempotent migrations for all new columns; auto-seed disabled in production.
- Dead `backend/mcp_auth.py` deleted; `.gitignore` covers venv/backups/secrets; corrupted junk file removed.

### Phase 1 — Data model & stock theory
- **`backend/models.py`**: `Inventory` is the **single source of truth**; `Product.quantity` kept only as a derived cache (`total_quantity` hybrid). Added `cost_price` (WAC) vs `price` (sale), `safety_stock`, `avg_daily_demand`, `lead_time_days`, `Supplier.lead_time_days`, computed `reorder_point` property, new `Lot` model (batch/expiry, FEFO), `AgentProposal`, hash-chained `AuditLog` (`prev_hash`/`entry_hash`/`correlation_id`/`entity_*`), and agent-governance fields on `User` (`autonomy_level`, `agent_scopes`, `api_key_expires_at`, `max_action_quantity`).
- **`backend/stock.py`** (new): WAC on receipt, avg-daily-demand from sales history, ROP = demand×lead-time + safety stock, EOQ (Wilson), **valuation at cost**, inventory-based alerts (`on_hand ≤ ROP`), FEFO lot consumption, expiring-lot detection.
- **`backend/repository.py`** (rewritten): all quantities sourced from `Inventory`; `restock_product` applies WAC + lot + traced movement; `create_sale` decrements per-branch stock, computes COGS, writes `unit_cost`; **`reverse_sale` / transfer flow are compensating transactions** (no history deletion). Every movement carries `actor_id` + `correlation_id`.
- **`backend/services.py`**: dashboard valued at cost with potential-margin = sale−cost; **destructive purge removed from the login path** (moved to explicit `purge_expired_accounts` admin task); real `analyze_product_mcp` forecast (days-until-stockout vs lead time).

### Phase 2 — AI-agent platform hardening
- **Two separate interfaces**: humans use `/api/*` (JWT, RBAC); agents use a dedicated **`backend/routers/agent.py`** (`/api/agent/*`, `X-API-Key`).
- **Autonomy levels** `read_only < suggest < propose < auto` and **fine-grained scopes** enforced by **`backend/agent_policy.py`** (least privilege + `max_action_quantity` cap).
- **Human-in-the-loop**: agents at `propose` create `AgentProposal`s; admins approve/reject via `/api/agent/proposals/*`, and execution is performed under a human identity (separation of duties). Transfer approve/confirm are human-only.
- **Credentials**: agent keys are admin-issued only, **expiring**, rotatable (`/api/agents/{id}/rotate-key`), returned once, never re-listed in clear, expiry enforced at auth time.
- **Audit & traceability**: tamper-evident hash chain (`backend/audit.py`) with `/api/audit/verify`; correlation IDs link intention→action→result; backups redact password hashes & API keys.
- **Rollback**: action-level compensating transactions (`reverse_sale`) instead of raw row deletes.
- **`/api/admin/restore` hardened**: JSON-only, **scoped to the caller's `company_id`** (cross-tenant rows ignored), audited before/after, FK-pragma toggling and raw `.db`/`.sql` overwrite paths removed.
- Mocked `/api/mcp/chat` replaced with a **data-grounded** intent router (alerts/valuation/sales) — no fabricated figures.

### Verification evidence
- `py_compile` passes for all backend modules and routers.
- App boots against a fresh SQLite DB: migrations apply, seed runs.
- Smoke test confirmed: unauthenticated `/api/inventory` → **401** (no `company_id=1` fallback); restock 450→460 with **WAC 0.0→1.087**; sale 460→457 with COGS; **`reverse_sale` restores 460** and marks `REVERSED`; `audit.verify_chain` → valid; agent-policy blocks an `auto` action for a `propose` agent.
- **Audit tamper-evidence hardened & proven.** `verify_chain` now performs a **full hash replay** of every entry from all persisted fields including a canonical `hash_ts` timestamp column (added via additive migration), so in-place edits of an entry's *content* are detected — not just `prev_hash` continuity breaks. Covered by `test_audit_integrity.py` (28 tests pass overall).
- Dashboard returns cost valuation + potential margin; forecast returns real `avg_daily_demand`, ROP, days-until-stockout.
- Enriched response schemas surface `reorder_point`, `total_quantity`, `cost_price`, and audit chain/correlation fields to the API.

### Remaining-gap closure (follow-up pass)

The gaps flagged above were subsequently closed:

- **Automated test suite added.** `backend/tests/` (+ `pytest.ini`) holds **28 passing tests** across three files, isolated on a temp SQLite DB via `conftest.py`:
  - `test_stock_theory.py` — WAC over successive receipts, WAC preserved when cost missing, ROP = demand×lead + safety (with `min_threshold` fallback), alert when `on_hand ≤ ROP`, valuation **at cost** (not price), EOQ/Wilson.
  - `test_repository.py` — sale decrements inventory + computes COGS, insufficient-stock rejection (transaction rolled back), **`reverse_sale` restores stock + marks `REVERSED` + emits compensating `IN` movement**, double-reverse rejected, **cycle-count positive/negative variance + `ADJUST` movement**, no-variance no-op, negative-count rejection, **FEFO consumes earliest-expiry lot first**.
  - `test_agent_readiness.py` — audit chain valid after appends, **tamper detection (broken `prev_hash` → `broken_at`)**, per-company chain isolation, autonomy-level enforcement (read-only/propose blocked from `auto`), missing-scope block, quantity-cap block, no-cap means no autonomous quantity, humans rejected from the agent path, wildcard scope.
  - `test_audit_integrity.py` (**new, follow-up**) — intact chain verifies (with `legacy_entries=0`), **in-place content tampering of a middle entry is now detected** (full `entry_hash` replay incl. persisted `hash_ts`), and a broken `prev_hash` continuity link is detected.

- **Cycle-count / variance adjustment implemented.** `repository.adjust_inventory()` reconciles system stock (Inventory = source of truth) with a physical count, records the signed variance as an `ADJUST` `StockMovement` (actor + correlation), recomputes the cache, and is exposed (human-only, multi-tenant-validated, audited) at **`POST /api/inventory/cycle-count`** with `CycleCountCreate`/`CycleCountResponse` schemas.

- **MCP `server.py` aligned to the new agent surface.** It now calls the dedicated **`/api/agent/*`** endpoints (not the human routes), surfaces `on_hand`/`reorder_point` (not raw `quantity`/`min_threshold`), exposes a **`propose_restock`** tool that creates a human-in-the-loop proposal (no direct write from chat), and maps `401`/`403` to clear "expired key" / "blocked by autonomy policy" messages. (`forecast` now also returns `lead_time_days`.)

- **Frontend shared client + governance view added.** `frontend/api.js` (`window.OmiAPI`) centralizes base URL, JWT header injection, 401→login redirect, and business shortcuts (`inventory`, `alerts`, `restock`, `cycleCount`, `proposals`, `approveProposal`/`rejectProposal`, `auditVerify`), removing the per-page fetch/token duplication. `frontend/agent-governance.html` is a human supervision screen: **pending agent-proposal queue with approve/reject** and an **audit-chain integrity check** (served at `/app/agent-governance.html`, and now **linked from the sidebar nav of all 7 ERP pages** — "Gouvernance IA").

- **Migration strategy documented.** `docs/migrations.md` (already referenced by `main.py`) explains the current additive `ALTER`-best-effort approach, its limits, and the recommended Alembic target (incl. SQLite batch mode).

### Still deferred (explicitly out of current scope)
- Full `PurchaseOrder` lifecycle promotion (draft→sent→received with auto-restock-on-receipt) is **not** implemented.
- Alembic is **documented but not wired in**; boot-time additive migration remains.
- HTTP-level (TestClient) integration tests remain blocked by an httpx/starlette version mismatch; coverage is at the service/DAL/policy layer plus an ASGI import smoke test. Pin `httpx` or use `ASGITransport` to add HTTP-level tests.
- Remaining HTML pages still inline their own fetch logic (the new `agent-governance.html` uses `OmiAPI`, and all pages now link it in the nav); migrating the legacy pages' fetch logic onto `OmiAPI` is incremental and left as a follow-up.
