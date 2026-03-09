"use client";

import { useState } from "react";
import { Search, Loader2, Mail, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { searchEmails, fetchEmailThread } from "@/lib/api";
import type { EmailResult } from "@/lib/types";
import ReactMarkdown from "react-markdown";

export default function EmailSearch() {
  const [from, setFrom] = useState("");
  const [subject, setSubject] = useState("");
  const [query, setQuery] = useState("");
  const [after, setAfter] = useState("");
  const [before, setBefore] = useState("");
  const [results, setResults] = useState<EmailResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedThread, setExpandedThread] = useState<string | null>(null);
  const [threadMessages, setThreadMessages] = useState<
    Array<{ from: string; date: string; body: string }>
  >([]);
  const [loadingThread, setLoadingThread] = useState(false);

  async function handleSearch() {
    setSearching(true);
    setError(null);
    setResults([]);
    setExpandedThread(null);
    try {
      const data = await searchEmails({
        from_address: from || undefined,
        subject: subject || undefined,
        query: query || undefined,
        after: after || undefined,
        before: before || undefined,
        max_results: 20,
      });
      setResults(data.emails);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setSearching(false);
    }
  }

  async function toggleThread(threadId: string) {
    if (expandedThread === threadId) {
      setExpandedThread(null);
      return;
    }
    setExpandedThread(threadId);
    setLoadingThread(true);
    try {
      const data = await fetchEmailThread(threadId);
      setThreadMessages(data.messages ?? []);
    } catch {
      setThreadMessages([]);
    } finally {
      setLoadingThread(false);
    }
  }

  return (
    <div>
      {/* Search form */}
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <input
          value={from}
          onChange={(e) => setFrom(e.target.value)}
          placeholder="From (email or domain)"
          className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder-[var(--text-secondary)] outline-none focus:border-[var(--accent)]"
        />
        <input
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="Subject keyword"
          className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder-[var(--text-secondary)] outline-none focus:border-[var(--accent)]"
        />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Free-form query"
          className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder-[var(--text-secondary)] outline-none focus:border-[var(--accent)]"
        />
        <input
          type="date"
          value={after}
          onChange={(e) => setAfter(e.target.value)}
          placeholder="After"
          className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
        />
        <input
          type="date"
          value={before}
          onChange={(e) => setBefore(e.target.value)}
          placeholder="Before"
          className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
        />
        <Button onClick={handleSearch} disabled={searching}>
          {searching ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Search className="h-4 w-4" />
          )}
          Search
        </Button>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-lg border border-red-600/30 bg-red-600/10 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Results */}
      {results.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-[var(--text-secondary)]">
            {results.length} result{results.length !== 1 ? "s" : ""}
          </p>
          {results.map((email) => (
            <div key={email.id}>
              <button
                onClick={() => toggleThread(email.thread_id)}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4 text-left transition-colors hover:bg-[var(--bg-tertiary)]"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3 min-w-0">
                    <Mail className="mt-0.5 h-4 w-4 shrink-0 text-[var(--text-secondary)]" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-[var(--text-primary)] truncate">
                        {email.subject || "(no subject)"}
                      </p>
                      <p className="text-xs text-[var(--text-secondary)]">
                        {email.from}
                      </p>
                      <p className="mt-1 text-xs text-[var(--text-secondary)] line-clamp-2">
                        {email.body?.slice(0, 200)}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-[var(--text-secondary)] whitespace-nowrap">
                      {new Date(email.date).toLocaleDateString()}
                    </span>
                    {expandedThread === email.thread_id ? (
                      <ChevronUp className="h-4 w-4 text-[var(--text-secondary)]" />
                    ) : (
                      <ChevronDown className="h-4 w-4 text-[var(--text-secondary)]" />
                    )}
                  </div>
                </div>
              </button>

              {/* Expanded thread */}
              {expandedThread === email.thread_id && (
                <div className="ml-7 mt-1 space-y-2 rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] p-4">
                  {loadingThread ? (
                    <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Loading thread...
                    </div>
                  ) : threadMessages.length > 0 ? (
                    threadMessages.map((msg, i) => (
                      <div
                        key={i}
                        className="border-b border-[var(--border)] pb-3 last:border-0 last:pb-0"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-medium text-[var(--text-primary)]">
                            {msg.from}
                          </span>
                          <span className="text-xs text-[var(--text-secondary)]">
                            {new Date(msg.date).toLocaleString()}
                          </span>
                        </div>
                        <div className="text-xs text-[var(--text-secondary)] markdown-body">
                          <ReactMarkdown>{msg.body}</ReactMarkdown>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="text-xs text-[var(--text-secondary)]">
                      No messages in thread
                    </p>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!searching && results.length === 0 && !error && (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <Mail className="mb-3 h-8 w-8 text-[var(--text-secondary)]" />
          <p className="text-sm text-[var(--text-secondary)]">
            Search emails by sender, subject, or keyword
          </p>
        </div>
      )}
    </div>
  );
}
