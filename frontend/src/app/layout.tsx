import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "車両AI問診チャット",
  description: "車両トラブル診断AIアシスタント",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja">
      <body className="antialiased">{children}</body>
    </html>
  );
}
