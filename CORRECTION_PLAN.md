# VoxyFlow — Plan de correction

> Audit du 1er avril 2026. Classement par priorite et severite.
> Chaque etape est independante sauf indication contraire.

---

## Phase 1 — Securite (CRITIQUE)

Ces correctifs doivent etre faits **avant tout deploiement** au-dela de localhost.

### ~~1.1 Retirer les cles API du code source~~ ✅

**Severite**: CRITIQUE — **DEJA FAIT**
- `settings.json` est dans `.gitignore` (ligne 58)
- `settings.json.example` existe avec de vrais placeholders

---

### ~~1.2 Restreindre la configuration CORS~~ ✅

**Severite**: CRITIQUE — **FAIT**
- `allow_origins=["*"]` remplace par `VOXYFLOW_CORS_ORIGINS` (env var)
- Default: `http://localhost:5173,http://localhost:3000`
- Pour Tailscale: setter `VOXYFLOW_CORS_ORIGINS` avec les IPs/hostnames Tailscale

---

### ~~1.3 Remplacer `create_subprocess_shell` par `create_subprocess_exec`~~ ✅

**Severite**: HAUTE — **FAIT**
- `backend/app/tools/system_tools.py` — `shlex` importé, `create_subprocess_exec(*shlex.split(command))` en place

---

### 1.4 Authentification locale (users/password/JWT)

**Severite**: MOYENNE — **REPORTÉ** (à faire avant d'ouvrir l'accès famille)
**Contexte**: Voxyflow est single-install sur machine contrôlée (Tailscale). Pas de cloud auth, pas de SSO, pas de LDAP.

**Décision**: Auth locale simple, auto-hébergée.

**Scope quand on s'y attaque**:
- Table `users` dans le SQLite existant (username + password bcrypt)
- Endpoint `/auth/login` qui retourne un JWT
- Middleware FastAPI qui valide le JWT sur toutes les routes
- Écran de login dans le frontend
- `useAuth.ts` branché sur le vrai flow

**Pour l'instant**: `isAuthenticated = true` dans `useAuth.ts` est intentionnel — l'auth réseau est déléguée à Tailscale pour les machines personnelles.

---

## Phase 2 — Splitter les fichiers monstres

Objectif: aucun fichier ne devrait depasser ~500 lignes.

### ~~2.1 Decouper `claude_service.py`~~ ✅ (2,767 → 1,041 lignes)

**Fichier**: `backend/app/services/claude_service.py`

**Modules extraits**:
- `services/llm/client_factory.py` — `_make_anthropic_client`, `_make_async_anthropic_client`, `_make_openai_client`
- `services/llm/model_utils.py` — `_LRUDict`, `_MODEL_MAP`, `_resolve_model`, `_strip_think_tags`, `_is_thinking_model`, `_inject_no_think`
- `services/llm/tool_defs.py` — `DELEGATE_ACTION_TOOL`, `INLINE_TOOLS`, `_execute_inline_tool`, `get_claude_tools`, `_call_mcp_tool`, etc.
- `services/llm/api_caller.py` — `ApiCallerMixin` avec les 9 méthodes `_call_api_*`
- `ClaudeService` hérite de `ApiCallerMixin` ✅

---

### ~~2.2 Decouper `chat_orchestration.py`~~ ✅ (2,656 → 1,593 lignes)

**Modules extraits**:
- `services/orchestration/worker_pool.py` — `DeepWorkerPool` + `_format_result_for_card` (~750 lignes)
- `services/orchestration/layer_runners.py` — `LayerRunnersMixin` avec `_run_fast_layer`, `_run_deep_chat_layer`, `_run_analyzer_layer`
- `ChatOrchestrator` hérite de `LayerRunnersMixin` ✅

---

### 2.3 Decouper `KanbanBoard.tsx` (1,049 lignes)

**Fichier**: `frontend-react/src/components/Kanban/KanbanBoard.tsx`

**Decoupage propose**:

| Nouveau fichier | Responsabilite |
|---|---|
| `Kanban/KanbanColumn.tsx` | Rendu d'une colonne individuelle |
| `Kanban/KanbanCardWrapper.tsx` | Wrapper de carte avec drag-drop |
| `Kanban/hooks/useDragDrop.ts` | Logique de drag-and-drop extraite |
| `Kanban/hooks/useKanbanFilters.ts` | Logique de filtrage |
| `Kanban/KanbanBoard.tsx` | Conteneur principal (devrait tomber a ~200 lignes) |

---

### 2.4 Decouper `ChatProvider.tsx` (946 lignes)

**Fichier**: `frontend-react/src/contexts/ChatProvider.tsx`

**Actions**:
1. Extraire les hooks custom dans des fichiers separes (`useChatSession.ts`, `useChatMessages.ts`)
2. Extraire la logique WebSocket dans un hook dedie (`useWebSocket.ts`) si pas deja fait
3. Le provider ne devrait contenir que le wiring entre les hooks

---

## Phase 3 — Error handling

### ~~3.1 Remplacer les `except Exception: pass` par du logging~~ ✅

**FAIT** — fichiers indépendants corrigés:
- `config.py`, `github.py`, `models.py`, `techdetect.py` → logger ajouté + pass remplacés
- `board_executor.py`, `scheduler_service.py`, `worker_session_store.py`, `pending_results.py`, `memory_service.py` → pass remplacés
- `chat_orchestration.py`, `llm/api_caller.py`, `orchestration/layer_runners.py` → 18 occurrences restantes corrigées après split Phase 2

---

### ~~3.2 Proteger le path WebSocket critique~~ ✅

**FAIT** — `backend/app/main.py` : `handle_message` wrappé dans try/except, erreur envoyée au client si orchestration plante.

---

### ~~3.3 Ajouter un Error Boundary React~~ ✅

**FAIT** — `ErrorBoundary.tsx` créé, wrappé autour de toute l'app dans `App.tsx`.

---

## Phase 4 — Configuration et constantes

### ~~4.1 Unifier les sources de configuration~~ ✅

**FAIT** — système à deux niveaux documenté dans `config.py`:
- **Tier 1** (infra): env vars > .env > defaults dans `config.py`
- **Tier 2** (app settings): DB > settings.json (auto-migration) > defaults

Constantes canoniques ajoutées dans `config.py`:
- `VOXYFLOW_DIR` (app: settings.json, personality, workspace) — respecte `VOXYFLOW_DIR` env var
- `VOXYFLOW_DATA_DIR` (data: DB, jobs, sessions) — respecte `VOXYFLOW_DATA_DIR` env var
- `SETTINGS_FILE` = `VOXYFLOW_DIR / "settings.json"`

`github.py` corrigé: utilisait `~/voxyflow` hardcodé sans env var, importe maintenant depuis `config.py`.

**Note**: les autres fichiers (`personality_service.py`, `claude_service.py`, etc.) définissent encore leur propre `VOXYFLOW_DIR` — migration complète lors du split Phase 2.

---

### ~~4.2 Extraire les magic strings en enums~~ ✅ (partiel)

**FAIT** — enums créés:
- `backend/app/models/enums.py`: `CardStatus`, `WorkerTaskStatus`, `WorkerSessionStatus`
- `frontend-react/src/constants/statuses.ts`: `CARD_STATUS`, `TASK_STATUS` (avec types TypeScript)
- `board_executor.py` migré pour utiliser `CardStatus`

**Reporté à Phase 2** — remplacement complet dans `claude_service.py`, `chat_orchestration.py`, `projects.py`, `KanbanBoard.tsx`.

---

### ~~4.3 Eliminer les localhost hardcodes~~ ✅

**FAIT** — vrais hardcodes corrigés:
- `routes/models.py` : utilise maintenant `get_settings().claude_proxy_url`
- `claude_service.py` : fallback utilise maintenant `get_settings().claude_proxy_url`

**Non-problèmes confirmés**:
- `config.py` : c'est le default déclaré, overridable via env var `CLAUDE_PROXY_URL` ✅
- `mcp_server.py` : déjà derrière `VOXYFLOW_API_BASE` env var ✅
- `routes/settings.py` : defaults de l'UI Settings, configurables par l'utilisateur ✅
- `scheduler_service.py:163-164` : dans un commentaire, pas du code ✅

---

## Phase 5 — Performance et qualite frontend

### ~~5.1 Ajouter le virtual scrolling pour les messages~~ ✅

**DÉJÀ FAIT** — `MessageList.tsx` utilise `useVirtualizer` de `@tanstack/react-virtual`.

---

### ~~5.2 Optimiser le card store avec Immer~~ ✅

**FAIT** — `useCardStore.ts` refactorisé avec `immer` middleware de zustand.
- `immer` installé (`npm install immer`)
- Toutes les mutations utilisent maintenant le pattern draft : `set((state) => { state.cardsById[id] = card; })`

---

### 5.3 Ajouter la pagination cote API

**Fichiers**: routes backend qui retournent des listes (cards, messages, projects)

**Actions**:
1. Ajouter des parametres `?page=1&per_page=50` aux endpoints de liste
2. Retourner un objet `{ items: [], total: N, page: N, per_page: N }`
3. Adapter le frontend pour charger par page ou en infinite scroll

---

## Phase 6 — Architecture et patterns

### 6.1 Remplacer les singletons par de l'injection de dependances

**Fichiers concernes**: tous les `get_*_service()` dans `backend/app/`

**Actions**:
1. Utiliser le systeme de `Depends()` de FastAPI:
```python
async def get_rag(rag: RAGService = Depends(get_rag_service)):
    ...
```
2. Cela rend les services mockables pour les tests
3. Migration incrementale: un service a la fois

---

### 6.2 Consolider la factory de clients API

**Fichier**: `backend/app/services/claude_service.py`

**Avant**: 3 fonctions quasi-identiques (`_make_anthropic_client`, `_make_async_anthropic_client`, `_make_openai_client`)

**Apres**: une seule factory:
```python
def make_llm_client(provider: str, *, async_mode: bool = True) -> Any:
    if provider == "anthropic":
        cls = AsyncAnthropic if async_mode else Anthropic
        return cls(api_key=..., base_url=...)
    elif provider == "openai":
        return AsyncOpenAI(api_key=..., base_url=...)
    raise ValueError(f"Unknown provider: {provider}")
```

---

### 6.3 Migrer vers Alembic pour les migrations DB

**Fichier actuel**: `backend/app/database.py` (lignes ~47-157) — raw SQL a chaque startup

**Actions**:
1. `pip install alembic` + `alembic init migrations`
2. Generer une migration initiale a partir du schema SQLAlchemy actuel
3. Convertir les migrations manuelles existantes en scripts Alembic
4. Supprimer le code de migration ad-hoc de `init_db()`
5. Documenter: `alembic upgrade head` dans le README

---

## Phase 7 — Nettoyage et hygiene

### ~~7.1 Supprimer le code commente~~ ✅

**FAIT** — `requirements.txt` : `sherpa-onnx` et `faster-whisper` supprimés (optionnels, jamais activés).

---

### 7.2 Mettre a jour les commentaires menteurs

**Fichiers concernes**:
- `backend/app/main.py` ligne ~173: changer "single-user, localhost" pour reflete la realite
- `frontend-react/src/hooks/useAuth.ts`: avertir clairement que l'auth est bypassee
- Tout commentaire qui dit "TODO" ou "temporary" depuis plus de 3 mois: le faire ou le supprimer

---

### 7.3 Uniformiser les messages d'erreur API

**Regle a appliquer**:
- Toujours utiliser `{"detail": "Message"}` comme format d'erreur
- Toujours terminer par un point
- Utiliser des termes coherents: "Project" (pas "Repository"), "Chat" (pas "Conversation")

---

### ~~7.4 Retirer les imports avec underscore inutiles~~ ✅

**FAIT** — `backend/app/main.py` :
- `import os as _os` → `import os` (déplacé en tête de fichier)
- `from logging.handlers import RotatingFileHandler as _RotatingFileHandler` → import normal
- `import os as _os_cors` supprimé (réutilise le `os` déjà importé)

---

## Ordre d'execution recommande

```
✅ Phase 1 (securite)          — FAIT (2026-04-01)
✅ Phase 2 (split fichiers)     — FAIT (2026-04-02)
✅ Phase 3 (error handling)     — FAIT (2026-04-02)
✅ Phase 4 (config/constantes)  — FAIT partiel (2026-04-02) — remplacement enums complet en Phase 2
→  Phase 5 (performance)        — Virtual scrolling, pagination
   Phase 6 (architecture)       — Scalabilite
   Phase 7 (nettoyage)          — Au fur et a mesure
```

---

## Suivi

| Phase | Status | Date completee |
|---|---|---|
| 1 — Securite | ✅ (3/4 — auth reportée) | 2026-04-01 |
| 2 — Split fichiers | ✅ (claude_service: 2767→1041, chat_orchestration: 2656→1593) | 2026-04-02 |
| 3 — Error handling | ✅ (complet) | 2026-04-02 |
| 4 — Config/constantes | ✅ (partiel — remplacement complet des enums en Phase 2) | 2026-04-02 |
| 5 — Performance frontend | 🔄 (5.1+5.2 ✅, 5.3 pagination TODO) | 2026-04-02 |
| 6 — Architecture | TODO | |
| 7 — Nettoyage | TODO | |
