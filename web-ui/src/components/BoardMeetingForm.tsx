"use client";

import { useState, useEffect } from "react";
import { Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { fetchAgents, type Agent } from "@/lib/api";

const DEFAULT_PARTICIPANTS = [
  "clio",
  "prometheus",
  "plutus",
  "hermes",
  "hephaestus",
  "themis",
  "tyche",
  "calliope",
];

interface BoardMeetingFormProps {
  onSubmit: (topic: string, participants: string[]) => void;
  loading: boolean;
}

export default function BoardMeetingForm({
  onSubmit,
  loading,
}: BoardMeetingFormProps) {
  const [topic, setTopic] = useState("");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selected, setSelected] = useState<Set<string>>(
    new Set(DEFAULT_PARTICIPANTS),
  );

  useEffect(() => {
    fetchAgents()
      .then(setAgents)
      .catch(() => {
        setAgents(
          DEFAULT_PARTICIPANTS.map((name) => ({
            name,
            role: "",
            description: "",
          })),
        );
      });
  }, []);

  function toggleAgent(name: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  }

  function handleSubmit() {
    if (!topic.trim() || selected.size === 0) return;
    onSubmit(topic.trim(), Array.from(selected));
  }

  const excludeFromSelection = new Set(["athena", "sphinx", "mnemon", "gapper"]);

  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1.5 block text-sm font-medium text-[var(--text-primary)]">
          Meeting Topic
        </label>
        <textarea
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="What should the board discuss?"
          rows={3}
          className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-3 text-sm text-[var(--text-primary)] placeholder-[var(--text-secondary)] outline-none focus:border-[var(--accent)]"
        />
      </div>

      <div>
        <label className="mb-2 block text-sm font-medium text-[var(--text-primary)]">
          Participants ({selected.size} selected)
        </label>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {agents
            .filter((a) => !excludeFromSelection.has(a.name))
            .map((agent) => (
              <label
                key={agent.name}
                className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 cursor-pointer transition-colors hover:bg-[var(--bg-tertiary)]"
              >
                <Checkbox
                  checked={selected.has(agent.name)}
                  onCheckedChange={() => toggleAgent(agent.name)}
                />
                <div className="min-w-0">
                  <span className="text-sm text-[var(--text-primary)]">
                    {agent.name}
                  </span>
                  {agent.role && (
                    <span className="ml-1.5 text-xs text-[var(--text-secondary)]">
                      ({agent.role})
                    </span>
                  )}
                </div>
              </label>
            ))}
        </div>
      </div>

      <Button
        onClick={handleSubmit}
        disabled={!topic.trim() || selected.size === 0 || loading}
        className="w-full"
      >
        <Users className="h-4 w-4" />
        Convene Board Meeting
      </Button>
    </div>
  );
}
