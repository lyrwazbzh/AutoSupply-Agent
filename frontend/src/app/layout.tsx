import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AutoSupply Agent",
  description: "新能源车智采链",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
