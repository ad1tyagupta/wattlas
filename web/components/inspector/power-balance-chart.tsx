import type { RegionalEnergyForecast } from "@/lib/snapshot/types";

type Props = { forecasts: RegionalEnergyForecast[] };
const fmt = (value: number) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
const range = (value: { low: number; high: number } | null) => value ? `${fmt(value.low)}–${fmt(value.high)} GWh` : "Unavailable";

export function PowerBalanceChart({ forecasts }: Props) {
  const ordered = [...forecasts].sort((a, b) => a.year - b.year);
  const validRange = (value: { low: number; central: number; high: number } | null) => value === null || ([value.low, value.central, value.high].every(Number.isFinite) && value.low <= value.central && value.central <= value.high);
  const valid = ordered.length === 6
    && ordered.every((row, index) => row.year === 2026 + index)
    && new Set(ordered.map((row) => row.year)).size === 6
    && ordered.every((row) => [row.metrics.demandGwh, row.metrics.localGenerationGwh, row.metrics.localGenerationGapGwh, row.metrics.netBalanceGwh, row.metrics.dependableCapacityMw, row.metrics.peakDemandMw].every(validRange));
  if (!valid) return <p className="empty-evidence" role="status">Demand-versus-supply chart unavailable because the annual series is incomplete or invalid.</p>;
  const data = ordered;
  const max = Math.max(1, ...data.flatMap((row) => [row.metrics.demandGwh.high, row.metrics.localGenerationGwh?.high ?? 0]));
  const x = (index: number) => 28 + index * (244 / Math.max(1, data.length - 1));
  const y = (value: number) => 116 - value / max * 92;
  const points = (key: "demand" | "supply") => data.map((row, index) => {
    const value = key === "demand" ? row.metrics.demandGwh.central : row.metrics.localGenerationGwh?.central;
    return value == null ? null : `${x(index)},${y(value)}`;
  }).filter(Boolean).join(" ");
  return <section className="power-balance-chart" aria-labelledby="power-outlook-title">
    <div className="section-heading"><span id="power-outlook-title">2026–2031 demand versus supply</span><small>low/base/high estimates</small></div>
    <svg viewBox="0 0 300 140" role="img" aria-label="2026 to 2031 demand versus local generation range chart" preserveAspectRatio="xMidYMid meet">
      <title>2026 to 2031 demand versus local generation</title>
      {data.map((row, index) => <g key={row.year}>
        <line className="demand-range" x1={x(index) - 3} x2={x(index) - 3} y1={y(row.metrics.demandGwh.high)} y2={y(row.metrics.demandGwh.low)} />
        {row.metrics.localGenerationGwh && <line className="supply-range" x1={x(index) + 3} x2={x(index) + 3} y1={y(row.metrics.localGenerationGwh.high)} y2={y(row.metrics.localGenerationGwh.low)} />}
        <text x={x(index)} y="134" textAnchor="middle">{row.year}</text>
      </g>)}
      <polyline className="demand-line" points={points("demand")} />
      <polyline className="supply-line" points={points("supply")} />
    </svg>
    <div className="chart-legend"><span className="demand-key">Demand</span><span className="supply-key">Local generation</span></div>
    <div className="chart-table-wrap"><table aria-label="Demand versus local generation data"><thead><tr><th>Year</th><th>Demand</th><th>Local generation</th></tr></thead><tbody>{data.map((row) => <tr key={row.year}><th>{row.year}</th><td>{range(row.metrics.demandGwh)}</td><td>{range(row.metrics.localGenerationGwh)}</td></tr>)}</tbody></table></div>
  </section>;
}
