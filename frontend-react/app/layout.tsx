import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";

export const metadata: Metadata = {
  title: "IntelliStock — NSE/BSE Market Intelligence",
  description: "LSTM-powered price forecasting and trading signals for Indian equities.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="style-nova dark h-full antialiased">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap"
          rel="stylesheet"
        />
        <style>{`
          :root {
            --font-inter: 'Inter', ui-sans-serif, system-ui, sans-serif;
            --font-space-grotesk: 'Space Grotesk', ui-sans-serif, system-ui, sans-serif;
          }
        `}</style>
      </head>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
