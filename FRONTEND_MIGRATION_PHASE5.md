# Frontend Migration — Phase 5: Assemblage final

Les 25 steps automatisés ont migré toutes les **composantes individuelles**. Il reste maintenant à les **assembler en pages fonctionnelles** et combler les trous.

---

## Ce qui est fait vs ce qui manque

| Composante | Status | Fichiers React |
|------------|--------|----------------|
| Stores Zustand (5) | OK | useCardStore, useProjectStore, useThemeStore, useSessionStore, useTabStore, useMessageStore, useNotificationStore |
| API hooks (TanStack Query) | OK | useCards, useProjects, useSessions, useAgents |
| WebSocket + offline queue | OK | useWebSocket, WebSocketProvider, useOfflineQueue |
| Auth + routing | OK | useAuth, ProtectedRoute, router.tsx |
| KanbanCard | OK | KanbanCard.tsx |
| KanbanBoard | OK | KanbanBoard.tsx |
| FreeBoard | OK | FreeBoard.tsx |
| CardDetailModal (3 passes) | OK | CardDetailModal.tsx + 16 sous-composantes |
| ChatWindow (2 passes) | OK | ChatWindow.tsx + MessageList, MessageBubble, ChatInput, etc. |
| ChatService / Provider | OK | ChatProvider.tsx, useChatService.ts |
| VoiceInput | OK | VoiceInput.tsx + STT/TTS services |
| SettingsPage (4 passes) | OK | SettingsPage.tsx + 7 panels |
| **AppShell layout** | **PARTIEL** | Shell OK, mais TopBar/Sidebar/TabBar/RightPanel manquent |
| **MainPage / ProjectPage** | **STUB** | Placeholder divs dans router.tsx |
| **Sidebar** | **MANQUANT** | Pas encore migré (450 lignes vanilla) |
| **TabBar** | **MANQUANT** | Pas encore migré (403 lignes vanilla) |
| **TopBar** | **MANQUANT** | Pas encore migré (178 lignes vanilla) |
| **RightPanel** | **MANQUANT** | Pas encore migré (403 lignes vanilla) |
| **WorkerPanel** | **MANQUANT** | Pas encore migré (523 lignes vanilla) |
| **ProjectList** | **MANQUANT** | Pas encore migré (451 lignes vanilla) |
| **ProjectHeader** | **MANQUANT** | Pas encore migré (136 lignes vanilla) |
| **ProjectStats** | **MANQUANT** | Pas encore migré (1210 lignes vanilla) |
| **ProjectKnowledge** | **MANQUANT** | Pas encore migré (313 lignes vanilla) |
| **ProjectDocuments** | **MANQUANT** | Pas encore migré (276 lignes vanilla) |

---

## Steps restants

> Même format que les phases précédentes: chaque step = un agent shot autonome.

### Phase 5A — Navigation (composantes structurelles)

**Step 16.** Migrer **Sidebar** (sonnet, 450 lignes)
- Source: `frontend/src/components/Navigation/Sidebar.ts`
- Logo + brand, Main item, Favorites, Active sessions, All projects grid, footer icons (Settings, Docs, Help)
- Connecter à useProjectStore, useSessionStore, useTabStore
- Événements: navigation entre vues, toggle sidebar mobile

**Step 17.** Migrer **TabBar** (sonnet, 403 lignes)
- Source: `frontend/src/components/Navigation/TabBar.ts`
- Tabs (Main + projects ouverts), emoji + label + notification dot + close button
- Bouton "+" pour créer un projet
- Middle-click to close, switch tabs
- Connecter à useTabStore, useProjectStore

**Step 18.** Migrer **TopBar** (sonnet, 178 lignes)
- Source: `frontend/src/components/Navigation/TopBar.ts`
- Hamburger mobile, nom du projet actif
- Mode pills: Fast (Sonnet) / Deep (Opus) / Analyzer
- Voice toggles: auto-send, auto-play
- Persistance localStorage + sync backend

### Phase 5B — Panels latéraux

**Step 19.** Migrer **RightPanel** (sonnet, 403 lignes)
- Source: `frontend/src/components/RightPanel/RightPanel.ts`
- Deux onglets: Opportunities | Notifications
- CardSuggestion objects, notifications timestampées
- Badge de compteur, toggle open/close
- Connecter à useNotificationStore

**Step 20.** Migrer **WorkerPanel** (sonnet, 523 lignes)
- Source: `frontend/src/components/RightPanel/WorkerPanel.ts`
- Live view des worker tasks (pending/running/done/failed)
- Polling REST (`GET /api/worker-tasks`) + WebSocket sync
- Auto-dismiss après 30s, résultats expandables
- Connecter à useWebSocket + API hooks

### Phase 5C — Pages projet

**Step 21.** Migrer **ProjectList** (sonnet, 451 lignes)
- Source: `frontend/src/components/Projects/ProjectList.ts`
- Grille de projets avec filtres (All/Active/Completed/Archived)
- Summary bar, project cards, bouton "+ New Project"
- Connecter à useProjects

**Step 22.** Migrer **ProjectHeader** (sonnet, 136 lignes)
- Source: `frontend/src/components/Projects/ProjectHeader.ts`
- Emoji + nom du projet (clickable → project properties)
- View tabs: Chat, Kanban, Board, Knowledge
- Masqué quand aucun projet sélectionné

**Step 23.** Migrer **ProjectStats** (sonnet, 1210 lignes — peut nécessiter split)
- Source: `frontend/src/components/Projects/ProjectStats.ts`
- Statistiques et analytics du projet
- Si trop gros: split en 23a (charts) et 23b (data tables)

**Step 24.** Migrer **ProjectKnowledge** + **ProjectDocuments** (sonnet, 313 + 276 = 589 lignes — une passe)
- Source: `frontend/src/components/Projects/ProjectKnowledge.ts` + `ProjectDocuments.ts`
- Knowledge base, document viewer

### Phase 5D — Assemblage des pages

**Step 25.** Assembler **MainPage** (sonnet)
- Remplacer le stub dans router.tsx
- Composer: TopBar + ProjectHeader (hidden on Main) + view switching (ChatWindow | KanbanBoard | FreeBoard | ProjectList)
- Default view = ChatWindow
- Utiliser le même pattern que App.ts `switchView()`

**Step 26.** Assembler **ProjectPage** (sonnet)
- Remplacer le stub dans router.tsx
- Même layout que MainPage mais avec un projet sélectionné
- ProjectHeader visible avec view tabs
- Views: Chat, Kanban, Board, Knowledge, Stats, Docs

**Step 27.** Assembler **AppShell** complet (sonnet)
- Wirer: TabBar (top) → Sidebar (left) → MainArea (center) → WorkerPanel (right-middle) → RightPanel (far right)
- Responsive: sidebar toggle mobile, panel collapse
- Keyboard shortcuts globaux
- Toast notifications

### Phase 5E — Nettoyage

**Step 28.** Nettoyage et wiring final (sonnet)
- Supprimer `CardDetail/placeholders.tsx` (obsolète — les vrais composants sont déjà importés)
- Fixer le TODO dans `KanbanCard.tsx:189` (wirer chat routing)
- Nettoyer les commentaires outdated dans CardDetailModal.tsx
- Implémenter le "Clear All Data" dans DataPanel
- Vérifier tous les imports/exports

**Step 29.** Build final + type-check (sonnet)
- `npm run build` — fixer toute erreur
- `npx tsc --noEmit` — 0 type errors
- Lister les warnings restants
- Rapport final de couverture: quelles features sont 100% vs partielles

---

## Résumé

| Phase | Steps | Model | Estimé |
|-------|-------|-------|--------|
| 5A — Navigation | 16, 17, 18 | sonnet | ~10 min |
| 5B — Panels | 19, 20 | sonnet | ~8 min |
| 5C — Pages projet | 21, 22, 23, 24 | sonnet | ~15 min |
| 5D — Assemblage | 25, 26, 27 | sonnet | ~10 min |
| 5E — Nettoyage | 28, 29 | sonnet | ~5 min |
| **Total** | **14 steps** | **tout sonnet** | **~48 min** |

Tous les steps sont sonnet — ce sont des migrations directes ou de l'assemblage de composantes qui existent déjà.

---

*Branche: `refactor/react-frontend`*
