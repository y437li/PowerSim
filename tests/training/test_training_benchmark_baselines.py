"""Tests for §11 benchmark baselines: Greedy Myopic, DP Oracle, MPC.

Contract:  contracts/training/benchmark_baselines.md
Spec:      §11.0 – §11.5  (section_11_benchmark_algorithms.md)

Test layout
-----------
Section A  — GreedyPolicy.action() step-level unit tests
Section B  — GreedyPolicy hand-computed single-step cost (arithmetic shown)
Section C  — run_benchmark("greedy") full-year property tests
Section D  — DpOraclePolicy ordering and correctness
Section E  — MpcPolicy property tests
Section F  — run_benchmark interface
Section G  — Telemetry integration (eval_compare keys)
"""

from __future__ import annotations

import math
import pytest
import jax
import jax.numpy as jnp
import numpy as np

# ---------------------------------------------------------------------------
# Guard-import jax_env (same pattern as test_training_training_pipeline.py)
# ---------------------------------------------------------------------------
_jax_env = pytest.importorskip(
    "energy_go.env.jax_env",
    reason="requires jax_env from PR #33 (jax_env_core)",
)
EnvParams   = _jax_env.EnvParams
EnvState    = _jax_env.EnvState
env_step    = _jax_env.step
env_reset   = _jax_env.reset
PRICE_TABLE = _jax_env.PRICE_TABLE_YPW

_syn = pytest.importorskip(
    "energy_go.generators.synthetic",
    reason="requires generate_year from jax_env_core",
)
generate_year = _syn.generate_year

# baselines is the module under test
_bsl = pytest.importorskip(
    "energy_go.training.baselines",
    reason="requires baselines from training_pipeline contract",
)
run_baseline   = _bsl.run_baseline   # existing §5 baselines
run_benchmark  = getattr(_bsl, "run_benchmark", None)   # new §11 entry point
GreedyPolicy   = getattr(_bsl, "GreedyPolicy",  None)
DpOraclePolicy = getattr(_bsl, "DpOraclePolicy", None)
MpcPolicy      = getattr(_bsl, "MpcPolicy",      None)

# Telemetry builder (for eval_compare key tests)
_tel = pytest.importorskip(
    "energy_go.training.telemetry",
    reason="requires telemetry from training_pipeline",
)
build_eval_compare = _tel.build_eval_compare

from energy_go.training.eval import PolicyEvalResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def synthetic_year_data():
    """Full 8760×4 synthetic year used across tests."""
    return generate_year(jax.random.PRNGKey(0))


@pytest.fixture(scope="module")
def gansu_params():
    """Gansu defaults with 8760-step eval year."""
    return EnvParams(episode_len=8760)


def _make_data(rows: int = 8760, wind_mps: float = 0.0, irr_wm2: float = 0.0,
               temp_c: float = 25.0, load_mw: float = 0.0) -> jax.Array:
    """Constant synthetic data array for deterministic single-step tests."""
    data = jnp.zeros((rows, 4), dtype=jnp.float32)
    data = data.at[:, 0].set(wind_mps)
    data = data.at[:, 1].set(irr_wm2)
    data = data.at[:, 2].set(temp_c)
    data = data.at[:, 3].set(load_mw)
    return data


# ---------------------------------------------------------------------------
# A — GreedyPolicy.action() step-level unit tests
# ---------------------------------------------------------------------------

class TestGreedyPolicyAction:
    """Greedy action conforms to §11.1 decision rules."""

    def test_action_shape_is_6(self):
        """GreedyPolicy returns a 6-dim action vector — same shape as §2.2 Energy Router."""
        if GreedyPolicy is None:
            pytest.skip("GreedyPolicy not yet implemented")
        data = _make_data(load_mw=100.0)
        params = EnvParams(episode_len=1)
        key = jax.random.PRNGKey(0)
        state, _ = env_reset(key, params, data)
        policy = GreedyPolicy()
        action = policy.action(state, data[0], params)
        assert action.shape == (6,), f"Expected (6,), got {action.shape}"

    def test_action_all_within_bounds(self):
        """All 6 action components lie within their valid ranges — §2.2.

        a[0] = a_bat ∈ [-1, 1]; a[1:6] = fractions ∈ [0, 1].
        """
        if GreedyPolicy is None:
            pytest.skip("GreedyPolicy not yet implemented")
        data = _make_data(load_mw=200.0)
        params = EnvParams(episode_len=1)
        key = jax.random.PRNGKey(1)
        state, _ = env_reset(key, params, data)
        policy = GreedyPolicy()
        action = policy.action(state, data[0], params)
        a = np.array(action)
        assert -1.0 - 1e-6 <= a[0] <= 1.0 + 1e-6, f"a_bat={a[0]:.4f} outside [-1,1]"
        for i in range(1, 6):
            assert -1e-6 <= a[i] <= 1.0 + 1e-6, f"action[{i}]={a[i]:.4f} outside [0,1]"

    def test_deficit_causes_discharge(self):
        """When renewable < load and SOC > SOC_MIN, greedy discharges battery (a_bat < 0).

        Rationale (§11.1): battery discharge costs c_deg=10 ¥/MWh — always cheaper
        than grid import at ANY price tier (min price = 250 ¥/MWh > 10 ¥/MWh).
        """
        if GreedyPolicy is None:
            pytest.skip("GreedyPolicy not yet implemented")
        # No renewable, 200 MW load, SOC well above SOC_MIN=0.2
        data = _make_data(wind_mps=0.0, irr_wm2=0.0, load_mw=200.0)
        params = EnvParams(episode_len=1, soc_init=0.6)
        key = jax.random.PRNGKey(0)
        state, _ = env_reset(key, params, data)
        policy = GreedyPolicy()
        action = policy.action(state, data[0], params)
        a_bat = float(action[0])
        assert a_bat < 0.0, (
            f"Expected discharge (a_bat < 0) for deficit with SOC=0.6, got {a_bat:.4f}"
        )

    def test_no_grid_charge_in_deficit(self):
        """Greedy NEVER charges battery from the grid (§11.1: no speculative arbitrage).

        When deficit > 0 (renewable < load), a_bat must be ≤ 0 (discharge or idle),
        never > 0 (charge). Any positive a_bat with f_sb=f_wb=0 would be a grid charge.
        """
        if GreedyPolicy is None:
            pytest.skip("GreedyPolicy not yet implemented")
        data = _make_data(wind_mps=0.0, irr_wm2=0.0, load_mw=150.0)
        params = EnvParams(episode_len=1, soc_init=0.5)
        key = jax.random.PRNGKey(0)
        state, _ = env_reset(key, params, data)
        policy = GreedyPolicy()
        action = policy.action(state, data[0], params)
        a_bat = float(action[0])
        assert a_bat <= 0.0 + 1e-6, (
            f"Greedy charged battery (a_bat={a_bat:.4f} > 0) while in deficit — "
            "violation of §11.1 'no speculative arbitrage' rule"
        )

    def test_surplus_below_export_cap_battery_idles(self):
        """When surplus ≤ grid_max_export_mw, greedy idles battery (§11.1).

        All surplus is exported profitably; no curtailment → no reason to charge.
        w=15 m/s → v_hub=15*(105/10)^0.14 ≥ v_rated=12 m/s → P_wind=615 MW (full rated).
        load=100 MW, surplus=515 MW < grid_max_export=945 MW → no curtailment.
        """
        if GreedyPolicy is None:
            pytest.skip("GreedyPolicy not yet implemented")
        # w=15 m/s gives full P_wind=615 MW (verified: v_hub=15*1.39≈20.8 < cutout=25)
        data = _make_data(wind_mps=15.0, irr_wm2=0.0, load_mw=100.0)
        params = EnvParams(episode_len=1, soc_init=0.5)
        key = jax.random.PRNGKey(0)
        state, _ = env_reset(key, params, data)
        policy = GreedyPolicy()
        action = policy.action(state, data[0], params)
        a_bat = float(action[0])
        # Battery should be idle when there's no curtailment risk
        assert abs(a_bat) < 1e-4, (
            f"Greedy should idle battery when surplus {515:.0f} MW ≤ export cap 945 MW, "
            f"got a_bat={a_bat:.4f}"
        )

    def test_surplus_exceeding_export_cap_charges_battery(self):
        """When surplus > grid_max_export_mw (reduced cap), greedy charges battery (§11.1).

        Uses EnvParams(grid_max_export_mw=100) so surplus=515 > 100 → curtailment risk.
        Greedy charges from would-be-curtailed renewable: a_bat > 0.
        """
        if GreedyPolicy is None:
            pytest.skip("GreedyPolicy not yet implemented")
        data = _make_data(wind_mps=15.0, irr_wm2=0.0, load_mw=100.0)
        params = EnvParams(episode_len=1, soc_init=0.5, grid_max_export_mw=100.0)
        key = jax.random.PRNGKey(0)
        state, _ = env_reset(key, params, data)
        policy = GreedyPolicy()
        action = policy.action(state, data[0], params)
        a_bat = float(action[0])
        assert a_bat > 0.0, (
            f"Expected a_bat > 0 (charge from curtailed surplus), got {a_bat:.4f}. "
            "With grid_max_export=100 MW and surplus=515 MW, should charge battery."
        )

    def test_full_battery_no_charge_in_curtailment(self):
        """When SOC = SOC_MAX (0.9), greedy cannot charge further — battery ignores curtailment.

        reviewer: edge case — SOC at ceiling; charge is infeasible regardless of curtailment.
        """
        if GreedyPolicy is None:
            pytest.skip("GreedyPolicy not yet implemented")
        data = _make_data(wind_mps=15.0, irr_wm2=0.0, load_mw=100.0)
        params = EnvParams(episode_len=1, soc_init=0.9, grid_max_export_mw=100.0)
        key = jax.random.PRNGKey(0)
        state, _ = env_reset(key, params, data)
        policy = GreedyPolicy()
        action = policy.action(state, data[0], params)
        a_bat = float(action[0])
        # At SOC_MAX, no headroom — a_bat should be 0 (or very small)
        assert a_bat < 1e-4, (
            f"At SOC=SOC_MAX=0.9, battery cannot charge; expected a_bat≈0, got {a_bat:.4f}"
        )

    def test_empty_battery_no_discharge_in_deficit(self):
        """When SOC = SOC_MIN (0.2), greedy cannot discharge — imports all load from grid.

        reviewer: edge case — SOC at floor; discharge is infeasible.
        """
        if GreedyPolicy is None:
            pytest.skip("GreedyPolicy not yet implemented")
        data = _make_data(wind_mps=0.0, irr_wm2=0.0, load_mw=100.0)
        params = EnvParams(episode_len=1, soc_init=0.2)  # SOC = SOC_MIN exactly
        key = jax.random.PRNGKey(0)
        state, _ = env_reset(key, params, data)
        policy = GreedyPolicy()
        action = policy.action(state, data[0], params)
        a_bat = float(action[0])
        # At SOC_MIN, no discharge headroom — a_bat should be 0 (or very small)
        assert a_bat > -1e-4, (
            f"At SOC=SOC_MIN=0.2, battery cannot discharge; expected a_bat≈0, got {a_bat:.4f}"
        )

    def test_zero_load_zero_renewable_battery_idles(self):
        """When load=0 and renewable=0, no cost-saving action exists — battery idles.

        reviewer: degenerate input — nothing to serve, nothing to curtail.
        """
        if GreedyPolicy is None:
            pytest.skip("GreedyPolicy not yet implemented")
        data = _make_data(wind_mps=0.0, irr_wm2=0.0, load_mw=0.0)
        params = EnvParams(episode_len=1, soc_init=0.5)
        key = jax.random.PRNGKey(0)
        state, _ = env_reset(key, params, data)
        policy = GreedyPolicy()
        action = policy.action(state, data[0], params)
        a_bat = float(action[0])
        assert abs(a_bat) < 1e-4, (
            f"With load=0 and renewable=0, battery should idle; got a_bat={a_bat:.4f}"
        )


# ---------------------------------------------------------------------------
# B — GreedyPolicy hand-computed single-step cost assertions
# ---------------------------------------------------------------------------

@pytest.mark.slow  # D30: every test calls run_benchmark() which JIT-compiles even at episode_len=1
class TestGreedySingleStepHandComputed:
    """Exact arithmetic for one-step greedy eval — arithmetic shown in comments.

    All tests use the deficit scenario: no renewable, so P_export=0 and
    price_sell does not appear → exact deterministic cost assertions.
    """

    def test_deficit_one_step_energy_cost(self):
        """Greedy, 1 step, no renewable, load=200 MW, SOC_init=0.6, hour h=0 (valley=250 ¥/MWh).

        Arithmetic:
          P_dis_max = min(bat_power_mw, (soc-soc_min)*bat_capacity_mwh*eta_dis)
                    = min(98.16,  (0.6-0.2)*294.5*0.97)
                    = min(98.16,  0.4*285.665)
                    = min(98.16,  114.266) = 98.16 MW
          P_dis_actual = min(deficit=200, 98.16) = 98.16 MW
          P_import = 200 - 98.16 = 101.84 MW
          P_export = 0 MW
          energy_cost_yuan = price_buy * P_import - price_sell * P_export
                           = 250 * 101.84 - price_sell * 0
                           = 25,460 ¥  (price_sell irrelevant: no export)
        """
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        data  = _make_data(load_mw=200.0)   # wind=0, irr=0 → P_wind=P_pv=0
        params = EnvParams(episode_len=1, soc_init=0.6)
        result = run_benchmark("greedy", data, params)
        # Price_buy at t=0 h=0 = 250 ¥/MWh (valley, PRICE_TABLE_YPW[0])
        # P_import = 200 - 98.16 = 101.84 MW → energy_cost = 250 * 101.84 = 25460 ¥
        assert result.energy_cost_yuan == pytest.approx(25_460.0, abs=0.5), (
            f"energy_cost_yuan={result.energy_cost_yuan:.2f} ≠ 25460 ¥"
        )

    def test_deficit_one_step_degradation_cost(self):
        """Same 1-step scenario: degradation = c_deg * P_dis_actual = 10 * 98.16 = 981.6 ¥.

        Arithmetic:
          C_deg = c_deg_yuan_per_mwh * (P_bat_ch + P_bat_dis) * Δt
                = 10 * (0 + 98.16) * 1 = 981.6 ¥
        """
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        data  = _make_data(load_mw=200.0)
        params = EnvParams(episode_len=1, soc_init=0.6)
        result = run_benchmark("greedy", data, params)
        # C_deg = 10 * P_dis = 10 * 98.16 = 981.6 ¥
        assert result.degradation_yuan == pytest.approx(981.6, abs=0.5), (
            f"degradation_yuan={result.degradation_yuan:.2f} ≠ 981.6 ¥"
        )

    def test_deficit_one_step_total_cost(self):
        """Total cost = energy + demand(=0) + degrad + curtail(=0) + voll(=0).

        Arithmetic:
          total = 25,460 + 0 + 981.6 + 0 + 0 = 26,441.6 ¥
          (demand_charge_yuan=0: t=0 is not month-end and is not t=8759)
        """
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        data  = _make_data(load_mw=200.0)
        params = EnvParams(episode_len=1, soc_init=0.6)
        result = run_benchmark("greedy", data, params)
        # 250 * 101.84 + 10 * 98.16 = 25460 + 981.6 = 26441.6 ¥
        assert result.total_cost_yuan == pytest.approx(26_441.6, abs=1.0), (
            f"total_cost_yuan={result.total_cost_yuan:.2f} ≠ 26441.6 ¥"
        )

    def test_deficit_one_step_no_voll_no_curtailment(self):
        """1-step deficit: load fully served → no VOLL; no renewable → no curtailment.

        grid_import = 101.84 ≤ grid_max_import_mw=400 → load is served.
        """
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        data  = _make_data(load_mw=200.0)
        params = EnvParams(episode_len=1, soc_init=0.6)
        result = run_benchmark("greedy", data, params)
        assert result.voll_yuan == pytest.approx(0.0, abs=1e-3), (
            f"voll_yuan={result.voll_yuan:.2f} ≠ 0 (load should be served)"
        )
        assert result.curtailment_yuan == pytest.approx(0.0, abs=1e-3), (
            f"curtailment_yuan={result.curtailment_yuan:.2f} ≠ 0 (no renewable → no curtailment)"
        )

    def test_deficit_one_step_no_soc_violation(self):
        """Greedy SOC stays within [0.2, 0.9] — no SOC violation for this step."""
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        data  = _make_data(load_mw=200.0)
        params = EnvParams(episode_len=1, soc_init=0.6)
        result = run_benchmark("greedy", data, params)
        assert result.soc_violations_count == 0
        assert result.soc_violation_mwh == pytest.approx(0.0, abs=1e-3)

    def test_curtailment_one_step_hand_computed(self):
        """1-step surplus-with-curtailment: greedy charges from would-be-curtailed wind.

        Setup:  grid_max_export_mw=100 (reduced), wind=15 m/s → P_wind=615 MW, load=100 MW.
        Arithmetic:
          surplus = 615 - 100 = 515 MW
          export_cap = 100 MW
          would_curtail = 515 - 100 = 415 MW (before battery)
          P_ch_max = min(bat_power_mw, (soc_max-soc)*bat_capacity_mwh/eta_ch)
                   = min(98.16, (0.9-0.5)*294.5/0.97)
                   = min(98.16, (0.4*294.5)/0.97)
                   = min(98.16, 117.8/0.97)
                   = min(98.16, 121.44) = 98.16 MW
          P_ch_actual = min(415, 98.16) = 98.16 MW
          actual_curtail = 415 - 98.16 = 316.84 MW
          C_deg = 10 * 98.16 = 981.6 ¥
          C_curtail = 800 * 316.84 = 253,472 ¥
        """
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        data = _make_data(wind_mps=15.0, irr_wm2=0.0, load_mw=100.0)
        params = EnvParams(episode_len=1, soc_init=0.5, grid_max_export_mw=100.0)
        result = run_benchmark("greedy", data, params)
        # C_deg = 10 * 98.16 = 981.6 ¥
        assert result.degradation_yuan == pytest.approx(981.6, abs=2.0), (
            f"degradation_yuan={result.degradation_yuan:.2f} ≠ 981.6 ¥ (expected full charge)"
        )
        # Curtail = 800 * 316.84 = 253,472 ¥ (approx — P_wind exact value depends on JAX float)
        assert result.curtailment_yuan == pytest.approx(253_472.0, rel=0.02), (
            f"curtailment_yuan={result.curtailment_yuan:.2f} outside 2% of 253472 ¥"
        )
        assert result.voll_yuan == pytest.approx(0.0, abs=1.0)


# ---------------------------------------------------------------------------
# C — run_benchmark("greedy") full-year property tests
# ---------------------------------------------------------------------------

class TestGreedyFullYearProperties:
    """Full 8760-step greedy eval over synthetic year — property invariants."""

    @pytest.mark.slow  # D30: calls run_benchmark which JIT-compiles lax.scan over 8760 steps
    def test_greedy_eval_result_additive_identity(self, synthetic_year_data, gansu_params):
        """total_cost_yuan = energy + demand + degradation + curtailment + voll within 0.1 ¥.

        Contract invariant I5.
        """
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        result = run_benchmark("greedy", synthetic_year_data, gansu_params)
        expected_total = (result.energy_cost_yuan + result.demand_charge_yuan
                          + result.degradation_yuan + result.curtailment_yuan
                          + result.voll_yuan)
        assert result.total_cost_yuan == pytest.approx(expected_total, abs=0.1), (
            f"Additive identity violated: total={result.total_cost_yuan:.2f} ≠ "
            f"sum of components={expected_total:.2f}"
        )

    @pytest.mark.slow  # D30: JIT-compiles lax.scan
    def test_greedy_eval_no_soc_violations(self, synthetic_year_data, gansu_params):
        """Greedy SOC stays in [0.2, 0.9] throughout the year — contract invariant I4.

        The greedy algorithm only charges/discharges within the SOC constraints by
        construction (P_dis limited by (soc-soc_min)*capacity*eta_dis, etc.).
        """
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        result = run_benchmark("greedy", synthetic_year_data, gansu_params)
        assert result.soc_violations_count == 0, (
            f"Greedy SOC violations: {result.soc_violations_count} steps"
        )
        assert result.soc_violation_mwh == pytest.approx(0.0, abs=1e-3)

    @pytest.mark.slow  # D30: JIT-compiles lax.scan
    def test_greedy_cost_components_are_finite(self, synthetic_year_data, gansu_params):
        """All cost components are finite (no NaN or Inf) — data quality guard."""
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        result = run_benchmark("greedy", synthetic_year_data, gansu_params)
        for name, val in [
            ("energy_cost_yuan",   result.energy_cost_yuan),
            ("demand_charge_yuan", result.demand_charge_yuan),
            ("degradation_yuan",   result.degradation_yuan),
            ("curtailment_yuan",   result.curtailment_yuan),
            ("voll_yuan",          result.voll_yuan),
            ("total_cost_yuan",    result.total_cost_yuan),
        ]:
            assert math.isfinite(val), f"{name} is not finite: {val}"

    @pytest.mark.slow  # D30: JIT-compiles lax.scan
    def test_greedy_degradation_positive(self, synthetic_year_data, gansu_params):
        """Greedy year degradation > 0: battery must be used at least once over 8760 steps."""
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        result = run_benchmark("greedy", synthetic_year_data, gansu_params)
        assert result.degradation_yuan > 0.0, (
            "Greedy degradation_yuan=0 — battery was never used; "
            "check renewable and load levels."
        )


# ---------------------------------------------------------------------------
# D — DpOraclePolicy ordering and correctness
# ---------------------------------------------------------------------------

class TestDpOracleOrdering:
    """DP oracle produces costs ≤ any causal policy (invariants I1–I2)."""

    @pytest.mark.slow  # D30: runs DP backward induction + full-year env rollout
    def test_dp_oracle_beats_greedy(self, synthetic_year_data, gansu_params):
        """dp_oracle.total_cost_yuan ≤ greedy.total_cost_yuan — invariant I1.

        The DP oracle has perfect foresight and solves for the global minimum;
        by definition it cannot cost more than any causal policy on the same data.

        Tolerance derivation (§3.2 SOC-grid resolution):
          Δsoc = 0.01 (71 states), bat_capacity = 294.5 MWh, max_price = 780 ¥/MWh
          Max per-step rounding: Δsoc × bat_cap × max_price = 0.01 × 294.5 × 780 = 2,297 ¥
          After replay through continuous-SOC env, ~12 months × 4 SOC bin crossings × 2,297 ¥
          ≈ 110,000 ¥ cumulative. Use 100_000 ¥ — tight vs ~750M ¥ year total (<0.014%).
          The 3-step exact test keeps +1e-3 (no accumulated error there).
        """
        if run_benchmark is None or DpOraclePolicy is None:
            pytest.skip("DpOraclePolicy / run_benchmark not yet implemented")
        greedy_result  = run_benchmark("greedy",    synthetic_year_data, gansu_params)
        oracle_result  = run_benchmark("dp_oracle", synthetic_year_data, gansu_params)
        # §3.2 discretization tolerance: 100_000 ¥ ≈ 12 months × 4 bin-crossings × 2,297 ¥/crossing
        DISCRETIZATION_TOL_YUAN = 100_000.0
        assert oracle_result.total_cost_yuan <= greedy_result.total_cost_yuan + DISCRETIZATION_TOL_YUAN, (
            f"DP oracle ({oracle_result.total_cost_yuan:.2f} ¥) is more than {DISCRETIZATION_TOL_YUAN:.0f} ¥ "
            f"more expensive than greedy ({greedy_result.total_cost_yuan:.2f} ¥) — "
            "discretization error exceeds expected bound; check oracle implementation."
        )

    @pytest.mark.slow  # D30: runs DP + TOU eval
    def test_dp_oracle_beats_rule_based_tou(self, synthetic_year_data, gansu_params):
        """dp_oracle.total_cost_yuan ≤ rule_based_tou.total_cost_yuan — invariant I2.

        Same §3.2 discretization tolerance as I1 (100_000 ¥).
        """
        if run_benchmark is None or DpOraclePolicy is None:
            pytest.skip("DpOraclePolicy / run_benchmark not yet implemented")
        tou_result    = run_baseline("rule_based_tou", synthetic_year_data, gansu_params)
        oracle_result = run_benchmark("dp_oracle",     synthetic_year_data, gansu_params)
        DISCRETIZATION_TOL_YUAN = 100_000.0  # §3.2 SOC-grid resolution; same derivation as I1
        assert oracle_result.total_cost_yuan <= tou_result.total_cost_yuan + DISCRETIZATION_TOL_YUAN, (
            f"DP oracle ({oracle_result.total_cost_yuan:.2f} ¥) more than {DISCRETIZATION_TOL_YUAN:.0f} ¥ "
            f"more expensive than rule-based TOU ({tou_result.total_cost_yuan:.2f} ¥)"
        )

    @pytest.mark.slow  # D30
    def test_dp_oracle_soc_stays_in_bounds(self, synthetic_year_data, gansu_params):
        """DP oracle SOC stays in [soc_min=0.2, soc_max=0.9] for all 8760 steps.

        Contract invariant I4 (extended to dp_oracle).
        """
        if run_benchmark is None or DpOraclePolicy is None:
            pytest.skip("DpOraclePolicy / run_benchmark not yet implemented")
        result = run_benchmark("dp_oracle", synthetic_year_data, gansu_params)
        assert result.soc_violations_count == 0, (
            f"DP oracle SOC violated at {result.soc_violations_count} steps "
            f"({result.soc_violation_mwh:.2f} MWh total)"
        )

    @pytest.mark.slow  # D30
    def test_dp_oracle_additive_identity(self, synthetic_year_data, gansu_params):
        """DP oracle PolicyEvalResult satisfies additive identity — invariant I5."""
        if run_benchmark is None or DpOraclePolicy is None:
            pytest.skip("DpOraclePolicy / run_benchmark not yet implemented")
        result = run_benchmark("dp_oracle", synthetic_year_data, gansu_params)
        expected = (result.energy_cost_yuan + result.demand_charge_yuan
                    + result.degradation_yuan + result.curtailment_yuan
                    + result.voll_yuan)
        assert result.total_cost_yuan == pytest.approx(expected, abs=0.1)

    @pytest.mark.slow  # D30
    def test_dp_oracle_wall_time_reported(self, synthetic_year_data, gansu_params):
        """DpOraclePolicy.metadata contains 'dp_wall_time_s' — contract §6.1.

        Value should be positive and < 600 s (10 min budget on standard CPU).
        """
        if run_benchmark is None or DpOraclePolicy is None:
            pytest.skip("DpOraclePolicy / run_benchmark not yet implemented")
        # run_benchmark returns PolicyEvalResult; to access metadata, construct DpOraclePolicy
        # directly. The oracle's metadata must be accessible via the policy object.
        # This test validates that run_benchmark("dp_oracle") internally creates a
        # DpOraclePolicy whose .metadata["dp_wall_time_s"] is set.
        # Implementation note: run_benchmark may expose metadata via a module-level
        # cache or via the DpOraclePolicy.last_metadata class attribute.
        policy = DpOraclePolicy.from_data(synthetic_year_data, gansu_params)
        assert "dp_wall_time_s" in policy.metadata, (
            "DpOraclePolicy.metadata missing 'dp_wall_time_s' key"
        )
        wt = policy.metadata["dp_wall_time_s"]
        assert wt > 0.0, f"dp_wall_time_s={wt} is not positive"
        assert wt < 600.0, f"DP oracle wall time {wt:.1f} s exceeds 600 s budget"

    @pytest.mark.slow  # D30
    def test_dp_oracle_3step_beats_greedy_and_tou(self):
        """3-step episode: DP oracle cost ≤ min(greedy, TOU) on the same data.

        Uses a hand-crafted 3-step scenario where arbitrage is profitable:
          h=0 (valley, 250 ¥):  load=0,   renewable=0  → no action is trivial
          h=11 (peak, 780 ¥):   load=200, renewable=0  → must import heavily without bat
          h=23 (valley, 250 ¥): load=0,   renewable=0  → N/A

        (episode_len=2 for simplicity: only h=0 and h=11)

        reviewer: 3-step oracle should beat greedy which can't charge speculatively.
        """
        if run_benchmark is None or DpOraclePolicy is None:
            pytest.skip("DpOraclePolicy / run_benchmark not yet implemented")
        # episode_len=2: step t=0 (h=0, valley) then t=1 (h=1, valley — loads at h=0 only)
        # To get the valley→peak arbitrage we need t=0 (h=0) and t=11 (h=11)
        # Use episode_len=12, data has high load only at row t=11
        data = _make_data(rows=8760, wind_mps=0.0, irr_wm2=0.0, load_mw=0.0)
        data = data.at[11, 3].set(200.0)  # 200 MW load only at t=11 (h=11, price=780)
        params = EnvParams(episode_len=12, soc_init=0.5)
        greedy_r = run_benchmark("greedy",    data, params)
        oracle_r = run_benchmark("dp_oracle", data, params)
        # DP should find the grid-charge-at-valley strategy if it's profitable
        assert oracle_r.total_cost_yuan <= greedy_r.total_cost_yuan + 1e-3, (
            f"oracle={oracle_r.total_cost_yuan:.2f} ¥ > greedy={greedy_r.total_cost_yuan:.2f} ¥"
        )


# ---------------------------------------------------------------------------
# E — MpcPolicy property tests
# ---------------------------------------------------------------------------

class TestMpcPolicyProperties:
    """MPC receding-horizon baseline satisfies contract §3.3."""

    @pytest.mark.slow  # D30: per-step LP solves + full-year env rollout
    def test_mpc_additive_identity(self, synthetic_year_data, gansu_params):
        """MPC PolicyEvalResult satisfies additive identity — invariant I5."""
        if run_benchmark is None or MpcPolicy is None:
            pytest.skip("MpcPolicy / run_benchmark not yet implemented")
        result = run_benchmark("mpc", synthetic_year_data, gansu_params)
        expected = (result.energy_cost_yuan + result.demand_charge_yuan
                    + result.degradation_yuan + result.curtailment_yuan
                    + result.voll_yuan)
        assert result.total_cost_yuan == pytest.approx(expected, abs=0.1)

    @pytest.mark.slow  # D30
    def test_mpc_soc_stays_in_bounds(self, synthetic_year_data, gansu_params):
        """MPC SOC stays in [soc_min, soc_max] for all 8760 steps."""
        if run_benchmark is None or MpcPolicy is None:
            pytest.skip("MpcPolicy / run_benchmark not yet implemented")
        result = run_benchmark("mpc", synthetic_year_data, gansu_params)
        assert result.soc_violations_count == 0, (
            f"MPC SOC violated at {result.soc_violations_count} steps"
        )

    @pytest.mark.slow  # D30
    def test_mpc_cost_finite(self, synthetic_year_data, gansu_params):
        """MPC PolicyEvalResult has no NaN/Inf — LP solver did not fail on any step."""
        if run_benchmark is None or MpcPolicy is None:
            pytest.skip("MpcPolicy / run_benchmark not yet implemented")
        result = run_benchmark("mpc", synthetic_year_data, gansu_params)
        assert math.isfinite(result.total_cost_yuan), "MPC total_cost_yuan is not finite"
        assert math.isfinite(result.energy_cost_yuan), "MPC energy_cost_yuan is not finite"

    @pytest.mark.slow  # D30
    def test_mpc_horizon_default_24(self, synthetic_year_data, gansu_params):
        """MpcPolicy default horizon is 24 steps (matching RL forecast horizon D6)."""
        if MpcPolicy is None:
            pytest.skip("MpcPolicy not yet implemented")
        policy = MpcPolicy()
        assert policy.horizon == 24, f"Default MPC horizon={policy.horizon} ≠ 24"

    @pytest.mark.slow  # D30
    def test_mpc_voll_zero(self, synthetic_year_data, gansu_params):
        """MPC voll_yuan = 0: LP always includes load as a hard constraint.

        reviewer: MPC feasibility — LP must be designed so load is always served
        (either from renewable, battery, or grid import up to max_import_mw).
        """
        if run_benchmark is None or MpcPolicy is None:
            pytest.skip("MpcPolicy / run_benchmark not yet implemented")
        result = run_benchmark("mpc", synthetic_year_data, gansu_params)
        assert result.voll_yuan == pytest.approx(0.0, abs=1.0), (
            f"MPC voll_yuan={result.voll_yuan:.2f} ≠ 0 — LP did not serve all load"
        )


# ---------------------------------------------------------------------------
# F — run_benchmark interface
# ---------------------------------------------------------------------------

class TestRunBenchmarkInterface:
    """run_benchmark() interface contract — §2.1."""

    def test_unknown_policy_raises_value_error(self):
        """run_benchmark raises ValueError for unknown policy_name."""
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        data = _make_data()
        params = EnvParams(episode_len=1)
        with pytest.raises(ValueError, match="greedy|dp_oracle|mpc"):
            run_benchmark("not_a_real_policy", data, params)

    def test_none_params_uses_gansu_defaults(self):
        """run_benchmark(params=None) does not raise — uses EnvParams defaults."""
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        data = generate_year(jax.random.PRNGKey(42))
        # Should not raise
        result = run_benchmark("greedy", data, params=None)
        assert isinstance(result, PolicyEvalResult)

    def test_returns_policy_eval_result_type(self):
        """run_benchmark returns a PolicyEvalResult instance — §2.1."""
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        data = _make_data(load_mw=100.0)
        params = EnvParams(episode_len=1)
        result = run_benchmark("greedy", data, params)
        assert isinstance(result, PolicyEvalResult), (
            f"run_benchmark returned {type(result)} instead of PolicyEvalResult"
        )

    def test_greedy_deterministic_same_data_same_result(self):
        """run_benchmark('greedy', ...) is deterministic: same data → same result."""
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        data   = _make_data(load_mw=100.0)
        params = EnvParams(episode_len=2, soc_init=0.5)
        r1 = run_benchmark("greedy", data, params)
        r2 = run_benchmark("greedy", data, params)
        assert r1.total_cost_yuan == pytest.approx(r2.total_cost_yuan, abs=1e-3)


# ---------------------------------------------------------------------------
# G — Telemetry integration: eval_compare message includes §11 policy keys
# ---------------------------------------------------------------------------

class TestTelemetryEvalCompareKeys:
    """eval_compare message adds 'greedy', 'dp_oracle', 'mpc' policy keys — §11.5.

    Schema confirmation (reviewer point 4):
    LOCKED telemetry_schema.md §LOCKED states: "'additionalProperties' is 'true' everywhere
    to honor the minor-forward-compat rule" — confirmed in contracts/shared/telemetry_schema.md
    line ~282. These tests verify that validate() ACCEPTS the new keys (does not reject them)
    precisely because additionalProperties=true is in the live LOCKED schema JSON.
    If the schema were to change to additionalProperties=false, these tests would catch it.

    Each key carries the standard policy_costs shape used by 'rl', 'no_battery',
    'rule_based_tou'.
    """

    def _make_policy_costs(self, **kwargs) -> dict:
        """Minimal valid policy_costs dict for eval_compare."""
        defaults = dict(
            energy_cost_yuan=0.0, demand_charge_yuan=0.0, degradation_yuan=0.0,
            curtailment_yuan=0.0, voll_yuan=0.0, total_cost_yuan=0.0,
            soc_violations_count=0, soc_violation_mwh=0.0, penalty_yuan=0.0,
        )
        defaults.update(kwargs)
        return defaults

    def test_greedy_key_accepted_in_eval_compare(self):
        """eval_compare message with 'greedy' policy key passes telemetry validation.

        §11.5: additive minor bump — policies object has additionalProperties=true.
        """
        _validate = pytest.importorskip(
            "energy_go.telemetry.validate",
            reason="requires telemetry_validate from PR #23",
        )
        msg = {
            "type": "eval_compare",
            "step": 100_000,
            "policies": {
                "rl":             self._make_policy_costs(total_cost_yuan=-5e6),
                "no_battery":     self._make_policy_costs(total_cost_yuan=-4e6),
                "rule_based_tou": self._make_policy_costs(total_cost_yuan=-4.5e6),
                "greedy":         self._make_policy_costs(total_cost_yuan=-4.8e6),  # NEW
            },
        }
        errors = _validate.validate(msg)
        assert not errors, (
            f"Telemetry validation failed for 'greedy' policy key: {errors}"
        )

    def test_dp_oracle_key_accepted_in_eval_compare(self):
        """eval_compare with 'dp_oracle' policy key passes validation — §11.5."""
        _validate = pytest.importorskip(
            "energy_go.telemetry.validate",
            reason="requires telemetry_validate from PR #23",
        )
        msg = {
            "type": "eval_compare",
            "step": 100_000,
            "policies": {
                "rl":             self._make_policy_costs(total_cost_yuan=-5e6),
                "no_battery":     self._make_policy_costs(total_cost_yuan=-4e6),
                "rule_based_tou": self._make_policy_costs(total_cost_yuan=-4.5e6),
                "dp_oracle":      self._make_policy_costs(total_cost_yuan=-5.2e6),  # NEW
            },
        }
        errors = _validate.validate(msg)
        assert not errors, (
            f"Telemetry validation failed for 'dp_oracle' policy key: {errors}"
        )

    def test_mpc_key_accepted_in_eval_compare(self):
        """eval_compare with 'mpc' policy key passes validation — §11.5."""
        _validate = pytest.importorskip(
            "energy_go.telemetry.validate",
            reason="requires telemetry_validate from PR #23",
        )
        msg = {
            "type": "eval_compare",
            "step": 100_000,
            "policies": {
                "rl":             self._make_policy_costs(total_cost_yuan=-5e6),
                "no_battery":     self._make_policy_costs(total_cost_yuan=-4e6),
                "rule_based_tou": self._make_policy_costs(total_cost_yuan=-4.5e6),
                "mpc":            self._make_policy_costs(total_cost_yuan=-5.0e6),  # NEW
            },
        }
        errors = _validate.validate(msg)
        assert not errors, (
            f"Telemetry validation failed for 'mpc' policy key: {errors}"
        )

    def test_all_three_keys_together_in_eval_compare(self):
        """Full §11 eval_compare with greedy + dp_oracle + mpc all present — §11.5."""
        _validate = pytest.importorskip(
            "energy_go.telemetry.validate",
            reason="requires telemetry_validate from PR #23",
        )
        msg = {
            "type": "eval_compare",
            "step": 500_000,
            "policies": {
                "rl":             self._make_policy_costs(total_cost_yuan=-5.1e6),
                "no_battery":     self._make_policy_costs(total_cost_yuan=-4.0e6),
                "rule_based_tou": self._make_policy_costs(total_cost_yuan=-4.5e6),
                "greedy":         self._make_policy_costs(total_cost_yuan=-4.9e6),
                "dp_oracle":      self._make_policy_costs(total_cost_yuan=-5.3e6),
                "mpc":            self._make_policy_costs(total_cost_yuan=-5.0e6),
            },
        }
        errors = _validate.validate(msg)
        assert not errors, (
            f"Full §11 eval_compare message failed validation: {errors}"
        )

    def test_build_eval_compare_includes_greedy_key(self, synthetic_year_data, gansu_params):
        """build_eval_compare() includes 'greedy' key when greedy result is provided — §11.5.

        reviewer: API shape — build_eval_compare must accept optional §11 policy kwargs.
        """
        if run_benchmark is None:
            pytest.skip("run_benchmark not yet implemented")
        greedy_result = run_benchmark("greedy", synthetic_year_data, gansu_params)
        # build_eval_compare must accept an optional 'greedy' kwarg (or **extra_policies)
        # Signature: build_eval_compare(step, rl_result, no_bat, tou, *, greedy=None, ...)
        msg = build_eval_compare(
            step=100_000,
            rl_result=PolicyEvalResult(0, 0, 0, 0, 0, 0, 0, 0.0, 0.0),
            no_battery_result=PolicyEvalResult(0, 0, 0, 0, 0, 0, 0, 0.0, 0.0),
            tou_result=PolicyEvalResult(0, 0, 0, 0, 0, 0, 0, 0.0, 0.0),
            greedy_result=greedy_result,
        )
        assert "greedy" in msg["policies"], (
            f"'greedy' key missing from eval_compare.policies: {list(msg['policies'].keys())}"
        )
