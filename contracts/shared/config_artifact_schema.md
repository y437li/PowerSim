# Contract: `config_artifact_schema` — the coherent versioned config-artifact

**Area:** shared · **Owner/Lead:** rl-architect · **Reviewers:** backend-reviewer + frontend-reviewer (advisory comment; rl-architect locks — shared-contract routing)
**Test file:** `tests/shared/test_shared_config_artifact_schema.py`
**Realizes:** the USER directive *"数据schema设计要合理"* + **D43** (config = first-class savable/forkable artifact), **D44** (actions mutate artifacts; author-tagged thread), **D42** (DESIGN-vs-UNCERTAINTY + common-vs-per-config finance scoping), **D41** (sizing/CRN/per-config re-sim), **D32** (public-repo secret-safety), **D37** (server-side assembly — the artifact stores the AUTHORED form, the resolver derives `EnvParams`).
**Underpins:** #19 (workbench), #18 (sizing sweep), #20 (agentic), serving persistence.

---

## 1. Purpose and the ONE binding design principle

The config has become a rich first-class artifact (D43) accumulating six concern-groups. This contract defines **ONE coherent, versioned schema** for it. The load-bearing principle:

> **COMPOSE, don't bolt-on. The artifact stores only the user-AUTHORED input + metadata; everything physical/result is REFERENCED by an existing join key or DERIVED by an existing single-source component — never duplicated.**

Concretely:
- **Physical/design** = the authored wizard form (D37); `resolve_site` DERIVES `EnvParams` — the artifact stores the form, **never** the resolved `EnvParams` (single-source, D37/D18).
- **Device selections** = `device_model_schema` IDs (the LOCKED v2.2.0 join key) — referenced, not copied.
- **Tariff** = a `tariff_model_schema` region ID (or D37 inline fallback) — referenced.
- **Finance** = a (partial) **`FinanceConfig`** (the §13.12 type) — embedded as overrides, not redefined.
- **Results** = referenced by the telemetry/§8.1/D41 join keys (`run_id`, `checkpoint_id`, `scenario_id`, `seed`) — never embedded.

This keeps the artifact a **thin authored layer** over the existing resolver / `finance()` / result store, so it can't drift from them.

---

## 2. Top-level schema

```
ConfigArtifact:
  schema_version:   str        # semver; this contract's version (§7)
  id:               str        # stable artifact id, UUIDv4; immutable across edits
  version:          int        # monotonic per-artifact revision (starts 1; +1 each mutation) — the undo/history axis (D44)
  name:             str        # human label
  created_at_utc:   str        # ISO-8601
  updated_at_utc:   str        # ISO-8601

  design:           DesignBlock          # §3  — concern (1): physical/design (authored form)
  finance_overrides: FinanceOverrides    # §4  — concern (2): per-config finance overrides ONLY
  comments:         list[CommentEntry]   # §5  — concern (3): author-tagged thread
  provenance:       Provenance           # §6  — concern (4): forked-from + param delta
  agent_config:     AgentConfig | null   # §6  — concern (5): model-interface (NO keys, D32)
  results:          list[ResultLink]     # §6  — concern (6): result-linkage + regime/confidence tags
  tags:             list[str]            # free labels
```

**Identity vs revision (binding):** `id` is stable for the lifetime of the artifact (a fork gets a NEW `id`); `version` increments on every mutation of the SAME `id` (the D44 shared-undo / history axis). `(id, version)` is the precise reference used by `provenance.forked_from` and by the comparison/session layer.

**`version` is the optimistic-concurrency token (binding — answers the D44 shared-mutation concern, backend-reviewer):** under D44 the human AND the agent mutate the same artifact, so every mutating action declares the `expected_base_version` it read; the action layer / serving persistence **accepts only if `expected_base_version == current.version`** (then writes `current.version + 1`), else **REJECTS as a conflict** — the writer must re-read the current version and rebase its change. This is standard optimistic concurrency control; it makes concurrent human/agent edits safe and is what the shared undo stack (D44) unwinds. The OCC check is enforced by the action layer (D44 / #19) + serving; this schema defines `version` as its token.

---

## 3. `DesignBlock` — the authored form (concern 1; DESIGN params, D42)

```
DesignBlock:
  fleet:            list[{ model_id: str, count: int }]   # model_id ∈ device_model_schema (v2.2.0) — ACTIVE types only (D38)
  battery:          { energy_mwh: float, power_mw: float } # the sizing axis (D41/D42 DESIGN); C-rate = power/energy bounded (D41)
  export_cap_mw:    float
  import_cap_mw:    float
  tariff_region:    str | null              # tariff_model_schema region id; null → inline (D37 fallback) in `tariff_inline`
  tariff_inline:    object | null           # D37 inline tariff fallback when tariff_region is null
  weather:          { mode: "synthetic" | "real", ... }    # §12 weather toggle (D39/§12) — drives M/sample_kind
  dispatch_policy_id: str                   # §11 baseline ("greedy"|"tou"|"mpc"|"dp_oracle") OR a checkpoint_id (a trained policy)
```

**Composition rules (binding):**
- `fleet[*].model_id` MUST resolve in `device_model_schema` and be an **ACTIVE** (resolver-live, non-INERT, non-pending) type per **D38** (`is_surfaceable`). An INERT/gated or provenance-pending device-model ID is **rejected**.
- `battery.{energy_mwh, power_mw}` define the DESIGN sizing point; the implied C-rate (`power_mw/energy_mwh`) MUST be within the realistic bound (D41 §scope; exact bound set by the §18 build, validated here).
- The artifact stores the FORM; **`resolve_site(design, device_models)` DERIVES `EnvParams`** at run time (D37/D18). The artifact MUST NOT carry a resolved `EnvParams` field (anti-drift; a test asserts its absence).
- `dispatch_policy_id` MUST be a known §11 baseline id OR a valid `checkpoint_id` (checkpoint_format join key).

---

## 4. `FinanceOverrides` — per-config overrides only (concern 2; D42/D43 scoping)

```
FinanceOverrides:        # a PARTIAL FinanceConfig — only the fields this config overrides
  <subset of FinanceConfig fields>   # typically financing-structure: { gearing?, cost_of_debt?, debt_toggle?, hurdle? }
```

**Common-vs-per-config scoping (binding, D42/D43) — SCOPE-RESTRICTED to preserve the D42 apples-to-apples guarantee (backend-reviewer):**
- **`finance_overrides` MAY carry ONLY financing-structure fields — the FROZEN allow-set `{ gearing, cost_of_debt, debt_toggle, hurdle }`.** Any other key is **REJECTED** at validation with: *"market-rate is common-scenario, not per-config; set it on `ComparisonSession.common_finance`."*
- **Market-rate assumptions are COMMON-ONLY and per-config override is FORBIDDEN** — every CAPM input (`beta_unlevered`, `equity_risk_premium`, `country_risk_premium`, `cost_of_equity`, the CGB/LPR curve, `discount_rate`), `escalation`, and `price_path`/`price_path_id` live ONLY at the **comparison/session layer** (§4.1). **Rationale (load-bearing):** without this reject, two compared configs could silently use different discount rates → D42's apples-to-apples (common-scenario) guarantee breaks. The allow-set is a *positive* whitelist (default-deny), not a denylist — a new FinanceConfig field is common-only until explicitly added to the allow-set by a superseding DECISION.
- **Effective FinanceConfig = common ⊕ finance_overrides**, overrides winning on key collision — the SAME overlay-merge semantics as the D32 private overlay (reused precedent). **Null-vs-absent (binding):** an ABSENT override key inherits common; an EXPLICIT `null` override key is treated as **absent/inherit** (it does NOT null-out the common value) — matching the D32 overlay precedent, removing the partial-merge ambiguity.

### 4.1 Comparison/session layer (sibling object — defined here, owned by #19)
```
ComparisonSession:
  schema_version: str
  id: str
  common_finance: FinanceConfig          # the COMMON market-rate assumptions (D42); applied to ALL member configs
  common_scenario: { weather_mode, M, seed, price_path_id, ... }   # the fixed UNCERTAINTY reference (D42) — CRN seed shared (D41)
  members: list[str]                     # ConfigArtifact ids in this comparison
```
`finance()` for a member = `finance(ensemble, price_paths, econ, effective_FinanceConfig)` where `effective = common_finance ⊕ member.finance_overrides`. The CRN `seed` + scenario are common (D41/D42 — clean deltas).

---

## 5. `CommentEntry` — author-tagged thread (concern 3; D43/D44)

```
CommentEntry:
  author:     "human" | "agent"     # D44 attribution — binding, exactly these two values
  ts:         str                   # ISO-8601
  text:       str
  action_ref: str | null            # optional: the D44 action id that produced this entry (audit link)
```
Ordered (append-only within a `version`). Agent-authored actions (D44) land here with `author="agent"` + `action_ref`. A test asserts `author ∈ {human, agent}` and rejects any other value.

---

## 6. Provenance, agent-config, result-linkage (concerns 4, 5, 6)

### 6.1 `Provenance` (concern 4; D44 fork lineage)
```
Provenance:
  forked_from:  str | null         # "<id>@<version>" of the parent artifact; null for a root artifact
  param_delta:  dict[path -> { old, new }]   # exactly what changed vs the parent (dotted path into DesignBlock/FinanceOverrides)
  created_by:   "human" | "agent"  # who created this artifact (D44)
```
A forked artifact records `forked_from` + the minimal `param_delta`; a root artifact has `forked_from=null` and empty `param_delta`. Test: fork → delta matches the actual diff; root → null/empty.

### 6.2 `AgentConfig` (concern 5; D32 secret-safety — BINDING)
```
AgentConfig:                       # null unless agent-operated
  provider:  str                   # e.g. "anthropic"
  model:     str                   # model id
  endpoint:  str                   # URL (no embedded credentials)
  params:    object                # temperature, max_tokens, etc.
  # NO api_key / secret / token FIELD — EVER (D32 public-repo).
```
**D32 (binding):** the artifact carries provider/model/endpoint/params but **NEVER a credential**. The key is resolved at run time from the **private overlay / env var** (`ENERGY_GO_PRIVATE_CONFIG` or provider-specific env) keyed by `(provider, endpoint)`. **Reviewer-grade reject rule (matching is RECURSIVE + SUBSTRING/SUFFIX, not exact-name — backend-reviewer):** validation **REJECTS** the artifact if any object key (at ANY depth, including inside `agent_config.params` — the likely real leak path, e.g. `params: { api_key: "sk-…" }`) contains a credential token as a substring/suffix: `key` / `api_key` / `access_token` / `refresh_token` / `token` / `secret` / `client_secret` / `password` / `passwd` / `pwd` / `authorization` / `x-api-key` (so `access_token`, `client_secret`, `x-api-key` are caught — exact-match would miss them). Additionally, an `endpoint` carrying a credential **anywhere** — userinfo (`https://user:pass@…`), **query string** (`…?api_key=sk-…`), or **fragment** (`…#token=…`) — is rejected, not only `user:pass@`. A stop-the-line guard mirroring the D32 commit rule.

### 6.3 `ResultLink` (concern 6; result-linkage + regime/confidence)
```
ResultLink:
  run_id:           str            # telemetry/§8.1 join key
  checkpoint_id:    str | null     # checkpoint_format join key (null for §11 baselines)
  scenario_id:      str
  seed:             int            # CRN seed (D41) — for reproducibility/pairing
  weather_mode:     "synthetic" | "real"
  M:                int
  sample_kind:      "bootstrap" | "empirical"   # D39 regime selector
  finance_result_ref: str | null   # opaque ref into the result store (the FinanceResult); NOT embedded
  regime:           "R1" | "R2" | "R3"          # D39 percentile regime
  discharge_status: "invariant" | "conservative_floor" | "pending" | "n/a"   # D39/D42 sensitivity-discharge state
```
Results are **referenced, never embedded** (results are large + versioned separately). The join keys match telemetry/checkpoint/§13.12 verbatim (no new identifiers). `regime`/`discharge_status` carry the D39/D42 honesty + gate state with the result link.

---

## 7. Versioning & migration (binding)

- `schema_version` is **semver**. **Additive** optional fields = **minor** (old artifacts still valid; no migration). **Removal / rename / retype / required-field-addition / merge-semantics change** = **major** → a registered **migration function** `migrate(artifact, from_ver, to_ver)` + a superseding DECISION + re-LOCK.
- **Migration-aware loader (binding):** every artifact carries its `schema_version`; the loader migrates `old → current` on read (forward-only chain). A test round-trips an N-1 artifact through `migrate` → current and asserts semantic equality.
- **Composition-version pinning:** the artifact references `device_model_schema` / `tariff_model_schema` / `checkpoint_format` by **ID only** (not by their version); the resolver/result-store enforces THOSE versions. So a bump in a referenced schema does NOT force a config-artifact major bump (decoupled), unless a referenced **join-key format** itself changes.
- **Dangling reference = resolve-time error, NOT a version mismatch (binding, backend-reviewer):** because IDs are pinned (not versions), a referent that no longer exists in the CURRENT schema/store (`fleet[*].model_id`, a `dispatch_policy_id`-as-`checkpoint_id`, or `tariff_region`) surfaces as a **clear resolve-time error** ("referent `<id>` not found in `<schema/store>`") — distinct from a schema-version/migration error. The artifact stays schema-valid; only resolution fails. (Test #16 pins this boundary.)

---

## 8. Test cases (reviewer-gated BEFORE implementation; `# reviewer:` marks reviewer additions)

1. **Valid round-trip:** a fully-populated artifact serializes/deserializes byte-stable; all six concern-blocks present.
2. **Required fields:** missing `id`/`version`/`schema_version`/`design` → validation error with the field named.
3. **Compose — device IDs:** `fleet[*].model_id` not in `device_model_schema` → reject; an **INERT/pending** id (electrolyzer, `pcc-sst-stub`) → reject per D38 `is_surfaceable`.
4. **Compose — no resolved EnvParams:** an artifact carrying a resolved `EnvParams`/physics field → reject (anti-drift, D37/D18); physics is derived, not stored.
5. **Finance scoping:** `effective = common ⊕ overrides` — a per-config `gearing` override wins over `common_finance.gearing`; an absent override inherits common (hand-checked: common gearing 0.0, override 0.6 → effective 0.6; no override → 0.0).
6. **D32 secret-safety (reviewer-grade):** artifact with `api_key`/`secret`/`token`/`*_key`/`authorization` anywhere → reject; `endpoint` with inline `user:pass@` → reject; valid `agent_config` (provider/model/endpoint/params, no key) → accept.
7. **Comment thread:** `author` ∉ {human, agent} → reject; valid entries ordered + append-only; `action_ref` optional.
8. **Provenance:** fork → `forked_from="<id>@<v>"` + `param_delta` equals the actual diff (hand example: parent battery 300→child 400 → delta `{ "design.battery.energy_mwh": {old:300, new:400} }`); root → `forked_from=null`, empty delta. A fork gets a NEW `id`; an edit bumps `version` on the SAME `id`.
9. **Result-linkage:** join keys (`run_id`/`checkpoint_id`/`scenario_id`/`seed`) match telemetry/checkpoint formats; `regime ∈ {R1,R2,R3}`; `discharge_status` ∈ the four values; `finance_result_ref` is a ref, full result NOT embedded.
10. **Versioning/migration:** an artifact at `schema_version = N-1` loads + migrates to current with semantic equality; an unknown future major → load-reject.
11. **# reviewer: C-rate bound** — `battery.power_mw/energy_mwh` outside the realistic C-rate band → validation warning/error (bound per #18).
12. **# reviewer: comparison-session CRN** — all `members` of a `ComparisonSession` share `common_scenario.seed` (D41 CRN); a member overriding the seed → reject (CRN is common, not per-config).

---

13. **# reviewer: D32 reject-set completeness** — beyond the listed set, validation MUST also reject `password`/`passwd`/`pwd`; matching is **substring/suffix** (so `access_token`, `refresh_token`, `client_secret`, `x-api-key` are caught), not exact-name; a credential nested in `agent_config.params` (e.g. `params: { api_key: "sk-…" }`) is rejected (recursion into nested objects); and an `endpoint` carrying a credential in the **query string or fragment** (`https://host/v1?api_key=sk-…`, `…#token=…`) is rejected, not only `user:pass@` userinfo.
14. **# reviewer: finance_overrides scope-restriction (D42 apples-to-apples)** — `finance_overrides` may ONLY carry financing-structure fields (`gearing`/`cost_of_debt`/`debt_toggle`/`hurdle`). An override of a COMMON market-rate field (any CAPM input — `beta_unlevered`/`equity_risk_premium`/`cgb_curve`/discount, escalation, or `price_path`) → **reject** ("market-rate is common-scenario, not per-config; set it on `ComparisonSession.common_finance`"). Without this, two compared configs could silently use different discount rates → the D42 apples-to-apples guarantee breaks. (hand example: `finance_overrides={gearing:0.6}` → accept; `finance_overrides={equity_risk_premium:0.07}` → reject.)
15. **# reviewer: dispatch_policy_id validity** — a `dispatch_policy_id` that is neither a known §11 baseline id (`greedy`/`tou`/`mpc`/`dp_oracle`) nor a resolvable `checkpoint_id` → reject (the §3 rule currently has no test).
16. **# reviewer: dangling join-key reference** — an artifact whose `fleet[*].model_id`, `dispatch_policy_id`-as-checkpoint, or `tariff_region` no longer exists in the CURRENT referenced schema/store → a clear **resolve-time** error, distinct from a schema-version/migration error. Exercises the §7 ID-decoupling boundary: the artifact pins IDs not versions, so a removed referent surfaces at resolve time, not as a config-artifact version mismatch.
17. **# reviewer: finance merge null-vs-absent** — pin the overlay-merge null semantics: an ABSENT override key inherits common (test 5); an EXPLICIT `null` override key must have a defined behavior (recommend: treated as absent/inherit, matching the D32 overlay precedent — assert it does NOT null-out the common value). Removes the classic partial-merge ambiguity.

## 9. Out of scope (fidelity boundary)
- The artifact does NOT store resolved `EnvParams`, full `FinanceResult` payloads, or weather ensembles (all derived/referenced).
- Credentials (D32 — overlay/env only).
- The permission/"follow" model (D44 → #20 phase).
- The action-API command definitions themselves (D44 → #19 contract); this schema defines the ARTIFACTS those actions mutate, and the `action_ref` link.
