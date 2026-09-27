import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Capacity Lab — Portfolio Capacity Dashboard",
  description: "Interactive long-only equity capacity analysis with liquidity migration, market impact and alpha decay.",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
  openGraph: {
    title: "Capacity Lab",
    description: "Explore portfolio capacity, liquidity migration and alpha decay.",
    images: ["/capacity-lab-og.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
