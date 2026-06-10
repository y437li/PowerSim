# Review Record: wind_power_curve (WORKED EXAMPLE)

> Example of `contracts/reviews/<feature>.md`. Real records live in `contracts/reviews/`.

- **Verdict:** APPROVED
- **Reviewer:** backend-reviewer · **Date:** 2026-06-09
- **Contract:** contracts/_example/wind_power_curve.md (locked v1)
- **Test file approved:** contracts/_example/test_env_wind_power_curve.py

## Checks performed
- Re-derived all expected values by hand from REBUILD_SPEC.md §3.1 — arithmetic in test
  comments verified independently (shear factor 10.5^0.14 = 1.389858 confirmed).
- Units pinned: output asserted in MW with rated 4.2, not 4200 — a kW slip would fail
  `test_rated_region_is_flat`.
- Naming/location convention checked (example path exempted; real tests → tests/env/).

## Reviewer-added cases (4)
1. `test_exactly_at_cutin_is_zero` — boundary must be 0 via the cubic, not the branch.
2. `test_exactly_at_cutout_is_zero_and_just_below_is_rated` — cut-out inclusivity; the
   developer cases only tested 2.08 and 27.8 m/s, leaving the 25.0 boundary unpinned.
3. `test_exactly_at_rated_is_p_rated` — seam between cubic and flat regions.
4. `test_vectorized_all_regimes` — vmappability is in the contract interface, was untested.

## Conditions
- None. Approved suite = 5 developer cases + 4 reviewer cases. Any change to these
  files requires re-review (re-submit through contract-first-dev step 3).
