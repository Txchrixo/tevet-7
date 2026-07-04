/**
 * Tevet-7 application constants — single source of truth.
 *
 * Anything user-visible that names the app, its tagline, or the current
 * prototype phase MUST be imported from here so a future rename or phase
 * bump only touches one file. Hardcoding these strings in component JSX
 * is forbidden by the design-system lint.
 */

/** Brand name — shown in headers, footers, the loading screen, document title. */
export const APP_NAME = "Tevet-7";

/** One-line product tagline (French). Shown in the footer + auth screen. */
export const APP_TAGLINE = "Plateforme d'agents IA configurable";

/**
 * Current prototype phase label — bumped as features ship. Rendered in the
 * header phase badge, the chat-dock caption, and the auth-screen footer.
 *
 * Keep the "Phase X" prefix intact so the badge reads naturally.
 */
export const APP_PHASE = "Phase 6d";
