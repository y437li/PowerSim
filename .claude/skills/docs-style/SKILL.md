---
name: docs-style
description: Documentation standard for all Energy GO docs (README, user_guide/, developer_guide/, architecture overviews, API references). Use whenever writing or editing any Markdown documentation so every doc is accurate to merged code, correctly placed and named, correctly routed for review, and grounded in the canonical spec.
---

# Energy GO Documentation Standard

Every doc in this repo follows these rules, no matter who writes it. Docs are a contract with the reader: if a doc says a thing exists, the reader will try to use it. The cost of an inaccurate doc is higher than the cost of an omitted one.

## 1. Accuracy — document only what is MERGED on `main`

This is the non-negotiable rule.

- **Document only what is merged on `main`.** Never describe aspirational, in-review, or planned features as if they exist. Check the three sources of record first (`git log --oneline -15`, `gh pr list --state open`, `LINEAGE.md`) and base every claim on the actual tree at `origin/main`.
- **Beware the working checkout.** The shared checkout may sit on a detached HEAD or a feature branch. Always verify against `origin/main` (e.g. `git fetch` then read from a worktree branched off `origin/main`), not whatever happens to be checked out.
- **Cite provenance.** Back substantive claims with the **PR number** (`PR #40`) and/or the **LINEAGE decision ID** (`D27`) that put them on main. A status table mapping each component to its merge state + PR/decision is the clearest way to do this.
- **Flag in-review work honestly.** If something is useful to mention but not yet merged, label it explicitly (🚧 in-review / "not yet on main", with the open PR number) and state the user-visible consequence (e.g. "end-to-end training is not yet runnable from main"). Distinguish an empty package stub from a real implementation — "implementations not on main" beats "not on main" when a doc-stub package exists.
- When code and the doc disagree, the **code on main wins** for "what exists"; the **spec wins** for "what is correct" (see §4). When unsure, escalate — never guess.

## 2. Where docs live, and naming

Three doc homes — keep them separate:

- **`docs/spec/`** — the canonical specification ONLY (`section_NN_<name>.md`). Do not put guides or how-tos here.
- **`user_guide/`** (top-level) — product-facing: install/launch, dashboard, 3D view, inference sessions, training panel, troubleshooting.
- **`developer_guide/`** (top-level) — contributor-facing: architecture, the contract-first workflow + verdict markers, worktree discipline, test layout / CI lanes, extension recipes, governance pointers.

Rules:

- Each of `user_guide/` and `developer_guide/` has a tree index — `index.md` (preferred) or `readme.md`.
- Files **inside** the guide trees are `snake_case.md` (e.g. `install_and_launch.md`).
- Root-level project docs are `SCREAMING_CASE.md` — `README.md`, `CLAUDE.md`, `LINEAGE.md`, `REBUILD_SPEC.md`, `STACK.md`.
- **Never encode versions or dates in filenames** (`_v2`, `_final`, `_2026`). Git history is the version record.
- `README.md`'s pointer map links **both** guide trees. When you add a tree (or its first page), update the pointer map in the **same PR** — and only link a tree that exists in that PR (don't link a not-yet-created tree).

## 3. Review routing

Docs go through the same PR + verdict-marker gate as code (CLAUDE.md). Route by what the doc describes:

- **Area-behavior docs** (how env / training / harness / serving / frontend / 3D actually behaves) → that area's reviewer: backend-reviewer for `env`/`training`/`harness`/`serving`, frontend-reviewer for `frontend`/`frontend3d`. Cross-cutting trees (the guides, README) → **rl-architect**, with area reviewers cc'd to fact-check the area-specific pages.
- Verdict markers per CLAUDE.md (top-level PR comment, `VERDICT: …` first line, `reviewer: <name>` second). Merge needs the required reviewer's latest = APPROVE **and** QA's latest = QA_PASS. **You do not merge — the team lead merges.** Adding a commit after approval supersedes the markers (the gate checker verifies markers cover the head commit), so re-request review when you push new content. Self-check with the `pr-merge-gate` skill before pinging the team lead.

## 4. Source of truth

- The **spec sections under `docs/spec/section_NN_<name>.md` are canonical**; `REBUILD_SPEC.md` (root) is the index/TOC and lists each section's Owner. Cite sections as `§N.M` — those citations are stable.
- For any **stack claim** (language, framework, library, test runner, data/asset format), `STACK.md` is the binding registry — cite it, don't invent.
- **Units are always explicit** (MW vs kW, MWh, ¥/MWh) in every documented value, per the engineering rules — a number without a unit is a bug.
- Project rules (workflow, naming, file locations) live in `CLAUDE.md`; binding decisions / locked contracts / blockers in `LINEAGE.md`. Point readers there rather than restating and risking drift.

## 5. Verification habit — run every command before documenting it

This is a **hard rule**, not advice.

- **Execute every command you document before writing it down** — install/launch script invocations, test commands, REST calls, `--help`, error paths. Document *observed* behavior, not assumed behavior. Quote real output and real remediation hints (copy them from the script/response, don't paraphrase from memory).
- For UI docs, **drive the live app** (the `run` / `verify` skills) and screenshot the real running stack. Capture screenshots into the guide tree (e.g. `user_guide/img/<snake>.png`). Use whatever ports are already up, or your own high ports — never collide with another project's ports.
- Verify that referenced files, paths, routes, env vars, and flags actually exist (`rg`, `git ls-files`, read the script). Confirm every internal doc link resolves.
- Re-check headline numbers against their source (site parameters against `src/reference/gansu_params.py`, formulas against `docs/spec/`).
- Report honestly: if a documented default points at something not yet in the repo (e.g. a config file a script defaults to), say so plainly rather than implying it works.
