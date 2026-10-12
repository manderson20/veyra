// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { BRANDING } from "@/components/Brand";
import { ToastProvider } from "@/components/ui";
import { SessionProvider } from "@/hooks/useSession";
import { THEME_BOOTSTRAP } from "@/lib/theme";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: { default: "Veyra", template: "%s · Veyra" },
  description: "Veyra — Open Communications Platform",
  icons: {
    icon: [
      { url: BRANDING.favicon, sizes: "any" },
      { url: BRANDING.favicon32, type: "image/png", sizes: "32x32" },
    ],
    apple: BRANDING.appleTouchIcon,
  },
  manifest: "/manifest.webmanifest",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#071629" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Applies the saved theme before first paint (prevents a flash of the wrong theme). */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body>
        <ToastProvider>
          <SessionProvider>{children}</SessionProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
