import { formatSimTime } from "../utils/units";

interface TimeAxisProps {
  simTimeUtc: string | null;
  step: number | null;
  dtHours: number;
  className?: string;
}

/** Displays the current simulation time (UTC) and step counter. */
export function TimeAxis({ simTimeUtc, step, dtHours: _dtHours, className = "" }: TimeAxisProps) {
  const timeLabel = simTimeUtc !== null ? formatSimTime(simTimeUtc) : "—";
  const stepLabel = step !== null ? String(step) : "—";

  return (
    <div className={`time-axis ${className}`.trim()}>
      <span className="time-axis__time">{timeLabel}</span>
      <span className="time-axis__sep"> · </span>
      <span className="time-axis__step">Step {stepLabel}</span>
    </div>
  );
}
