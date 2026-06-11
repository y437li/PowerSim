import { Component } from "react";
import type { ReactNode, ErrorInfo } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  /** When this value changes while in error state, the boundary self-heals.
   *  Contract: contracts/frontend/error_boundary_reset_key.md §2 */
  resetKey?: string | number;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  /** Tracks last-seen resetKey so we can detect changes across renders.
   *  Contract: contracts/frontend/error_boundary_reset_key.md §2.2 */
  prevResetKey: string | number | undefined;
}

/** Class-based error boundary. Catches render errors in children and shows a fallback.
 *
 *  Accepts an optional `resetKey` prop. When the key changes while the boundary is in
 *  error state the boundary self-heals (resets to healthy, remounts children). When the
 *  key changes while healthy, only prevResetKey is advanced — no UI change.
 *
 *  Contract: contracts/frontend/error_boundary_reset_key.md §2.3 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null, prevResetKey: undefined };
  }

  static getDerivedStateFromProps(
    props: ErrorBoundaryProps,
    state: ErrorBoundaryState,
  ): Partial<ErrorBoundaryState> | null {
    if (state.hasError && props.resetKey !== state.prevResetKey) {
      // Key changed while in error — self-heal.
      return { hasError: false, error: null, prevResetKey: props.resetKey };
    }
    if (props.resetKey !== state.prevResetKey) {
      // Key changed while healthy — advance tracking so a future crash on this key
      // does NOT trigger a spurious reset.
      return { prevResetKey: props.resetKey };
    }
    return null;
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Log for diagnostics — do not suppress in production
    console.error("[ErrorBoundary] Caught render error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback !== undefined) {
        return this.props.fallback;
      }
      return (
        <div className="error-boundary-fallback" role="alert">
          <p>Something went wrong.</p>
          {this.state.error && (
            <pre className="error-boundary-fallback__detail">
              {this.state.error.message}
            </pre>
          )}
        </div>
      );
    }
    return this.props.children;
  }
}
