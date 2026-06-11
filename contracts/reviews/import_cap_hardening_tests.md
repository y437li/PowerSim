# Review record — `contracts/env/import_cap_hardening_tests.md` (PR #66)

**Reviewer:** backend-reviewer
**Feature:** reference F-IMPORT test hardening (tests-only)
**Contract:** `contracts/env/import_cap_hardening_tests.md` (test-plan; source of truth is `jax_env_core.md` §5.3/§3.6)
**Tests:** `tests/env/test_env_import_cap_priority.py` (18 collected)

## Origin
Converted from the closed PR #65 per team-lead's ruling: PR #33 owns the §3.6-row-9
load-first F-IMPORT fix in both `jax_env.py` and `gansu_env.py`; PR #66 carries the
superior reference-side test suite **tests-only** (no env code), rebased onto main
after #33 merged so the tests validate the already-fixed reference.

## Verdict: APPROVE (@ 22e7305, pre-reviewed at draft 55af231)

### Verified
- **Scope:** diff vs main is exactly `tests/env/test_env_import_cap_priority.py` +
  `contracts/env/import_cap_hardening_tests.md`. No `gansu_env.py`/`jax_env.py`/env-core
  changes; zero JAX dependency (pure Python/NumPy).
- **Hand-derived expected values** (re-computed independently; `bat_power_mw=98.16`,
  `max_import` per scenario, no SOC clip at soc=0.5):
  - TC-1 (load=350, max=400): grid_to_load=350, bat=50, import=400, unserved=0, VOLL=0.
  - TC-2 (load=400=max): grid_to_load=400, headroom=0, bat=0, unserved=0.
  - TC-3 (load=500>max): grid_to_load=400, unserved=100, bat=0, c_voll=20000×100=2,000,000 ¥.
  - TC-4 (load=200, total<max): no cap, bat fully served.
  - Cost-correctness (zero spurious VOLL when served; real-vs-reward split) + parametrised
    identities (`p_import = grid_to_bat + grid_to_load`, `≤ max`, `unserved ≥ 0`) over 4 loads.
- **Superset of #33's 3-case `TestImportCapPriority`**: additionally asserts `grid_to_load_mw`
  directly and the real-vs-reward cost split. Plain docstrings — no `# reviewer:` mislabels.
- **Green against merged main**: `gansu_env.py` STEP 8 is load-first (§3.6 row 9); the 18 tests
  were correctly RED pre-#33 and pass post-merge — the hardening intent.
- **Doc** is a test-plan citing `jax_env_core.md` §5.3/§3.6; explicitly does NOT re-specify
  §3.6 behavior (single source of truth preserved, no competing contract).

### No reviewer-added cases
The developer suite already covers the §3.6-row-9 regimes more thoroughly than #33's; no
additional reviewer cases needed. Approved suite = developer's 18.
