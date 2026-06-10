import { useTrainingStore } from "../stores/trainingStore";
import { Card } from "../components/Card";

/**
 * Route: /training — training metrics dashboard.
 * The dashboard-engineer plugs training charts into this mount point.
 */
export default function TrainingPanel() {
  const latest = useTrainingStore((s) => s.latest);

  return (
    <div data-testid="training-panel" className="route-training-panel">
      <Card title="Training Metrics">
        {latest ? (
          <div className="training-panel__latest">
            <span>Step: {latest.global_step.toLocaleString()}</span>
          </div>
        ) : (
          <p className="training-panel__empty">No training data yet.</p>
        )}
      </Card>
    </div>
  );
}
