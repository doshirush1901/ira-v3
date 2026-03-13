"use client";

import { usePipeline } from "@/lib/swr";
import { Loader2, AlertCircle, TrendingUp } from "lucide-react";
import DealsByHeat from "@/components/DealsByHeat";

const STAGE_ORDER = [
  "NEW",
  "CONTACTED",
  "ENGAGED",
  "QUALIFIED",
  "PROPOSAL",
  "NEGOTIATION",
  "WON",
  "LOST",
];

const STAGE_COLORS: Record<string, string> = {
  NEW: "border-l-blue-500",
  CONTACTED: "border-l-sky-500",
  ENGAGED: "border-l-cyan-500",
  QUALIFIED: "border-l-emerald-500",
  PROPOSAL: "border-l-amber-500",
  NEGOTIATION: "border-l-orange-500",
  WON: "border-l-green-500",
  LOST: "border-l-red-500",
};

function formatCurrency(value: number): string {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return `$${value.toFixed(0)}`;
}

export default function PipelineBoard() {
  const { data, error, isLoading } = usePipeline();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--text-secondary)]" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-red-600/30 bg-red-600/10 px-4 py-3 text-sm text-red-400">
        <AlertCircle className="h-4 w-4 shrink-0" />
        Failed to load pipeline: {error.message}
      </div>
    );
  }

  const pipeline = data?.pipeline;
  if (!pipeline) return null;

  return (
    <div>
      {/* Summary bar */}
      <div className="mb-4 flex items-center gap-4 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-3">
        <TrendingUp className="h-5 w-5 text-[var(--accent)]" />
        <div>
          <span className="text-sm font-medium text-[var(--text-primary)]">
            {pipeline.total_count} deals
          </span>
          <span className="mx-2 text-[var(--text-secondary)]">&middot;</span>
          <span className="text-sm text-[var(--text-secondary)]">
            {formatCurrency(pipeline.total_value)} total value
          </span>
        </div>
      </div>

      {/* Kanban columns */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        {STAGE_ORDER.map((stage) => {
          const info = pipeline.stages[stage];
          const count = info?.count ?? 0;
          const value = info?.total_value ?? 0;

          return (
            <div
              key={stage}
              className={`rounded-lg border border-[var(--border)] border-l-4 ${STAGE_COLORS[stage] ?? ""} bg-[var(--bg-secondary)] p-3`}
            >
              <p className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
                {stage.replace(/_/g, " ")}
              </p>
              <p className="mt-1 text-2xl font-semibold text-[var(--text-primary)]">
                {count}
              </p>
              <p className="text-xs text-[var(--text-secondary)]">
                {formatCurrency(value)}
              </p>
            </div>
          );
        })}
      </div>

      {/* Deals by heat: sort by hottest (quote sent + reply) to least */}
      <div className="mt-8">
        <h2 className="mb-3 text-sm font-semibold text-[var(--text-primary)]">
          Deals by heat
        </h2>
        <DealsByHeat />
      </div>
    </div>
  );
}
