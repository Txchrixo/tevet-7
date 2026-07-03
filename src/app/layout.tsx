import type { Metadata } from "next";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster as SonnerToaster } from "@/components/ui/sonner";

export const metadata: Metadata = {
  title: "Tevet-7 — Producer Copilot (Drive Producteur)",
  description:
    "Tevet-7 — plateforme d'agents IA configurable. Producer Copilot Phase 0 pour Drive Producteur : agent SQL scopé par tenant avec row-level security visible.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fr" className="dark" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        {/* eslint-disable-next-line @next/next/no-page-custom-font -- Tevet-7 design system loads Caudex + Manrope via <link> tags per spec (no next/font). */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Caudex:wght@400;500;600&display=swap"
        />
        {/* eslint-disable-next-line @next/next/no-page-custom-font -- see above. */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500&display=swap"
        />
      </head>
      <body className="font-body antialiased bg-background text-foreground">
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          forcedTheme="dark"
          enableSystem={false}
          disableTransitionOnChange
        >
          {children}
          <SonnerToaster position="top-center" closeButton />
        </ThemeProvider>
      </body>
    </html>
  );
}
