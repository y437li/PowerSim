import { useRef, useEffect } from "react";

interface SceneMountPointProps {
  /** Called with the container element once it is mounted in the DOM. */
  onReady?: (el: HTMLDivElement) => void;
  className?: string;
}

/**
 * A plain div that the 3d-assets-engineer mounts Three.js/R3F into.
 * This component intentionally renders NO canvas or 3D children of its own —
 * the 3D scene is injected by the 3d-assets-engineer via the onReady callback.
 */
export function SceneMountPoint({ onReady, className = "" }: SceneMountPointProps) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (ref.current && onReady) {
      onReady(ref.current);
    }
    // onReady is called once on mount only — no dependency on onReady to avoid
    // calling it on every parent re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      ref={ref}
      className={`scene-mount-point ${className}`.trim()}
      data-testid="scene-mount-point"
    />
  );
}
