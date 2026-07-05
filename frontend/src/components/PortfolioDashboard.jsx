import { useEffect, useRef, useState } from "react";
import { getPortfolioValuation } from "../api.js";

const PERIODS = [
  ["1mo", "1M"],
  ["3mo", "3M"],
  ["6mo", "6M"],
  ["1y", "1Y"],
];

const DONUT_COLORS = [
  "#7cb2ff", "#1fe0a0", "#ffc24b", "#ff5c7a",
  "#a78bfa", "#38bdf8", "#f97316", "#e879f9",
];

const money = (n) =>
  n == null
    ? "—"
    : n.toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: n >= 1000 ? 0 : 2,
      });

const pct = (n) => (n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(2)}%`);

/* Animated portfolio-value line chart, drawn like landing.html's hero chart:
   gradient area fill, glowing stroke, subtle horizontal gridlines. */
function ValueChart({ dates, values }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || values.length < 2) return;

    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    let frame;

    function draw(progress) {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const pad = { top: 14, right: 10, bottom: 22, left: 10 };
      const min = Math.min(...values);
      const max = Math.max(...values);
      const span = max - min || 1;
      const x = (i) =>
        pad.left + (i / (values.length - 1)) * (w - pad.left - pad.right);
      const y = (v) =>
        pad.top + (1 - (v - min) / span) * (h - pad.top - pad.bottom);

      // Gridlines
      ctx.strokeStyle = "rgba(255,255,255,0.05)";
      ctx.lineWidth = 1;
      for (let g = 0; g <= 3; g++) {
        const gy = pad.top + (g / 3) * (h - pad.top - pad.bottom);
        ctx.beginPath();
        ctx.moveTo(pad.left, gy);
        ctx.lineTo(w - pad.right, gy);
        ctx.stroke();
      }

      const count = Math.max(2, Math.floor(values.length * progress));
      const up = values[count - 1] >= values[0];
      const color = up ? "#1fe0a0" : "#ff5c7a";
      const glow = up ? "rgba(31,224,160,0.5)" : "rgba(255,92,122,0.5)";

      // Area fill
      const grad = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
      grad.addColorStop(0, up ? "rgba(31,224,160,0.22)" : "rgba(255,92,122,0.22)");
      grad.addColorStop(1, "rgba(0,0,0,0)");
      ctx.beginPath();
      ctx.moveTo(x(0), y(values[0]));
      for (let i = 1; i < count; i++) ctx.lineTo(x(i), y(values[i]));
      ctx.lineTo(x(count - 1), h - pad.bottom);
      ctx.lineTo(x(0), h - pad.bottom);
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();

      // Line with glow
      ctx.beginPath();
      ctx.moveTo(x(0), y(values[0]));
      for (let i = 1; i < count; i++) ctx.lineTo(x(i), y(values[i]));
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.shadowColor = glow;
      ctx.shadowBlur = 12;
      ctx.stroke();
      ctx.shadowBlur = 0;

      // End dot
      ctx.beginPath();
      ctx.arc(x(count - 1), y(values[count - 1]), 3.5, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();

      // Min/max labels
      ctx.fillStyle = "rgba(169,183,218,0.75)";
      ctx.font =
        "11px Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(money(max), pad.left + 2, pad.top - 3);
      ctx.fillText(money(min), pad.left + 2, h - pad.bottom + 14);
      // First/last dates
      if (dates.length) {
        ctx.fillText(dates[0], pad.left + 2, h - 4);
        ctx.textAlign = "right";
        ctx.fillText(dates[dates.length - 1], w - pad.right - 2, h - 4);
      }
    }

    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    if (reduceMotion) {
      draw(1);
    } else {
      const start = performance.now();
      const DURATION = 900;
      const tick = (now) => {
        const p = Math.min(1, (now - start) / DURATION);
        draw(1 - Math.pow(1 - p, 3)); // ease-out cubic
        if (p < 1) frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    }

    const onResize = () => draw(1);
    window.addEventListener("resize", onResize);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
    };
  }, [dates, values]);

  if (values.length < 2) {
    return <p className="empty">Not enough price history to chart yet.</p>;
  }
  return (
    <div className="value-chart-wrap">
      <canvas
        ref={canvasRef}
        role="img"
        aria-label="Line chart of total portfolio value over the selected period"
      />
    </div>
  );
}

/* SVG allocation donut with legend. */
function AllocationDonut({ holdings }) {
  const withValue = holdings.filter((h) => h.value > 0);
  const total = withValue.reduce((s, h) => s + h.value, 0);
  if (!total) return null;

  const R = 15.915; // circumference ≈ 100 for easy percent math
  let offset = 25; // start at 12 o'clock
  const slices = withValue.map((h, i) => {
    const share = (h.value / total) * 100;
    const slice = (
      <circle
        key={h.id}
        r={R}
        cx="21"
        cy="21"
        fill="transparent"
        stroke={DONUT_COLORS[i % DONUT_COLORS.length]}
        strokeWidth="5"
        strokeDasharray={`${share} ${100 - share}`}
        strokeDashoffset={offset}
      />
    );
    offset -= share;
    return slice;
  });

  return (
    <div className="donut-row">
      <svg
        viewBox="0 0 42 42"
        className="donut"
        role="img"
        aria-label="Donut chart of portfolio allocation by holding"
      >
        {slices}
      </svg>
      <ul className="donut-legend">
        {withValue.map((h, i) => (
          <li key={h.id}>
            <span
              className="legend-dot"
              style={{ background: DONUT_COLORS[i % DONUT_COLORS.length] }}
            />
            <span className="legend-ticker">{h.ticker}</span>
            <span className="legend-pct">
              {((h.value / total) * 100).toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function PortfolioDashboard({ refreshKey = 0 }) {
  const [period, setPeriod] = useState("6mo");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    getPortfolioValuation(period)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || "Could not load valuation.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [period, refreshKey]);

  if (loading && !data) {
    return (
      <section className="panel">
        <h3>Portfolio value</h3>
        <div className="loading">
          <span className="spinner" aria-hidden="true"></span>
          Fetching live prices…
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="panel">
        <h3>Portfolio value</h3>
        <p className="auth-error" role="alert">{error}</p>
      </section>
    );
  }

  if (!data || data.holdings.length === 0) return null;

  const up = (data.day_change_pct ?? 0) >= 0;
  const gainUp = (data.total_gain ?? 0) >= 0;

  return (
    <section className="panel dashboard">
      <div className="panel-head-row">
        <h3>Portfolio value</h3>
        <div className="timeframe-tabs" role="tablist" aria-label="Chart period">
          {PERIODS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={period === id}
              className={period === id ? "active" : ""}
              onClick={() => setPeriod(id)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="portfolio-value">
        <span className="amt">{money(data.total_value)}</span>
        <span className={up ? "chg" : "chg down"}>
          {pct(data.day_change_pct)} today
        </span>
      </div>

      <div className="stat-grid-mini">
        <div className="stat-mini">
          <span className="num">{money(data.total_cost)}</span>
          <span className="lbl">Cost basis</span>
        </div>
        <div className="stat-mini">
          <span className={gainUp ? "num pos" : "num neg"}>
            {money(data.total_gain)}
          </span>
          <span className="lbl">Total gain</span>
        </div>
        <div className="stat-mini">
          <span className={gainUp ? "num pos" : "num neg"}>
            {pct(data.total_gain_pct)}
          </span>
          <span className="lbl">Total return</span>
        </div>
        <div className="stat-mini">
          <span className="num">{data.holdings.length}</span>
          <span className="lbl">Holdings</span>
        </div>
      </div>

      <ValueChart dates={data.history.dates} values={data.history.values} />

      <div className="dashboard-split">
        <div>
          <h4 className="dash-subhead">Allocation</h4>
          <AllocationDonut holdings={data.holdings} />
        </div>
        <div>
          <h4 className="dash-subhead">Live positions</h4>
          <table className="holdings-table">
            <thead>
              <tr>
                <th>Ticker</th><th>Price</th><th>Day</th>
                <th>Value</th><th>Gain</th>
              </tr>
            </thead>
            <tbody>
              {data.holdings.map((h) => (
                <tr key={h.id}>
                  <td className="ticker-cell">{h.ticker}</td>
                  <td
                    title={
                      h.price_source === "summary"
                        ? `From your latest research summary (${h.price_as_of})`
                        : undefined
                    }
                  >
                    {money(h.price)}
                    {h.price_source === "summary" && (
                      <span className="price-src-mark">*</span>
                    )}
                  </td>
                  <td className={
                    h.day_change_pct == null
                      ? ""
                      : h.day_change_pct >= 0
                        ? "pos"
                        : "neg"
                  }>
                    {pct(h.day_change_pct)}
                  </td>
                  <td>{money(h.value)}</td>
                  <td className={
                    h.gain_pct == null ? "" : h.gain_pct >= 0 ? "pos" : "neg"
                  }>
                    {pct(h.gain_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {data.holdings.some((h) => h.price_source === "summary") && (
        <p className="panel-note">
          * Live quotes unavailable — price taken from your latest research
          summary. Run a summary from the Daily Feed to refresh it.
        </p>
      )}

      {data.errors.length > 0 && (
        <p className="panel-note">
          No price found for: {data.errors.join(", ")} — run a research
          summary for these tickers to capture one (excluded from totals).
        </p>
      )}
    </section>
  );
}
