# Review record: Install & Launch Scripts (serving)

- **Contract:** `contracts/serving/launch_scripts.md`
- **Tests:** `tests/serving/test_serving_launch_scripts.py`
- **Spec:** REBUILD_SPEC.md §9 (§9.1–§9.5)
- **PR:** #10 (`feat/serving-launch-scripts`)
- **Reviewer:** backend-reviewer
- **Stage 1 (contract + tests gate) verdict:** APPROVE — 2026-06-10 (commit a7d233d)
  - Round 1 (gate commit): REQUEST_CHANGES — 3 blockers (B1–B3) + §9.5 coverage gaps.
  - Round 2 (a7d233d): all blockers resolved, T1–T8 added → APPROVE.

## Round-2 verification (all PASS)

- **B1 (exit-code contradiction)** — FIXED. §5 unsupported OS/arch + toolchain → `exit 2`; §7 GPU-no-GPU → `exit 6`; both now match the §10 table and the test assertions. `ERROR [<code>]: …` format consistent. Deviations note added.
- **B2 (parity not actually tested)** — FIXED. `CONTRACTED_FLAGS` maps all 9 kebab flags → PascalCase; `_sh_flags_from_help`/`_ps1_params_from_help` parse `--help`/`-Help` output (skip-not-fail pre-implementation); three assertions: .sh covers all contracted flags, .ps1 covers all contracted params, and set-equality under the kebab→Pascal bijection. Site/Checkpoint/BackendPort/FrontendPort now verified on both sides.
- **B3 (jaxlib vs jax core)** — FIXED. `jax-cpu = jax[cpu]>=0.4.25` (installs jax core + CPU jaxlib); `jax-gpu` split into `jax-gpu-cuda` (`jax[cuda12]`) and `jax-gpu-metal` (`jax` + `jax-metal`). `test_jax_cpu_extras_has_jax_package` asserts the `jax[` prefix; T7 confirms `import jax` at runtime. This also resolves my non-blocking PEP 508 marker note (split instead of markers, `uv sync`-compatible).
- **T1** serving venv excludes optax/flax/sbx/purejaxrl (pip-freeze) — present, correct.
- **T2** serving extras exclude sbx + purejaxrl (pyproject parse) — present.
- **T3** built frontend bundle (`dist/` non-empty) after serving install — present, skips if npm/package.json absent.
- **T4** no script version pin absent from pyproject — present; operator-prefixed pin scan, port/year guarded.
- **T5** port out-of-range / 0 / non-integer → exit 1, on both .sh and .ps1 — present.
- **T6** launch on a bound port → exit 5 — present (slow; honest note if hard to trigger).
- **T7** `import jax` succeeds in serving venv — present (B3 runtime check).
- **T8** health-endpoint gap made explicit via an always-pass placeholder (not silently absent) — present.

## Reviewer-added test (pushed this round, marked `# reviewer:`)

- `test_purge_preserves_config_but_removes_checkpoints_sh` — the suite pinned uninstall-preserves-config but not the **destructive `--purge` path**, which is the riskier one. §9.4/§9 (contract line 155) states `--purge` additionally removes `checkpoints/` but `config/` is **NEVER** removed. The reviewer test installs serving+cpu, runs `--uninstall --purge`, and asserts `config/site_gansu.yaml` survives while `checkpoints/run_001` is gone. (slow; skips if toolchain absent.) The approved suite = developer cases + this case.

## Non-blocking notes (optional polish; do NOT gate)

- `_sh_flags_from_help` docstring promises a source-parse fallback that only `_ps1_params_from_help` actually implements; behavior is still correct because `_sh_flag_set` skips on an empty result. Cosmetic.
- `test_no_hardcoded_version_in_scripts_not_in_pyproject` 4-digit guard is slightly coarse but adequate.
- Exit code **2** (unsupported OS/arch) remains structurally untestable in CI (can't fake the OS); like T8's health gap, it's left to manual/QA verification rather than a brittle mock. Acceptable.

## Skill-enforcement note (team-lead directive, PR #13)

`validate-telemetry` and `physics-invariants` are **not applicable** to this contract: launch scripts neither emit/consume telemetry nor run env physics. They bind the future FastAPI **serving implementation** contract (telemetry producer) and env-physics contracts respectively — not these deployment scripts.
