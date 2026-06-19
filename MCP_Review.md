# OMISTOCK — MCP Layer Deep Review

> **Scope:** the Model Context Protocol (MCP) layer of OMISTOCK and its integration with the AI-agent-ready platform.
> **Repository:** https://github.com/sarahgacem/omistock — working branch `mainbr` (working-tree hardening refactor over committed baseline HEAD `2346ca6`).
> **Reviewed:** 2026-06-17
> **Method:** every MCP-related file read directly in the workspace (`mcp/server.py`, `backend/routers/agent.py`, `backend/agent_policy.py`, `backend/dependencies.py`, `backend/services.py`, `backend/routers/admin.py`, `backend/models.py`, the two HTML MCP consoles, dashboard integration, requirements). Claims are grounded in those files; the running app and 28-test suite were verified in earlier passes.

---

## 1. Executive Summary

OMISTOCK ships a **real Model Context Protocol server** (`mcp/server.py`, built on `FastMCP`) that exposes inventory intelligence to an AI agent, **plus** a separate, dedicated, authenticated, audited backend agent surface (`/api/agent/*`) behind a proper autonomy/scope policy. Conceptually this is one of the strongest parts of the project: the **two-interface principle (human JWT vs agent X-API-Key), human-in-the-loop proposals, autonomy levels, scopes, quantity caps, hash-chained audit, and correlation IDs are all genuinely implemented** — not just described.

However, as an MCP *product* the layer is **thin and unfinished**:

- Only **3 MCP tools** exist, all stock-read / restock-propose oriented. A usable stock-management agent needs roughly **12–16 tools** (valuation, EOQ, transfers, supplier/lead-time, lot/expiry, cycle-count proposal, sales/velocity, reporting, audit verification, proposal status).
- The **`mcp` / `fastmcp` dependency is not declared in any `requirements*.txt`** — the server as written **cannot be installed or run** out of the box (verified: `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`).
- There is a **naming collision / partial dead code**: a legacy REST endpoint `/api/mcp/chat` + `/api/mcp/analyze` and two near-duplicate "MCP test" HTML consoles are labeled "MCP" but are **not MCP at all** (plain keyword-intent REST). This confuses the architecture and the two-interface story.
- **No tests exercise the MCP tools themselves** (the policy/DAL layer is well tested; the MCP client functions are not).
- The agent surface lacks several agent-platform primitives: **no transfer proposal tool** (only restock), **no explicit rollback/undo tool**, **no idempotency keys**, **no rate limiting / quota**, **no tool to read its own pending proposals or autonomy/scope ("self-introspection")**.

**MCP-layer maturity (indicative):**

| Axis | Rating (/5) | Justification |
|------|:-----------:|---------------|
| MCP server structure & code quality | 3.0 | Clean, documented, correct error mapping; but single file, no tests, undeclared dependency |
| Tool coverage for stock management | 2.0 | 3 tools; ~10+ essential tools missing (valuation, transfer, supplier, lot/expiry, cycle-count, reporting) |
| Two-interface separation | 4.0 | Real dedicated `/api/agent/*` surface, X-API-Key vs JWT, agents barred from human mutation routes |
| Authorization model | 4.0 | Autonomy levels + scopes + quantity cap, least-privilege, enforced server-side and well tested |
| Audit & traceability | 3.5 | Hash-chained audit + correlation IDs on every agent action; chain replay verified; minor gaps |
| Rollback / reversibility | 2.5 | Compensating `reverse_sale` exists at DAL level, but **no agent/MCP-facing rollback tool** |
| Consistency / hygiene | 2.0 | Dual "MCP" surfaces, dead HTML consoles, dependency gap, dashboard calls REST not MCP |

---

## 2. MCP Layer Structure & Architecture

```
omistock/
├── mcp/
│   └── server.py                 # ← THE actual MCP server (FastMCP, stdio); 3 tools
├── backend/
│   ├── routers/agent.py          # /api/agent/* — dedicated agent HTTP surface (what MCP calls)
│   ├── agent_policy.py           # autonomy levels + scopes + quantity cap (authorization)
│   ├── dependencies.py           # get_current_agent / X-API-Key auth + key expiry
│   ├── audit.py                  # hash-chained, correlation-ID audit (tamper-evident)
│   ├── routers/admin.py          # human side: proposal approve/reject (HITL execution); + legacy /api/mcp/chat
│   └── services.py               # analyze_product_mcp (forecast used by agent + REST)
├── frontend/
│   ├── agent-governance.html     # human supervision: proposal queue + audit verify
│   ├── test-mcp.html             # legacy "MCP" console → calls /api/mcp/chat (NOT MCP)
│   └── dashboard.html            # "Omistock Intelligence MCP" modal → calls /api/mcp/analyze (NOT MCP)
└── outil_test_mcp.html           # duplicate of frontend/test-mcp.html (stray file)
```

### Intended architecture (and it is mostly real)

```
AI Agent / LLM host
   │  (MCP stdio, FastMCP)
   ▼
mcp/server.py  ── 3 tools ──►  X-API-Key  ──►  /api/agent/*  ──►  agent_policy  ──►  repository/DAL
                                                    │                                     │
                                              (audit chained + correlation_id)      Inventory = SoT
                                                    ▼
                              PROPOSE → AgentProposal (PENDING) → human approves in /agent-governance.html
                                                    ▼
                              admin executes under HUMAN identity (Separation of Duties), same correlation_id
```

This data-flow is **correctly implemented end-to-end** and is the layer's main strength.

---

## 3. The MCP Tools — Inventory & Quality

There are exactly **3 MCP tools** (`@mcp.tool()` in `mcp/server.py`):

| # | Tool | Backend call | Autonomy/scope required | Quality | Notes |
|---|------|--------------|-------------------------|---------|-------|
| 1 | `get_stock_alerts()` | `GET /api/agent/alerts` | `stock:read`, READ_ONLY+ | **Good** | Returns `on_hand` vs `reorder_point` (ROP), not raw quantity. Clean empty-state. |
| 2 | `predict_stockout(product_id)` | `GET /api/agent/forecast/{id}` | `stock:read`, SUGGEST+ | **Good** | Real `avg_daily_demand`, ROP, days-until-stockout, lead time; backend-computed (no fabricated numbers). |
| 3 | `propose_restock(product_id, branch_id, quantity, unit_cost, rationale)` | `POST /api/agent/proposals/restock` | `restock:propose`, PROPOSE+ | **Good** | Human-in-the-loop: creates a proposal, never writes stock directly. |

### Quality strengths
- **No fabricated data.** Forecast/alerts are computed server-side from real history (`stock.compute_avg_daily_demand`, ROP), addressing the classic "LLM invents numbers" failure mode.
- **Correct, agent-aware error mapping** (`_handle_http_error`): 401 → "key absent/expired", 403 → "blocked by autonomy policy", surfacing the *governance* reason to the agent.
- **Good docstrings** that state the scope/level each tool needs — useful for an LLM planner.
- **Write path is gated**: the only writing tool produces a *proposal*, never a direct mutation, matching the PROPOSE autonomy level. Direct `/api/agent/restock` (AUTO) exists on the backend but is deliberately **not** exposed as an MCP tool — a sound, conservative default.

### Quality flaws (verified)
1. **Undeclared dependency (critical).** `from mcp.server.fastmcp import FastMCP` and `import httpx`, yet **no requirements file lists `mcp`/`fastmcp`** (`httpx` is present in `backend/requirements.txt`, `mcp` is not anywhere). The server cannot be installed/run as shipped. There is also **no `mcp/requirements.txt`** and no run instructions tying `API_BASE_URL`/`AGENT_API_KEY` to a launch command.
2. **No tests for the tools.** `backend/tests/test_agent_readiness.py` thoroughly tests `agent_policy`, but the three MCP functions have **zero coverage** (no mock-`httpx` tests, no contract test against the agent routes).
3. **Hard-coupled transport.** Each tool re-creates an `httpx` call with a 10s timeout; there's no shared client, no retry/backoff, no connection reuse, no pagination handling for `get_stock_alerts` (could return a very large list to the model).
4. **No structured output.** Tools return **human prose strings** (with emojis). For agent *reasoning/chaining*, returning **structured JSON** (or MCP structured content) is better: e.g. `propose_restock` returns a sentence, so the agent can't easily read back the `proposal_id` programmatically.
5. **`unit_cost` defaults to 0.0** in `propose_restock`; an agent that omits it will create a WAC-distorting proposal unless the human catches it. The tool should fetch the supplier's last cost or require a non-zero value.
6. **No company/tenant parameter and no self-introspection.** The agent cannot ask "what are my scopes / autonomy level / pending proposals?" — it only learns its limits by being refused (403). A `get_my_capabilities()` tool would make the agent self-aware and reduce blocked calls.

---

## 4. Best Stock-Management MCP Tools Needed (Gap List)

The current 3 tools cover **alerting, forecasting, and restock-proposal** only. A credible stock-management agent needs the toolset below. **~10–13 additional tools** are recommended; the platform/DAL already computes most of the underlying values (`stock.py`, `repository.py`), so most are thin wrappers.

### P0 — Essential (the agent is not really useful without these)
1. **`get_inventory(branch_id?, low_stock_only?)`** — paginated on-hand by product/branch (SoT = `Inventory`). *Backend: `stock.get_alerts` exists; a general list endpoint is needed.*
2. **`get_stock_valuation()`** — total inventory value **at cost (WAC)**. *Backend already has `stock.stock_value_at_cost`; just expose under `/api/agent/*`.*
3. **`propose_transfer(product_id, from_branch, to_branch, quantity, rationale)`** — inter-branch rebalancing as a HITL proposal. *Backend supports transfers + `AgentProposal.action_type` already allows `TRANSFER`, but the approve handler only implements `RESTOCK` — needs completion.*
4. **`get_reorder_suggestions()`** — products at/under ROP **with EOQ-based suggested order quantity**. *Backend has ROP + `economic_order_quantity` (Wilson); not surfaced.*
5. **`list_my_proposals(status?)`** — let the agent see the fate of its own proposals (PENDING/EXECUTED/REJECTED). *Backend has `get_agent_proposals`; currently only the human governance UI reads it.*

### P1 — Strongly recommended (stock theory completeness)
6. **`get_eoq(product_id)`** — economic order quantity + assumptions (order cost, holding cost). *Backend `stock.economic_order_quantity` exists.*
7. **`get_expiring_lots(days?)`** — FEFO/expiry risk. *Backend has `Lot` model + FEFO + expiring-lot detection.*
8. **`get_supplier_info(product_id)`** — supplier + **lead-time** (drives ROP). *Backend has `Supplier.lead_time_days`.*
9. **`get_sales_velocity(product_id, window_days)`** — demand trend / moving average beyond the single forecast number.
10. **`propose_cycle_count(branch_id, product_id, counted_qty, rationale)`** — physical-count reconciliation as a proposal. *Backend has `adjust_inventory` + `/api/inventory/cycle-count` (human-only); an agent *proposal* variant is missing.*

### P2 — Agent-platform / governance tools
11. **`get_my_capabilities()`** — autonomy level, scopes, `max_action_quantity`, key expiry (self-introspection).
12. **`verify_audit_integrity()`** — agent-readable audit-chain check (read-only). *Backend `/api/audit/verify` is admin-only today; a read-only agent-scoped variant would aid trust.*
13. **`request_rollback(movement_id|sale_id, rationale)`** — propose a **compensating transaction** (reverse a sale/restock) as a HITL proposal. *DAL `reverse_sale` exists but is not reachable by the agent in any form — this is the single biggest "agent-ready" gap (see §6.5).*

> Net: **3 tools today → target ~13–16 tools.** Most are low-effort wrappers because the stock math and DAL already exist; the work is (a) exposing them under `/api/agent/*` with the right scope/level, (b) adding a thin MCP tool, and (c) returning structured JSON.

---

## 5. Evaluation Axis A — Best Stock-Management MCP Tools

| Capability (stock theory) | Backend support | Exposed as MCP tool? | Verdict |
|---------------------------|:---------------:|:--------------------:|---------|
| Reorder point (ROP) alerts | ✅ `reorder_point` property | ✅ `get_stock_alerts` | **Covered** |
| Demand forecast / days-to-stockout | ✅ `compute_avg_daily_demand` | ✅ `predict_stockout` | **Covered** |
| Restock proposal (HITL) | ✅ `create_agent_proposal` | ✅ `propose_restock` | **Covered** |
| Inventory valuation at cost (WAC) | ✅ `stock_value_at_cost` | ❌ | **Missing** |
| EOQ (Wilson) order sizing | ✅ `economic_order_quantity` | ❌ | **Missing** |
| Inter-branch transfer proposal | ⚠️ transfers exist; approve handler RESTOCK-only | ❌ | **Missing / incomplete** |
| Lot / FEFO / expiry risk | ✅ `Lot` + FEFO | ❌ | **Missing** |
| Supplier lead time | ✅ `Supplier.lead_time_days` | ❌ (only inside forecast) | **Partial** |
| Cycle-count / variance | ✅ `adjust_inventory` (human) | ❌ (no agent proposal path) | **Missing** |
| Sales velocity / trend | ⚠️ partial (single avg) | ❌ | **Missing** |

**Assessment:** the *theory* is implemented in the backend to a respectable degree (WAC, ROP, EOQ, safety stock, lead time, FEFO), but the **MCP surface exposes only ~30% of it**. The agent currently cannot value stock, size an order with EOQ, rebalance branches, or reason about expiry — all core stock-management agent jobs.

---

## 6. Evaluation Axis B — MCP Integration with AI-Agent-Ready Best Practice

### 6.1 Two separate interfaces (human vs agent) — **Strong (4/5)**
- Humans: `/api/*` with **JWT Bearer** + RBAC (`get_current_human`/`get_current_admin`).
- Agents: dedicated **`/api/agent/*`** with **X-API-Key** (`get_current_agent` enforces `user_type == "AGENT"`).
- Agents are **explicitly barred** from human mutation routes; humans are **explicitly barred** from the agent path (`test_human_rejected_from_agent_path`).
- The MCP server only ever sends `X-API-Key` and **never a human JWT** (documented and enforced).
- **Flaw:** the *naming* undermines the story — the legacy `/api/mcp/chat` and `/api/mcp/analyze` REST endpoints and the `test-mcp.html` / `dashboard.html` "MCP" modal are **human-side REST**, not the agent MCP server. This blurs the clean separation and should be renamed (e.g. `/api/assistant/*`) or removed.

### 6.2 Autonomy levels — **Strong (4/5)**
- `AutonomyLevel`: `read_only < suggest < propose < auto`, **default `read_only`** (safe).
- Enforced by `agent_policy.level_at_least` and required on every agent route (alerts=READ_ONLY, forecast=SUGGEST, proposal=PROPOSE, auto-restock=AUTO).
- Well tested: read-only/propose agents are blocked from AUTO; propose agents can propose (`test_propose_agent_blocked_from_auto_but_allowed_to_propose`).
- **Flaw:** autonomy/level mapping lives in code, not config; there is **no per-tool or time-boxed escalation** and **no "dry-run" level** between SUGGEST and PROPOSE.

### 6.3 Authorization model — **Strong (4/5)**
- **Least-privilege scopes** (`stock:read`, `restock:propose`, `restock:auto`, wildcard `domain:*`/`*`), parsed from `User.agent_scopes`.
- **Quantity cap** (`max_action_quantity`): `cap <= 0` ⇒ **no autonomous quantitative action** (safe default), tested (`test_no_cap_means_no_autonomous_quantity`, `test_auto_agent_blocked_by_quantity_cap`).
- **API key lifecycle:** admin-issued only, **expiring** (`api_key_expires_at` enforced at auth → 401), rotatable (`/api/agents/{id}/rotate-key`), shown once.
- **Flaws:** API key is stored/compared **in plaintext** (`User.api_key`) rather than hashed; there is **no rate limiting / quota** per key; wildcard `*` scope is supported (convenient but dangerous if mis-issued).

### 6.4 Audit & traceability — **Good (3.5/5)**
- **Every** agent action (`AGENT_READ_ALERTS`, `AGENT_FORECAST`, `AGENT_PROPOSE_RESTOCK`, `AGENT_AUTO_RESTOCK`) writes a **hash-chained** audit entry with **`correlation_id`** linking intention → proposal → human approval → execution (the approve handler reuses the proposal's `correlation_id`).
- Chain is **tamper-evident with full replay** (recomputes `entry_hash` from all fields incl. persisted `hash_ts`), proven by `test_audit_integrity.py`.
- **Flaws:** even read-only forecasts/alerts write audit rows (audit-log bloat / no separation of read vs write trails); audit verification is **admin-only** (no agent-readable integrity attestation); per-company chains are isolated (good) but there is no signed/external anchoring.

### 6.5 Rollback / reversibility — **Weak for the agent (2.5/5)**
- The DAL implements **compensating transactions** (`reverse_sale` restores stock, marks `REVERSED`, emits an `IN` movement; double-reverse rejected) — verified by tests. History is never hard-deleted.
- **Critical gap:** **none of this is reachable by the agent or via MCP.** There is no `request_rollback` tool and no `/api/agent/*` reversal route. An agent that proposes/executes a bad restock has **no governed way to propose undoing it** — a human must act entirely outside the agent loop. For an "agent-ready" platform this is the most important missing primitive (see P2 tool #13).
- No **idempotency keys** on `propose_restock`/`restock`: a retried tool call can create duplicate proposals or double-execute an AUTO restock.

### 6.6 Human-in-the-loop (HITL) — **Strong**
- PROPOSE agents create `AgentProposal` (status `PENDING`); admins approve/reject in `agent-governance.html`.
- On approve, the action is **executed under the human admin's identity** (`actor_type="ADMIN"`, `actor_id=current_user.id`) — genuine **Separation of Duties**.
- Status machine `PENDING → EXECUTED | REJECTED`, double-processing blocked.
- **Flaw:** approve handler implements **only `RESTOCK`**; `TRANSFER` (and any future action type) raises "type non supporté", so the transfer-proposal path is effectively dead until completed.

---

## 7. Bugs, Errors & Inconsistencies (consolidated)

| # | Severity | Finding | Evidence |
|---|:--------:|---------|----------|
| 1 | **High** | MCP server's `mcp`/`fastmcp` dependency is **undeclared**; server can't run as shipped | not in `requirements*.txt`; `ModuleNotFoundError` on import |
| 2 | **High** | **No MCP-facing rollback** path; `reverse_sale` exists only in DAL | `repository.reverse_sale` present; no agent route/tool |
| 3 | Medium | **Dual "MCP" surfaces**: real MCP (`/api/agent/*`) vs mislabeled REST (`/api/mcp/chat`, `/api/mcp/analyze`) | `admin.py:572`, `products.py:130`, dashboard/test-mcp HTML |
| 4 | Medium | **Duplicate stray file**: `outil_test_mcp.html` ≈ `frontend/test-mcp.html` (legacy console) | both call `http://localhost:8000/api/mcp/chat` |
| 5 | Medium | **No tests** for MCP tool functions (only policy/DAL tested) | `tests/` has no `test_mcp*` |
| 6 | Medium | Approve handler supports **only `RESTOCK`**; transfer proposals dead | `admin.py` approve: `else → 400 type non supporté` |
| 7 | Medium | API keys stored/compared in **plaintext** | `User.api_key` filtered directly in `dependencies.py` |
| 8 | Low | Tools return **prose strings**, not structured JSON (hard to chain) | `mcp/server.py` returns formatted text |
| 9 | Low | `propose_restock` `unit_cost` defaults **0.0** (WAC distortion risk) | `mcp/server.py` signature |
| 10 | Low | **No idempotency / rate limiting** on agent writes | no key/limit in `agent.py` |
| 11 | Low | Read-only tools also write audit rows (log bloat, no read/write split) | `agent_alerts`/`agent_forecast` call `audit.record` |
| 12 | Low | Hard-coded `localhost:8000` in HTML consoles; no shared httpx client/retry in MCP | HTML + `mcp/server.py` |

---

## 8. Prioritized Recommendations

### P0 — Make it runnable & safe
1. **Declare the MCP dependency.** Add `mcp[cli]` (FastMCP) and `httpx` to a dedicated `mcp/requirements.txt`; document launch: `API_BASE_URL`, `AGENT_API_KEY`, `python mcp/server.py`. Add an import smoke test in CI.
2. **Add an agent-facing rollback proposal tool** (`request_rollback`) backed by a `/api/agent/proposals/reverse` route → HITL approve → `reverse_sale`. Closes the biggest agent-ready gap.
3. **Hash agent API keys at rest** and compare by hash; keep "shown once" issuance.

### P1 — Tool coverage for stock management
4. Add the P0/P1 tools from §4: `get_inventory`, `get_stock_valuation`, `propose_transfer` (and finish the `TRANSFER` approve branch), `get_reorder_suggestions` (EOQ), `get_expiring_lots`, `list_my_proposals`. Most are thin wrappers over existing `stock.py`/`repository.py`.
5. **Return structured JSON** from tools (or MCP structured content) so the model can chain results (esp. `proposal_id`).

### P2 — Platform hardening
6. Add **idempotency keys** and **per-key rate limiting/quota** to agent write routes.
7. **Rename or remove** the legacy `/api/mcp/*` REST endpoints and consolidate the duplicate HTML consoles; reserve the term "MCP" for the actual MCP server to keep the two-interface story crisp.
8. Add `get_my_capabilities()` (self-introspection) and a **read-only, agent-scoped audit attestation**.
9. Split **read vs write audit trails** (or sample reads) to avoid log bloat.
10. Add **tests for the MCP tools** (mock `httpx`, assert scope/level error mapping and structured output) and a contract test against `/api/agent/*`.

---

## 9. Conclusion

OMISTOCK's MCP layer is **architecturally sound and unusually mature for its category on the *governance* axes**: it has a real FastMCP server, a genuinely separate authenticated agent interface, a least-privilege autonomy/scope/quantity model, hash-chained correlated audit, and a working human-in-the-loop proposal/approval flow with separation of duties. Those are exactly the AI-agent-ready primitives most projects only claim.

Where it falls short is **breadth and operational completeness**: only **3 of the ~13–16 tools** a stock-management agent needs are implemented; the **MCP dependency isn't declared** so the server can't run as shipped; there is **no agent-facing rollback** despite the DAL supporting compensating transactions; the **transfer-proposal path is half-built**; and a **legacy mislabeled "MCP" REST surface + duplicate consoles** muddy the otherwise clean two-interface design. None of these are deep design flaws — they are finishing work, and most of the missing tools are thin wrappers over math that already exists. Addressing the P0/P1 items would move this from a strong *demonstration* of an agent-ready MCP layer to a genuinely *usable* one.

---

### Appendix — Files inspected (evidence index)
- `mcp/server.py` (166 lines, 3 `@mcp.tool()`)
- `backend/routers/agent.py` (`/api/agent/alerts|forecast|proposals/restock|restock`)
- `backend/agent_policy.py` (levels, scopes, quantity cap)
- `backend/dependencies.py` (`get_current_agent`, X-API-Key, key expiry)
- `backend/services.py` (`analyze_product_mcp`)
- `backend/routers/admin.py` (proposal approve/reject; legacy `/api/mcp/chat`)
- `backend/routers/products.py` (`/api/mcp/analyze`)
- `backend/models.py` (`AutonomyLevel`, `User` agent fields, `AgentProposal`)
- `backend/requirements.txt` / `requirements-test.txt` (no `mcp`/`fastmcp`)
- `frontend/agent-governance.html`, `frontend/test-mcp.html`, `outil_test_mcp.html`, `frontend/dashboard.html`
- `backend/tests/test_agent_readiness.py`, `test_audit_integrity.py`
