"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import BoardMeetingForm from "@/components/BoardMeetingForm";
import BoardMeetingView from "@/components/BoardMeetingView";
import { startBoardMeeting } from "@/lib/api";
import type { BoardMeetingResponse } from "@/lib/types";

export default function BoardMeetingPage() {
  const [result, setResult] = useState<BoardMeetingResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(topic: string, participants: string[]) {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await startBoardMeeting({ topic, participants });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Board meeting failed");
    } finally {
      setLoading(false);
    }
  }

  function handleReset() {
    setResult(null);
    setError(null);
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className="mx-auto max-w-6xl">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">
            The Boardroom
          </h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Convene a multi-agent strategic discussion
          </p>
        </div>

        {!result && !loading && (
          <div className="mx-auto max-w-xl">
            <BoardMeetingForm onSubmit={handleSubmit} loading={loading} />
          </div>
        )}

        {loading && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Loader2 className="mb-4 h-8 w-8 animate-spin text-[var(--accent)]" />
            <p className="text-sm text-[var(--text-secondary)]">
              Board meeting in progress... This may take a minute as each agent
              contributes their perspective.
            </p>
          </div>
        )}

        {error && (
          <div className="mx-auto max-w-xl">
            <div className="mb-4 rounded-lg border border-red-600/30 bg-red-600/10 px-4 py-3 text-sm text-red-400">
              {error}
            </div>
            <Button variant="outline" onClick={handleReset}>
              Try Again
            </Button>
          </div>
        )}

        {result && (
          <div>
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-medium text-[var(--text-primary)]">
                  {result.topic}
                </h2>
                <p className="text-xs text-[var(--text-secondary)]">
                  {result.participants.length} agents participated
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={handleReset}>
                New Meeting
              </Button>
            </div>
            <BoardMeetingView data={result} />
          </div>
        )}
      </div>
    </div>
  );
}
