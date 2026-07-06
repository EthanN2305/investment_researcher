// StockOfTheDay — vertical (1080x1920) Remotion composition, 30s or 1m05s.
//
// Shared by the in-app <Player> preview (Learn tab) and the CLI render the
// backend triggers for the TikTok-ready MP4 download. Everything is driven by
// props (including `duration_sec`, the enriched `details`/`news`/`reasons`, the
// per-scene `captions`, and an optional `voice` manifest) so one composition
// serves any pick at either length, with or without a voiceover.
//
// Eight beats: hook → ticker → at-a-glance details → momentum → in the news →
// why the AI picked it → confidence → outro. A synced subtitle track and an
// optional narration audio track make it feel like a produced short.

import React from "react";
import {
  AbsoluteFill,
  Audio,
  Easing,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export const FPS = 30;
export const DURATION_OPTIONS = [30, 65]; // seconds: 30s and 1m05s

// Scene order (drives layout + the caption/audio track). "about" — what the
// company actually does — sits right after the ticker reveal.
const SCENE_ORDER = [
  "hook", "ticker", "about", "details", "momentum", "news", "why",
  "confidence", "outro",
];

// Minimum on-screen time per scene (frames) — enough for the animation to land
// and be read even when there's no voiceover. When narration IS present, the
// scene stretches to fit the clip (see sceneDurations) so audio is NEVER cut.
// The two "lengths" now just set a floor and how much detail the script packs
// in; the real runtime follows the narration, so nothing is hard-capped.
const MIN_BUDGET = {
  30: {
    hook: 70, ticker: 96, about: 120, details: 116, momentum: 120,
    news: 116, why: 132, confidence: 96, outro: 66,
  },
  65: {
    hook: 96, ticker: 140, about: 200, details: 170, momentum: 170,
    news: 190, why: 220, confidence: 150, outro: 120,
  },
};

// Narration timing within a scene: a short beat before the voice starts, and
// breathing room after it ends so the audio finishes comfortably on-screen.
export const LEAD_IN = 9; // frames
export const TAIL_OUT = 20; // frames

const clipFramesFor = (voice, id) => {
  const c =
    voice && voice.available && voice.scenes && voice.scenes[id];
  return c && c.seconds ? Math.ceil(c.seconds * FPS) : null;
};

// Per-scene frame counts. Each scene lasts at least its visual floor, and at
// least long enough to contain its narration clip (+ lead-in + tail-out).
export function sceneDurations(sec = 30, voice = null) {
  const base = MIN_BUDGET[sec] ?? MIN_BUDGET[30];
  const out = {};
  for (const id of SCENE_ORDER) {
    let dur = base[id] ?? 120;
    const audio = clipFramesFor(voice, id);
    if (audio != null) dur = Math.max(dur, audio + LEAD_IN + TAIL_OUT);
    out[id] = dur;
  }
  return out;
}

export const timelineFor = (sec, voice = null) => sceneDurations(sec, voice);

export const videoDurationInFrames = (sec, voice = null) =>
  Object.values(sceneDurations(sec, voice)).reduce((a, b) => a + b, 0);

// Back-compat: the classic 30s length (no voiceover floor).
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
  card: "rgba(255,255,255,0.06)",
  cardBorder: "rgba(255,255,255,0.12)",
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
  // A slow diagonal light sweep adds life without distracting from the text.
  const sweep = interpolate(frame % 240, [0, 240], [-40, 140]);
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
      <AbsoluteFill
        style={{
          background: `linear-gradient(115deg, transparent ${sweep - 20}%, rgba(124,178,255,0.06) ${sweep}%, transparent ${sweep + 20}%)`,
        }}
      />
      <Particles />
    </AbsoluteFill>
  );
}

// Slow-drifting motes of light — cheap, deterministic, and add a sense of depth
// and motion so static text scenes never feel dead.
function Particles({ count = 14 }) {
  const frame = useCurrentFrame();
  const dots = Array.from({ length: count }, (_, i) => {
    const seedX = (i * 97) % 100;
    const seedY = (i * 53) % 100;
    const speed = 0.4 + ((i % 5) * 0.18);
    const size = 4 + ((i * 7) % 9);
    const x = (seedX + Math.sin((frame + i * 30) / 70) * 6) % 100;
    const y = (seedY - ((frame * speed) / 12) + 100) % 100;
    const twinkle = 0.25 + (Math.sin((frame + i * 40) / 24) + 1) * 0.22;
    const green = i % 3 === 0;
    return { x, y, size, opacity: twinkle, green };
  });
  return (
    <AbsoluteFill>
      {dots.map((d, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: `${d.x}%`,
            top: `${d.y}%`,
            width: d.size,
            height: d.size,
            borderRadius: "50%",
            background: d.green ? C.green : C.accentSoft,
            opacity: d.opacity,
            boxShadow: `0 0 ${d.size * 3}px ${d.green ? C.green : C.accent}`,
          }}
        />
      ))}
    </AbsoluteFill>
  );
}

// Springs in from below + fades. `delay` in frames within the sequence.
function Pop({ delay = 0, from = 90, children, style }) {
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
        transform: `translateY(${(1 - s) * from}px) scale(${0.92 + s * 0.08})`,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// Slides in from the side — used for list items (news, reasons) so they feel
// like they're being dealt onto the screen.
function SlideIn({ delay = 0, dir = -1, children, style }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({
    frame: frame - delay,
    fps,
    config: { damping: 16, stiffness: 140, mass: 0.7 },
  });
  return (
    <div
      style={{
        opacity: Math.min(1, s * 1.6),
        transform: `translateX(${(1 - s) * 120 * dir}px)`,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// Scene wrapper: scales/fades in on entry and fades out over its last frames,
// so cuts feel like transitions rather than hard jumps.
function Scene({ durationInFrames, fade = 12, children }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({
    frame,
    fps,
    config: { damping: 200, stiffness: 90, mass: 0.7 },
  });
  const outOpacity = interpolate(
    frame,
    [durationInFrames - fade, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  return (
    <AbsoluteFill
      style={{
        opacity: outOpacity * Math.min(1, enter * 1.5),
        transform: `scale(${0.97 + enter * 0.03})`,
        // Leave room for the caption bar at the very bottom (~230px).
        padding: "150px 90px 300px",
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
        top: 72,
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        gap: 16,
        alignItems: "center",
        fontFamily: FONT,
        zIndex: 5,
      }}
    >
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none">
        <path
          d="M4 16l4-7 4 4 4-8 4 6"
          stroke={C.accentSoft}
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span
        style={{ fontSize: 36, fontWeight: 700, letterSpacing: 2, color: C.muted }}
      >
        MarketPilot
      </span>
    </div>
  );
}

// Thin progress bar across the very top — a classic "short video" affordance.
function ProgressBar() {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const pct = interpolate(frame, [0, durationInFrames], [0, 100], {
    extrapolateRight: "clamp",
  });
  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        height: 10,
        background: "rgba(255,255,255,0.08)",
        zIndex: 6,
      }}
    >
      <div
        style={{
          width: `${pct}%`,
          height: "100%",
          background: `linear-gradient(90deg, ${C.accent}, ${C.green})`,
        }}
      />
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

function Kicker({ children }) {
  return (
    <Pop from={40}>
      <p
        style={{
          fontSize: 44,
          color: C.muted,
          letterSpacing: 6,
          margin: 0,
          fontWeight: 700,
        }}
      >
        {children}
      </p>
    </Pop>
  );
}

// --- Caption / subtitle track ------------------------------------------------

// Renders the caption for whichever scene is active, pinned near the bottom.
// Words fade in progressively so it reads like animated captions on a Short.
function CaptionTrack({ windows }) {
  const frame = useCurrentFrame();
  const active = windows.find((w) => frame >= w.from && frame < w.from + w.dur);
  if (!active || !active.text) return null;
  const local = frame - active.from;
  const words = active.text.split(" ");
  // Reveal words in sync with the narration when we know its length+start;
  // otherwise fall back to spreading them over the first ~70% of the scene.
  const revealLocal = local - (active.lead || 0);
  const span = active.speak || active.dur * 0.7;
  const per = Math.max(2, Math.floor(span / words.length));
  const appear = interpolate(local, [0, 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div
      style={{
        position: "absolute",
        left: 70,
        right: 70,
        bottom: 150,
        display: "flex",
        justifyContent: "center",
        zIndex: 7,
        opacity: appear,
      }}
    >
      <div
        style={{
          maxWidth: 940,
          padding: "26px 40px",
          borderRadius: 26,
          background: "rgba(5,7,12,0.62)",
          border: `1px solid ${C.cardBorder}`,
          backdropFilter: "blur(6px)",
          fontFamily: FONT,
          fontSize: 46,
          fontWeight: 800,
          lineHeight: 1.28,
          color: C.text,
          textAlign: "center",
        }}
      >
        {words.map((w, i) => {
          const lit = revealLocal >= i * per;
          return (
            <span
              key={i}
              style={{
                opacity: lit ? 1 : 0.28,
                color: lit ? C.text : C.muted,
                transition: "opacity 0.1s",
              }}
            >
              {w}
              {i < words.length - 1 ? " " : ""}
            </span>
          );
        })}
      </div>
    </div>
  );
}

// --- Scenes ------------------------------------------------------------------

function HookScene({ dateLabel, duration = 90 }) {
  const frame = useCurrentFrame();
  const flash = interpolate(frame, [0, 6, 20], [0, 1, 0], {
    extrapolateRight: "clamp",
  });
  const pulse = 1 + Math.sin(frame / 6) * 0.03;
  return (
    <Scene durationInFrames={duration}>
      <AbsoluteFill style={{ background: `rgba(47,129,255,${flash * 0.18})` }} />
      <Pop>
        <div style={{ fontSize: 78, transform: `scale(${pulse})` }}>⚡</div>
      </Pop>
      <Pop delay={4}>
        <h1
          style={{
            fontSize: 132,
            fontWeight: 900,
            lineHeight: 1.02,
            margin: "24px 0 0",
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
        <p style={{ fontSize: 44, color: C.muted, marginTop: 46 }}>
          {dateLabel} · picked by AI agents
        </p>
      </Pop>
    </Scene>
  );
}

function TickerScene({ ticker, price, stance, name, momentum3mo, duration = 150 }) {
  const color = stanceColor(stance);
  const up = (momentum3mo ?? 0) >= 0;
  return (
    <Scene durationInFrames={duration}>
      <Kicker>TODAY'S PICK</Kicker>
      <Pop delay={6}>
        <h1
          style={{
            fontSize: ticker.length > 4 ? 200 : 260,
            fontWeight: 900,
            margin: "16px 0 0",
            letterSpacing: -4,
            textShadow: `0 0 120px rgba(47,129,255,0.55)`,
          }}
        >
          ${ticker}
        </h1>
      </Pop>
      {name && (
        <Pop delay={12}>
          <p style={{ fontSize: 40, color: C.muted, margin: "6px 0 0" }}>
            {name}
          </p>
        </Pop>
      )}
      <Pop delay={16}>
        <div style={{ fontSize: 96, fontWeight: 800, marginTop: 26 }}>
          <AnimatedNumber value={price ?? 0} delay={16} format={money} />
        </div>
      </Pop>
      <Pop delay={22} from={30}>
        <div style={{ marginTop: 30 }}>
          <Sparkline up={up} delay={24} />
        </div>
      </Pop>
      <Pop delay={26}>
        <div
          style={{
            marginTop: 48,
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

// A little animated line chart used behind the ticker reveal — direction and
// tint follow 3-month momentum, so the visual matches the story.
function Sparkline({ up = true, width = 620, height = 150, delay = 0 }) {
  const frame = useCurrentFrame();
  const color = up ? C.green : C.red;
  // Deterministic jagged-but-trending series (no randomness → stable renders).
  const seed = [0.15, 0.28, 0.22, 0.44, 0.38, 0.62, 0.55, 0.8, 0.74, 1];
  const pts = seed.map((v) => (up ? v : 1 - v));
  const n = pts.length;
  const draw = interpolate(frame - delay, [0, 34], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const shown = Math.max(2, Math.round(n * draw));
  const coords = pts.slice(0, shown).map((v, i) => {
    const x = (i / (n - 1)) * width;
    const y = height - v * (height - 16) - 8;
    return [x, y];
  });
  const line = coords.map((c) => c.join(",")).join(" ");
  const area = `${line} ${coords[coords.length - 1][0]},${height} 0,${height}`;
  const [hx, hy] = coords[coords.length - 1];
  return (
    <svg width={width} height={height} style={{ overflow: "visible" }}>
      <polygon points={area} fill={`${color}22`} />
      <polyline
        points={line}
        fill="none"
        stroke={color}
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ filter: `drop-shadow(0 0 16px ${color}88)` }}
      />
      <circle cx={hx} cy={hy} r="12" fill={color} style={{ filter: `drop-shadow(0 0 18px ${color})` }} />
    </svg>
  );
}

// "What they do" — the business, in plain English, with a couple of quick
// facts. Grounded in yfinance's company profile; degrades if it's missing.
function AboutScene({ ticker, details = {}, duration = 150 }) {
  const about = details.about || details.about_short;
  const facts = [
    details.industry && { icon: "🏷️", label: "INDUSTRY", value: details.industry },
    details.employees && { icon: "👥", label: "EMPLOYEES", value: details.employees },
    details.headquarters && { icon: "📍", label: "HQ", value: details.headquarters },
  ].filter(Boolean);

  if (!about && facts.length === 0) {
    return (
      <Scene durationInFrames={duration}>
        <Kicker>WHAT THEY DO</Kicker>
        <Pop delay={8}>
          <p style={{ fontSize: 56, color: C.muted, marginTop: 40 }}>
            Let's break down ${ticker} 👇
          </p>
        </Pop>
      </Scene>
    );
  }

  return (
    <Scene durationInFrames={duration}>
      <Kicker>WHAT THEY DO</Kicker>
      {details.name && (
        <Pop delay={4}>
          <h2
            style={{
              fontSize: 64,
              fontWeight: 900,
              margin: "18px 0 0",
              letterSpacing: -1,
            }}
          >
            {details.name}
          </h2>
        </Pop>
      )}
      {about && (
        <Pop delay={10} from={50}>
          <div
            style={{
              marginTop: 34,
              maxWidth: 900,
              padding: "34px 40px",
              borderRadius: 28,
              background: C.card,
              border: `1px solid ${C.cardBorder}`,
              fontSize: 46,
              lineHeight: 1.36,
              fontWeight: 600,
              color: C.text,
            }}
          >
            {about}
          </div>
        </Pop>
      )}
      {facts.length > 0 && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 20,
            justifyContent: "center",
            marginTop: 40,
          }}
        >
          {facts.map((f, i) => (
            <SlideIn key={f.label} delay={18 + i * 8} dir={-1}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 16,
                  padding: "22px 30px",
                  borderRadius: 999,
                  background: C.card,
                  border: `1px solid ${C.cardBorder}`,
                }}
              >
                <span style={{ fontSize: 40 }}>{f.icon}</span>
                <span style={{ fontSize: 34, color: C.muted }}>{f.label}</span>
                <span style={{ fontSize: 38, fontWeight: 800 }}>{f.value}</span>
              </div>
            </SlideIn>
          ))}
        </div>
      )}
    </Scene>
  );
}

function StatCard({ label, value, delay = 0, accent = C.text }) {
  return (
    <Pop delay={delay} from={50}>
      <div
        style={{
          padding: "34px 30px",
          borderRadius: 26,
          background: C.card,
          border: `1px solid ${C.cardBorder}`,
          minWidth: 340,
        }}
      >
        <div style={{ fontSize: 34, color: C.muted, letterSpacing: 2 }}>
          {label}
        </div>
        <div
          style={{
            fontSize: 60,
            fontWeight: 900,
            marginTop: 10,
            color: accent,
          }}
        >
          {value}
        </div>
      </div>
    </Pop>
  );
}

function DetailsScene({ details = {}, duration = 126 }) {
  const frame = useCurrentFrame();
  const pos = details.range_pos;
  const cards = [
    details.sector && { label: "SECTOR", value: details.sector },
    details.market_cap &&
      details.market_cap !== "—" && {
        label: "MARKET CAP",
        value: details.market_cap,
      },
    details.pe_ratio && { label: "P/E RATIO", value: `${details.pe_ratio}×` },
  ].filter(Boolean);

  // Fallback when live fundamentals aren't available.
  if (cards.length === 0 && pos == null) {
    return (
      <Scene durationInFrames={duration}>
        <Kicker>AT A GLANCE</Kicker>
        <Pop delay={8}>
          <p style={{ fontSize: 56, color: C.muted, marginTop: 40 }}>
            A closer look at the numbers 👇
          </p>
        </Pop>
      </Scene>
    );
  }

  const fill = pos == null ? 0 : interpolate(frame - 30, [0, 30], [0, pos], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  return (
    <Scene durationInFrames={duration}>
      <Kicker>AT A GLANCE</Kicker>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 26,
          justifyContent: "center",
          marginTop: 44,
        }}
      >
        {cards.map((c, i) => (
          <StatCard key={c.label} label={c.label} value={c.value} delay={8 + i * 8} />
        ))}
      </div>
      {pos != null && (
        <Pop delay={26} from={40}>
          <div style={{ marginTop: 56, width: 900 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 32,
                color: C.muted,
                marginBottom: 16,
              }}
            >
              <span>52-wk low {details.range_low}</span>
              <span>high {details.range_high}</span>
            </div>
            <div
              style={{
                position: "relative",
                height: 26,
                borderRadius: 999,
                background: "rgba(255,255,255,0.08)",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  left: `calc(${fill}% - 22px)`,
                  top: -12,
                  width: 50,
                  height: 50,
                  borderRadius: "50%",
                  background: C.accentSoft,
                  boxShadow: `0 0 40px ${C.accent}`,
                  border: `4px solid ${C.bg}`,
                }}
              />
              <div
                style={{
                  width: `${fill}%`,
                  height: "100%",
                  borderRadius: 999,
                  background: `linear-gradient(90deg, ${C.accent}, ${C.accentSoft})`,
                }}
              />
            </div>
            <p style={{ fontSize: 34, color: C.muted, marginTop: 22 }}>
              {pos >= 60
                ? "Trading near the top of its 52-week range"
                : pos <= 35
                ? "Sitting in the lower half of its range"
                : "Mid-range over the past year"}
            </p>
          </div>
        </Pop>
      )}
    </Scene>
  );
}

function MomentumScene({ momentum3mo, screenScore, duration = 180 }) {
  const frame = useCurrentFrame();
  const pctVal = (momentum3mo ?? 0) * 100;
  const up = pctVal >= 0;
  const color = up ? C.green : C.red;
  const bars = 7;
  return (
    <Scene durationInFrames={duration}>
      <Kicker>3-MONTH MOMENTUM</Kicker>
      <Pop delay={6}>
        <div style={{ fontSize: 170, fontWeight: 900, color, margin: "20px 0" }}>
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
          height: 340,
          marginTop: 20,
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
      <Pop delay={54}>
        <p style={{ fontSize: 42, color: C.muted, marginTop: 52 }}>
          Technical screen score:{" "}
          <span style={{ color: C.text, fontWeight: 800 }}>
            {screenScore != null ? screenScore.toFixed(1) : "—"}
          </span>
        </p>
      </Pop>
    </Scene>
  );
}

function NewsScene({ news = [], duration = 138 }) {
  if (!news.length) {
    return (
      <Scene durationInFrames={duration}>
        <Kicker>THE SETUP</Kicker>
        <Pop delay={8}>
          <p style={{ fontSize: 52, color: C.muted, marginTop: 40, maxWidth: 860 }}>
            The AI flagged this one on price action and technicals.
          </p>
        </Pop>
      </Scene>
    );
  }
  return (
    <Scene durationInFrames={duration}>
      <Kicker>IN THE NEWS</Kicker>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 28,
          marginTop: 46,
          width: 920,
        }}
      >
        {news.map((n, i) => (
          <SlideIn key={i} delay={10 + i * 16} dir={i % 2 === 0 ? -1 : 1}>
            <div
              style={{
                display: "flex",
                gap: 24,
                alignItems: "flex-start",
                padding: "30px 34px",
                borderRadius: 24,
                background: C.card,
                border: `1px solid ${C.cardBorder}`,
                textAlign: "left",
              }}
            >
              <div style={{ fontSize: 46, lineHeight: 1 }}>📰</div>
              <div>
                <p style={{ fontSize: 42, fontWeight: 700, margin: 0, lineHeight: 1.28 }}>
                  {n.title}
                </p>
                <p style={{ fontSize: 30, color: C.muted, margin: "12px 0 0" }}>
                  {n.source} · {n.when}
                </p>
              </div>
            </div>
          </SlideIn>
        ))}
      </div>
    </Scene>
  );
}

// Cut a sentence at a word boundary so cards never run past the frame.
function clip(s, max) {
  if (s.length <= max) return s;
  const cut = s.slice(0, max);
  return `${cut.slice(0, cut.lastIndexOf(" "))}…`;
}

function WhyScene({ reasons, summary, long = false, duration = 240 }) {
  const maxReasons = long ? 5 : 3;

  // Prefer structured reasons; fall back to splitting the agent summary.
  let cards = (reasons || []).slice(0, maxReasons).map((r) => ({
    icon: r.icon || "•",
    label: r.label || "",
    text: clip(r.text || "", long ? 150 : 120),
  }));

  if (cards.length === 0) {
    const sentences = (summary || "")
      .split(/(?<=[.!?])\s+/)
      .filter(Boolean)
      .slice(0, maxReasons)
      .map((s) => clip(s, long ? 140 : 120));
    cards = (sentences.length
      ? sentences
      : ["The agents flagged this one on technicals and valuation."]
    ).map((s) => ({ icon: "✅", label: "", text: s }));
  }

  const step = Math.max(
    28,
    Math.floor((duration - 110) / Math.max(cards.length, 1))
  );

  return (
    <Scene durationInFrames={duration}>
      <Kicker>WHY THE AI PICKED IT</Kicker>
      <div style={{ marginTop: 46, display: "flex", flexDirection: "column", gap: 26, width: 940 }}>
        {cards.map((c, i) => (
          <SlideIn key={i} delay={10 + i * Math.min(step, 44)} dir={-1}>
            <div
              style={{
                display: "flex",
                gap: 26,
                alignItems: "center",
                padding: "28px 34px",
                borderRadius: 26,
                background: C.card,
                border: `1px solid ${C.cardBorder}`,
                textAlign: "left",
              }}
            >
              <div style={{ fontSize: 56, lineHeight: 1 }}>{c.icon}</div>
              <div>
                {c.label && (
                  <p style={{ fontSize: 34, color: C.accentSoft, fontWeight: 800, margin: 0, letterSpacing: 1 }}>
                    {c.label.toUpperCase()}
                  </p>
                )}
                <p style={{ fontSize: 44, fontWeight: 600, margin: c.label ? "8px 0 0" : 0, lineHeight: 1.3 }}>
                  {c.text}
                </p>
              </div>
            </div>
          </SlideIn>
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

  // Circular gauge.
  const R = 210;
  const CIRC = 2 * Math.PI * R;
  const dash = (fill / 100) * CIRC;

  return (
    <Scene durationInFrames={duration}>
      <Kicker>AGENT CONFIDENCE</Kicker>
      <Pop delay={6}>
        <div style={{ position: "relative", width: 520, height: 520, marginTop: 20 }}>
          <svg width="520" height="520" viewBox="0 0 520 520">
            <circle cx="260" cy="260" r={R} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="34" />
            <circle
              cx="260"
              cy="260"
              r={R}
              fill="none"
              stroke={color}
              strokeWidth="34"
              strokeLinecap="round"
              strokeDasharray={`${dash} ${CIRC}`}
              transform="rotate(-90 260 260)"
              style={{ filter: `drop-shadow(0 0 24px ${color})` }}
            />
          </svg>
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 150,
              fontWeight: 900,
              color,
            }}
          >
            {Math.round(fill)}%
          </div>
        </div>
      </Pop>
      {rank != null && (
        <Pop delay={40}>
          <p style={{ fontSize: 50, marginTop: 44, color: C.muted }}>
            Ranked <span style={{ color: C.text, fontWeight: 900 }}>#{rank}</span>{" "}
            of the top 10 picks today
          </p>
        </Pop>
      )}
    </Scene>
  );
}

function OutroScene({ ticker, duration = 90 }) {
  const frame = useCurrentFrame();
  const bounce = 1 + Math.sin(frame / 5) * 0.06;
  return (
    <Scene durationInFrames={duration} fade={8}>
      <Pop>
        <h2 style={{ fontSize: 96, fontWeight: 900, margin: 0, letterSpacing: -2 }}>
          Would you buy{" "}
          <span style={{ color: C.accentSoft }}>${ticker}</span>?
        </h2>
      </Pop>
      <Pop delay={10}>
        <p style={{ fontSize: 52, color: C.text, marginTop: 44, fontWeight: 700 }}>
          Drop your take in the comments{" "}
          <span style={{ display: "inline-block", transform: `scale(${bounce})` }}>👇</span>
        </p>
      </Pop>
      <Pop delay={20}>
        <div
          style={{
            marginTop: 60,
            padding: "24px 54px",
            borderRadius: 999,
            fontSize: 44,
            fontWeight: 800,
            color: C.bg,
            background: `linear-gradient(90deg, ${C.accent}, ${C.green})`,
          }}
        >
          Follow for tomorrow's pick
        </div>
      </Pop>
      <Pop delay={30}>
        <p style={{ fontSize: 32, color: C.muted, marginTop: 64, opacity: 0.8 }}>
          Generated by MarketPilot's AI agents.
          <br />
          Informational only — not investment advice.
        </p>
      </Pop>
    </Scene>
  );
}

// --- Voiceover ---------------------------------------------------------------

// Renders the narration clip for a scene, if the manifest has one. `voice` is
// { available, dir, scenes: { <id>: { file, seconds } } } where `dir` is a
// public-relative folder (e.g. "voiceover/abc123").
function SceneAudio({ voice, id, delay = 0 }) {
  if (!voice || !voice.available || !voice.dir) return null;
  const clipInfo = voice.scenes && voice.scenes[id];
  if (!clipInfo || !clipInfo.file) return null;
  let src;
  try {
    src = staticFile(`${voice.dir}/${clipInfo.file}`);
  } catch {
    return null;
  }
  // A short beat after the scene appears before the voice comes in.
  return (
    <Sequence from={delay}>
      <Audio src={src} />
    </Sequence>
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
  details = {},
  news = [],
  reasons = [],
  captions = {},
  voice = null,
}) {
  const long = duration_sec >= 65;
  const T = sceneDurations(duration_sec, voice);

  // Walk the timeline once, tracking each scene's absolute frame window so the
  // caption track and per-scene audio line up exactly with the visuals.
  let cursor = 0;
  const windows = {};
  for (const id of SCENE_ORDER) {
    windows[id] = { from: cursor, dur: T[id] };
    cursor += T[id];
  }

  // Captions reveal in step with the narration clip (lead-in + spoken length)
  // when we have it, so subtitles track the voice precisely.
  const captionWindows = SCENE_ORDER.map((id) => {
    const audio = clipFramesFor(voice, id);
    return {
      from: windows[id].from,
      dur: windows[id].dur,
      text: captions[id] || "",
      lead: audio != null ? LEAD_IN : 0,
      speak: audio != null ? audio : null,
    };
  });

  const sceneEl = {
    hook: <HookScene dateLabel={date_label} duration={T.hook} />,
    ticker: (
      <TickerScene
        ticker={ticker}
        price={price}
        stance={stance}
        name={details && details.name}
        momentum3mo={momentum_3mo}
        duration={T.ticker}
      />
    ),
    about: <AboutScene ticker={ticker} details={details} duration={T.about} />,
    details: <DetailsScene details={details} duration={T.details} />,
    momentum: (
      <MomentumScene
        momentum3mo={momentum_3mo}
        screenScore={screen_score}
        duration={T.momentum}
      />
    ),
    news: <NewsScene news={news} duration={T.news} />,
    why: (
      <WhyScene reasons={reasons} summary={summary} long={long} duration={T.why} />
    ),
    confidence: (
      <ConfidenceScene confidence={confidence} rank={rank} duration={T.confidence} />
    ),
    outro: <OutroScene ticker={ticker} duration={T.outro} />,
  };

  return (
    <AbsoluteFill>
      <Background />
      <ProgressBar />
      <BrandTag />
      {SCENE_ORDER.map((id) => (
        <Sequence key={id} from={windows[id].from} durationInFrames={windows[id].dur}>
          {sceneEl[id]}
          <SceneAudio voice={voice} id={id} delay={LEAD_IN} />
        </Sequence>
      ))}
      <CaptionTrack windows={captionWindows} />
    </AbsoluteFill>
  );
}
