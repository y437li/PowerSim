# parity_gansu — contract cross-reference (D11)

This file exists to satisfy the tests↔contract naming convention
(`tests/env/test_env_parity_gansu.py` ↔ `contracts/env/parity_gansu.md`).

**The feature contract is `contracts/env/reference_implementation.md`** (D11).

D11 (rl-architect decision): the Gansu JAX parity tests live alongside the
reference-implementation contract because the reference implementation IS the
ground truth for JAX parity — they share one contract, one review record.

`tests/env/test_env_parity_gansu.py` contains two suites:
- **Suite 1 (TestReferenceConsistency)** — always runs; validates the NumPy
  reference implementation itself (internal consistency, physics invariants).
- **Suite 2 (TestJaxReferenceParity)** — skipped until the JAX env lands
  (`energy_go.env.jax_env`); asserts JAX step-for-step parity with Suite 1.

**Review record:** `contracts/reviews/reference_implementation.md`
