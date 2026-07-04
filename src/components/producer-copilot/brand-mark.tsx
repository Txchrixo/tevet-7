/**
 * Tevet-7 brand mark.
 *
 * The heptagon (7-sided polygon) directly references the "7" in Tevet-7.
 * Drawn as an SVG outline in the accent color (#A8C090), with a small filled
 * circle (node/spark) at the top vertex in the foreground (#E8E0C9).
 *
 * Geometrically: regular heptagon, circumradius 9, centered at (12,12),
 * first vertex pointing straight up. Coordinates precomputed.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

interface BrandMarkProps {
  size?: number;
  className?: string;
}

/**
 * The icon mark only — heptagon outline + top-vertex node.
 *
 * Uses a `useEffect` + `useState` "mounted" guard so the SVG (which reads
 * CSS variables `--accent` / `--foreground` that resolve differently once
 * the theme provider has applied the dark theme) only renders after the
 * client has hydrated. Before mount we emit a same-sized empty span — this
 * guarantees the server-rendered HTML and the first client render produce
 * the same markup, so React can reconcile without a hydration warning.
 */
export function BrandMark({ size = 28, className }: BrandMarkProps) {
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <span
        aria-hidden="true"
        className={cn("inline-block", className)}
        style={{ width: size, height: size }}
      />
    );
  }

  // Regular heptagon, circumradius 9, center (12,12), top vertex up.
  const points = [
    [12.0, 3.0],
    [19.04, 6.39],
    [20.77, 14.0],
    [15.91, 20.11],
    [8.09, 20.11],
    [3.23, 14.0],
    [4.96, 6.39],
  ];
  const path =
    "M " +
    points.map(([x, y]) => `${x} ${y}`).join(" L ") +
    " Z";
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <path
        d={path}
        stroke="var(--accent, #A8C090)"
        strokeWidth={1.75}
        strokeLinejoin="round"
      />
      <circle cx={12} cy={3} r={1.6} fill="var(--foreground, #E8E0C9)" />
    </svg>
  );
}

interface BrandWordmarkProps {
  size?: number;
  className?: string;
}

/**
 * The wordmark: "Tevet" in Caudex (foreground) + "-7" where the "7" is in the
 * accent color. Uses the `font-heading` class (Caudex serif).
 */
export function BrandWordmark({ size = 18, className }: BrandWordmarkProps) {
  return (
    <span
      className={cn("font-heading font-medium tracking-tight", className)}
      style={{ fontSize: `${size}px`, color: "var(--foreground)" }}
    >
      Tevet<span style={{ color: "var(--muted-foreground)" }}>-</span>
      <span style={{ color: "var(--accent)" }}>7</span>
    </span>
  );
}

interface BrandLogoProps {
  size?: number;
  className?: string;
}

/** BrandMark + BrandWordmark side by side with a small gap. */
export function BrandLogo({ size = 26, className }: BrandLogoProps) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <BrandMark size={size} />
      <BrandWordmark size={Math.round(size * 0.7)} />
    </div>
  );
}
