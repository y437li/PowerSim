"""Tests for contracts/serving/training_config.md v1.0.0.

POST /api/training/config — wizard algorithm/hyperparam → RunConfig assembly.

Contract: contracts/serving/training_config.md
Module (to be implemented): src/energy_go/serving/training_config.py

All tests are RED until implementation lands (contract-first-dev step 2).

Units:
  lr               — dimensionless
  total_env_steps  — env steps (counting each vmapped step as 1 step per env, × n_envs actual)
  buffer_size      — env-step tuples
  eval_every_steps — env steps
  n_envs           — parallel environments (must be power of 2)
"""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from energy_go.serving.app import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# §4 / §6 — Happy path: SAC default hyperparams
# ---------------------------------------------------------------------------

class TestSacDefaults:
    """POST /api/training/config with algorithm_type='sac' and minimal body
    (no sac_hyperparams supplied) must return a fully-assembled RunConfig
    populated entirely with defaults (contract §5.1 / §5.2)."""

    def test_returns_200(self, client):
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery", "tou"],
        })
        assert resp.status_code == 200, resp.text

    def test_response_has_required_top_level_keys(self, client):
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        body = resp.json()
        for key in ("config_id", "config_hash", "algorithm_type", "baselines", "run_config"):
            assert key in body, f"Missing key '{key}' in response"

    def test_algorithm_type_echoed(self, client):
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        assert resp.json()["algorithm_type"] == "sac"

    def test_run_config_gamma_always_0999(self, client):
        """gamma=0.999 is server-enforced (RunConfig §3.1 / contract §5.2).
        Arithmetic: gamma LOCKED at 0.999; any other value is a contract violation."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        assert resp.json()["run_config"]["gamma"] == 0.999, (
            "gamma MUST be 0.999 (locked — RunConfig §3.1; change requires rl-architect DECISION)"
        )

    def test_run_config_defaults(self, client):
        """RunConfig defaults when no sac_hyperparams supplied (contract §4.2):
          lr=1e-4, hidden_sizes=[256,256], batch_size=512, buffer_size=1_000_000,
          total_env_steps=500_000, eval_every_steps=10_000, n_envs=4096, seed=42."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        rc = resp.json()["run_config"]
        assert rc["lr"] == pytest.approx(1e-4), "lr default must be 1e-4"
        assert rc["hidden_sizes"] == [256, 256], "hidden_sizes default must be [256, 256]"
        assert rc["batch_size"] == 512, "batch_size default must be 512"
        assert rc["buffer_size"] == 1_000_000, "buffer_size default must be 1_000_000"
        assert rc["total_env_steps"] == 500_000, "total_env_steps default must be 500_000"
        assert rc["eval_every_steps"] == 10_000, "eval_every_steps default must be 10_000"
        assert rc["n_envs"] == 4096, "n_envs default must be 4096"
        assert rc["seed"] == 42, "seed default must be 42"

    def test_run_config_server_constants(self, client):
        """Server-enforced constants present in every response (contract §5.2)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        rc = resp.json()["run_config"]
        assert rc["gamma"] == 0.999
        assert rc["tau"] == pytest.approx(0.005)
        assert rc["ent_coef"] == "auto"
        assert rc["episode_len"] == 168       # 7-day @ Δt=1h (D3)
        assert rc["eval_episode_len"] == 8760  # full-year eval (§5)
        assert rc["norm_obs"] is True
        assert rc["norm_reward"] is True
        assert rc["clip_obs"] == pytest.approx(10.0)
        assert rc["clip_reward"] == pytest.approx(10.0)
        assert rc["log_every_steps"] == 1000
        assert rc["run_id"] == ""             # assigned at /training/start (§5.2)

    def test_run_config_site_config_id_threaded(self, client):
        """site_config_id from request is threaded into run_config (contract §5.1)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        assert resp.json()["run_config"]["site_config_id"] == "site_gansu"

    def test_run_config_all_fields_present(self, client):
        """run_config object must contain every RunConfig field — no optional omissions
        (contract §7 invariant 7)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        rc = resp.json()["run_config"]
        required = {
            "lr", "gamma", "batch_size", "buffer_size", "tau", "ent_coef",
            "total_env_steps", "n_envs", "episode_len", "eval_episode_len",
            "norm_obs", "norm_reward", "clip_obs", "clip_reward",
            "hidden_sizes", "eval_every_steps", "log_every_steps",
            "seed", "run_id", "site_config_id",
        }
        missing = required - set(rc.keys())
        assert not missing, f"run_config missing required fields: {missing}"


# ---------------------------------------------------------------------------
# §5.3 — config_id and config_hash
# ---------------------------------------------------------------------------

class TestConfigIdAndHash:
    """config_id is a UUID4 string; config_hash is sha256 of canonical JSON
    of run_config (contract §5.3 / §8 invariant 3)."""

    def test_config_id_is_uuid4_format(self, client):
        import re
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        config_id = resp.json()["config_id"]
        uuid4_pattern = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        )
        assert uuid4_pattern.match(config_id), (
            f"config_id must be a UUID4 string; got '{config_id}'"
        )

    def test_config_id_unique_per_call(self, client):
        """Each call generates a fresh UUID4 even for identical params (§8 invariant 4)."""
        body = {"algorithm_type": "sac", "site_config_id": "site_gansu",
                "baselines": ["no_battery"]}
        id1 = client.post("/api/training/config", json=body).json()["config_id"]
        id2 = client.post("/api/training/config", json=body).json()["config_id"]
        assert id1 != id2, "Each call must produce a distinct config_id"

    def test_config_hash_is_sha256_of_canonical_run_config(self, client):
        """config_hash = sha256(json.dumps(run_config, sort_keys=True, separators=(',',':')))
        (contract §5.3 invariant 3).
        Arithmetic: canonical JSON → UTF-8 bytes → sha256 → 64-char hex string."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        body = resp.json()
        run_config = body["run_config"]
        canonical = json.dumps(run_config, sort_keys=True, separators=(",", ":"))
        expected_hash = hashlib.sha256(canonical.encode()).hexdigest()
        assert body["config_hash"] == expected_hash, (
            f"config_hash mismatch.\n"
            f"  Expected: {expected_hash}\n"
            f"  Got:      {body['config_hash']}\n"
            f"  Canonical JSON: {canonical[:120]}..."
        )

    def test_config_hash_length_64_hex(self, client):
        """sha256 produces a 64-character hex string."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        h = resp.json()["config_hash"]
        assert len(h) == 64, f"config_hash must be 64 hex chars; got {len(h)}"
        assert all(c in "0123456789abcdef" for c in h), f"config_hash must be hex; got {h[:10]}..."

    def test_identical_params_produce_identical_hash(self, client):
        """Same inputs → same canonical JSON → same hash (deterministic assembly)."""
        body = {
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"lr": 3e-4, "batch_size": 256},
        }
        h1 = client.post("/api/training/config", json=body).json()["config_hash"]
        h2 = client.post("/api/training/config", json=body).json()["config_hash"]
        assert h1 == h2, "Same inputs must produce the same config_hash"


# ---------------------------------------------------------------------------
# §4.2 — User-supplied sac_hyperparams
# ---------------------------------------------------------------------------

class TestSacHyperparams:
    """Custom sac_hyperparams are merged over defaults and reflected in run_config."""

    def test_custom_lr(self, client):
        """lr=3e-4 is threaded into run_config.lr.
        Arithmetic: 3e-4 is within (0, 1e-2] → valid."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"lr": 3e-4},
        })
        assert resp.status_code == 200
        assert resp.json()["run_config"]["lr"] == pytest.approx(3e-4)

    def test_custom_hidden_sizes(self, client):
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"hidden_sizes": [128, 128]},
        })
        assert resp.status_code == 200
        assert resp.json()["run_config"]["hidden_sizes"] == [128, 128]

    def test_custom_batch_size(self, client):
        """batch_size=256 (power of 2, in allowed set {64..1024}) → valid."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"batch_size": 256},
        })
        assert resp.status_code == 200
        assert resp.json()["run_config"]["batch_size"] == 256

    def test_custom_n_envs_power_of_two(self, client):
        """n_envs=1024 (power of 2, ≤ 4096) → valid."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"n_envs": 1024, "total_env_steps": 1_024_000},
        })
        assert resp.status_code == 200
        assert resp.json()["run_config"]["n_envs"] == 1024

    def test_total_env_steps_divisible_by_n_envs(self, client):
        """total_env_steps must be divisible by n_envs (RunConfig §3.1).
        Arithmetic: 512_000 / 1024 = 500 exactly → valid."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"n_envs": 1024, "total_env_steps": 512_000},
        })
        assert resp.status_code == 200

    def test_seed_from_request(self, client):
        """Top-level seed is threaded into run_config.seed."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "seed": 7,
        })
        assert resp.status_code == 200
        assert resp.json()["run_config"]["seed"] == 7

    def test_both_baselines_present(self, client):
        """baselines=['no_battery','tou'] are echoed in response."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery", "tou"],
        })
        assert resp.status_code == 200
        assert sorted(resp.json()["baselines"]) == ["no_battery", "tou"]


# ---------------------------------------------------------------------------
# §4.4 — baseline_only mode
# ---------------------------------------------------------------------------

class TestBaselineOnly:
    """algorithm_type='baseline_only' — no sac_hyperparams in request;
    full RunConfig at defaults in response (§4.4)."""

    def test_baseline_only_returns_200(self, client):
        resp = client.post("/api/training/config", json={
            "algorithm_type": "baseline_only",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery", "tou"],
        })
        assert resp.status_code == 200

    def test_baseline_only_algorithm_type_echoed(self, client):
        resp = client.post("/api/training/config", json={
            "algorithm_type": "baseline_only",
            "site_config_id": "site_gansu",
            "baselines": ["tou"],
        })
        assert resp.json()["algorithm_type"] == "baseline_only"

    def test_baseline_only_run_config_has_defaults(self, client):
        """baseline_only run_config still contains full RunConfig at defaults (§4.4)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "baseline_only",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        rc = resp.json()["run_config"]
        assert rc["lr"] == pytest.approx(1e-4)
        assert rc["gamma"] == 0.999
        assert rc["hidden_sizes"] == [256, 256]

    def test_baseline_only_with_sac_hyperparams_is_422(self, client):
        """sac_hyperparams MUST be absent when algorithm_type='baseline_only' (§4.4).
        Sending it is a VALIDATION_ERROR."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "baseline_only",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"lr": 1e-4},
        })
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# §4.2 — Constraint validation (422 cases)
# ---------------------------------------------------------------------------

class TestValidation422:
    """Constraint violations in sac_hyperparams must return 422 VALIDATION_ERROR
    with a non-empty errors list (contract §3.1 / §7)."""

    def test_lr_zero_is_422(self, client):
        """lr=0 violates constraint (0, 1e-2] → 422."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"lr": 0.0},
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_lr_above_max_is_422(self, client):
        """lr=0.1 > 1e-2 → 422.
        Arithmetic: 0.1 > 0.01 = 1e-2 → out of range."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"lr": 0.1},
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_total_env_steps_below_minimum_is_422(self, client):
        """total_env_steps=1000 < 500_000 → 422 (RunConfig §3.1 + contract §4.2)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"total_env_steps": 1000},
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_total_env_steps_not_divisible_by_n_envs_is_422(self, client):
        """total_env_steps=500_001 is not divisible by n_envs=4096 → 422.
        Arithmetic: 500_001 % 4096 = 500_001 - 4096*122 = 500_001 - 499_712 = 289 ≠ 0."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"total_env_steps": 500_001},
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_n_envs_not_power_of_two_is_422(self, client):
        """n_envs=3 is not a power of 2 → 422 (contract §4.2)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"n_envs": 3, "total_env_steps": 500_000},
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_n_envs_above_max_is_422(self, client):
        """n_envs=8192 > 4096 → 422 (contract §4.2)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"n_envs": 8192, "total_env_steps": 8_192_000},
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_batch_size_not_in_allowed_set_is_422(self, client):
        """batch_size=300 is not in {64, 128, 256, 512, 1024} → 422."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"batch_size": 300},
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_hidden_sizes_empty_is_422(self, client):
        """hidden_sizes=[] violates 'non-empty' constraint (§4.2)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"hidden_sizes": []},
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_hidden_sizes_too_many_is_422(self, client):
        """hidden_sizes with 5 elements violates '1–4 elements' constraint (§4.2)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"hidden_sizes": [64, 64, 64, 64, 64]},
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_hidden_size_below_min_is_422(self, client):
        """hidden_sizes=[8] — element 8 < 16 → 422 (§4.2: each ∈ [16, 1024])."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"hidden_sizes": [8]},
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_eval_every_steps_exceeds_total_is_422(self, client):
        """eval_every_steps=1_000_000 > total_env_steps=500_000 → 422 (§4.2)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"eval_every_steps": 1_000_000},
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_unknown_sac_field_is_422(self, client):
        """Unknown field in sac_hyperparams (e.g. 'gamma') → 422 (§4.2; server-enforced
        constants must not be overridden by clients)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"gamma": 0.99},
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_error_body_has_errors_list(self, client):
        """422 response must include 'errors' list with at least one field+message entry
        (contract §7 error body schema)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
            "sac_hyperparams": {"lr": 0.0},
        })
        assert resp.status_code == 422
        body = resp.json()
        assert "errors" in body, "422 response must have 'errors' list"
        assert isinstance(body["errors"], list) and len(body["errors"]) >= 1
        err = body["errors"][0]
        assert "field" in err and "message" in err


# ---------------------------------------------------------------------------
# §4.3 — Baseline validation
# ---------------------------------------------------------------------------

class TestBaselineValidation:

    def test_unknown_baseline_is_422(self, client):
        """Unknown baseline name 'random_policy' → 422 UNKNOWN_BASELINE (§4.3)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["random_policy"],
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_empty_baselines_is_422(self, client):
        """baselines=[] (empty) → 422 (baselines is required non-empty, §4.1)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": [],
        })
        assert resp.status_code == 422

    def test_valid_single_baseline_no_battery(self, client):
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        assert resp.status_code == 200

    def test_valid_single_baseline_tou(self, client):
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["tou"],
        })
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# §4.1 / §7 — Site config validation
# ---------------------------------------------------------------------------

class TestSiteConfigValidation:

    def test_unknown_site_config_id_is_422(self, client):
        """site_config_id='site_nonexistent' → 422 UNKNOWN_SITE (contract §7)."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_nonexistent",
            "baselines": ["no_battery"],
        })
        assert resp.status_code == 422
        assert resp.json()["code"] == "UNKNOWN_SITE"

    def test_missing_site_config_id_is_422(self, client):
        """site_config_id is required (§4.1) — omitting it → 422."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "baselines": ["no_battery"],
        })
        assert resp.status_code == 422

    def test_missing_algorithm_type_is_422(self, client):
        """algorithm_type is required — omitting it → 422."""
        resp = client.post("/api/training/config", json={
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        assert resp.status_code == 422

    def test_invalid_algorithm_type_is_422(self, client):
        """algorithm_type='ddpg' is not in {'sac','baseline_only'} → 422."""
        resp = client.post("/api/training/config", json={
            "algorithm_type": "ddpg",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# §5.4 — Persistence: config_id round-trip (config stored in-process)
# ---------------------------------------------------------------------------

class TestPersistence:
    """config_id persists in-process so /training/start can look it up."""

    def test_config_id_is_retrievable_after_submission(self, client):
        """After POST /api/training/config, the returned config_id should be
        retrievable from the server's in-memory store.

        We test this indirectly: calling GET /api/training/configs/{config_id}
        returns the stored config (or we verify via /training/start lookup).
        For now, assert config_id is a non-empty string (store is opaque in v1).
        """
        resp = client.post("/api/training/config", json={
            "algorithm_type": "sac",
            "site_config_id": "site_gansu",
            "baselines": ["no_battery"],
        })
        assert resp.status_code == 200
        config_id = resp.json()["config_id"]
        assert isinstance(config_id, str) and len(config_id) > 0
