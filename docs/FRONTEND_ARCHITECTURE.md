# Voxyflow Frontend Architecture

## Overview

Voxyflow's frontend is a **zero-framework TypeScript PWA** built with class-based components, event-driven architecture, and offline-first design.

## Design Principles

1. **No frameworks** — Pure TypeScript, DOM manipulation, minimal dependencies
2. **Offline-first** — IndexedDB storage, message queue, service worker caching
3. **Voice-first** — Speech-to-text as primary input, keyboard as secondary
4. **Event-driven** — Components communicate via EventBus, not direct references
5. **State-centric** — Single AppState manages all UI state with localStorage persistence

## Architecture Layers

```
┌─────────────────────────────────────────────┐
│                   App.ts                     │
│         (Root component, routing)            │
├─────────────────────────────────────────────┤
│              Components Layer                │
│  Chat │ Kanban │ Projects │ Nav │ Shared     │
├─────────────────────────────────────────────┤
│              Services Layer                  │
│  ApiClient │ ChatService │ SttService │ ...  │
├─────────────────────────────────────────────┤
│            State Management                  │
│          AppState (localStorage)             │
├─────────────────────────────────────────────┤
│               Utilities                      │
│     EventBus │ helpers │ constants           │
└─────────────────────────────────────────────┘
```

## Component Pattern

All components follow the same interface:

```typescript
class MyComponent {
  constructor(parentElement: HTMLElement) {
    // Create container, render, setup listeners
  }

  render(): void {
    // Build DOM tree
  }

  update(data?: unknown): void {
    // Re-render with new data
  }

  destroy(): void {
    // Unsubscribe events, remove DOM
  }
}
```

### Communication Flow

1. **User action** → Component method
2. **Component** → Service method call
3. **Service** → AppState update + API call
4. **AppState** → EventBus emission
5. **EventBus** → Other components react

### No Direct Component References

Components never reference each other directly. All cross-component communication goes through:
- **EventBus** — for events (message received, card moved, etc.)
- **AppState** — for shared state (current view, selected project, etc.)

## State Management

### AppState

Single source of truth for all UI state:

```typescript
interface AppStateData {
  currentView: ViewMode;        // 'chat' | 'kanban' | 'projects' | 'settings'
  currentProjectId: string | null;
  selectedCardId: string | null;
  messages: Message[];
  projects: Project[];
  cards: Card[];
  sidebarOpen: boolean;
  connectionState: ConnectionState;
  voiceActive: boolean;
  volume: number;
  theme: 'dark' | 'light';
}
```

### Persistence Strategy

| Data | Storage | Reason |
|------|---------|--------|
| UI state | localStorage | Fast, sync, small |
| Messages | localStorage + IndexedDB | Offline access |
| Projects/Cards | localStorage + IndexedDB | Offline access |
| Offline queue | localStorage | Survive page reload |
| Large blobs | IndexedDB | Better for binary data |

## Services

### ApiClient (WebSocket)

- Exponential backoff reconnection (100ms → 30s)
- Heartbeat every 30s
- Offline message queue with persistence
- Handler registry for message types

### ChatService

- Streaming response rendering
- Voice transcript integration
- Card suggestion toasts

### SttService

- Device detection (mobile vs desktop)
- Web Speech API (mobile/fallback)
- Whisper WASM placeholder (desktop)
- Error handling for permissions

### AudioService

- Web Audio API playback
- Queue-based audio segments
- Volume control

### StorageService

- IndexedDB wrapper with typed tables
- Auto-backup every 5 minutes
- Export/import for data portability

## Rendering Pipeline

```
View Change
  └→ App.switchView()
       └→ Destroy old component
       └→ Create new component
            └→ constructor()
                 └→ render() — DOM creation
                 └→ setupListeners() — EventBus subscriptions
                 └→ Load data from AppState
```

## Build System

- **Webpack 5** — Bundling, dev server, HMR
- **ts-loader** — TypeScript compilation
- **MiniCssExtractPlugin** — CSS extraction in production
- **Workbox** — Service worker generation
- **Code splitting** — Vendor chunk separation

## Testing Strategy

- **Jest + jsdom** — Unit tests
- **ts-jest** — TypeScript support
- **Coverage targets** — 50% minimum (branches, functions, lines, statements)
- **Test structure** — One test file per critical module

## Directory Map

```
frontend/
├── src/
│   ├── main.ts                    # Entry point, HMR, SW registration
│   ├── App.ts                     # Root component, view routing
│   ├── types/                     # All TypeScript types
│   ├── state/AppState.ts          # Centralized state management
│   ├── services/                  # 7 services (API, Chat, STT, Audio, Storage, Project, Card)
│   ├── components/                # 16 component files across 5 groups
│   ├── utils/                     # EventBus, helpers, constants
│   └── styles/                    # 3 CSS files (main, components, responsive)
├── public/                        # Static assets (HTML, manifest, icons, SW)
├── tests/                         # 4 test suites
└── config files                   # webpack, tsconfig, eslint, prettier, jest
```
