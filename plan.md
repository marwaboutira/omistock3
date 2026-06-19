# Plan — Close remaining gaps (from review_report_Claude.md §10/§11)

## Gaps to close (prioritized)
- [ ] 1. (High) Audit `verify_chain` must recompute `entry_hash`.
      - Add `hash_ts` column to AuditLog model + additive migration.
      - `record()` persists the exact canonical ts used in the hash.
      - `verify_chain()` replays the full hash and reports `broken_at`.
      - Add a tamper test.
- [ ] 2. (Med-High) Replace naive `datetime.now()` with tz-aware UTC.
      - admin.py: deletion_deadline, reviewed_at (x2)
      - seed_data.py, backup_db.py (make consistent)
- [ ] 3. (Med) Frontend: link orphaned agent-governance.html into ERP nav (admin).
- [ ] 4. (Med) Dependency drift: pin bcrypt<4.1 in requirements.
- [ ] 5. Verify: pytest 25+ pass, app boots, route count stable.
- [ ] 6. Update review report addendum noting fixes.

## Constraints
- Keep app importable/bootable; preserve backward compat.
- Use Bash/Write/Edit; run tests in omistock/.venv.
- Additive migrations only (SQLite).
