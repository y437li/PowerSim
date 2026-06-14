# `src/routes`

<!-- curated -->
## Purpose

Top-level page components that correspond 1-to-1 with React Router routes. Each route component is responsible for layout and composition only — it delegates data access to stores, animation to `scene/`, and rendering to `components/`.

`SiteView.tsx` (route `/`) is the primary live-operations view: it combines the 3D scene (via `SceneMountPoint`) with the live dashboard, as defined in `contracts/frontend/app_integration.md §4`. `LiveDashboard.tsx` composes the `components/live/` panels into the live-operations sidebar. `TrainingPanel.tsx` (route `/training`) composes the `components/training/` panels into the training metrics view. `EvalComparison.tsx` (route `/eval`) renders the policy comparison table.

No route component owns state logic (that belongs to `stores/`), performs animation (that belongs to `scene/`), or opens network connections (that belongs to `clients/`).
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `EvalComparison.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `EvalComparison` | `function` | Route: /eval — policy comparison table. |

### `LiveDashboard.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `LiveDashboard` | `function` | LiveDashboard — live operations panel at the / route (SiteView). |

### `SiteView.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `SiteView` | `function` | Route: / — live site view with 3D scene + live dashboard. |

### `TrainingPanel.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `TrainingPanel` | `function` | Route: /training — training metrics dashboard. |

<!-- generated:end -->
