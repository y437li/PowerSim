import { useState } from "react";
import { SceneMountPoint } from "../components/SceneMountPoint";
import { SiteScene } from "../scene/SiteScene";
import { SessionControlStrip } from "../components/SessionControlStrip";
import { LiveDashboard } from "./LiveDashboard";
import { GANSU_SITE_CONFIG, ASSET_REGISTRY } from "../config/gansuSiteConfig";

/**
 * Route: / — live site view with 3D scene + live dashboard.
 * Contract: contracts/frontend/app_integration.md §4
 *
 * SceneMountPoint.onReady fires once on mount with the container div.
 * That div is passed to SiteScene as containerEl — SiteScene.useEffect([containerEl])
 * re-runs on the null→div transition and attaches the R3F canvas.
 * LiveDashboard renders alongside the scene; both read from telemetryStore.
 */
export default function SiteView() {
  const [containerEl, setContainerEl] = useState<HTMLDivElement | null>(null);

  return (
    <div data-testid="site-view" className="route-site-view">
      <SceneMountPoint onReady={setContainerEl} />
      <SiteScene
        config={GANSU_SITE_CONFIG}
        registry={ASSET_REGISTRY}
        containerEl={containerEl}
      />
      <SessionControlStrip />
      <LiveDashboard />
    </div>
  );
}
