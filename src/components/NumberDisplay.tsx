/** Displays a numeric value with unit; shows nullText for null/NaN/Infinity. */
interface NumberDisplayProps {
  value: number | null;
  unit: string;
  decimals?: number;
  nullText?: string;
  className?: string;
}

export function NumberDisplay({
  value,
  unit,
  decimals = 1,
  nullText = "—",
  className = "",
}: NumberDisplayProps) {
  // Guard: treat null, NaN, and any non-finite number as missing data.
  // NOTE: negative finite values (e.g. cost_total_real_yuan = -52700) MUST render.
  const isInvalid = value === null || !Number.isFinite(value);

  return (
    <span className={`number-display ${className}`.trim()}>
      {isInvalid ? (
        <span className="number-display__null">{nullText}</span>
      ) : (
        <>
          <span className="number-display__value">{(value as number).toFixed(decimals)}</span>
          <span className="number-display__unit"> {unit}</span>
        </>
      )}
    </span>
  );
}
