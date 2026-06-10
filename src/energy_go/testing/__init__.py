"""
energy_go.testing — reusable physics invariant helpers.

Importable by the reference implementation tests, JAX parity tests,
and qa-engineer's qa-verification skill.

    from energy_go.testing.invariants import (
        assert_energy_conserved,
        assert_cost_identities,
        assert_physical_bounds,
        assert_soc_dynamics,
        run_determinism_check,
        run_episode,
    )
"""
