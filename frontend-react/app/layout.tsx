import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";

export const metadata: Metadata = {
  title: "IntelliStock — NSE/BSE Market Intelligence",
  description: "Price ranges, risk tools and alerts for Indian equities. End-of-day data, not advice.",
  icons: { apple: "/apple-touch-icon.png" },
  appleWebApp: { capable: true, title: "IntelliStock", statusBarStyle: "black-translucent" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover", // lets env(safe-area-inset-*) work behind notches and home bars
  colorScheme: "dark",
  themeColor: "#0a0a10",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="style-nova dark h-full antialiased">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Syne:wght@600;700;800&display=swap"
          rel="stylesheet"
        />
        <style>{`
          :root {
            --font-plex-sans: 'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif;
            --font-plex-mono: 'IBM Plex Mono', ui-monospace, monospace;
            --font-syne: 'Syne', ui-sans-serif, system-ui, sans-serif;
          }
        `}</style>
      </head>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
