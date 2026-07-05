"use client";

/**
 * Scroll-reveal animation primitives for the landing page.
 *
 * Design philosophy: each section gets a motion metaphor tied to its content
 * meaning, not a generic fade-in-up. All animations are bidirectional
 * (replay when scrolling back into view) and respect prefers-reduced-motion.
 *
 * Metaphors:
 *   - SocialProof:   blurFocus  ("credibility comes into focus")
 *   - Problem:       slideLeft  ("tension drags in, heavier")
 *   - Solution:      slideRight ("resolution slides in, lighter")
 *   - Features:      cardRise   ("capabilities assemble, diagonal cascade")
 *   - HowItWorks:    stepPop    ("process unfolds sequentially")
 *   - UseCases:      cardPlace  ("cards placed on a table, 3D tilt")
 *   - Pricing:       tierElevate("recommendation rises above")
 *   - FAQ:           hazeClear  ("questions surface from haze")
 *   - FinalCTA:      heptagonDraw + wordReveal ("the call crystallizes")
 */

import * as React from "react";
import {
  motion,
  useInView,
  type Variants,
  type Transition,
} from "framer-motion";

// ─────────────────────────────────────────────────────────────────────────────
// Accessibility: respect prefers-reduced-motion
// ─────────────────────────────────────────────────────────────────────────────

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = React.useState(false);
  React.useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const handler = () => setReduced(mq.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);
  return reduced;
}

// ─────────────────────────────────────────────────────────────────────────────
// Easing curves (custom, not the default "easeOut" everywhere)
// ─────────────────────────────────────────────────────────────────────────────

// Smooth deceleration — used for most reveals
const EASE_OUT_EXPO: Transition["ease"] = [0.16, 1, 0.3, 1];
// Soft overshoot — used for "pop" elements (circles, badges)
const EASE_SOFT_BACK: Transition["ease"] = [0.34, 1.56, 0.64, 1];

// ─────────────────────────────────────────────────────────────────────────────
// Variant library — each named after its metaphor
// ─────────────────────────────────────────────────────────────────────────────

/** Blur-to-focus: element materializes from a blur. */
export const blurFocus: Variants = {
  hidden: { opacity: 0, filter: "blur(10px)" },
  visible: {
    opacity: 1,
    filter: "blur(0px)",
    transition: { duration: 0.7, ease: EASE_OUT_EXPO },
  },
};

/** Slide from left with a slight counter-clockwise tilt — "heavier, dragging in". */
export const slideFromLeft: Variants = {
  hidden: { opacity: 0, x: -48, rotate: -1.2 },
  visible: {
    opacity: 1,
    x: 0,
    rotate: 0,
    transition: { duration: 0.65, ease: EASE_OUT_EXPO },
  },
};

/** Slide from right with a slight clockwise tilt — "lighter, resolving". */
export const slideFromRight: Variants = {
  hidden: { opacity: 0, x: 48, rotate: 1.2 },
  visible: {
    opacity: 1,
    x: 0,
    rotate: 0,
    transition: { duration: 0.65, ease: EASE_OUT_EXPO },
  },
};

/** Card rises + scales in — used in the Features grid. */
export const cardRise: Variants = {
  hidden: { opacity: 0, y: 28, scale: 0.96 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.55, ease: EASE_OUT_EXPO },
  },
};

/** Step circle pops in with a soft overshoot — used in HowItWorks. */
export const stepPop: Variants = {
  hidden: { opacity: 0, scale: 0 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.5, ease: EASE_SOFT_BACK },
  },
};

/** Card placed on a table — 3D tilt from rotateX. Used in UseCases. */
export const cardPlace: Variants = {
  hidden: { opacity: 0, y: 34, rotateX: 10 },
  visible: {
    opacity: 1,
    y: 0,
    rotateX: 0,
    transition: { duration: 0.6, ease: EASE_OUT_EXPO },
  },
};

/** Pricing tier rises — side tiers. */
export const tierRise: Variants = {
  hidden: { opacity: 0, y: 24 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.55, ease: EASE_OUT_EXPO },
  },
};

/** Pricing tier elevates — the highlighted (Pro) tier rises higher + scales up. */
export const tierElevate: Variants = {
  hidden: { opacity: 0, y: 48, scale: 0.94 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1.03,
    transition: { duration: 0.65, ease: EASE_OUT_EXPO, delay: 0.1 },
  },
};

/** Surface from haze — FAQ items clear from a slight blur. */
export const hazeClear: Variants = {
  hidden: { opacity: 0, y: 18, filter: "blur(4px)" },
  visible: {
    opacity: 1,
    y: 0,
    filter: "blur(0px)",
    transition: { duration: 0.5, ease: EASE_OUT_EXPO },
  },
};

/** Simple fade-up — used for footers and subtle elements. */
export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: EASE_OUT_EXPO },
  },
};

/** Scale-in — used for badges, buttons, small marks. */
export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.8 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.45, ease: EASE_SOFT_BACK },
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// Stagger container factory
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Builds a parent variant that staggers its children's reveals.
 * Use <RevealGroup variants={staggerChildren(0.08)}> with <RevealItem> children.
 */
export function staggerChildren(
  stagger: number,
  delayChildren = 0,
): Variants {
  return {
    hidden: {},
    visible: {
      transition: { staggerChildren: stagger, delayChildren },
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Reveal components
// ─────────────────────────────────────────────────────────────────────────────

interface RevealProps {
  children: React.ReactNode;
  /** Variant name from the library above, or a custom Variants object. */
  variants?: Variants;
  className?: string;
  /** Delay before the reveal starts (seconds). */
  delay?: number;
  /** Fraction of the element that must be visible to trigger (0-1). */
  amount?: number;
  /** HTML element / motion component tag. Defaults to "div". */
  as?: "div" | "section" | "li" | "span" | "tr";
  style?: React.CSSProperties;
}

/**
 * Single-element scroll reveal. Animates from `hidden` → `visible` when the
 * element scrolls into view, and reverses when it leaves (bidirectional).
 */
export function Reveal({
  children,
  variants = fadeUp,
  className,
  delay = 0,
  amount = 0.25,
  as = "div",
  style,
}: RevealProps) {
  const reduced = usePrefersReducedMotion();
  if (reduced) {
    const Tag = as as React.ElementType;
    return (
      <Tag className={className} style={style}>
        {children}
      </Tag>
    );
  }
  const MotionTag = motion[as] as typeof motion.div;
  return (
    <MotionTag
      className={className}
      style={style}
      variants={variants}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: false, amount }}
      transition={{ delay }}
    >
      {children}
    </MotionTag>
  );
}

/**
 * Stagger container. Wrap <RevealItem> children to cascade their reveals.
 * The parent itself doesn't animate — it only orchestrates child timing.
 */
export function RevealGroup({
  children,
  variants,
  className,
  amount = 0.25,
  style,
}: {
  children: React.ReactNode;
  variants: Variants;
  className?: string;
  amount?: number;
  style?: React.CSSProperties;
}) {
  const reduced = usePrefersReducedMotion();
  if (reduced) {
    return (
      <div className={className} style={style}>
        {children}
      </div>
    );
  }
  return (
    <motion.div
      className={className}
      style={style}
      variants={variants}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: false, amount }}
    >
      {children}
    </motion.div>
  );
}

/**
 * Stagger child. Must be inside a <RevealGroup>. Inherits the parent's
 * stagger timing. Use `variants` to pick which motion metaphor applies.
 */
export function RevealItem({
  children,
  variants = fadeUp,
  className,
  style,
}: {
  children: React.ReactNode;
  variants?: Variants;
  className?: string;
  style?: React.CSSProperties;
}) {
  const reduced = usePrefersReducedMotion();
  if (reduced) {
    return (
      <div className={className} style={style}>
        {children}
      </div>
    );
  }
  return (
    <motion.div className={className} style={style} variants={variants}>
      {children}
    </motion.div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// HeptagonDraw — animated SVG heptagon path-draw for the FinalCTA
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Draws the Tevet-7 heptagon outline by animating strokeDashoffset from
 * full path length → 0. Re-triggers on every scroll into view.
 * The top-vertex node (filled circle) fades in after the outline completes.
 */
export function HeptagonDraw({
  size = 48,
  className,
}: {
  size?: number;
  className?: string;
}) {
  const ref = React.useRef<SVGSVGElement>(null);
  const inView = useInView(ref, { once: false, amount: 0.5 });
  const reduced = usePrefersReducedMotion();

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
    "M " + points.map(([x, y]) => `${x} ${y}`).join(" L ") + " Z";
  // Approximate perimeter of this heptagon (7 sides ~ 7 * 8.4 = ~58.8)
  const pathLen = 59;

  return (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <motion.path
        d={path}
        stroke="var(--accent, #A8C090)"
        strokeWidth={1.75}
        strokeLinejoin="round"
        initial={reduced ? undefined : { strokeDasharray: pathLen, strokeDashoffset: pathLen }}
        animate={
          reduced
            ? undefined
            : inView
              ? { strokeDashoffset: 0 }
              : { strokeDashoffset: pathLen }
        }
        transition={{ duration: 1.4, ease: EASE_OUT_EXPO }}
      />
      <motion.circle
        cx={12}
        cy={3}
        r={1.6}
        fill="var(--foreground, #E8E0C9)"
        initial={reduced ? undefined : { opacity: 0, scale: 0 }}
        animate={
          reduced
            ? undefined
            : inView
              ? { opacity: 1, scale: 1 }
              : { opacity: 0, scale: 0 }
        }
        transition={{ duration: 0.4, ease: EASE_SOFT_BACK, delay: 1.1 }}
        style={{ transformOrigin: "12px 3px" }}
      />
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// WordReveal — splits text into words and reveals sequentially
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Splits `text` into words and reveals them one-by-one with a slight y-rise.
 * Used for the FinalCTA headline. Words are wrapped in spans with
 * overflow-hidden so the rise feels like words emerging from behind a mask.
 */
export function WordReveal({
  text,
  className,
  delay = 0,
  stagger = 0.06,
}: {
  text: string;
  className?: string;
  delay?: number;
  stagger?: number;
}) {
  const reduced = usePrefersReducedMotion();
  const words = text.split(" ");
  if (reduced) {
    return <span className={className}>{text}</span>;
  }
  return (
    <motion.span
      className={className}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: false, amount: 0.5 }}
      variants={{ visible: { transition: { staggerChildren: stagger, delayChildren: delay } } }}
    >
      {words.map((word, i) => (
        <span
          key={i}
          className="inline-block overflow-hidden align-bottom"
          style={{ paddingBottom: "0.1em", marginBottom: "-0.1em" }}
        >
          <motion.span
            className="inline-block"
            variants={{
              hidden: { y: "110%", opacity: 0 },
              visible: {
                y: 0,
                opacity: 1,
                transition: { duration: 0.55, ease: EASE_OUT_EXPO },
              },
            }}
          >
            {word}
            {i < words.length - 1 ? "\u00A0" : ""}
          </motion.span>
        </span>
      ))}
    </motion.span>
  );
}
