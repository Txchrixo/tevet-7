/**
 * loading.tsx — Instant loader shown by Next.js while the page chunk loads.
 *
 * This renders BEFORE React hydration — it's pure HTML/CSS served by Next.js
 * streaming. No JS, no framer-motion, no state. That's why it's instant.
 *
 * The technique: Next.js App Router automatically wraps each route segment
 * in a Suspense boundary. While the route's JS chunk downloads + parses +
 * executes, this file's HTML is streamed to the browser immediately.
 *
 * The animation is pure CSS (no JS dependency) so it starts rendering
 * before any JS has loaded.
 */
export default function Loading() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background">
      {/* SVG heptagon (same shape as BrandMark) — inline so no JS needed */}
      <svg
        width="48"
        height="48"
        viewBox="0 0 24 24"
        fill="none"
        className="animate-spin"
        style={{ animationDuration: "2s", animationTimingFunction: "linear" }}
      >
        <path
          d="M 12 3 L 19.04 6.39 L 20.77 14 L 15.91 20.11 L 8.09 20.11 L 3.23 14 L 4.96 6.39 Z"
          stroke="var(--accent, #A8C090)"
          strokeWidth="1.75"
          strokeLinejoin="round"
          opacity="0.3"
        />
        {/* Spinning arc */}
        <path
          d="M 12 3 L 19.04 6.39"
          stroke="var(--accent, #A8C090)"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}
