"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  MessageSquare,
  BarChart3,
  Users,
  ClipboardList,
} from "lucide-react";
import { cn } from "@/lib/utils";
import HealthDot from "./HealthDot";

const NAV_ITEMS = [
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/crm", label: "CRM", icon: BarChart3 },
  { href: "/board-meeting", label: "Boardroom", icon: Users },
  { href: "/corrections", label: "Corrections", icon: ClipboardList },
];

export default function NavBar() {
  const pathname = usePathname();

  return (
    <header className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg-primary)] px-6 py-2.5">
      <div className="flex items-center gap-6">
        <Link href="/chat" className="flex items-center gap-2">
          <h1 className="text-lg font-semibold tracking-tight text-[var(--text-primary)]">
            Ira
          </h1>
          <span className="text-xs text-[var(--text-secondary)]">
            Machinecraft AI
          </span>
        </Link>

        <nav className="flex items-center gap-1">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-[var(--bg-tertiary)] text-[var(--text-primary)]"
                    : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]",
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>
      </div>

      <HealthDot />
    </header>
  );
}
