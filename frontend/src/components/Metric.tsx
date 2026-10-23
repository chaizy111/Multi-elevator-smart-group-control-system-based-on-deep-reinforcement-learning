export function numeric(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
export function format(value: unknown, digits = 1): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("zh-CN", { maximumFractionDigits: digits })
    : "暂无样本";
}
export function Metric({
  label,
  value,
  unit,
  note,
}: {
  label: string;
  value: unknown;
  unit?: string;
  note?: string;
}) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <strong>
        {format(value)}
        <small>{typeof value === "number" ? unit : ""}</small>
      </strong>
      {note && <span>{note}</span>}
    </div>
  );
}
