import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { NodeHistoryPoint } from "../../api/types";

interface Props {
  points: NodeHistoryPoint[];
}

export default function HistoryChart({ points }: Props) {
  if (points.length === 0) {
    return <p className="history-empty">No history yet for this window — check back after a few probe cycles.</p>;
  }

  const data = points.map((p) => ({
    t: new Date(p.run_started_at).toLocaleTimeString(),
    loss: p.loss_pct,
    avg: p.avg_ms,
  }));

  return (
    <div className="history-charts">
      <div>
        <h4>Loss %</h4>
        <ResponsiveContainer width="100%" height={120}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="t" tick={{ fontSize: 10 }} minTickGap={30} />
            <YAxis tick={{ fontSize: 10 }} width={32} domain={[0, 100]} />
            <Tooltip />
            <Line type="monotone" dataKey="loss" stroke="#e03131" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div>
        <h4>Avg latency (ms)</h4>
        <ResponsiveContainer width="100%" height={120}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="t" tick={{ fontSize: 10 }} minTickGap={30} />
            <YAxis tick={{ fontSize: 10 }} width={32} />
            <Tooltip />
            <Line type="monotone" dataKey="avg" stroke="#1c7ed6" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
