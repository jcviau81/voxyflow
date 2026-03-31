# Frontend Migration — Vanilla TS → React + Vite

## Pourquoi migrer

Le frontend actuel (vanilla TypeScript + webpack) fonctionne, mais les composantes sont devenues monstrueuses:

| Fichier | Lignes |
|---------|--------|
| SettingsPage.ts | 2420 |
| CardDetailModal.ts | 2058 |
| ChatWindow.ts | 1581 |
| KanbanBoard.ts | 936 |
| ... | ... |

Sans virtual DOM ni reactive layer, chaque composante fait du `createElement` / `innerHTML` / event listeners à la main. Résultat: fichiers de 1000-2000 lignes, couplage fort, difficile à maintenir.

**React + Vite** règle ça:
- HMR quasi-instantané (vs ~1min avec webpack)
- Composantes déclaratives, état réactif
- Écosystème mature, Claude Code connaît ça par cœur

---

## Stratégie: Dossier parallèle

Ne pas essayer de faire coexister React dans l'app vanilla — deux systèmes de state = cauchemar.

**Approche:** Nouveau dossier `frontend-react/` en parallèle. L'ancien `frontend/` reste intact jusqu'au swap final.

```
voxyflow/
├── frontend/          ← ancien (vanilla TS + webpack) — reste intact
├── frontend-react/    ← nouveau (React + Vite) — build ici
└── backend/           ← inchangé à 100%
```

---

## Stack cible

- **React 18** + TypeScript
- **Vite** (remplace webpack — HMR instantané)
- **Tailwind CSS** (remplace le CSS custom fait à la main)
- **Zustand** (state management léger, remplace AppState.ts)
- **TanStack Query** (fetches API avec cache, remplace ApiClient.ts manuel)
- **React Router** (routing côté client — settings, board, etc.)
- Même WebSocket / API backend — rien ne change côté serveur

---

## Librairies à évaluer par feature

Tant qu'à casser le frontend, autant ne pas réinventer la roue. Le frontend actuel a réimplémenté from scratch plusieurs systèmes qui existent déjà en librairies matures. Pour chaque feature, évaluer si une lib fait mieux avant de coder.

### Kanban / Cards
| Feature actuelle | Librairie à évaluer |
|-----------------|---------------------|
| KanbanBoard.ts (936 lignes) | **@dnd-kit/core** + **@dnd-kit/sortable** — drag & drop accessible, léger |
| Drag & drop colonnes/cartes | **react-beautiful-dnd** (plus simple mais maintenance ralentie) |
| Card detail modal | **Headless UI** (Tailwind Labs) — modal/dialog accessible |

### Chat
| Feature actuelle | Librairie à évaluer |
|-----------------|---------------------|
| ChatWindow.ts (1581 lignes) | **stream-chat-react** (overkill) ou builder from scratch avec hooks — le chat custom Voxyflow est trop spécifique (workers, delegates, tool calls) pour une lib générique |
| Message rendering Markdown | **react-markdown** + **react-syntax-highlighter** |
| Auto-scroll, virtual list | **react-virtual** / **@tanstack/react-virtual** si la liste devient longue |

### Emoji
| Feature actuelle | Librairie à évaluer |
|-----------------|---------------------|
| Emoji picker custom | **Picmo** — déjà utilisé dans le frontend actuel, plus simple qu'emoji-mart, garder |

### Éditeur de texte riche (cards description)
| Feature actuelle | Librairie à évaluer |
|-----------------|---------------------|
| CodeMirror intégré à la main | **@uiw/react-codemirror** — wrapper React propre |
| Rich text / markdown | **TipTap** (extensible) ou **Milkdown** |

### Forms & Validation
| Feature actuelle | Librairie à évaluer |
|-----------------|---------------------|
| Forms manuels (ProjectForm.ts 804 lignes) | **React Hook Form** + **Zod** |

### UI Components généraux
| Besoin | Librairie à évaluer |
|--------|---------------------|
| Composantes de base (buttons, inputs, etc.) | **shadcn/ui** — composantes Tailwind copiables, pas de dépendance runtime |
| Tooltips, dropdowns, menus | **Radix UI** (base de shadcn) |
| Icons | **Lucide React** |
| Notifications / toasts | **react-hot-toast** ou **Sonner** |

### Approche recommandée
1. **shadcn/ui + Tailwind** pour la base UI — pas une dépendance npm, le code est dans ton projet
2. **@dnd-kit** pour le kanban — le meilleur DnD React en 2025
3. **react-markdown** pour le rendering des messages
4. **Picmo** pour le picker (déjà utilisé dans le frontend actuel — pas de raison de changer)
5. **React Hook Form + Zod** pour tous les forms
6. Le reste (chat WS, workers, delegates) reste custom — trop spécifique à Voxyflow

---

## Ordre de migration (composante par composante)

### Phase 1 — Setup + fondations
1. `npx create vite@latest frontend-react -- --template react-ts`
2. Configurer SSL via `.env.local` (même certs que le frontend actuel)
3. Configurer le proxy dans `vite.config.ts` (vers `:8000`)
4. Installer et configurer Tailwind CSS + shadcn/ui
5. Créer le store Zustand (remplace `AppState.ts`) — **nécessaire avant toute composante avec state**
6. Porter `ApiClient.ts` → hooks TanStack Query (`useProjects`, `useCards`, etc.)
7. Mettre en place le routing (React Router) et l'authentification (token refresh, protected routes)

### Phase 2 — Composantes simples + services
8. Migrer **KanbanCard** (la plus simple, peu de state)
9. Migrer **FreeBoard**
10. Porter `ChatService.ts` → context + hooks WebSocket (avec reconnexion, message queuing, auth token — préserver la logique existante de `ChatService.ts`)

### Phase 3 — Composantes complexes
11. Migrer **KanbanBoard** (intégrer @dnd-kit)
12. Migrer **CardDetailModal**
13. Migrer **ChatWindow** + **VoiceInput**
14. Migrer **SettingsPage** (la plus grosse, garder pour la fin)

### Phase 4 — Swap final
15. Valider E2E complet sur `frontend-react/`
16. Mettre à jour `voxy-dev.sh` pour pointer sur `frontend-react/`
17. Archiver `frontend/` → `frontend-legacy/` ou supprimer
18. Renommer `frontend-react/` → `frontend/`

---

## Points d'attention

### WebSocket
Le chat utilise un WS persistant. En React: un seul `useEffect` avec cleanup dans un context global — pas de reconnexion à chaque render.

> **Important:** Le snippet ci-dessous est un squelette minimal. La migration doit préserver la logique de reconnexion, message queuing et auth token de `ChatService.ts`. Ne pas simplifier ces comportements.

```tsx
// ChatContext.tsx — squelette, la version complète doit inclure reconnexion + queue
const ws = useRef<WebSocket | null>(null);
useEffect(() => {
  ws.current = new WebSocket(WS_URL);
  // TODO: porter reconnection logic depuis ChatService.ts
  // TODO: porter message queue pour les envois pendant déconnexion
  return () => ws.current?.close();
}, []);
```

### Authentification
L'auth doit être migrée en Phase 1 — c'est un prérequis pour les routes protégées et les appels API. Porter la logique existante de token storage / refresh avant de migrer les composantes.

### SSL dev (même config)

> **Attention:** Les variables préfixées `VITE_` sont exposées au bundle client. Pour `server.https`, utiliser des variables non-préfixées lues via `fs.readFileSync` dans `vite.config.ts`.

```env
# frontend-react/.env.local
SSL_KEY_PATH=/home/jcviau/rog.tail6531d.ts.net.key
SSL_CERT_PATH=/home/jcviau/rog.tail6531d.ts.net.crt
```

```ts
// vite.config.ts
import fs from 'fs';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    server: {
      https: env.SSL_KEY_PATH ? {
        key: fs.readFileSync(env.SSL_KEY_PATH),
        cert: fs.readFileSync(env.SSL_CERT_PATH),
      } : false,
      proxy: {
        '/api': 'http://localhost:8000',
        '/ws': { target: 'ws://localhost:8000', ws: true },
      },
    },
  };
});
```

### STT / ONNX Whisper
Le Whisper WASM worker existant peut être réutilisé tel quel dans un `useRef` — pas besoin de réécrire.

---

## Prompt de départ pour Claude Code

```
Migrate Voxyflow frontend from vanilla TypeScript + webpack to React + Vite.

Context:
- Existing frontend: ./frontend/ (vanilla TS, ~27k lines, webpack)
- New frontend: create ./frontend-react/ (React 18 + TypeScript + Vite)
- Backend: FastAPI on :8000, WebSocket on /ws — do NOT touch
- Keep identical UI and behavior

Start with Phase 1:
1. Scaffold frontend-react/ with create-vite react-ts template
2. Configure vite.config.ts with proxy (/api → :8000, /ws → ws://:8000)
   and SSL via env vars (SSL_KEY_PATH / SSL_CERT_PATH from .env.local — NOT VITE_ prefixed)
3. Install and configure Tailwind CSS + shadcn/ui
4. Set up Zustand store mirroring AppState.ts
5. Port ApiClient.ts → TanStack Query hooks
6. Set up React Router + auth (protected routes, token refresh)
7. Then migrate KanbanCard component (simplest, least state)

Reference files to read first:
- frontend/src/components/Kanban/KanbanCard.ts
- frontend/src/state/AppState.ts
- frontend/src/services/ApiClient.ts
```

---

*Créé: 2026-03-30 — branche: `refactor/react-frontend`*
