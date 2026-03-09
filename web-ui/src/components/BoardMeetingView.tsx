"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Badge } from "@/components/ui/badge";
import { CheckCircle } from "lucide-react";
import type { BoardMeetingResponse } from "@/lib/types";

interface BoardMeetingViewProps {
  data: BoardMeetingResponse;
}

export default function BoardMeetingView({ data }: BoardMeetingViewProps) {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      {/* Left: Agent contributions */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-[var(--text-secondary)] uppercase tracking-wider">
          Agent Contributions
        </h3>
        <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-2">
          {data.participants.map((agent) => {
            const contribution = data.contributions[agent];
            if (!contribution) return null;
            return (
              <div
                key={agent}
                className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4"
              >
                <div className="mb-2 flex items-center gap-2">
                  <Badge variant="secondary">{agent}</Badge>
                </div>
                <div className="markdown-body text-sm">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {contribution}
                  </ReactMarkdown>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Right: Synthesis + action items */}
      <div className="space-y-4">
        <div>
          <h3 className="mb-2 text-sm font-medium text-[var(--text-secondary)] uppercase tracking-wider">
            Synthesis
          </h3>
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
            <div className="markdown-body text-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {data.synthesis}
              </ReactMarkdown>
            </div>
          </div>
        </div>

        {data.action_items.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-medium text-[var(--text-secondary)] uppercase tracking-wider">
              Action Items
            </h3>
            <div className="space-y-2">
              {data.action_items.map((item, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-3"
                >
                  <CheckCircle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--accent)]" />
                  <span className="text-sm text-[var(--text-primary)]">
                    {item}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
