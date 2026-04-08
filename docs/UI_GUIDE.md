# Voxyflow — Guide de l'interface utilisateur

> Ce guide décrit chaque vue de Voxyflow : ce qu'elle montre, comment y accéder, et les actions disponibles. Il est conçu pour les nouveaux utilisateurs, les contributeurs, et l'IA intégrée (Voxy) qui s'en sert pour répondre à des questions du type "comment faire X ?".

---

## Table des matières

1. [Navigation et structure générale](#1-navigation-et-structure-générale)
2. [Vue Chat](#2-vue-chat)
3. [Vue Kanban](#3-vue-kanban)
4. [Vue FreeBoard (Board)](#4-vue-freeboard-board)
5. [Vue Knowledge (Documents, Wiki, RAG)](#5-vue-knowledge-documents-wiki-rag)
6. [Vue Stats (projets uniquement)](#6-vue-stats-projets-uniquement)
7. [Card Detail Modal](#7-card-detail-modal)
8. [Opportunities et Notifications](#8-opportunities-et-notifications)
9. [WorkerPanel — Suivi des workers](#9-workerpanel--suivi-des-workers)
10. [Settings](#10-settings)
11. [Onboarding](#11-onboarding)
12. [Jobs et Scheduler](#12-jobs-et-scheduler)
13. [Raccourcis clavier — Référence complète](#13-raccourcis-clavier--référence-complète)

---

## 1. Navigation et structure générale

### Structure globale (AppShell)

L'interface se compose de quatre zones fixes :

- **Sidebar** — colonne gauche, navigation principale
- **TabBar** — barre horizontale en haut, onglets ouverts
- **ProjectHeader** — sous la TabBar, titre du projet et onglets de vue
- **Contenu principal** — zone centrale, change selon la vue active
- **Drawers droits** — panneaux glissants (Opportunities, Notifications)

### Sidebar

La sidebar est la colonne de navigation principale, accessible via `Ctrl+B` pour l'afficher ou la masquer. Sur mobile, elle s'affiche en overlay et se ferme automatiquement après un clic.

**Sections de haut en bas :**

| Section | Description |
|---------|-------------|
| Logo | Voxyflow — identifiant de l'application |
| Main | Lien vers l'onglet principal (vue générale) |
| Jobs | Lien vers la page de gestion des tâches planifiées |
| Projects | Lien vers la liste complète des projets |
| Favoris | Projets marqués comme favoris, avec un point de progression coloré |
| New Project | Bouton de création rapide de projet |
| WorkerPanel | Arbre des sessions et workers actifs (voir section 9) |
| Statut de connexion | Point coloré : vert = connecté, jaune = reconnexion, rouge = déconnecté |
| Footer | Cloche notifications, bascule thème, Settings, Documentation, Aide |

**Points de progression (favoris) :**

Chaque projet favori affiche un point coloré qui indique l'avancement global :
- Vert : 100 % des cartes terminées
- Jaune : 50 % ou plus terminées
- Bleu : au moins une carte terminée
- Gris : aucune carte terminée

Au survol, une info-bulle affiche le détail : nombre de cartes, done, in progress, pourcentage.

**Footer de la sidebar :**
- Cloche avec badge rouge = notifications non lues (clic → drawer Notifications)
- Soleil/Lune = bascule thème clair/sombre
- Engrenage = Settings
- Livre = Documentation
- Point d'interrogation = Aide

### TabBar

La TabBar est la barre horizontale en haut de l'écran. Elle gère les onglets ouverts.

- **Onglet Main** — toujours présent, non fermable, donne accès aux vues générales
- **Onglets projet** — s'ouvrent en cliquant sur un projet (sidebar ou liste), fermables avec `×` ou `Ctrl+W`
- **Bouton "+"** — ouvre la liste des projets pour en ajouter un onglet
- **Badge opportunités** — indique le nombre de suggestions IA en attente
- **Cloche** — accès rapide aux notifications

Naviguer entre les onglets : `Ctrl+Tab`

### ProjectHeader

Affiché sous la TabBar quand un projet ou le Main est actif. Contient :
- Emoji et nom du projet (ou "Main" pour l'onglet principal)
- Onglets de vue selon le contexte :
  - **Main** : Chat, Kanban, Board, Knowledge
  - **Projet** : Chat, Kanban, Board, Knowledge, Stats

Cliquer sur un onglet de vue change le contenu principal sans changer d'onglet.

---

## 2. Vue Chat

### Accès

- **Chat général** : onglet Main → onglet "Chat" dans le ProjectHeader
- **Chat projet** : onglet d'un projet → onglet "Chat"
- **Chat carte** : depuis la Card Detail Modal (colonne centrale)

### Contextes du chat — les 3 niveaux

Le contexte du chat change automatiquement selon ce qui est sélectionné dans l'interface. Il n'y a rien à configurer manuellement.

| Niveau | Déclencheur | Ce que Voxy peut faire |
|--------|-------------|------------------------|
| **Général** | Onglet Main actif, aucune carte sélectionnée | Gérer les cartes du Main Board, créer des projets, recherche web, commandes système, planifier des jobs |
| **Projet** | Onglet d'un projet actif, aucune carte sélectionnée | Tout ce que le niveau général fait + gérer les cartes du projet, wiki, documents, opérations IA (standup, brief, health, prioritize) |
| **Carte** | Une carte est ouverte dans la Card Detail Modal | Tout ce que le niveau projet fait + assistance ciblée sur la tâche, gestion checklist, implémentation |

Chaque niveau a son propre historique isolé. Changer de contexte ne supprime pas l'historique précédent.

### Composants du chat

- **MessageList** — liste des messages du fil actif, avec rendu markdown
- **ChatInput** — zone de saisie en bas, supporte le texte et les commandes slash
- **SessionTabBar** — onglets de sessions (jusqu'à 5 par contexte), visible sous le header
- **ModePill** — bascule entre les modes d'analyse :
  - **Deep** — active le modèle de raisonnement approfondi
  - **Analyzer** — active l'analyse IA en parallèle (opportunités, suggestions)
- **SmartSuggestions** — chips de suggestions rapides, contextuelles (changent selon le niveau chat)
- **VoiceInput** — saisie vocale push-to-talk (`Alt+V` maintenu)

### Message de bienvenue (WelcomePrompt)

Chaque contexte affiche un message de bienvenue adapté avec des boutons d'action rapide :

- **Général** : "Hey ! Qu'est-ce qu'on fait ?" + 4 options (Just chatting, Work on a project, Brainstorm, Review tasks)
- **Projet** : nom du projet + statut (X in progress, Y todo) + boutons de reprise des cartes en cours
- **Carte** : titre de la carte + agent assigné + statut + priorité + actions ciblées (Start working, Enrich, Research, Edit, Discuss)

### Sessions

Chaque contexte (général, projet, carte) supporte plusieurs sessions indépendantes, accessibles via la SessionTabBar. Une session = un fil de conversation séparé. Limite : 5 sessions par contexte.

Actions sur les sessions :
- Créer une nouvelle session : `/new` ou bouton "+" dans la SessionTabBar
- Vider l'historique de la session courante : `/clear`

### Slash commands

Tapez `/` dans le champ de saisie pour déclencher une commande :

| Commande | Action |
|----------|--------|
| `/new` | Crée une nouvelle session dans le contexte actuel |
| `/clear` | Vide l'historique de la session courante |
| `/help` | Affiche l'aide des commandes disponibles |
| `/agent [nom]` | Change l'agent IA actif pour la session |
| `/meeting` | Lance un assistant de prise de notes de réunion |
| `/standup` | Génère un standup à partir des cartes du projet actif |

### Raccourcis clavier (vue Chat)

| Raccourci | Action |
|-----------|--------|
| `Alt+V` (maintenu) | Push-to-Talk — saisie vocale |
| `Ctrl+Shift+F` | Recherche dans l'historique du chat |

---

## 3. Vue Kanban

### Accès

- Onglet Main → "Kanban" dans le ProjectHeader
- Onglet d'un projet → "Kanban"

### Ce qu'elle montre

Tableau à 4 colonnes représentant le cycle de vie des cartes :

| Colonne | Description |
|---------|-------------|
| **Idea** | Idées brutes, non planifiées |
| **Todo** | Tâches planifiées, prêtes à démarrer |
| **In Progress** | Tâches en cours |
| **Done** | Tâches terminées |

Chaque carte affiche : titre, priorité, agent assigné, tags, et indicateurs visuels (couleur de fond, badge récurrence, progression checklist).

### Actions principales

- **Déplacer une carte** — drag & drop entre colonnes, ou via les boutons de statut dans la Card Detail Modal
- **Ouvrir une carte** — clic sur une carte → Card Detail Modal
- **Créer une carte** — bouton "+" dans l'en-tête d'une colonne
- **Filtrer les cartes** — barre de filtres en haut : recherche texte, priorité, agent assigné, tags
- **Actions groupées (bulk)** — sélectionner plusieurs cartes (case à cocher) → déplacer, supprimer, assigner un agent en lot
- **En-tête Kanban** — boutons d'actions rapides : créer une carte, lancer une analyse IA, trier

---

## 4. Vue FreeBoard (Board)

### Accès

- Onglet Main → "Board" dans le ProjectHeader
- Onglet d'un projet → "Board"

### Ce qu'elle montre

Un espace de type tableau blanc avec des sticky notes colorées. Chaque note est indépendante du Kanban. C'est un espace de brainstorming rapide, sans workflow imposé.

**6 couleurs disponibles** : jaune, bleu, vert, rose, violet, orange.

### Actions principales

- **Créer une note** — formulaire de saisie rapide en haut (titre + couleur + clic "Add")
- **Supprimer une note** — bouton de suppression sur la note
- **Promouvoir une note en carte Kanban** — bouton "Promote" sur la note → transforme la sticky note en carte Kanban complète dans la colonne "Idea"
- **Filtrer les notes** — même barre de filtres que le Kanban (recherche, priorité, agent, tags)

---

## 5. Vue Knowledge (Documents, Wiki, RAG)

### Accès

- Onglet Main → "Knowledge" dans le ProjectHeader
- Onglet d'un projet → "Knowledge"

### Ce qu'elle montre

Trois onglets pour gérer la base de connaissances :

#### Documents

Upload et gestion de fichiers. Formats supportés : `.txt`, `.md`, `.pdf`, `.docx`, `.xlsx`.

Actions :
- Glisser-déposer un fichier dans la zone d'upload, ou cliquer pour sélectionner
- Voir la liste des documents indexés avec leur statut
- Supprimer un document

Les documents uploadés sont automatiquement indexés dans la collection RAG du contexte (général ou projet), ce qui permet à Voxy de les citer en réponse à des questions.

#### Wiki

Pages markdown éditables, organisées par projet. Chaque projet a son propre wiki.

Actions :
- Créer une nouvelle page
- Éditer une page existante (éditeur markdown intégré)
- Naviguer entre les pages

#### RAG Status

Tableau de bord de la collection vectorielle :
- Nombre de documents indexés
- Nombre de chunks
- Statut de la collection (active, vide, en cours d'indexation)
- Statistiques d'utilisation

---

## 6. Vue Stats (projets uniquement)

### Accès

Onglet d'un projet → "Stats" dans le ProjectHeader. Cette vue n'est pas disponible dans l'onglet Main.

### Ce qu'elle montre

Tableau de bord analytique du projet, organisé en sections :

| Section | Contenu |
|---------|---------|
| **Progress ring** | Anneau de progression global (% cartes terminées) |
| **Distribution** | Répartition des cartes par colonne (Idea / Todo / In Progress / Done) |
| **Velocity** | Graphiques de vélocité sur les dernières périodes |
| **Standup** | Résumé quotidien auto-généré. Bouton "Generate" pour lancer l'IA |
| **Brief** | Résumé exécutif du projet généré par l'IA |
| **Health** | Score de santé du projet + recommandations priorisées |
| **Priority** | Backlog priorisé par l'IA — les cartes à traiter en premier selon les dépendances et la valeur |
| **Focus** | Statistiques Pomodoro — temps de concentration, sessions complétées |

Le Standup, le Brief, le Health score et la priorisation du backlog sont générés à la demande via les boutons correspondants.

---

## 7. Card Detail Modal

### Accès

Cliquer sur n'importe quelle carte (Kanban ou FreeBoard) ouvre la Card Detail Modal.

### Ce qu'elle montre

**Sur desktop : 3 colonnes côte à côte**

| Colonne | Contenu |
|---------|---------|
| **Gauche — Description** | Éditeur de description (CodeMirror), markdown complet |
| **Centre — Chat carte** | Chat intégré, scoped à cette carte uniquement. Voxy voit le contenu de la carte |
| **Droite — Métadonnées** | Sidebar de configuration de la carte |

**Sur mobile : 3 onglets** (Description / Chat / Details) pour naviguer entre les mêmes contenus.

### Sidebar de métadonnées (colonne droite)

| Élément | Description |
|---------|-------------|
| **Titre** | Champ texte éditable inline |
| **StatusButtons** | Boutons de statut : Idea → Todo → In Progress → Done |
| **AgentSelector** | Choisir quel agent IA est assigné à la carte |
| **Tags** | Ajouter/supprimer des tags libres |
| **Couleur** | 6 couleurs de fond pour la carte |
| **ProjectPicker** | Déplacer la carte vers un autre projet |
| **RecurrenceSection** | Programmer la récurrence : 15min, 30min, hourly, 6hours, daily, weekdays, weekly, biweekly, monthly, ou cron personnalisé |
| **ChecklistSection** | Liste de tâches internes à la carte, avec barre de progression |
| **AttachmentsSection** | Pièces jointes par glisser-déposer |
| **LinkedFiles** | Fichiers liés (référencés, pas uploadés) |
| **DependenciesSection** | Dépendances entre cartes |
| **RelationsSection** | Relations typées : blocks, blocked_by, relates_to, duplicates |
| **HistorySection** | Journal d'audit — toutes les modifications horodatées |

### Actions dans la modal

- **Archiver** — bouton Archive (icône) → retire la carte du Kanban sans supprimer
- **Exécuter** — bouton Play → lance un worker IA sur la carte
- **Fermer** — touche `Échap` ou clic en dehors de la modal

---

## 8. Opportunities et Notifications

### Drawer Opportunities

**Accès** : badge dans la TabBar (nombre de suggestions en attente), ou via le bouton dédié.

**Ce qu'il montre** : suggestions de cartes générées automatiquement par l'Analyzer IA. L'Analyzer analyse le contexte du projet et propose des tâches manquantes, des risques, ou des actions à prendre.

**Actions** :
- **Create Card** — crée directement la carte suggérée dans le projet
- **Dismiss** — ignore la suggestion

### Drawer Notifications

**Accès** : cloche dans le footer de la sidebar (avec badge rouge si non lues) ou cloche dans la TabBar.

**Ce qu'il montre** : liste des événements récents :
- Carte créée, déplacée, enrichie
- Document indexé
- Session Focus terminée
- Résultat de worker

**Actions** :
- **Open Card** — ouvre directement la carte concernée
- **View in Opportunities** — bascule vers le drawer Opportunities
- **Mark all read** — marque toutes les notifications comme lues
- **Clear all** — efface toutes les notifications

---

## 9. WorkerPanel — Suivi des workers

### Accès

Le WorkerPanel est intégré dans la sidebar, sous la section de navigation principale. Il est toujours visible quand la sidebar est ouverte.

### Ce qu'il montre

Arbre hiérarchique des activités en cours :

```
Projet A
  └── Session #1
        ├── Worker: [claude] Enriching card "Build auth module"  [2m 14s]  running
        └── Worker: [haiku] Indexing document                   [0m 45s]  done
Projet B
  └── Session #2
        └── Worker: [opus] Deep analysis                        [5m 02s]  running
```

Par worker, on voit :
- Emoji indiquant le modèle utilisé
- Type d'action (enrichissement, indexation, analyse, exécution...)
- Temps écoulé depuis le démarrage
- Statut : `running` (en cours), `done` (terminé), `failed` (erreur)

### Actions sur les workers

- **Steer** — envoyer une instruction au worker en cours pour guider ou corriger son travail
- **Cancel** — annuler un worker en cours d'exécution

---

## 10. Settings

### Accès

- Icône engrenage dans le footer de la sidebar
- Route `/settings`

### Ce qu'il montre

Page de configuration complète, avec une sidebar de navigation interne à gauche et 9 panneaux :

| Panneau | Contenu |
|---------|---------|
| **Appearance** | Thème (clair/sombre), taille de police (small/medium/large) |
| **Personality** | Nom de l'assistant, ton, chaleur, langue préférée. Éditeur de fichiers : SOUL.md, USER.md, AGENTS.md, IDENTITY.md |
| **Models** | Configuration des 3 couches IA : Fast (réponses rapides), Deep (raisonnement), Analyzer (analyse parallèle). Pour chaque couche : URL du provider, clé API, modèle |
| **Voice & STT** | Configuration de la reconnaissance vocale (moteur STT) |
| **GitHub** | Intégration GitHub : token, repo par défaut |
| **Workspace** | Paramètres de l'espace de travail |
| **Data** | Export et import des données (projets, cartes, historique) |
| **Jobs** | Scheduler de tâches planifiées (alias du panneau Jobs) |
| **About** | Version, informations système, licences |

**Panneau Personality — fichiers éditables** :

| Fichier | Rôle |
|---------|------|
| `SOUL.md` | Personnalité centrale de l'assistant |
| `USER.md` | Informations sur l'utilisateur (préférences, contexte) |
| `AGENTS.md` | Définition des agents IA disponibles |
| `IDENTITY.md` | Identité et comportements de l'assistant |

---

## 11. Onboarding

### Accès

Automatique au premier lancement de l'application, avant l'accès à l'interface principale. Non accessible manuellement depuis l'UI une fois complété (les réglages sont ensuite modifiables depuis Settings).

### Ce qu'il montre

Formulaire de configuration initiale en une seule page scrollable :

| Champ | Description |
|-------|-------------|
| **Votre nom** | Utilisé par l'assistant pour vous appeler |
| **Nom de l'assistant** | Nom de Voxy (défaut : "Voxy") |
| **API URL** | URL du backend LLM (défaut : proxy local) |
| **API Key** | Clé d'accès à l'API |
| **Fast model** | Modèle rapide pour les réponses courtes |
| **Deep model** | Modèle de raisonnement pour les tâches complexes |
| **Thème** | Clair ou sombre |
| **Taille de police** | Small, Medium, Large |

Une fois le formulaire validé, l'application démarre et redirige vers la vue principale.

---

## 12. Jobs et Scheduler

### Accès

- Lien "Jobs" dans la sidebar
- Route `/jobs`
- Panneau "Jobs" dans les Settings

### Ce qu'il montre

Liste de toutes les tâches planifiées (jobs). Chaque job peut être déclenché manuellement ou s'exécuter selon une planification cron.

### Types de jobs

| Type | Description |
|------|-------------|
| `reminder` | Rappel à une heure donnée |
| `rag_index` | Réindexation automatique des documents |
| `board_run` | Exécution automatique de cartes marquées récurrentes |
| `github_sync` | Synchronisation avec un dépôt GitHub |
| `custom` | Job personnalisé avec commande arbitraire |

### Actions

- **Créer** — bouton "New Job" → formulaire : nom, type, planification cron, paramètres
- **Éditer** — modifier un job existant
- **Supprimer** — supprimer définitivement un job
- **Lancer manuellement** — bouton "Run" sur un job → exécution immédiate sans attendre la prochaine occurrence

---

## 13. Raccourcis clavier — Référence complète

| Raccourci | Action |
|-----------|--------|
| `Ctrl+B` | Afficher / masquer la sidebar |
| `Ctrl+K` | Ouvrir la command palette |
| `Ctrl+W` | Fermer l'onglet projet actif (non applicable à l'onglet Main) |
| `Ctrl+Tab` | Naviguer vers l'onglet suivant |
| `Alt+V` (maintenu) | Push-to-Talk — saisie vocale dans le chat |
| `Ctrl+Shift+F` | Recherche dans l'historique du chat actif |
| `?` | Ouvrir la modal des raccourcis clavier (liste complète) |
| `Échap` | Fermer la modal ou le drawer actif |

> Appuyez sur `?` depuis n'importe quelle vue pour afficher la liste complète des raccourcis disponibles dans le contexte courant.

---

_Guide généré pour Voxyflow — avril 2026._
