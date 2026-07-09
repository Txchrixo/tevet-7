import type { Metadata } from "next";
import "./globals.css";
import { AuthSessionProvider } from "@/components/providers/auth-session-provider";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster as SonnerToaster } from "@/components/ui/sonner";

export const metadata: Metadata = {
  title: "Tevet-7 - Configurable AI Agent Platform",
  description:
    "Tevet-7 - plateforme d'agents IA configurable. Premier tenant : Drive Producteur. Chaque question est sécurisée par un scope tenant.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fr" className="dark" suppressHydrationWarning>
      <head>
        <link rel="manifest" href="/manifest.json" />
        <meta name="theme-color" content="#2D3A2F" />
        <link rel="icon" href="/icon.svg" type="image/svg+xml" />
        <link rel="apple-touch-icon" href="/icon.svg" />
        {/*
          Web fonts loaded NON-BLOCKING. Two render-blocking external
          <link rel="stylesheet"> used to stall first paint (and hang for
          seconds on restricted networks where fonts.googleapis.com is
          unreachable). We now inject a single combined stylesheet from a
          tiny inline script AFTER the parser is past the head, so the page
          paints instantly with the system fallback stack (globals.css) and
          upgrades to Caudex/Manrope when - and only if - they arrive.
          A <noscript> keeps the fonts for JS-disabled clients.
        */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){var l=document.createElement('link');" +
              "l.rel='stylesheet';l.media='print';" +
              "l.href='https://fonts.googleapis.com/css2?family=Caudex:wght@400;500;600&family=Manrope:wght@400;500&display=swap';" +
              "l.onload=function(){l.media='all'};" +
              "document.head.appendChild(l);})();",
          }}
        />
        <noscript>
          {/* eslint-disable-next-line @next/next/no-page-custom-font */}
          <link
            rel="stylesheet"
            href="https://fonts.googleapis.com/css2?family=Caudex:wght@400;500;600&family=Manrope:wght@400;500&display=swap"
          />
        </noscript>
      </head>
      <body className="font-body antialiased bg-background text-foreground">
        <AuthSessionProvider>
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
        </AuthSessionProvider>
      </body>
    </html>
  );
}
