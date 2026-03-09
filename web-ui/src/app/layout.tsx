import type { Metadata } from "next";
import NavBar from "@/components/NavBar";
import ToastContainer from "@/components/Toast";
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
      <body className="antialiased">
        <div className="flex h-screen flex-col bg-[var(--bg-primary)]">
          <NavBar />
          <main className="flex flex-1 flex-col overflow-hidden">
            {children}
          </main>
          <ToastContainer />
        </div>
      </body>
    </html>
  );
}
