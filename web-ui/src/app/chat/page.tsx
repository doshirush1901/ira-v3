"use client";

import { useState, useEffect } from "react";
import Chat from "@/components/Chat";
import { fetchAgents, type Agent } from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const FALLBACK_AGENTS: Agent[] = [
  { name: "athena", role: "Orchestrator", description: "" },
  { name: "prometheus", role: "Sales", description: "" },
  { name: "plutus", role: "Finance", description: "" },
  { name: "clio", role: "Research", description: "" },
];

export default function ChatPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selected, setSelected] = useState("athena");
  const [runAsTaskLoop, setRunAsTaskLoop] = useState(false);

  useEffect(() => {
    fetchAgents()
      .then((list) => {
        setAgents(list);
        if (list.length > 0 && !list.some((a) => a.name === "athena")) {
          setSelected(list[0].name);
        }
      })
      .catch(() => {
        setAgents(FALLBACK_AGENTS);
      });
  }, []);

  const current = agents.find((a) => a.name === selected);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center gap-3 border-b border-[var(--border)] bg-[var(--bg-secondary)] px-6 py-2">
        <span className="text-xs text-[var(--text-secondary)]">Agent:</span>
        <Select value={selected} onValueChange={setSelected}>
          <SelectTrigger className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {agents.map((a) => (
              <SelectItem key={a.name} value={a.name}>
                {a.name} — {a.role}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {current?.description && (
          <span className="text-xs text-[var(--text-secondary)] truncate">
            {current.description}
          </span>
        )}
        <label className="ml-auto flex items-center gap-2 text-xs text-[var(--text-secondary)]">
          <input
            type="checkbox"
            checked={runAsTaskLoop}
            onChange={(e) => setRunAsTaskLoop(e.target.checked)}
          />
          Run as task loop
        </label>
      </div>

      <Chat targetAgent={selected} runAsTaskLoop={runAsTaskLoop} />
    </div>
  );
}
