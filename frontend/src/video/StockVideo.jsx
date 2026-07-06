// StockOfTheDay — vertical (1080x1920) Remotion composition, 30s or 1m05s.
//
// Shared by the in-app <Player> preview (Learn tab) and the CLI render the
// backend triggers for the TikTok-ready MP4 download. Everything is driven
// by props (including `duration_sec`) so one composition serves any pick at
// either length.

import React from "react";
import {
  AbsoluteFill,
  Easing,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export const FPS = 30;
export const DURATION_OPTIONS = [30, 65]; // seconds: 30s and 1m05s

// Per-scene frame budgets for each supported video length. The 65s cut keeps
// the same six-scene story but lets every beat breathe (and shows more of the
// agent summary in the "why" scene).
const TIMELINES = {
  30: { hook: 90, ticker: 150, momentum: 180, why: 240, confidence: 150, outro: 90 }, // 900f
  65: { hook: 150, ticker: 330, momentum: 420, why: 570, confidence: 330, outro: 150 }, // 1950f
};

export const timelineFor = (sec) => TIMELINES[sec] ?? TIMELINES[30];

export const videoDurationInFrames = (sec) =>
  Object.values(timelineFor(sec)).reduce((a, b) => a + b, 0);

// Back-compat: the classic 30s length.
export const DURATION_IN_FRAMES = videoDurationInFrames(30);

// Brand palette (mirrors the app's styles.css).
const C = {
  bg: "#05070c",
  bg2: "#0d1220",
  text: "#f4f7ff",
  muted: "#a9b7da",
  accent: "#2f81ff",
  accentSoft: "#7cb2ff",
  green: "#1fe0a0",
  amber: "#ffc24b",
  red: "#ff5c7a",
};

const FONT =
  "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";

const stanceColor = (s) =>
  s === "bullish" ? C.green : s === "bearish" ? C.red : C.amber;

const money = (n) =>
  n == null
    ? "—"
    : n.toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
      });

// --- Building blocks ---------------------------------------------------------

function Background() {
  const frame = useCurrentFrame();
  const drift = Math.sin(frame / 90) * 60;
  return (
    <AbsoluteFill style={{ background: C.bg }}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(700px 700px at ${300 + drift}px 400px, rgba(47,129,255,0.22), transparent 70%),
             radial-gradient(600px 600px at ${800 - drift}px 1500px, rgba(31,224,160,0.14), transparent 70%),
             linear-gradient(180deg, ${C.bg} 0%, ${C.bg2} 100%)`,
        }}
      />
      <AbsoluteFill
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px)",
          backgroundSize: "72px 72px",
          maskImage:
            "radial-gradient(ellipse 90% 70% at 50% 40%, black 30%, transparent 80%)",
        }}
      />
    </AbsoluteFill>
  );
}

// Springs in from below + fades. `delay` in frames within the sequence.
function Pop({ delay = 0, children, style }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({
    frame: frame - delay,
    fps,
    config: { damping: 14, stiffness: 120, mass: 0.6 },
  });
  return (
    <div
      style={{
        opacity: Math.min(1, s * 1.4),
        transform: `translateY(${(1 - s) * 90}px) scale(${0.92 + s * 0.08})`,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// Fades a whole scene out over its last `fade` frames.
function Scene({ durationInFrames, fade = 12, children }) {
  const frame = useCurrentFrame();
  const opacity = interpolate(
    frame,
    [durationInFrames - fade, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  return (
    <AbsoluteFill
      style={{
        opacity,
        padding: "140px 90px",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: FONT,
        color: C.text,
        textAlign: "center",
      }}
    >
      {children}
    </AbsoluteFill>
  );
}

function BrandTag() {
  return (
    <div
      style={{
        position: "absolute",
        top: 90,
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        gap: 18,
        alignItems: "center",
        fontFamily: FONT,
      }}
    >
      <svg width="44" height="44" viewBox="0 0 24 24" fill="none">
        <path
          d="M4 16l4-7 4 4 4-8 4 6"
          stroke={C.accentSoft}
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span
        style={{
          fontSize: 40,
          fontWeight: 700,
          letterSpacing: 2,
          color: C.muted,
        }}
      >
        MarketPilot
      </span>
    </div>
  );
}

function AnimatedNumber({ value, format, delay = 0, duration = 35, style }) {
  const frame = useCurrentFrame();
  const t = interpolate(frame - delay, [0, duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  return <span style={style}>{format(value * t)}</span>;
}

// --- Scenes ------------------------------------------------------------------

function HookScene({ dateLabel, duration = 90 }) {
  const frame = useCurrentFrame();
  const flash = interpolate(frame, [0, 6, 20], [0, 1, 0], {
    extrapolateRight: "clamp",
  });
  return (
    <Scene durationInFrames={duration}>
      <AbsoluteFill style={{ background: `rgba(47,129,255,${flash * 0.18})` }} />
      <Pop>
        <div style={{ fontSize: 64 }}>⚡</div>
      </Pop>
      <Pop delay={4}>
        <h1
          style={{
            fontSize: 130,
            fontWeight: 900,
            lineHeight: 1.02,
            margin: "30px 0 0",
            letterSpacing: -3,
          }}
        >
          STOCK
          <br />
          OF THE
          <br />
          <span
            style={{
              background: `linear-gradient(90deg, ${C.accent}, ${C.green})`,
              WebkitBackgroundClip: "text",
              color: "transparent",
            }}
          >
            DAY
          </span>
        </h1>
      </Pop>
      <Pop delay={14}>
        <p style={{ fontSize: 44, color: C.muted, marginTop: 50 }}>
          {dateLabel} · picked by AI agents
        </p>
      </Pop>
    </Scene>
  );
}

function TickerScene({ ticker, price, stance, duration = 150 }) {
  const color = stanceColor(stance);
  return (
    <Scene durationInFrames={duration}>
      <Pop>
        <p style={{ fontSize: 42, color: C.muted, letterSpacing: 6, margin: 0 }}>
          TODAY'S PICK
        </p>
      </Pop>
      <Pop delay={6}>
        <h1
          style={{
            fontSize: ticker.length > 4 ? 200 : 260,
            fontWeight: 900,
            margin: "20px 0",
            letterSpacing: -4,
            textShadow: `0 0 120px rgba(47,129,255,0.55)`,
          }}
        >
          ${ticker}
        </h1>
      </Pop>
      <Pop delay={16}>
        <div style={{ fontSize: 90, fontWeight: 800 }}>
          <AnimatedNumber value={price ?? 0} delay={16} format={money} />
        </div>
      </Pop>
      <Pop delay={26}>
        <div
          style={{
            marginTop: 55,
            display: "inline-block",
            padding: "22px 60px",
            borderRadius: 999,
            fontSize: 54,
            fontWeight: 800,
            letterSpacing: 4,
            color: C.bg,
            background: color,
            boxShadow: `0 0 90px ${color}66`,
          }}
        >
          {(stance || "neutral").toUpperCase()}
        </div>
      </Pop>
    </Scene>
  );
}

function MomentumScene({ momentum3mo, screenScore, duration = 180 }) {
  const frame = useCurrentFrame();
  const pctVal = (momentum3mo ?? 0) * 100;
  const up = pctVal >= 0;
  const color = up ? C.green : C.red;

  // Stylized momentum bars climbing (or sinking) toward the 3-mo move.
  const bars = 7;
  return (
    <Scene durationInFrames={duration}>
      <Pop>
        <p style={{ fontSize: 46, color: C.muted, letterSpacing: 5, margin: 0 }}>
          3-MONTH MOMENTUM
        </p>
      </Pop>
      <Pop delay={6}>
        <div style={{ fontSize: 170, fontWeight: 900, color, margin: "26px 0" }}>
          <AnimatedNumber
            value={pctVal}
            delay={8}
            format={(v) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`}
          />
        </div>
      </Pop>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          gap: 26,
          height: 360,
          marginTop: 30,
        }}
      >
        {Array.from({ length: bars }).map((_, i) => {
          const grow = interpolate(frame - 18 - i * 5, [0, 24], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.out(Easing.cubic),
          });
          const trend = up ? (i + 1) / bars : (bars - i) / bars;
          const h = (110 + trend * 250) * grow;
          return (
            <div
              key={i}
              style={{
                width: 74,
                height: h,
                borderRadius: 14,
                background: `linear-gradient(180deg, ${color}, ${color}33)`,
                boxShadow: `0 0 40px ${color}44`,
              }}
            />
          );
        })}
      </div>
      <Pop delay={60}>
        <p style={{ fontSize: 42, color: C.muted, marginTop: 60 }}>
          Technical screen score:{" "}
          <span style={{ color: C.text, fontWeight: 800 }}>
            {screenScore != null ? screenScore.toFixed(1) : "—"}
          </span>
        </p>
      </Pop>
    </Scene>
  );
}

// Cut a sentence at a word boundary so cards never run past the frame.
function clip(s, max) {
  if (s.length <= max) return s;
  const cut = s.slice(0, max);
  return `${cut.slice(0, cut.lastIndexOf(" "))}…`;
}

function WhyScene({ summary, duration = 240 }) {
  // Split the agent summary into punchy lines that appear in turn. The longer
  // cut has time for more of the summary; long summaries get clipped lines and
  // a smaller font so nothing ever crops off the bottom of the 1920px frame.
  const long = duration > 300;
  const maxLines = long ? 5 : 3;
  const sentences = (summary || "")
    .split(/(?<=[.!?])\s+/)
    .filter(Boolean)
    .slice(0, maxLines)
    .map((s) => clip(s, long ? 120 : 150));
  const lines = sentences.length
    ? sentences
    : ["The agents flagged this one on technicals and valuation."];
  const totalChars = lines.join("").length;
  // ~58px comfortably fits short text; scale down toward 40px as text grows.
  const fontSize = Math.round(
    Math.max(40, Math.min(58, 58 - (totalChars - 180) * 0.07))
  );
  const gap = totalChars > 300 ? 36 : 55;
  // Spread the line reveals across the scene, leaving hold time at the end.
  const step = Math.max(
    40,
    Math.floor((duration - 130) / Math.max(lines.length, 1))
  );
  return (
    <Scene durationInFrames={duration}>
      <Pop>
        <p style={{ fontSize: 46, color: C.muted, letterSpacing: 5, margin: 0 }}>
          WHY THE AI PICKED IT
        </p>
      </Pop>
      <div style={{ marginTop: 50, display: "flex", flexDirection: "column", gap }}>
        {lines.map((line, i) => (
          <Pop key={i} delay={12 + i * Math.min(step, 55 + (long ? 30 : 0))}>
            <p
              style={{
                fontSize,
                lineHeight: 1.32,
                fontWeight: 600,
                margin: 0,
                padding: "30px 40px",
                borderRadius: 28,
                background: "rgba(255,255,255,0.06)",
                border: "1px solid rgba(255,255,255,0.12)",
                textAlign: "left",
              }}
            >
              {line}
            </p>
          </Pop>
        ))}
      </div>
    </Scene>
  );
}

function ConfidenceScene({ confidence, rank, duration = 150 }) {
  const frame = useCurrentFrame();
  const pct = Math.round((confidence ?? 0.5) * 100);
  const color = pct >= 70 ? C.green : pct >= 45 ? C.amber : C.red;
  const fill = interpolate(frame - 14, [0, 40], [0, pct], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  return (
    <Scene durationInFrames={duration}>
      <Pop>
        <p style={{ fontSize: 46, color: C.muted, letterSpacing: 5, margin: 0 }}>
          AGENT CONFIDENCE
        </p>
      </Pop>
      <Pop delay={6}>
        <div style={{ fontSize: 190, fontWeight: 900, color, margin: "24px 0" }}>
          {Math.round(fill)}%
        </div>
      </Pop>
      <div
        style={{
          width: "86%",
          height: 44,
          borderRadius: 999,
          background: "rgba(255,255,255,0.08)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${fill}%`,
            height: "100%",
            borderRadius: 999,
            background: `linear-gradient(90deg, ${C.accent}, ${color})`,
            boxShadow: `0 0 60px ${color}66`,
          }}
        />
      </div>
      {rank != null && (
        <Pop delay={44}>
          <p style={{ fontSize: 52, marginTop: 70, color: C.muted }}>
            Ranked{" "}
            <span style={{ color: C.text, fontWeight: 900 }}>#{rank}</span> of
            the top 10 picks today
          </p>
        </Pop>
      )}
    </Scene>
  );
}

function OutroScene({ ticker, duration = 90 }) {
  return (
    <Scene durationInFrames={duration} fade={8}>
      <Pop>
        <h2 style={{ fontSize: 92, fontWeight: 900, margin: 0, letterSpacing: -2 }}>
          Would you buy{" "}
          <span style={{ color: C.accentSoft }}>${ticker}</span>?
        </h2>
      </Pop>
      <Pop delay={10}>
        <p style={{ fontSize: 50, color: C.muted, marginTop: 50 }}>
          Drop your take in the comments 👇
        </p>
      </Pop>
      <Pop delay={20}>
        <p style={{ fontSize: 34, color: C.muted, marginTop: 90, opacity: 0.8 }}>
          Generated by MarketPilot's AI agents.
          <br />
          Informational only — not investment advice.
        </p>
      </Pop>
    </Scene>
  );
}

// --- Composition --------------------------------------------------------------

export default function StockVideo({
  ticker = "AAPL",
  price = 231.45,
  stance = "bullish",
  confidence = 0.72,
  momentum_3mo = 0.124,
  screen_score = 8.2,
  rank = 1,
  summary = "Strong uptrend with price above key moving averages. Valuation remains reasonable versus peers. Agents see continued momentum into next quarter.",
  date_label = "Today",
  duration_sec = 30,
}) {
  const T = timelineFor(duration_sec);
  let cursor = 0;
  const at = (n) => {
    const from = cursor;
    cursor += n;
    return from;
  };
  return (
    <AbsoluteFill>
      <Background />
      <BrandTag />
      <Sequence from={at(T.hook)} durationInFrames={T.hook}>
        <HookScene dateLabel={date_label} duration={T.hook} />
      </Sequence>
      <Sequence from={at(T.ticker)} durationInFrames={T.ticker}>
        <TickerScene
          ticker={ticker}
          price={price}
          stance={stance}
          duration={T.ticker}
        />
      </Sequence>
      <Sequence from={at(T.momentum)} durationInFrames={T.momentum}>
        <MomentumScene
          momentum3mo={momentum_3mo}
          screenScore={screen_score}
          duration={T.momentum}
        />
      </Sequence>
      <Sequence from={at(T.why)} durationInFrames={T.why}>
        <WhyScene summary={summary} duration={T.why} />
      </Sequence>
      <Sequence from={at(T.confidence)} durationInFrames={T.confidence}>
        <ConfidenceScene
          confidence={confidence}
          rank={rank}
          duration={T.confidence}
        />
      </Sequence>
      <Sequence from={at(T.outro)} durationInFrames={T.outro}>
        <OutroScene ticker={ticker} duration={T.outro} />
      </Sequence>
    </AbsoluteFill>
  );
}
