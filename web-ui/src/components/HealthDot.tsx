"use client";

import useSWR from "swr";
import { fetchHealth } from "@/lib/api";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const STATUS_COLORS: Record<string, string> = {
  ok: "bg-emerald-500",
  degraded: "bg-amber-500",
  unhealthy: "bg-red-500",
};

export default function HealthDot() {
  const { data, error } = useSWR("health", fetchHealth, {
    refreshInterval: 30_000,
    errorRetryCount: 2,
  });

  const status = error ? "offline" : data?.status ?? "loading";
  const colorClass = error
    ? "bg-red-500"
    : STATUS_COLORS[data?.status ?? ""] ?? "bg-zinc-500";

  const serviceList = data?.services
    ? Object.entries(data.services)
        .map(([name, s]) => `${name}: ${s.status}`)
        .join("\n")
    : "";

  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex items-center gap-2 cursor-default">
            <div className={`h-2 w-2 rounded-full ${colorClass}`} />
            <span className="text-xs text-[var(--text-secondary)]">
              {status}
            </span>
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          <pre className="text-xs whitespace-pre">
            {serviceList || (error ? "Cannot reach Ira backend" : "Loading...")}
          </pre>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
