"use client"

import { useTheme } from "next-themes"
import { Toaster as Sonner, ToasterProps } from "sonner"

/**
 * Tevet-7 Sonner toaster.
 *
 * The default sonner styling pulls from Radix color tokens (gray2 / gray11)
 * that we don't define in this design system - those tokens resolve to
 * literal black/white, which is why the close button rendered as a black X
 * on the dark-green toast background.
 *
 * To fix it we:
 *   1. Pin every toast background/border/text CSS variable to the Tevet-7
 *      palette via `--normal-bg` / `--normal-border` / `--normal-text`.
 *   2. Pass explicit Tailwind classes on the toaster root so the toast,
 *      its description, and its close button all inherit palette colors.
 *   3. Force the close button to `text-muted-foreground` (visible on the
 *      dark-green toast) with a `hover:text-foreground` affordance - the
 *      matching rule lives in `globals.css` under `.toaster [data-close-button]`
 *      because sonner injects the button deep enough that Tailwind variants
 *      from this component can't reliably reach it.
 */
const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = "system" } = useTheme()

  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group toasts-tevet7"
      toastOptions={{
        classNames: {
          toast:
            "group toast-tevet7 !bg-background !text-foreground !border !border-border",
          description: "!text-muted-foreground",
          actionButton: "!bg-primary !text-primary-foreground",
          cancelButton: "!bg-secondary !text-muted-foreground",
          closeButton:
            "!bg-transparent !border !border-border !text-muted-foreground hover:!text-foreground",
        },
      }}
      style={
        {
          "--normal-bg": "var(--background)",
          "--normal-text": "var(--foreground)",
          "--normal-border": "var(--border)",
          "--normal-border-radius": "var(--radius)",
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
