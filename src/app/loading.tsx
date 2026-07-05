/**
 * loading.tsx - Tech minimalist loader.
 *
 * The heptagon outline draws itself (stroke-dasharray animation) while the
 * top vertex dot pulses. Pure SVG + CSS, no JS. Renders before hydration.
 *
 * Animation cycle (2s):
 * 1. Outline draws from top vertex clockwise (0-60%)
 * 2. Holds complete (60-75%)
 * 3. Fades out (75-90%)
 * 4. Reset (90-100%)
 * The dot pulses throughout (scale + opacity).
 */

export default function Loading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <svg width="56" height="56" viewBox="0 0 24 24" fill="none">
        {/* Heptagon outline - draws itself */}
        <path
          d="M 12 3 L 19.04 6.39 L 20.77 14 L 15.91 20.11 L 8.09 20.11 L 3.23 14 L 4.96 6.39 Z"
          stroke="var(--accent, #A8C090)"
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
          style={{
            strokeDasharray: 55,
            strokeDashoffset: 55,
            animation: "hept-draw 2s cubic-bezier(0.4, 0, 0.2, 1) infinite",
          }}
        />
        {/* Top vertex dot - pulses */}
        <circle
          cx="12"
          cy="3"
          r="1.8"
          fill="var(--foreground, #E8E0C9)"
          style={{
            transformOrigin: "12px 3px",
            animation: "hept-pulse 2s ease-in-out infinite",
          }}
        />
        <style>{`
          @keyframes hept-draw {
            0%      { stroke-dashoffset: 55; opacity: 1; }
            60%     { stroke-dashoffset: 0; opacity: 1; }
            75%     { stroke-dashoffset: 0; opacity: 1; }
            90%     { stroke-dashoffset: 0; opacity: 0.15; }
            100%    { stroke-dashoffset: 55; opacity: 0.15; }
          }
          @keyframes hept-pulse {
            0%, 100%  { transform: scale(1); opacity: 1; }
            50%       { transform: scale(1.6); opacity: 0.7; }
          }
        `}</style>
      </svg>
    </div>
  );
}
