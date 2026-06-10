import { SceneMountPoint } from "../components/SceneMountPoint";

/**
 * Route: / — live site view with 3D scene.
 * The 3d-assets-engineer mounts the Three.js/R3F scene onto the SceneMountPoint div.
 */
export default function SiteView() {
  return (
    <div data-testid="site-view" className="route-site-view">
      <SceneMountPoint />
    </div>
  );
}
