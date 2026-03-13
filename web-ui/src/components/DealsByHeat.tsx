"use client";

import { useState } from "react";
import { useDeals } from "@/lib/swr";
import { Loader2, AlertCircle, Flame, ThermometerSnowflake } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { DealWithHeat } from "@/lib/types";

function formatCurrency(value: number): string {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return `$${value.toFixed(0)}`;
}

function HeatBadge({ label }: { label: DealWithHeat["heat_label"] }) {
  if (label === "hot") {
    return (
      <Badge className="bg-orange-600/90 text-white border-0 shrink-0">
        <Flame className="h-3 w-3 mr-1" />
        Hot
      </Badge>
    );
  }
  if (label === "warm") {
    return (
      <Badge variant="secondary" className="bg-amber-600/20 text-amber-700 dark:text-amber-400 shrink-0">
        Warm
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-[var(--text-secondary)] shrink-0">
      <ThermometerSnowflake className="h-3 w-3 mr-1" />
      Cold
    </Badge>
  );
}

export default function DealsByHeat() {
  const [sort, setSort] = useState<"heat_desc" | "heat_asc">("heat_desc");
  const { data, error, isLoading } = useDeals(sort);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--text-secondary)]" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-red-600/30 bg-red-600/10 px-4 py-3 text-sm text-red-400">
        <AlertCircle className="h-4 w-4 shrink-0" />
        Failed to load deals: {error.message}
      </div>
    );
  }

  const deals = data?.deals ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-[var(--text-secondary)]">
          Hottest = we sent a quote and customer replied. Sorted by engagement.
        </p>
        <Select
          value={sort}
          onValueChange={(v) => setSort(v as "heat_desc" | "heat_asc")}
        >
          <SelectTrigger className="w-[180px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="heat_desc">Hottest first</SelectItem>
            <SelectItem value="heat_asc">Least hot first</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {deals.length === 0 ? (
        <p className="py-6 text-center text-sm text-[var(--text-secondary)]">
          No deals in CRM yet.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--bg-tertiary)]">
                <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
                  Heat
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
                  Company
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
                  Contact
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
                  Stage
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
                  Machine
                </th>
                <th className="px-4 py-2.5 text-right font-medium text-[var(--text-secondary)]">
                  Value
                </th>
              </tr>
            </thead>
            <tbody>
              {deals.map((d) => (
                <tr
                  key={d.id}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-tertiary)]/50"
                >
                  <td className="px-4 py-2.5">
                    <HeatBadge label={d.heat_label} />
                  </td>
                  <td className="px-4 py-2.5 font-medium text-[var(--text-primary)]">
                    {d.company_name ?? "—"}
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-primary)]">
                    {d.contact_name ?? d.contact_email ?? "—"}
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-secondary)]">
                    {d.stage.replace(/_/g, " ")}
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-secondary)]">
                    {d.machine_model ?? "—"}
                  </td>
                  <td className="px-4 py-2.5 text-right text-[var(--text-secondary)]">
                    {formatCurrency(d.value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
