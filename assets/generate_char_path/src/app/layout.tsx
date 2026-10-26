import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Generate Character Path",
  description: "Create and manage character vectors on a 17×17 grid."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
