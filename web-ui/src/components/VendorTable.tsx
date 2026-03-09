"use client";

import { useVendorsOverdue } from "@/lib/swr";
import { Loader2, AlertCircle, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export default function VendorTable() {
  const { data, error, isLoading } = useVendorsOverdue();

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
        Failed to load vendor payables: {error.message}
      </div>
    );
  }

  const overdue = data?.overdue ?? [];

  if (overdue.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <AlertTriangle className="mb-3 h-8 w-8 text-[var(--text-secondary)]" />
        <p className="text-sm text-[var(--text-secondary)]">
          No overdue payables
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--border)] bg-[var(--bg-tertiary)]">
            <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
              Vendor
            </th>
            <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
              Invoice
            </th>
            <th className="px-4 py-2.5 text-right font-medium text-[var(--text-secondary)]">
              Amount
            </th>
            <th className="px-4 py-2.5 text-left font-medium text-[var(--text-secondary)]">
              Due Date
            </th>
            <th className="px-4 py-2.5 text-right font-medium text-[var(--text-secondary)]">
              Days Overdue
            </th>
          </tr>
        </thead>
        <tbody>
          {overdue.map((item, i) => (
            <tr
              key={item.id ?? i}
              className={`border-b border-[var(--border)] transition-colors hover:bg-[var(--bg-secondary)] ${
                item.days_overdue >= 30 ? "bg-red-600/5" : ""
              }`}
            >
              <td className="px-4 py-2.5 font-medium text-[var(--text-primary)]">
                {item.vendor_name}
              </td>
              <td className="px-4 py-2.5 text-[var(--text-secondary)]">
                {item.invoice_number ?? "—"}
              </td>
              <td className="px-4 py-2.5 text-right font-mono text-[var(--text-primary)]">
                {item.currency ?? "$"}
                {typeof item.amount === "number"
                  ? item.amount.toLocaleString()
                  : item.amount}
              </td>
              <td className="px-4 py-2.5 text-[var(--text-secondary)]">
                {item.due_date
                  ? new Date(item.due_date).toLocaleDateString()
                  : "—"}
              </td>
              <td className="px-4 py-2.5 text-right">
                <Badge
                  variant={item.days_overdue >= 30 ? "destructive" : "warning"}
                >
                  {item.days_overdue}d
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
