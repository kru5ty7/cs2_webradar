# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CS2 WebRadar is a browser-based radar for Counter-Strike 2. It has two components:
1. **usermode** — a C++ executable that reads game memory and streams JSON over WebSocket
2. **webapp** — a React/Vite frontend that receives and renders that JSON on a radar map

## Architecture

### Data Flow

```
CS2 process (game memory)
    → usermode.exe (C++ memory reader, 10Hz polling)
        → WebSocket client (easywsclient) → ws://HOST:22006/cs2_webradar
            → webapp/ws/app.js (Node.js relay server, port 22006)
                → browser WebSocket clients
                    → React components
```

The relay server in `webapp/ws/app.js` broadcasts every message it receives from the C++ client to all connected browser clients. It does no parsing — it is a pure relay.

### usermode (C++)

Entry point: `usermode/src/dllmain.cpp`

Initialization sequence (all must succeed or the process exits):
1. `cfg::setup()` — reads `config.json` for `m_use_localhost`, `m_local_ip`, `m_public_ip`
2. `exc::setup()` — installs exception handler
3. `m_memory->setup()` — opens handle to CS2 process
4. `i::setup()` — resolves game interfaces (SchemaSystem, GameEntitySystem, GlobalVars) via signatures
5. `schema::setup()` — dumps CS2 schema for offset resolution

Main loop runs at 10Hz (`std::chrono::milliseconds(100)`), calling:
- `sdk::update()` — refreshes local player controller
- `f::run()` — collects all feature data into `f::m_data` (a `nlohmann::json` object)
- `web_socket->send(f::m_data.dump())` — sends the JSON blob

**Feature modules** (under `usermode/src/features/`):
- `players/` — iterates game entity list, reads per-player fields (position, health, weapons, eye angle, etc.)
- `bomb/` — handles both carried (`C_C4`) and planted (`C_PlantedC4`) bomb states

**SDK layer** (under `usermode/src/sdk/`):
- `entity.hpp/.cpp` — CS2 entity classes accessed via schema-derived offsets
- `interfaces/` — wrappers for `c_game_entity_system`, `c_schema_system`, `c_global_vars`
- `datatypes/` — `utl_vector`, `utl_ts_hash`, `vector` matching CS2 internal types

Offsets are resolved at runtime via `schema::setup()`, not hardcoded, making the cheat more resilient to CS2 updates. Signatures in `common.hpp` are used for interface resolution.

### webapp (React + Vite)

Entry: `webapp/src/app.jsx`

**Connection logic** (in `App` component):
- `USE_LOCALHOST` flag switches between localhost and `PUBLIC_IP`/`window.location.hostname`
- `VITE_WS_URL` env var overrides for ngrok tunnels
- WebSocket connects to `ws://HOST:22006/cs2_webradar`

**JSON payload fields** received from usermode:
- `m_players[]` — array of player objects (m_position.x/y, m_team, m_health, m_eye_angle, m_weapons, etc.)
- `m_local_team` — team number of local player
- `m_bomb` — bomb state (x, y, m_blow_time, m_is_defusing, m_defuse_time, m_is_defused)
- `m_grenades[]` — active grenade positions
- `m_map` — map name string (e.g. `"de_dust2"`) or `"invalid"`

**Map data** lives in `webapp/public/data/<mapname>/`:
- `data.json` — `{ x, y, scale }` — world-space origin and units-per-pixel for coordinate mapping
- `radar.png` — overhead map image
- `background.png` — blurred background image
- `callouts.json` — named area coordinates for the callout overlay layer

**Radar coordinate conversion**: world (x, y) → radar pixel = `(worldCoord - mapOrigin) / scale`. Both `Player` and `Bomb` components implement this.

**Component structure**:
- `Radar` — container; renders radar image + all child layers
- `Player` — individual dot with view cone and name label
- `Bomb` — C4 icon on radar
- `GrenadeLayer` — all active grenades
- `CalloutLayer` — area name labels from `callouts.json`
- `PlayerCard` — sidebar card (health, weapons, armor) shown on lg+ screens
- `Latency` — ping display + settings panel trigger

Settings (dot size, show names, view cones, grenades) are persisted to `localStorage` under key `radarSettings`.

## ai_agent_helper (Python usermode alternative)

`ai_agent_helper/` is a pure-Python drop-in replacement for `usermode.exe` — no Visual Studio required.

**How it works:**
1. On first run it fetches current offsets from [a2x/cs2-dumper](https://github.com/a2x/cs2-dumper) and caches them in `offsets_cache.json` (refreshed every hour).
2. Opens CS2 process via `ReadProcessMemory` (requires admin or a process with a handle CS2 already has).
3. Walks the entity list at 10 Hz, builds the same JSON payload as usermode.exe, and sends it to the relay at `ws://HOST:22006/cs2_webradar`.

**Run:**
```bat
cd ai_agent_helper
run.bat          # installs deps if needed, then starts
# or manually:
pip install -r requirements.txt
python main.py
```

**Config:** reads the same `config.json` as usermode (`m_use_localhost`, `m_local_ip`). Created automatically on first run.

**Offset updates:** delete `offsets_cache.json` to force a fresh fetch, or just wait for the 1-hour TTL.

**Only external dependency:** `websocket-client` (pip). Everything else uses stdlib (`ctypes`, `urllib`, `json`, `threading`).

## Development Commands

### webapp
```bash
cd webapp
npm install          # install dependencies
npm run dev          # start relay server + Vite dev server (localhost:5173)
npm run build        # production build to webapp/dist/
npm run lint         # ESLint
npm run preview      # serve the production build
```

### usermode (C++)
Open `usermode/cs2_webradar.sln` in Visual Studio. Build with `Ctrl+Shift+B`. Output goes to `usermode/release/usermode.exe`.

## Configuration

**Localhost vs. LAN/remote** (two places must match):

| File | Setting |
|------|---------|
| `usermode/release/config.json` | `m_use_localhost: true/false` |
| `webapp/src/app.jsx` line ~12 | `const USE_LOCALHOST = 1/0` |

**ngrok**: Set `VITE_WS_URL=wss://<tunnel>.ngrok-free.app/cs2_webradar` in a `.env` file before running `npm run dev`.

## Adding a New Map

1. Create `webapp/public/data/<mapname>/` with `radar.png`, `background.png`, and `data.json` (origin x/y and scale from CS2 map overview files).
2. Optionally add `callouts.json` for the callout overlay.
3. No code changes needed — the map name comes from the usermode payload and is used to fetch the data directory dynamically.
