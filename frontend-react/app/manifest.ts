import type { MetadataRoute } from "next";

// Lets people add IntelliStock to a phone's home screen. There is no offline mode on purpose:
// a stale cached price is worse than an honest "no connection".
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "IntelliStock",
    short_name: "IntelliStock",
    description: "Price ranges, risk tools and alerts for Indian equities. End-of-day data, not advice.",
    start_url: "/dashboard",
    scope: "/",
    display: "standalone",
    background_color: "#0a0a10",
    theme_color: "#0a0a10",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
