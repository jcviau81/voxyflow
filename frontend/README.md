# Voxyflow Frontend

Voice-first project assistant — PWA frontend built with TypeScript, zero frameworks.

## Quick Start

```bash
# Install dependencies
npm install

# Start dev server (port 3000)
npm run dev

# Build for production
npm run build

# Run tests
npm test
```

## Architecture

- **No frameworks** — pure TypeScript, class-based components
- **WebSocket** — real-time communication with backend
- **IndexedDB** — offline storage for messages, projects, cards
- **Web Speech API** — voice input (mobile), Whisper WASM ready (desktop)
- **PWA** — installable, offline-capable, service worker

## Project Structure

```
src/
├── main.ts              # Entry point
├── App.ts               # Root application component
├── types/               # TypeScript type definitions
├── state/               # AppState (localStorage-backed)
├── services/            # API, Chat, STT, Audio, Storage, Project, Card
├── components/
│   ├── Chat/            # ChatWindow, VoiceInput, MessageBubble
│   ├── Kanban/          # KanbanBoard, Column, Card, CardDetailModal
│   ├── Projects/        # ProjectList
│   ├── Navigation/      # Sidebar, TopBar
│   └── Shared/          # Toast, LoadingSpinner
├── utils/               # EventBus, helpers, constants
└── styles/              # main.css, components.css, responsive.css
```

## Key Features

- **Voice Input** — Push-to-talk (Alt+V) with real-time transcript
- **Chat** — Streaming responses with markdown support
- **Kanban Board** — Drag & drop cards across 4 columns
- **Projects** — Create, manage, archive projects
- **Offline Queue** — Messages queued when disconnected, sent on reconnect
- **Dark Theme** — Full dark UI with CSS variables
- **Responsive** — Mobile, tablet, desktop breakpoints

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Alt+V` | Toggle voice recording |
| `Enter` | Send message |
| `Shift+Enter` | New line in message |
| `Ctrl+B` | Toggle sidebar |
| `Ctrl+1` | Switch to Chat |
| `Ctrl+2` | Switch to Kanban |
| `Ctrl+3` | Switch to Projects |
| `Escape` | Close modal |

## Scripts

| Script | Description |
|--------|-------------|
| `npm run dev` | Start dev server with HMR |
| `npm run build` | Production build to `dist/` |
| `npm test` | Run Jest test suite |
| `npm run lint` | ESLint check |
| `npm run format` | Prettier format |
| `npm run type-check` | TypeScript type check |

## Tech Stack

- TypeScript 5.5
- Webpack 5 (dev server, HMR, code splitting)
- Jest + ts-jest + jsdom (testing)
- ESLint + Prettier (code quality)
- Workbox (PWA/service worker)
- Web Audio API (audio playback)
- Web Speech API / Whisper WASM (speech-to-text)
- IndexedDB (offline storage)
- WebSocket (real-time backend communication)

## Backend Connection

The frontend connects to the backend via WebSocket at `ws://localhost:8000` (configurable via `VOXYFLOW_WS_URL`).

The dev server proxies `/api/*` and `/ws/*` requests to the backend.

## License

Private — JC Viau
