# Refactor Plan — Close gaps from OMISTOCK review

Working on branch `mainbr` (== main). Phased, evidence-grounded.

## Phase 0 — Hygiene & secrets (P0)
- [Y] Remove junk file, debug scripts, committed backups, ngrok log from working tree; fix .gitignore
- [Y] Externalize SECRET_KEY -> env (config module), keep dev fallback warning
- [Y] Fix CORS: explicit allow-list via env
- [Y] Lock down /api/admin/restore (no executescript / no live overwrite by default)
- [Y] Decouple purge from login

## Phase 1 — Data model & stock correctness (P1)
- [Y] Make Inventory single source of truth; Product.quantity -> computed/hybrid
- [Y] Add cost vs price separation + weighted-average cost valuation; use purchase_price in restock
- [Y] Add supplier lead_time + reorder point + safety stock; alerts use on_hand <= ROP
- [Y] Add lot/batch + expiry (FEFO) + cycle-count/variance adjustment (repository.adjust_inventory + /api/inventory/cycle-count + tests)
- [N] (scope) Promote PurchaseOrder lifecycle minimally — deferred (out of current scope; documented)
- [Y] Alembic-style note documented (docs/migrations.md; main.py already references it)

## Phase 2 — AI-agent platform hardening (P2)
- [Y] Autonomy levels per agent (read/suggest/propose/auto) enforced
- [Y] Scoped, expiring agent credentials + admin-gated issuance
- [Y] Agent write actions via human-in-the-loop approval
- [Y] Structured + tamper-evident (hash-chained) audit w/ correlation IDs; protect from clean/restore
- [Y] Action-level rollback / compensating transactions
- [Y] Replace mock analyze/chat with real (or clearly-labeled) forecasting; consolidate

## Phase 3 — Engineering hygiene (P3)
- [Y] Tests (pytest) for repository/services/stock/audit/agent_policy — 25 tests pass (backend/tests/, pytest.ini)
- [Y] Remove dead code (mcp_auth) + duplicate seeder
- [Y] Frontend shared api.js client + agent-governance.html (proposal queue + audit-verify view)
- [Y] Fix docs (docs/migrations.md added; report addendum updated)

## Verification
- [Y] App imports & starts; 63 routes incl. cycle-count; pytest suite (25) passes
