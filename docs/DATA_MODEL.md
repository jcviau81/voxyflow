# DATA MODEL — Entities & Relationships

> Every entity in Voxyflow, its fields, its relationships, and its persistence layer.

---

## Entity Relationship Overview

```
Project 1───* Card
Project 1───* WikiPage
Project 1───* Document
Project 1───* Sprint
Project 1───* Chat

Card 1───* CardComment
Card 1───* TimeEntry
Card 1───* ChecklistItem
Card 1───* CardAttachment
Card 1───* CardRelation (source or target)
Card 1───* CardHistory
Card *───1 Sprint (optional)

Chat 1───* Message

FocusSession *───1 Card (optional)
FocusSession *───1 Project (optional)
```

---

## Card

The central entity. Everything is a Card — whether in the Home project (system) or in a regular Project.

### SQLAlchemy Model

```python
class CardTask(Base):
    __tablename__ = "cards"

    id              = Column(String, primary_key=True, default=uuid4)
    project_id      = Column(String, ForeignKey("projects.id"), nullable=True)  # legacy: null = Home (now migrated to "system-main")
    title           = Column(String, nullable=False)
    description     = Column(Text, default="")
    status          = Column(String, default="card")    # card|todo|in-progress|done|archived
    priority        = Column(Integer, default=0)        # 0=none, 1=low, 2=medium, 3=high, 4=critical
    color           = Column(String, nullable=True)     # yellow|blue|green|pink|purple|orange
    position        = Column(Integer, default=0)        # Sort order within column
    agent_type      = Column(String, nullable=True)     # ember|researcher|coder|designer|architect|writer|qa
    agent_assigned  = Column(String, nullable=True)     # Display name of assigned agent
    agent_context   = Column(Text, nullable=True)       # Context for agent execution
    assignee        = Column(String, nullable=True)     # Human assignee name
    watchers        = Column(String, nullable=True)     # Comma-separated watcher names
    votes           = Column(Integer, default=0)
    sprint_id       = Column(String, ForeignKey("sprints.id"), nullable=True)
    recurrence      = Column(String, nullable=True)     # daily|weekly|monthly
    recurrence_next = Column(String, nullable=True)     # ISO date of next recurrence
    created_at      = Column(DateTime, default=utcnow)
    updated_at      = Column(DateTime, default=utcnow, onupdate=utcnow)
```

### Pydantic Schemas

```python
class CardCreate(BaseModel):
    title: str
    description: str = ""
    status: str = "card"            # card|todo|in-progress|done
    priority: int = 0               # 0-4
    color: str | None = None
    agent_type: str | None = None
    agent_context: str | None = None
    recurrence: str | None = None
    recurrence_next: str | None = None
    dependency_ids: list[str] = []

class CardUpdate(BaseModel):        # All fields optional
    title: str | None
    description: str | None
    status: str | None              # card|todo|in-progress|done|archived
    priority: int | None            # 0-4
    color: str | None
    agent_type: str | None
    agent_context: str | None
    assignee: str | None
    watchers: str | None
    votes: int | None
    sprint_id: str | None
    recurrence: str | None
    recurrence_next: str | None

class CardResponse(BaseModel):
    id: str
    project_id: str | None
    title: str
    description: str
    status: str
    priority: int
    color: str | None
    position: int
    agent_type: str | None
    agent_assigned: str | None
    agent_context: str | None
    dependency_ids: list[str]
    total_minutes: int
    checklist_progress: ChecklistProgress | None
    assignee: str | None
    watchers: str | None
    votes: int
    sprint_id: str | None
    recurrence: str | None
    recurrence_next: str | None
    created_at: datetime
    updated_at: datetime
```

### Status Values

| Status | Where | Meaning |
|--------|-------|---------|
| `card` | Backlog | Backlog card (freeboard view) |
| `todo` | Kanban | Ready for work |
| `in-progress` | Kanban | Currently active |
| `done` | Kanban | Completed |
| `archived` | Both | Hidden from active views |

### Relationships

| Related Entity | Relationship | Description |
|---------------|-------------|-------------|
| Project | Many-to-One | `project_id` — defaults to `"system-main"` (Home) for unassigned cards |
| Sprint | Many-to-One (optional) | `sprint_id` — time-boxed grouping |
| CardComment | One-to-Many | Comments on the card |
| TimeEntry | One-to-Many | Logged time entries |
| ChecklistItem | One-to-Many | Checklist items with completion |
| CardAttachment | One-to-Many | File attachments |
| CardRelation | Many-to-Many (self) | Relations: duplicates, blocks, related_to |
| CardHistory | One-to-Many | Audit trail of changes |

---

## Project

Container for cards, wiki pages, documents, and sprints.

### SQLAlchemy Model

```python
class Project(Base):
    __tablename__ = "projects"

    id              = Column(String, primary_key=True, default=uuid4)
    title           = Column(String, nullable=False)
    description     = Column(Text, default="")
    status          = Column(String, default="active")   # active|archived
    context         = Column(Text, default="")           # AI context for the project
    github_repo     = Column(String, nullable=True)      # "owner/repo"
    github_url      = Column(String, nullable=True)
    github_branch   = Column(String, nullable=True)
    github_language = Column(String, nullable=True)
    local_path      = Column(String, nullable=True)      # Filesystem path
    created_at      = Column(DateTime, default=utcnow)
    updated_at      = Column(DateTime, default=utcnow, onupdate=utcnow)
```

### Pydantic Schemas

```python
class ProjectCreate(BaseModel):
    title: str
    description: str = ""
    context: str = ""
    github_repo: str | None = None
    github_url: str | None = None
    github_branch: str | None = None
    github_language: str | None = None
    local_path: str | None = None

class ProjectResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    context: str
    github_repo: str | None
    github_url: str | None
    github_branch: str | None
    github_language: str | None
    local_path: str | None
    created_at: datetime
    updated_at: datetime

class ProjectWithCards(ProjectResponse):
    cards: list[CardResponse]
```

### Relationships

| Related Entity | Relationship | Description |
|---------------|-------------|-------------|
| Card | One-to-Many | Project's task cards |
| Chat | One-to-Many | Chat sessions within project |
| WikiPage | One-to-Many | Documentation pages |
| Document | One-to-Many | Uploaded files for RAG |
| Sprint | One-to-Many | Time-boxed card groups |

---

## Chat & Message

Chat sessions and their messages. Used for conversation persistence.

### SQLAlchemy Models

```python
class Chat(Base):
    __tablename__ = "chats"

    id          = Column(String, primary_key=True, default=uuid4)
    title       = Column(String, default="")
    project_id  = Column(String, ForeignKey("projects.id"), nullable=True)
    created_at  = Column(DateTime, default=utcnow)
    updated_at  = Column(DateTime, default=utcnow, onupdate=utcnow)

class Message(Base):
    __tablename__ = "messages"

    id          = Column(String, primary_key=True, default=uuid4)
    chat_id     = Column(String, ForeignKey("chats.id"), nullable=False)
    role        = Column(String, nullable=False)      # user|assistant|system
    content     = Column(Text, nullable=False)
    audio_url   = Column(String, nullable=True)
    model_used  = Column(String, nullable=True)       # fast|deep
    tokens_used = Column(Integer, nullable=True)
    latency_ms  = Column(Integer, nullable=True)
    created_at  = Column(DateTime, default=utcnow)
```

---

## Session

Sessions are file-based (not DB), stored in `~/.voxyflow/data/sessions/`.

### Chat ID Format

| Context | Chat ID Format | Example |
|---------|---------------|---------|
| General | `general:{session_uuid}` | `general:a1b2c3d4` |
| Project | `project:{project_id}` | `project:proj-xyz` |
| Card | `card:{card_id}` | `card:card-abc` |

### File Structure

```
~/.voxyflow/data/sessions/
├── general/
│   └── {session_uuid}.json
├── project/
│   └── {project_id}.json
└── card/
    └── {card_id}.json
```

Each file is a JSON array of message objects with atomic writes (temp file + rename).

---

## WikiPage

Markdown documentation pages per project.

```python
class WikiPage(Base):
    __tablename__ = "wiki_pages"

    id          = Column(String, primary_key=True, default=uuid4)
    project_id  = Column(String, ForeignKey("projects.id"), nullable=False)
    title       = Column(String, nullable=False)
    content     = Column(Text, default="")
    tags        = Column(String, default="")           # JSON-encoded array
    created_at  = Column(DateTime, default=utcnow)
    updated_at  = Column(DateTime, default=utcnow, onupdate=utcnow)
```

---

## Document

Uploaded files indexed for RAG retrieval.

```python
class Document(Base):
    __tablename__ = "documents"

    id          = Column(String, primary_key=True, default=uuid4)
    project_id  = Column(String, ForeignKey("projects.id"), nullable=False)
    filename    = Column(String, nullable=False)
    filetype    = Column(String, default="")
    size_bytes  = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0)
    created_at  = Column(DateTime, default=utcnow)
    indexed_at  = Column(DateTime, nullable=True)
```

---

## Sprint

Time-boxed card grouping.

```python
class Sprint(Base):
    __tablename__ = "sprints"

    id          = Column(String, primary_key=True, default=uuid4)
    project_id  = Column(String, ForeignKey("projects.id"), nullable=False)
    name        = Column(String, nullable=False)
    goal        = Column(Text, default="")
    start_date  = Column(DateTime, nullable=True)
    end_date    = Column(DateTime, nullable=True)
    status      = Column(String, default="planning")   # planning|active|completed
    created_at  = Column(DateTime, default=utcnow)
```

---

## Card Sub-Entities

### CardComment

```python
class CardComment(Base):
    id       = Column(String, primary_key=True)
    card_id  = Column(String, ForeignKey("cards.id"))
    author   = Column(String, default="user")
    content  = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)
```

### TimeEntry

```python
class TimeEntry(Base):
    id       = Column(String, primary_key=True)
    card_id  = Column(String, ForeignKey("cards.id"))
    minutes  = Column(Integer, nullable=False)
    note     = Column(String, default="")
    created_at = Column(DateTime, default=utcnow)
```

### ChecklistItem

```python
class ChecklistItem(Base):
    id       = Column(String, primary_key=True)
    card_id  = Column(String, ForeignKey("cards.id"))
    text     = Column(String, nullable=False)
    done     = Column(Boolean, default=False)
    position = Column(Integer, default=0)
```

### CardAttachment

```python
class CardAttachment(Base):
    id          = Column(String, primary_key=True)
    card_id     = Column(String, ForeignKey("cards.id"))
    filename    = Column(String, nullable=False)
    file_size   = Column(Integer, default=0)
    mime_type   = Column(String, default="")
    storage_path = Column(String, nullable=False)
    created_at  = Column(DateTime, default=utcnow)
```

### CardRelation

```python
class CardRelation(Base):
    id            = Column(String, primary_key=True)
    source_card_id = Column(String, ForeignKey("cards.id"))
    target_card_id = Column(String, ForeignKey("cards.id"))
    relation_type  = Column(String, nullable=False)    # duplicates|blocks|related_to
    created_at     = Column(DateTime, default=utcnow)
```

### CardHistory

```python
class CardHistory(Base):
    id        = Column(String, primary_key=True)
    card_id   = Column(String, ForeignKey("cards.id"))
    field     = Column(String, nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    changed_by = Column(String, default="system")
    changed_at = Column(DateTime, default=utcnow)
```

### FocusSession

```python
class FocusSession(Base):
    id               = Column(String, primary_key=True)
    card_id          = Column(String, nullable=True)
    project_id       = Column(String, nullable=True)
    duration_minutes = Column(Integer, nullable=False)
    completed        = Column(Boolean, default=False)
    started_at       = Column(DateTime, nullable=False)
    ended_at         = Column(DateTime, nullable=True)
```

---

_Every entity is documented. No placeholders. No guessing._
