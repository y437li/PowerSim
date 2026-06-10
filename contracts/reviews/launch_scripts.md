# Review record: Install & Launch Scripts (serving)

- **Contract:** `contracts/serving/launch_scripts.md`
- **Tests:** `tests/serving/test_serving_launch_scripts.py`
- **Spec:** REBUILD_SPEC.md §9 (§9.1–§9.5)
- **PR:** #10 (`feat/serving-launch-scripts`)
- **Reviewer:** backend-reviewer
- **Stage 1 (contract + tests gate) verdict:** REQUEST_CHANGES — 2026-06-10
- **Re-review verdict:** _(pending revision)_

## Summary

Contract is well-structured and largely spec-faithful (file list §9.1, server-type→extras §9.2,
ordered install §9.3, idempotency/uninstall §9.4, exit-code table, state files). The test suite has
good breadth (flag errors, checkpoint-required, accel fail-loud, pyproject extras separation,
idempotency/uninstall slow tests, no-secrets scan). Three blockers and several §9.5 coverage gaps
must be resolved before APPROVE; none are architectural.

## Blockers (must fix)

- **B1 — internal exit-code contradiction.** Contract §5 prose (lines 105–106) says unsupported
  OS/arch → `exit 1`, but the §10 table assigns code **2** (preflight). §7 prose (line 127) says
  `--accel gpu` on a no-GPU box → `exit 1`, but the §10 table assigns code **6** and the tests
  (`test_accel_gpu_no_gpu_exits_6_*`) assert **6**. An implementer following the prose emits the
  wrong codes and fails the tests. Fix §5/§7 prose to cite codes 2 and 6 to match §10.
- **B2 — cross-platform parity test does not test parity.** `TestCrossPlatformFlagParity`
  (a) extracts `.ps1` params with `re.findall(r'\$([A-Za-z]+)', …)`, which matches *every* shell
  variable, not just the param block (massive false positives); (b) never compares the `.sh` flag
  set against the `.ps1` param set — each side is independently checked for a hand-picked subset;
  (c) omits `-Site`/`-Checkpoint`/`-BackendPort`/`-FrontendPort` on the `.ps1` side, so their parity
  is unverified. Parity is acceptance criterion §9.5 #6. Redo as a real set-equality check
  (kebab↔Pascal mapping) over the full flag set, ideally driven by each script's `--help`/`-Help`
  output rather than source-text scraping.
- **B3 — JAX extras install `jaxlib`, not the `jax` core package.** §4.1 `jax-cpu`/`jax-gpu` list
  `jaxlib[cpu]`/`jaxlib[cuda12]`. STACK.md binds the env/serving core to the **`jax`** package
  (jaxlib is only the wheel backend); `import jax` fails with jaxlib alone, breaking the
  "JAX core (inference only)" serving acceptance (§9.2). Use `jax[cpu]`/`jax[cuda12]` (or add `jax`
  explicitly). Version values still defer to STACK.md/pyproject; the *package set* is structural.
  Test `test_jax_cpu_extras_has_jaxlib` only checks the `jaxlib` substring and so passes a broken set.

## Must-add tests (§9.5 coverage gaps) — to be pushed `# reviewer:` on the approving round

- **T1** serving venv EXCLUDES training deps (`optax`/`flax`/`sbx`) via `pip freeze` — the headline
  §9.5 #1 "serving not training"; current acceptance only checks `fastapi` present. (slow)
- **T2** serving extras group excludes `sbx` and `purejaxrl` (pyproject parse; contract §4 names all
  four training-only deps but tests only assert optax+flax). (fast)
- **T3** built frontend bundle exists after serving/full install (§9.5 #1 "built static assets";
  `dist/` output present). (slow)
- **T4** no-hardcoded-versions scan (§9.5 #7): no `==`/`>=` version pin appears in script text that
  is not also in pyproject. (fast)
- **T5** port validation → exit 1 (§10 code 1; contract §3 range 1–65535): `--backend-port 99999`
  / non-integer → exit 1. (fast)
- **T6** launch failure → exit 5 (otherwise untested): launch with `--backend-port` already bound
  → exit 5. (slow; or document as hard-to-test)
- **T7** `jax` core package present in `jax-cpu` extras (ties to B3); optional slow `import jax`
  inside the serving venv. (fast)
- **T8 (note)** FastAPI health endpoint responds after `run_app` launch (§9.5 #4) is currently only
  a skipped placeholder — acknowledge as a known slow/CI gap, don't leave it silently uncovered.

## Non-blocking notes

- §4.1 `jax-gpu` mixes CUDA (`jaxlib[cuda12]`) and Metal (`jax-metal`) in one group; a single extras
  group can't resolve per-OS without PEP 508 markers
  (`platform_system=='Darwin' and platform_machine=='arm64'`). Either add markers or split into
  `jax-gpu-cuda` / `jax-gpu-metal`. Clarify in the contract.
- `test_pids_json_schema` validates its own hand-written JSON, not script output (tests the test);
  the real launch test is skipped, so PID-file behavior is effectively untested. Acknowledge.
- `test_last_checkpoint_fallback_accepted_sh` asserts only `!= 4` (weak but acceptable);
  optionally strengthen to assert the resolved checkpoint is actually used.
- Idempotency: test accepts three message variants while §8 specifies one exact string — fine
  (looser is more robust).

## Answers to the developer's review questions

1. **§4.1 serving/optax-flax separation** — correctly enforced; ADD `sbx`/`purejaxrl` exclusion (T2)
   and verify the `jax` core package is present (B3).
2. **Exit code 6 for GPU fail-loud** — a fine choice (spec only requires non-zero + remediation);
   the problem is the §7 prose still says `exit 1` (B1).
3. **Exit-code gaps** — assignments are reasonable; the gap is the §5/§7-vs-§10 contradiction (B1)
   plus untested codes 1 (port), 2 (OS/arch), 5 (launch) — add T5/T6.
4. **`.run/last_checkpoint` fallback test** — adequate but weak (asserts `!= 4`); keep, optionally
   strengthen.
5. **Regex parity approach** — NOT sufficient (B2): brittle, over-broad `.ps1` capture, and never
   compares the two sides. Prefer help-output- or behavior-driven set-equality.
6. **§9.5 not covered** — #1 (serving-excludes-training + built bundle), #4 (health endpoint),
   #6 (real parity), #7 (no-hardcoded-versions) need coverage (T1/T3/T8/B2/T4).
