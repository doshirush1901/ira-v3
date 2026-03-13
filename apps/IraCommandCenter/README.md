# Ira Command Center (macOS)

Bloomberg-style, dark-mode Command Center for Ira: 4-panel view of agents, vitals, event stream, and CRM metrics. Native SwiftUI app; talks to Ira API on `http://localhost:8000`.

## Requirements

- macOS 13+
- Xcode 15+ (recommended) or Swift 5.9+ command line tools
- Ira API running (e.g. `poetry run uvicorn ira.interfaces.server:app --host 0.0.0.0 --port 8000`). If port 8000 is in use, use another port (e.g. `--port 8001`) and set the same URL in the app’s **Settings** (gear icon).

## Build and run

**Recommended:** Open the project in Xcode and run.

1. **Open the project** — any of these:
   - **Easiest:** In Finder go to `ira-v3/apps/IraCommandCenter/` and **double-click `OpenInXcode.command`**. (First time, macOS may ask to confirm — click Open.) That opens the project in Xcode.
   - **From Terminal** (use this so Xcode opens, not Finder):  
     `open -a Xcode /Users/rushabhdoshi/ira-v3/apps/IraCommandCenter/IraCommandCenter.xcodeproj`  
     (Or from repo root: `open -a Xcode apps/IraCommandCenter/IraCommandCenter.xcodeproj`)
   - **From Finder**: Go to `ira-v3/apps/IraCommandCenter/` and double-click **IraCommandCenter.xcodeproj** (the blue project icon; if you only see a folder with `project.pbxproj` inside, you’re inside the project — go back one level and double-click the **IraCommandCenter.xcodeproj** folder).
2. In Xcode, select the **IraCommandCenter** scheme and **My Mac** as destination.
3. Press **⌘R** (or **Product → Run**).

The project is preconfigured: all Swift sources are in the target, macOS 13.0 deployment, SwiftUI app. No manual file adding or project creation needed.

**Alternative (if you have a working Swift toolchain):** From this directory run `swift build` then `swift run IraCommandCenter`. If that fails with linker errors, use Xcode as above.

## Layout

- **Top-left**: Pantheon — agents table (name, role, power level, tier, tool success rate).
- **Bottom-left**: Circulatory Ledger — live WebSocket stream of DataEventBus events (Neo4j, Qdrant, CRM).
- **Top-right**: Vitals — endocrine levels, last pipeline stage timings, immune/system health (Qdrant, Neo4j, Postgres, Mem0, etc.).
- **Bottom-right**: CRM & Metrics — pipeline value, active campaigns, stale leads (14d), recent interactions.

REST endpoints are polled every 5 seconds. WebSocket stays connected and reconnects with backoff.

## API base URL

The app uses `http://localhost:8000` by default. Use **Settings** (gear icon in the toolbar) to change the base URL; the value is saved and used for both REST and WebSocket. If the API is unreachable, an error banner appears at the top (dismissible).
