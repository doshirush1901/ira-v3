# `memory/` — Memory Subsystems

10 memory modules modeled after how human memory works. Memory is
first-class in Ira — if an agent learns something useful, it gets stored.

## Subsystems

| Module | Storage | What It Remembers |
|:-------|:--------|:------------------|
| `conversation.py` | SQLite | Per-user, per-channel chat history |
| `long_term.py` | Mem0 | Semantic facts extracted from interactions |
| `episodic.py` | SQLite + Mem0 | Narratives of significant interactions |
| `relationship.py` | SQLite | Contact warmth, preferences, communication style |
| `procedural.py` | SQLite | Learned response patterns ("when X, do Y") |
| `goal_manager.py` | SQLite | Active goals with slot-filling tracking |
| `emotional_intelligence.py` | SQLite | Emotion tracking across conversations |
| `inner_voice.py` | Runtime | Post-response self-reflection |
| `metacognition.py` | Runtime | Confidence scoring and knowledge gap detection |
| `dream_mode.py` | All | 11-stage overnight consolidation cycle |

## Agent Access

Agents access memory through ReAct tools auto-registered by `BaseAgent`:
`recall_memory`, `store_memory`, `get_conversation_history`,
`check_relationship`, `check_goals`, `recall_episodes`.

Direct memory access in `handle()` is reserved for Mnemosyne and Nemesis.
