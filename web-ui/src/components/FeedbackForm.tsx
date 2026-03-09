"use client";

import { useState } from "react";
import { ThumbsUp, ThumbsDown, Send, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { submitFeedback } from "@/lib/api";
import { toast } from "@/components/Toast";

interface FeedbackFormProps {
  previousQuery: string;
  previousResponse: string;
}

export default function FeedbackForm({
  previousQuery,
  previousResponse,
}: FeedbackFormProps) {
  const [showForm, setShowForm] = useState(false);
  const [correction, setCorrection] = useState("");
  const [severity, setSeverity] = useState<"LOW" | "MEDIUM" | "HIGH">("HIGH");
  const [submitted, setSubmitted] = useState<"positive" | "negative" | null>(
    null,
  );
  const [submitting, setSubmitting] = useState(false);

  async function handlePositive() {
    setSubmitted("positive");
    try {
      await submitFeedback({
        correction: "Response was helpful and accurate",
        previous_query: previousQuery,
        previous_response: previousResponse,
        severity: "LOW",
      });
      toast({ type: "success", text: "Thanks for the feedback!" });
    } catch {
      toast({ type: "error", text: "Failed to submit feedback" });
    }
  }

  async function handleNegativeSubmit() {
    if (!correction.trim()) return;
    setSubmitting(true);
    try {
      await submitFeedback({
        correction: correction.trim(),
        previous_query: previousQuery,
        previous_response: previousResponse,
        severity,
      });
      setSubmitted("negative");
      setShowForm(false);
      toast({ type: "success", text: "Correction submitted — Nemesis will learn from this" });
    } catch {
      toast({ type: "error", text: "Failed to submit correction" });
    } finally {
      setSubmitting(false);
    }
  }

  if (submitted) {
    return (
      <div className="flex items-center gap-1 mt-1">
        <span className="text-xs text-[var(--text-secondary)]">
          {submitted === "positive" ? "Helpful" : "Corrected"}
        </span>
      </div>
    );
  }

  return (
    <div className="mt-2">
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={handlePositive}
          title="Helpful"
        >
          <ThumbsUp className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => setShowForm(!showForm)}
          title="Needs correction"
        >
          <ThumbsDown className="h-3.5 w-3.5" />
        </Button>
      </div>

      {showForm && (
        <div className="mt-2 space-y-2 rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] p-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              What was wrong?
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => setShowForm(false)}
            >
              <X className="h-3 w-3" />
            </Button>
          </div>

          <textarea
            value={correction}
            onChange={(e) => setCorrection(e.target.value)}
            placeholder="Describe the correction..."
            rows={2}
            className="w-full resize-none rounded-md border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder-[var(--text-secondary)] outline-none focus:border-[var(--accent)]"
          />

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs text-[var(--text-secondary)]">
                Severity:
              </span>
              {(["LOW", "MEDIUM", "HIGH"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setSeverity(s)}
                  className={`rounded px-2 py-0.5 text-xs transition-colors ${
                    severity === s
                      ? s === "HIGH"
                        ? "bg-red-600/20 text-red-400"
                        : s === "MEDIUM"
                          ? "bg-amber-600/20 text-amber-400"
                          : "bg-emerald-600/20 text-emerald-400"
                      : "text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>

            <Button
              size="sm"
              disabled={!correction.trim() || submitting}
              onClick={handleNegativeSubmit}
            >
              <Send className="h-3 w-3" />
              Submit
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
