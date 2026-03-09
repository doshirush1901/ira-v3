"use client";

import { useState, useEffect } from "react";
import { RefreshCw, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Correction {
  id: number;
  entity: string;
  category: string;
  severity: string;
  old_value: string;
  new_value: string;
  source: string;
  created_at: string;
  status: string;
}

interface Stats {
  total: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  by_severity: Record<string, number>;
}

const SEVERITY_VARIANT: Record<string, "destructive" | "warning" | "success" | "secondary"> = {
  CRITICAL: "destructive",
  HIGH: "destructive",
  MEDIUM: "warning",
  LOW: "success",
};

export default function CorrectionsPage() {
  const [corrections, setCorrections] = useState<Correction[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (filter) params.set("status", filter);
      const res = await fetch(`${API_URL}/api/corrections?${params}`);
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      const data = await res.json();
      setCorrections(data.corrections);
      setStats(data.stats);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [filter]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className="mx-auto max-w-5xl">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-[var(--text-primary)]">
              Corrections Log
            </h1>
            <p className="text-sm text-[var(--text-secondary)]">
              Corrections submitted by the team that train Nemesis
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        {/* Stats cards */}
        {stats && (
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Total" value={stats.total} />
            <StatCard
              label="Pending"
              value={stats.by_status?.pending ?? 0}
            />
            <StatCard
              label="Processed"
              value={stats.by_status?.processed ?? 0}
            />
            <StatCard
              label="High/Critical"
              value={
                (stats.by_severity?.HIGH ?? 0) +
                (stats.by_severity?.CRITICAL ?? 0)
              }
            />
          </div>
        )}

        {/* Filter tabs */}
        <div className="mb-4 flex gap-2">
          {[null, "pending", "processed"].map((f) => (
            <button
              key={f ?? "all"}
              onClick={() => setFilter(f)}
              className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
                filter === f
                  ? "bg-[var(--bg-tertiary)] text-[var(--text-primary)]"
                  : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]"
              }`}
            >
              {f ?? "All"}
            </button>
          ))}
        </div>

        {/* Error state */}
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-red-600/30 bg-red-600/10 px-4 py-3 text-sm text-red-400">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        {/* Table */}
        {!error && (
          <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--bg-tertiary)]">
                  <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
                    #
                  </th>
                  <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
                    Entity
                  </th>
                  <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
                    Correction
                  </th>
                  <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
                    Severity
                  </th>
                  <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
                    Category
                  </th>
                  <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
                    Status
                  </th>
                  <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
                    Date
                  </th>
                </tr>
              </thead>
              <tbody>
                {corrections.length === 0 && !loading && (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-4 py-8 text-center text-[var(--text-secondary)]"
                    >
                      No corrections found
                    </td>
                  </tr>
                )}
                {corrections.map((c) => (
                  <tr
                    key={c.id}
                    className="border-b border-[var(--border)] hover:bg-[var(--bg-secondary)] transition-colors"
                  >
                    <td className="px-4 py-2.5 text-[var(--text-secondary)]">
                      {c.id}
                    </td>
                    <td className="px-4 py-2.5 font-medium text-[var(--text-primary)]">
                      {c.entity}
                    </td>
                    <td className="max-w-xs truncate px-4 py-2.5 text-[var(--text-primary)]">
                      {c.old_value && (
                        <span className="text-[var(--text-secondary)] line-through mr-2">
                          {c.old_value}
                        </span>
                      )}
                      {c.new_value}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge variant={SEVERITY_VARIANT[c.severity] ?? "secondary"}>
                        {c.severity}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-[var(--text-secondary)]">
                      {c.category}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge
                        variant={c.status === "pending" ? "warning" : "success"}
                      >
                        {c.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-[var(--text-secondary)] whitespace-nowrap">
                      {new Date(c.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-3">
      <p className="text-xs text-[var(--text-secondary)]">{label}</p>
      <p className="text-2xl font-semibold text-[var(--text-primary)]">
        {value}
      </p>
    </div>
  );
}
