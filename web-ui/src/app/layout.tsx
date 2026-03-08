import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ira — Machinecraft AI",
  description: "Talk to Ira, the AI that runs Machinecraft.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
