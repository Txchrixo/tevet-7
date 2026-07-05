/**
 * loading.tsx — Instant loader with animated heptagon dot.
 *
 * The cream dot travels along the 7 vertices of the heptagon (BrandMark shape),
 * creating a smooth loading animation. Pure SVG + CSS keyframes — no JS
 * dependency, renders before React hydration.
 *
 * The animation: dot moves vertex by vertex (7 steps), 0.25s per vertex,
 * linear easing, infinite loop. Total cycle = 1.75s.
 */

// Heptagon vertices (same as BrandMark: circumradius 9, center 12,12)
const VERTICES = [
  [12.0, 3.0],
  [19.04, 6.39],
  [20.77, 14.0],
  [15.91, 20.11],
  [8.09, 20.11],
  [3.23, 14.0],
  [4.96, 6.39],
];

export default function Loading() {
  // Build keyframes for the dot: move through all 7 vertices + back to start
  const keyframes = VERTICES.concat([VERTICES[0]]).map(([x, y]) => ({
    transform: `translate(${x}px, ${y}px)`,
  }));

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <svg width="56" height="56" viewBox="0 0 24 24" fill="none">
        {/* Heptagon outline (static, dimmed) */}
        <path
          d="M 12 3 L 19.04 6.39 L 20.77 14 L 15.91 20.11 L 8.09 20.11 L 3.23 14 L 4.96 6.39 Z"
          stroke="var(--accent, #A8C090)"
          strokeWidth="1"
          strokeLinejoin="round"
          opacity="0.2"
        />
        {/* Moving dot — travels along the 7 vertices */}
        <circle
          r="2"
          fill="var(--foreground, #E8E0C9)"
          style={{
            animation: "heptagon-dot 1.75s linear infinite",
          }}
        />
        <style>{`
          @keyframes heptagon-dot {
            0%      { transform: translate(12px, 3px); }
            14.28%  { transform: translate(19.04px, 6.39px); }
            28.57%  { transform: translate(20.77px, 14px); }
            42.85%  { transform: translate(15.91px, 20.11px); }
            57.14%  { transform: translate(8.09px, 20.11px); }
            71.42%  { transform: translate(3.23px, 14px); }
            85.71%  { transform: translate(4.96px, 6.39px); }
            100%    { transform: translate(12px, 3px); }
          }
        `}</style>
      </svg>
    </div>
  );
}
