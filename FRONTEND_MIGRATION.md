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
4. **emoji-mart** pour le picker
5. **React Hook Form + Zod** pour tous les forms
6. Le reste (chat WS, workers, delegates) reste custom — trop spécifique à Voxyflow

---

## Ordre de migration (composante par composante)

### Phase 1 — Setup + composantes simples
1. `npx create vite@latest frontend-react -- --template react-ts`
2. Configurer SSL via `.env.local` (même certs que le frontend actuel)
3. Configurer le proxy dans `vite.config.ts` (vers `:8000`)
4. Migrer **KanbanCard** (la plus simple, peu de state)
5. Migrer **FreeBoard**

### Phase 2 — State & services
6. Créer le store Zustand (remplace `AppState.ts`)
7. Porter `ApiClient.ts` → hooks React (`useProjects`, `useCards`, etc.)
8. Porter `ChatService.ts` → context + hooks WebSocket

### Phase 3 — Composantes complexes
9. Migrer **KanbanBoard**
10. Migrer **CardDetailModal**
11. Migrer **ChatWindow** + **VoiceInput**
12. Migrer **SettingsPage** (la plus grosse, garder pour la fin)

### Phase 4 — Swap final
13. Valider E2E complet sur `frontend-react/`
14. Mettre à jour `voxy-dev.sh` pour pointer sur `frontend-react/`
15. Archiver `frontend/` → `frontend-legacy/` ou supprimer
16. Renommer `frontend-react/` → `frontend/`

---

## Points d'attention

### WebSocket
Le chat utilise un WS persistant. En React: un seul `useEffect` avec cleanup dans un context global — pas de reconnexion à chaque render.

```tsx
// ChatContext.tsx
const ws = useRef<WebSocket | null>(null);
useEffect(() => {
  ws.current = new WebSocket(WS_URL);
  return () => ws.current?.close();
}, []);
```

### SSL dev (même config)
```env
# frontend-react/.env.local
VITE_SSL_KEY=/home/jcviau/rog.tail6531d.ts.net.key
VITE_SSL_CERT=/home/jcviau/rog.tail6531d.ts.net.crt
```

```ts
// vite.config.ts
server: {
  https: process.env.VITE_SSL_KEY ? {
    key: process.env.VITE_SSL_KEY,
    cert: process.env.VITE_SSL_CERT,
  } : false,
  proxy: {
    '/api': 'http://localhost:8000',
    '/ws': { target: 'ws://localhost:8000', ws: true },
  }
}
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
   and SSL via env vars (VITE_SSL_KEY / VITE_SSL_CERT from .env.local)
3. Set up Zustand store mirroring AppState.ts
4. Migrate KanbanCard component first (simplest, least state)

Reference files to read first:
- frontend/src/components/Kanban/KanbanCard.ts
- frontend/src/state/AppState.ts
- frontend/src/services/ApiClient.ts
```

---

*Créé: 2026-03-30 — branche cible: `ember/react-vite-migration`*
