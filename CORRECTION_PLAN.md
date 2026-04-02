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

### 2.1 Decouper `claude_service.py` (2,767 lignes)

**Fichier**: `backend/app/services/claude_service.py`

**Decoupage propose**:

| Nouveau fichier | Responsabilite | Lignes approximatives a extraire |
|---|---|---|
| `services/llm/client_factory.py` | Creation des clients Anthropic/OpenAI | `_make_anthropic_client`, `_make_async_anthropic_client`, `_make_openai_client` |
| `services/llm/model_router.py` | Selection du modele selon le layer (fast/deep/analyzer) | Logique de routing des modeles |
| `services/llm/message_handler.py` | Construction et envoi des messages | Preparation des prompts, streaming |
| `services/llm/tool_executor.py` | Execution des tools et parsing des resultats | Tool calls, delegation |
| `services/llm/cache_manager.py` | Gestion du cache et de l'historique | Cache prompt, history management |

**Etapes**:
1. Creer le dossier `backend/app/services/llm/`
2. Extraire chaque module un a la fois, en gardant les imports fonctionnels
3. `claude_service.py` devient un facade mince qui delegue aux sous-modules
4. Tester apres chaque extraction (pas tout d'un coup)

---

### 2.2 Decouper `chat_orchestration.py` (2,656 lignes)

**Fichier**: `backend/app/services/chat_orchestration.py`

**Decoupage propose**:

| Nouveau fichier | Responsabilite |
|---|---|
| `services/orchestration/fast_layer.py` | Logique du mode Fast |
| `services/orchestration/deep_layer.py` | Logique du mode Deep |
| `services/orchestration/analyzer_layer.py` | Logique de l'Analyzer |
| `services/orchestration/delegate_handler.py` | Parsing et execution des blocs delegate |
| `services/orchestration/event_bus.py` | Systeme d'evenements interne |

**Meme approche**: extraction incrementale, test apres chaque etape.

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

### ~~3.1 Remplacer les `except Exception: pass` par du logging~~ ✅ (partiel)

**FAIT** — fichiers indépendants corrigés:
- `config.py`, `github.py`, `models.py`, `techdetect.py` → logger ajouté + pass remplacés
- `board_executor.py`, `scheduler_service.py`, `worker_session_store.py`, `pending_results.py`, `memory_service.py` → pass remplacés

**Reporté à Phase 2** — `claude_service.py` et `chat_orchestration.py` (~40 occurrences restantes) seront traités lors du split de ces fichiers.

---

### ~~3.2 Proteger le path WebSocket critique~~ ✅

**FAIT** — `backend/app/main.py` : `handle_message` wrappé dans try/except, erreur envoyée au client si orchestration plante.

---

### ~~3.3 Ajouter un Error Boundary React~~ ✅

**FAIT** — `ErrorBoundary.tsx` créé, wrappé autour de toute l'app dans `App.tsx`.

---

## Phase 4 — Configuration et constantes

### 4.1 Unifier les sources de configuration

**Probleme**: 5 sources (env vars, `.env`, `settings.json`, DB, hardcode).

**Solution**: Etablir une hierarchie claire et documentee:

```
Priorite (la plus haute gagne):
1. Variables d'environnement (override runtime)
2. Base de donnees app_settings (config utilisateur persistee)
3. settings.json (config fichier local)
4. Valeurs par defaut dans config.py (fallback)
```

**Actions**:
1. Documenter cette hierarchie dans `backend/app/config.py` en commentaire de tete
2. Creer une fonction `get_setting(key)` centralisee qui respecte cette priorite
3. Supprimer les lectures ad-hoc de settings.json eparpillees dans le code

---

### 4.2 Extraire les magic strings en enums

**Fichiers concernes**: `database.py`, `KanbanBoard.tsx`, routes diverses

**Actions**:

Backend — creer `backend/app/models/enums.py`:
```python
from enum import StrEnum

class CardStatus(StrEnum):
    IDEA = "idea"
    TODO = "todo"
    IN_PROGRESS = "in-progress"
    DONE = "done"
    CARD = "card"

class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
```

Frontend — creer `frontend-react/src/constants/statuses.ts`:
```typescript
export const CARD_STATUS = {
  IDEA: "idea",
  TODO: "todo",
  IN_PROGRESS: "in-progress",
  DONE: "done",
} as const;
```

Remplacer toutes les strings hardcodees par les enums/constantes.

---

### 4.3 Eliminer les localhost hardcodes

**Fichiers concernes**:
- `backend/app/config.py` (ligne ~73)
- `backend/app/services/scheduler_service.py` (lignes ~163-164)
- `backend/app/routes/models.py` (ligne ~117)
- `backend/app/routes/settings.py` (lignes ~79, 85, 91)

**Action**: Remplacer chaque occurrence par une lecture de `config.py` ou d'une variable d'environnement:
```python
# config.py
api_base_url: str = os.environ.get("VOXYFLOW_API_BASE", "http://localhost:3457/v1")
```

Puis utiliser `settings.api_base_url` partout au lieu de la string hardcodee.

---

## Phase 5 — Performance et qualite frontend

### 5.1 Ajouter le virtual scrolling pour les messages

**Fichier**: `frontend-react/src/components/Chat/MessageList.tsx`

**Actions**:
1. `@tanstack/react-virtual` est deja installe — l'utiliser
2. Implementer un `useVirtualizer` pour la liste de messages
3. Tester avec 1000+ messages pour valider la fluidite

---

### 5.2 Optimiser le card store avec Immer

**Fichier**: `frontend-react/src/stores/useCardStore.ts`

**Avant**:
```typescript
set((state) => ({
  cardsById: { ...state.cardsById, [card.id]: card },
}));
```

**Apres**:
```typescript
// Dans la creation du store, ajouter le middleware Immer
import { immer } from "zustand/middleware/immer";

// Puis:
set((state) => {
  state.cardsById[card.id] = card;
});
```

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

### 7.1 Supprimer le code commente

**Fichiers concernes**: `requirements.txt` (lignes ~20-24), et tout autre fichier avec du code commente

**Regle**: si c'est commente depuis plus de 2 semaines et jamais utilise, supprimer. Git garde l'historique.

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

### 7.4 Retirer les imports avec underscore inutiles

**Fichier**: `backend/app/main.py` (lignes ~39-40)

```python
# AVANT
import os as _os
from logging.handlers import RotatingFileHandler as _RotatingFileHandler

# APRES
import os
from logging.handlers import RotatingFileHandler
```

---

## Ordre d'execution recommande

```
✅ Phase 1 (securite)          — FAIT (2026-04-01)
✅ Phase 3 (error handling)     — FAIT partiel (2026-04-02) — reste: claude_service + chat_orchestration en Phase 2
→  Phase 4 (config/constantes)  — Prochaine étape
   Phase 2 (split fichiers)     — Apres Phase 4
   Phase 5 (performance)        — UX
   Phase 6 (architecture)       — Scalabilite
   Phase 7 (nettoyage)          — Au fur et a mesure
```

---

## Suivi

| Phase | Status | Date completee |
|---|---|---|
| 1 — Securite | ✅ (3/4 — auth reportée) | 2026-04-01 |
| 2 — Split fichiers | TODO | |
| 3 — Error handling | ✅ (partiel — gros fichiers en Phase 2) | 2026-04-02 |
| 4 — Config/constantes | TODO | |
| 5 — Performance frontend | TODO | |
| 6 — Architecture | TODO | |
| 7 — Nettoyage | TODO | |
