import type { ChartSpec } from "./api";

const COLORS = ["#0e6b67", "#8a5a12", "#1e4d86", "#8e2f2f", "#3d6b3a", "#6b4c7a"];

export function ChartView({ chart }: { chart: ChartSpec }) {
  const points = chart.series[0]?.points ?? [];
  return (
    <figure className="chart-block" data-chart-type={chart.chart_type}>
      <figcaption>{chart.title}</figcaption>
      <svg viewBox="0 0 360 200" role="img" aria-label={chart.title}>
        <ChartShape chart={chart} />
      </svg>
      <div className="chart-scroll">
        <table className="chart-table">
          <thead>
            <tr>
              <th>{chart.category_field}</th>
              {chart.series.map((series) => (
                <th key={series.name}>{series.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {points.map((point, index) => (
              <tr key={`${point.category}-${index}`}>
                <td>{latin(point.category) ? <bdi>{point.category}</bdi> : point.category}</td>
                {chart.series.map((series) => (
                  <td key={series.name}>
                    <bdi>{series.points[index]?.value}</bdi>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}

function ChartShape({ chart }: { chart: ChartSpec }) {
  const points = chart.series[0]?.points ?? [];
  const values = chart.series.flatMap((series) => series.points.map((point) => numberOf(point.value)));
  const max = Math.max(0, ...values, 0);
  const min = Math.min(0, ...values, 0);
  const span = max - min || 1;
  if (chart.chart_type === "pie") return <Pie points={points} />;
  if (chart.chart_type === "bar") return <Bars chart={chart} horizontal span={span} min={min} />;
  if (chart.chart_type === "scatter") return <Scatter chart={chart} />;
  return <Bars chart={chart} horizontal={false} span={span} min={min} />;
}

function Bars({
  chart,
  horizontal,
  span,
  min,
}: {
  chart: ChartSpec;
  horizontal: boolean;
  span: number;
  min: number;
}) {
  const points = chart.series[0].points;
  const count = Math.max(points.length, 1);
  const plot = { left: 28, right: 348, top: 12, bottom: 176 };
  const zero = plot.bottom - ((0 - min) / span) * (plot.bottom - plot.top);
  return (
    <g>
      <line x1={plot.left} y1={plot.top} x2={plot.left} y2={plot.bottom} stroke="#e3ddd2" />
      <line x1={plot.left} y1={zero} x2={plot.right} y2={zero} stroke="#e3ddd2" />
      {points.map((point, index) => {
        const slot = (plot.right - plot.left) / count;
        const band = horizontal ? (plot.bottom - plot.top) / count : slot;
        return chart.series.map((series, seriesIndex) => {
          const value = numberOf(series.points[index]?.value);
          const color = COLORS[seriesIndex % COLORS.length];
          const shapeKey = `${point.category}-${series.name}-${index}`;
          if (horizontal) {
            const y = plot.top + index * band + band * 0.2;
            const width = (Math.abs(value) / span) * (plot.right - plot.left);
            return <rect key={shapeKey} x={plot.right - width} y={y} width={width} height={band * 0.55} fill={color} />;
          }
          const height = (Math.abs(value) / span) * (plot.bottom - plot.top);
          const x = plot.left + index * slot + slot * 0.18 + seriesIndex * 6;
          const y = value >= 0 ? zero - height : zero;
          const line = chart.chart_type === "line" || (chart.chart_type === "combo" && seriesIndex > 0);
          if (line || chart.chart_type === "area") return null;
          return <rect key={shapeKey} x={x} y={y} width={slot * 0.55} height={height} fill={color} />;
        });
      })}
      {chart.chart_type === "line" || chart.chart_type === "area" || chart.chart_type === "combo" ? (
        <Trend chart={chart} plot={plot} span={span} min={min} area={chart.chart_type === "area"} />
      ) : null}
    </g>
  );
}

function Trend({
  chart,
  plot,
  span,
  min,
  area,
}: {
  chart: ChartSpec;
  plot: { left: number; right: number; top: number; bottom: number };
  span: number;
  min: number;
  area: boolean;
}) {
  const series = area || chart.chart_type === "line" ? chart.series[0] : chart.series[chart.series.length - 1];
  const count = Math.max(series.points.length, 1);
  const coords = series.points.map((point, index) => {
    const slot = (plot.right - plot.left) / count;
    const x = plot.left + index * slot + slot / 2;
    const y = plot.bottom - ((numberOf(point.value) - min) / span) * (plot.bottom - plot.top);
    return `${x},${y}`;
  });
  const line = coords.join(" ");
  if (area && coords.length) {
    const first = coords[0].split(",")[0];
    const last = coords[coords.length - 1].split(",")[0];
    return <polygon points={`${first},${plot.bottom} ${line} ${last},${plot.bottom}`} fill="#0e6b67" opacity="0.35" />;
  }
  return <polyline points={line} fill="none" stroke="#8a5a12" strokeWidth="2" />;
}

function Scatter({ chart }: { chart: ChartSpec }) {
  const points = chart.series[0].points;
  const xs = points.map((point) => numberOf(point.category));
  const ys = points.map((point) => numberOf(point.value));
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(0, ...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  return (
    <g>
      {points.map((point, index) => {
        const x = 28 + ((numberOf(point.category) - minX) / spanX) * 310;
        const y = 176 - ((numberOf(point.value) - minY) / spanY) * 160;
        return <circle key={point.category + index} cx={x} cy={y} r="4" fill="#0e6b67" />;
      })}
    </g>
  );
}

function Pie({ points }: { points: { category: string; value: string }[] }) {
  const values = points.map((point) => Math.max(numberOf(point.value), 0));
  const total = values.reduce((sum, value) => sum + value, 0);
  if (total <= 0) return null;
  if (values.filter((value) => value > 0).length === 1) {
    return <circle cx="180" cy="96" r="70" fill={COLORS[0]} />;
  }
  let angle = -Math.PI / 2;
  return (
    <g>
      {values.map((value, index) => {
        const sweep = (value / total) * Math.PI * 2;
        const start = angle;
        angle += sweep;
        if (sweep <= 0) return null;
        return <path key={points[index].category + index} d={arc(180, 96, 70, start, angle)} fill={COLORS[index % COLORS.length]} />;
      })}
    </g>
  );
}

function arc(cx: number, cy: number, radius: number, start: number, end: number): string {
  const x1 = cx + radius * Math.cos(start);
  const y1 = cy + radius * Math.sin(start);
  const x2 = cx + radius * Math.cos(end);
  const y2 = cy + radius * Math.sin(end);
  const large = end - start > Math.PI ? 1 : 0;
  return `M ${cx} ${cy} L ${x1} ${y1} A ${radius} ${radius} 0 ${large} 1 ${x2} ${y2} Z`;
}

function numberOf(value: string | undefined): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function latin(value: string): boolean {
  return /^[0-9.+-]+$/.test(value);
}
