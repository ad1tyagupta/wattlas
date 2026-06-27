import type { Metadata } from "next";
import {
  IBM_Plex_Mono,
  IBM_Plex_Sans,
  IBM_Plex_Sans_Condensed,
} from "next/font/google";

import "./globals.css";

const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const plexCondensed = IBM_Plex_Sans_Condensed({
  variable: "--font-plex-condensed",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Wattlas · Global Infrastructure Opportunity Radar",
  description:
    "A daily-refreshed, explainable view of global electricity demand from data centres and water infrastructure.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${plexSans.variable} ${plexCondensed.variable} ${plexMono.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
