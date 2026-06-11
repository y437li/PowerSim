# Contract: frontend/error_boundary_reset_key

**Status:** DRAFT  
**Area:** frontend  
**Task:** #30  
**Branch:** feat/frontend-error-boundary-reset-key  
**Origin:** Follow-up from PR #53 stage-1 review (frontend-reviewer A4 finding):
`ErrorBoundary` is sticky — once `hasError: true`, there is no reset path.
PR #53 removes the primary crash trigger (malformed telemetry frames are now
validated+dropped at the wsClient gate before reaching components). This contract
adds a `resetKey` prop so that any _residual_ non-telemetry render crash
self-heals when fresh session state arrives, rather than requiring a manual page reload.

---

## §1 Motivation

The app-level `ErrorBoundary` wraps the entire route tree in `App.tsx`. A single
render crash in any route component trips it — the fallback ("Something went
wrong") replaces the whole UI permanently until the user reloads. With live
telemetry arriving every second, a brief DOM error caused by a stale state slice
(e.g. shape mismatch at the start of a new training run) should self-heal once
the new run's data arrives.

---

## §2 ErrorBoundary prop addition

`ErrorBoundary` gains one new optional prop:

```typescript
interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  /** When this value changes, any active error state is cleared and children
   *  re-render. Does not affect the boundary when it is not in error state. */
  resetKey?: string | number;
}
```

### §2.1 Reset semantics

When `resetKey` changes **while the boundary is in error state**, the boundary
MUST reset: `hasError → false`, `error → null`. Children then re-render. If the
children throw again (the root cause is not fixed), the boundary catches it again
and returns to `hasError: true` — it does not suppress future errors.

When `resetKey` changes **while the boundary is NOT in error state**, no
visible change occurs. The new key is recorded internally for the next comparison.

The reset mechanism MUST use `getDerivedStateFromProps` (not `componentDidUpdate`)
so the reset happens synchronously before the children re-render, avoiding a
flash of the stale error UI.

### §2.2 prevResetKey tracking

State gains a `prevResetKey` field (same type as `resetKey`, initial value
`undefined`). It is updated to match the current `resetKey` on every prop change,
whether or not a reset occurs.

```typescript
interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  prevResetKey: string | number | undefined;
}
```

### §2.3 getDerivedStateFromProps logic

```
if (hasError && resetKey !== prevResetKey) → { hasError: false, error: null, prevResetKey: resetKey }
elif (!hasError && resetKey !== prevResetKey) → { prevResetKey: resetKey }
else → null  (no state update)
```

---

## §3 App.tsx wiring

`App.tsx` MUST read `runId` from `useTelemetryStore` and pass it as `resetKey`
to the top-level `ErrorBoundary`:

```tsx
const runId = useTelemetryStore((s) => s.runId);
// ...
<ErrorBoundary resetKey={runId ?? ""}>
  <Routes>...</Routes>
</ErrorBoundary>
```

Rationale: `runId` advances when a new training session starts, clearing stale
state from the prior run that may have caused a render crash. The `?? ""` coalesce
means the initial state (no run yet, `runId = null`) maps to the empty string —
consistent and avoids passing `null` as a key.

---

## §4 Fallback UI unchanged

The existing default fallback (`<div role="alert">…</div>`) and the optional
`fallback` prop render path are unchanged. No new fallback UI is required.

---

## §5 Acceptance criteria (EB.RK series)

| ID | Test | Must verify |
|----|------|-------------|
| EB.RK.1 | resetKey absent — existing behaviour unchanged | Crash → error UI shown; no resetKey → stays in error state |
| EB.RK.2 | resetKey change resets error | Crash with key="a" → change key to "b" → children re-render |
| EB.RK.3 | resetKey same value — no reset | Crash with key="a" → rerender with same key="a" → error UI still shown |
| EB.RK.4 | No reset when not in error state | Start with key="a", no crash, change to key="b" → children render normally, no flash |
| EB.RK.5 | Re-crash after reset | Crash, reset key, child still throws → boundary catches again |
| EB.RK.6 | App.tsx wiring | `<ErrorBoundary resetKey={runId ?? ""}>` present; runId change triggers reset |
| EB.RK.7 | prevResetKey tracks key | After reset, key stored = new key (prevents double-reset on next render) |
