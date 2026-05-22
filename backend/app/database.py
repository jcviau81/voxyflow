"""Database setup: async SQLAlchemy engine + session factory."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    Boolean,
    Integer,
    Float,
    ForeignKey,
    Table,
    Enum as SAEnum,
)
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.pool import StaticPool

from app.config import get_settings

# ---------------------------------------------------------------------------
# Engine & session
# ---------------------------------------------------------------------------

engine = create_async_engine(
    get_settings().database_url,
    echo=get_settings().debug,
    # SQLite: use StaticPool (single shared connection) to avoid pool exhaustion
    # under heavy concurrent access. SQLite handles its own locking.
    poolclass=StaticPool,
    connect_args={
        "check_same_thread": False,
        "timeout": 30,  # wait up to 30s for lock instead of failing immediately
    },
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Enable WAL journal mode for every new SQLite connection — allows concurrent
# readers while a write is in progress and eliminates most "database is locked" errors.
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields a database session."""
    async with async_session() as session:
        yield session


async def init_db():
    """Create all tables (call once at startup) and apply lightweight migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrate: add assignee / watchers columns if they don't exist yet
        from sqlalchemy import text
        result = await conn.execute(text("PRAGMA table_info(cards)"))
        existing_columns = {row[1] for row in result.fetchall()}
        if "assignee" not in existing_columns:
            await conn.execute(text("ALTER TABLE cards ADD COLUMN assignee TEXT"))
        if "watchers" not in existing_columns:
            await conn.execute(text("ALTER TABLE cards ADD COLUMN watchers TEXT NOT NULL DEFAULT ''"))
        if "votes" not in existing_columns:
            await conn.execute(text("ALTER TABLE cards ADD COLUMN votes INTEGER NOT NULL DEFAULT 0"))

        if "preferred_model" not in existing_columns:
            await conn.execute(text("ALTER TABLE cards ADD COLUMN preferred_model TEXT"))
        if "recurrence" not in existing_columns:
            await conn.execute(text("ALTER TABLE cards ADD COLUMN recurrence TEXT"))
        if "recurrence_next" not in existing_columns:
            await conn.execute(text("ALTER TABLE cards ADD COLUMN recurrence_next DATETIME"))
        if "color" not in existing_columns:
            await conn.execute(text("ALTER TABLE cards ADD COLUMN color TEXT"))
        if "files" not in existing_columns:
            await conn.execute(text("ALTER TABLE cards ADD COLUMN files TEXT NOT NULL DEFAULT '[]'"))
        if "archived_at" not in existing_columns:
            await conn.execute(text("ALTER TABLE cards ADD COLUMN archived_at DATETIME"))
        if "recurring" not in existing_columns:
            await conn.execute(text("ALTER TABLE cards ADD COLUMN recurring INTEGER NOT NULL DEFAULT 0"))
        # Migrate: remove 'idea' status — cards go to 'backlog'
        await conn.execute(text("UPDATE cards SET status='backlog' WHERE status='idea'"))
        # Migrate: rename 'card' status → 'backlog'
        await conn.execute(text("UPDATE cards SET status='backlog' WHERE status='card'"))
        # Migrate: drop removed card_comments table (feature fully deleted)
        await conn.execute(text("DROP TABLE IF EXISTS card_comments"))
        # Ensure card_relations table exists (created via create_all above, but explicit for safety)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS card_relations (
                id TEXT PRIMARY KEY,
                source_card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                target_card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL,
                created_at DATETIME NOT NULL
            )
        """))
        # Ensure card_history table exists
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS card_history (
                id TEXT PRIMARY KEY,
                card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                field_changed TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                changed_at DATETIME NOT NULL,
                changed_by TEXT NOT NULL DEFAULT 'User'
            )
        """))
        # Ensure focus_sessions table exists
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS focus_sessions (
                id TEXT PRIMARY KEY,
                card_id TEXT REFERENCES cards(id) ON DELETE SET NULL,
                workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
                duration_minutes INTEGER NOT NULL,
                completed BOOLEAN NOT NULL DEFAULT 0,
                started_at DATETIME NOT NULL,
                ended_at DATETIME NOT NULL
            )
        """))
        # Ensure app_settings table exists (key-value store for app config)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """))
        # Migrate: add is_system / deletable columns to workspaces if missing
        ws_result = await conn.execute(text("PRAGMA table_info(workspaces)"))
        ws_columns = {row[1] for row in ws_result.fetchall()}
        if "is_system" not in ws_columns:
            await conn.execute(text("ALTER TABLE workspaces ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT 0"))
        if "deletable" not in ws_columns:
            await conn.execute(text("ALTER TABLE workspaces ADD COLUMN deletable BOOLEAN NOT NULL DEFAULT 1"))
        if "is_favorite" not in ws_columns:
            await conn.execute(text("ALTER TABLE workspaces ADD COLUMN is_favorite BOOLEAN NOT NULL DEFAULT 0"))
        if "inherit_main_context" not in ws_columns:
            await conn.execute(text("ALTER TABLE workspaces ADD COLUMN inherit_main_context BOOLEAN NOT NULL DEFAULT 1"))

        # Ensure the system "Home" workspace exists (formerly "Main", briefly "Global")
        SYSTEM_MAIN_ID = "system-main"
        from pathlib import Path as _Path
        HOME_LOCAL_PATH = str(_Path.home() / ".voxyflow" / "sandbox" / "workspaces" / "system-home")
        OLD_HOME_LOCAL_PATH = str(_Path.home() / ".voxyflow" / "workspace")
        existing = await conn.execute(text("SELECT id FROM workspaces WHERE id = :id"), {"id": SYSTEM_MAIN_ID})
        if existing.fetchone() is None:
            await conn.execute(text(
                "INSERT INTO workspaces (id, title, description, status, context, local_path, is_system, deletable, is_favorite, inherit_main_context, created_at, updated_at) "
                "VALUES (:id, :title, :desc, 'active', '', :lp, 1, 0, 0, 1, :now, :now)"
            ), {"id": SYSTEM_MAIN_ID, "title": "Home", "desc": "Default workspace", "lp": HOME_LOCAL_PATH, "now": utcnow().isoformat()})
        else:
            # Rename system workspace to "Home" if it still has a previous default name.
            await conn.execute(text(
                "UPDATE workspaces SET title = 'Home' WHERE id = :id AND title IN ('Main', 'Global')"
            ), {"id": SYSTEM_MAIN_ID})
            # Backfill local_path: empty/null OR pointing at the old default (workspace root).
            await conn.execute(text(
                "UPDATE workspaces SET local_path = :lp "
                "WHERE id = :id AND (local_path IS NULL OR local_path = '' OR local_path = :old)"
            ), {"id": SYSTEM_MAIN_ID, "lp": HOME_LOCAL_PATH, "old": OLD_HOME_LOCAL_PATH})

        # Make sure the directory exists so workers can chdir into it on first launch.
        _Path(HOME_LOCAL_PATH).mkdir(parents=True, exist_ok=True)

        # Migrate all cards with workspace_id = NULL → system-main
        await conn.execute(text(
            "UPDATE cards SET workspace_id = :pid WHERE workspace_id IS NULL"
        ), {"pid": SYSTEM_MAIN_ID})

        # Ensure worker_tasks table exists (Worker Ledger)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS worker_tasks (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                workspace_id TEXT,
                action TEXT NOT NULL,
                description TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                result_summary TEXT,
                error TEXT,
                started_at DATETIME NOT NULL,
                completed_at DATETIME,
                created_at DATETIME NOT NULL
            )
        """))
        # Migrate: add card_id column to worker_tasks if missing
        wt_result = await conn.execute(text("PRAGMA table_info(worker_tasks)"))
        wt_columns = {row[1] for row in wt_result.fetchall()}
        if "card_id" not in wt_columns:
            await conn.execute(text("ALTER TABLE worker_tasks ADD COLUMN card_id TEXT"))
        # On startup: mark stuck running/pending tasks as cancelled (orphaned by restart)
        await conn.execute(text(
            "UPDATE worker_tasks SET status='cancelled', error='Process restarted — task cancelled', "
            "completed_at=CURRENT_TIMESTAMP WHERE status IN ('running', 'pending')"
        ))

        # --- Knowledge Graph tables ---
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS kg_entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                properties TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_kg_entity_name_type_workspace "
            "ON kg_entities (name, entity_type, workspace_id)"
        ))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS kg_triples (
                id TEXT PRIMARY KEY,
                subject_id TEXT NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
                predicate TEXT NOT NULL,
                object_id TEXT NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
                confidence REAL NOT NULL DEFAULT 1.0,
                source TEXT NOT NULL DEFAULT 'auto',
                valid_from DATETIME NOT NULL,
                valid_to DATETIME,
                created_at DATETIME NOT NULL
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_kg_triples_subject_valid "
            "ON kg_triples (subject_id, valid_to)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_kg_triples_object_valid "
            "ON kg_triples (object_id, valid_to)"
        ))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS kg_attributes (
                id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
                key TEXT NOT NULL,
                value TEXT,
                valid_from DATETIME NOT NULL,
                valid_to DATETIME,
                created_at DATETIME NOT NULL
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_kg_attributes_entity_valid "
            "ON kg_attributes (entity_id, valid_to)"
        ))

        # Ensure push_subscriptions table exists (Web Push / VAPID endpoints)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id TEXT PRIMARY KEY,
                endpoint TEXT NOT NULL,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                user_agent TEXT,
                created_at DATETIME NOT NULL,
                last_used_at DATETIME
            )
        """))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_push_subscriptions_endpoint "
            "ON push_subscriptions (endpoint)"
        ))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_MAIN_WORKSPACE_ID = "system-main"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Association table: card ↔ card dependencies (many-to-many self-ref)
# ---------------------------------------------------------------------------

card_dependencies = Table(
    "card_dependencies",
    Base.metadata,
    Column("card_id", String, ForeignKey("cards.id"), primary_key=True),
    Column("depends_on_id", String, ForeignKey("cards.id"), primary_key=True),
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AppSettings(Base):
    """Key-value store for app-wide settings (`key='app_settings'` holds the JSON blob)."""
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)


class Chat(Base):
    __tablename__ = "chats"

    id = Column(String, primary_key=True, default=new_uuid)
    title = Column(String, default="New Chat")
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan", order_by="Message.created_at")
    workspace = relationship("Workspace", back_populates="chats")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=new_uuid)
    chat_id = Column(String, ForeignKey("chats.id"), nullable=False)
    role = Column(String, nullable=False)  # user | assistant | system
    content = Column(Text, nullable=False)
    audio_url = Column(String, nullable=True)
    model_used = Column(String, nullable=True)
    tokens_used = Column(Integer, nullable=True)
    latency_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    chat = relationship("Chat", back_populates="messages")


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True, default=new_uuid)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    status = Column(String, default="active")  # active | archived
    context = Column(Text, default="")  # relevant docs, requirements summary
    is_system = Column(Boolean, default=False)  # True for the built-in "Home" workspace
    deletable = Column(Boolean, default=True)   # False for system workspaces
    github_repo = Column(String, nullable=True)      # "owner/repo"
    github_url = Column(String, nullable=True)        # "https://github.com/owner/repo"
    github_branch = Column(String, nullable=True)     # "main"
    github_language = Column(String, nullable=True)    # "TypeScript"
    local_path = Column(String, nullable=True)         # "~/projects/voxyflow"
    is_favorite = Column(Boolean, default=False, nullable=False)  # User-pinned favorite
    inherit_main_context = Column(Boolean, default=True, nullable=False)  # Include Home workspace RAG context
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    chats = relationship("Chat", back_populates="workspace")
    cards = relationship("Card", back_populates="workspace", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="workspace", cascade="all, delete-orphan")
    wiki_pages = relationship("WikiPage", back_populates="workspace", cascade="all, delete-orphan")


class WikiPage(Base):
    __tablename__ = "wiki_pages"

    id = Column(String, primary_key=True, default=new_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False, default="Untitled Page")
    content = Column(Text, default="")  # markdown content
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    workspace = relationship("Workspace", back_populates="wiki_pages")



class Card(Base):
    __tablename__ = "cards"

    id = Column(String, primary_key=True, default=new_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True)  # system-main = Main Board
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    status = Column(String, default="backlog")  # backlog | todo | in-progress | done | archived
    priority = Column(Integer, default=0)  # 0=none, 1=low, 2=medium, 3=high, 4=critical
    color = Column(String, nullable=True)  # yellow|blue|green|pink|purple|orange (for Main Board notes)
    position = Column(Integer, default=0)  # ordering within status column
    source_message_id = Column(String, ForeignKey("messages.id"), nullable=True)
    auto_generated = Column(Boolean, default=False)
    agent_assigned = Column(String, nullable=True)
    agent_type = Column(String, nullable=True)  # general|researcher|coder|designer|architect|writer|qa
    agent_context = Column(Text, nullable=True)  # relevant docs/requirements for the agent
    assignee = Column(String, nullable=True)  # display name of assigned person
    watchers = Column(String, nullable=False, default="")  # comma-separated watcher names
    votes = Column(Integer, nullable=False, default=0)  # upvote count

    recurring = Column(Boolean, default=False, nullable=False)  # reset to todo after board run
    recurrence = Column(String, nullable=True)  # "daily" | "weekly" | "monthly" | None
    recurrence_next = Column(DateTime, nullable=True)  # next occurrence datetime
    preferred_model = Column(String, nullable=True)  # worker class UUID or legacy name — override worker model for this card
    files = Column(Text, nullable=False, default="[]")  # JSON array of relative file paths
    archived_at = Column(DateTime, nullable=True)  # set when archived, NULL = active
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    workspace = relationship("Workspace", back_populates="cards")
    source_message = relationship("Message", foreign_keys=[source_message_id])

    dependencies = relationship(
        "Card",
        secondary=card_dependencies,
        primaryjoin=(id == card_dependencies.c.card_id),
        secondaryjoin=(id == card_dependencies.c.depends_on_id),
        backref="dependents",
    )
    time_entries = relationship("TimeEntry", back_populates="card", cascade="all, delete-orphan")
    checklist_items = relationship("ChecklistItem", back_populates="card", cascade="all, delete-orphan", order_by="ChecklistItem.position")
    attachments = relationship("CardAttachment", back_populates="card", cascade="all, delete-orphan", order_by="CardAttachment.created_at")
    relations_as_source = relationship("CardRelation", foreign_keys="[CardRelation.source_card_id]", back_populates="source_card", cascade="all, delete-orphan")
    relations_as_target = relationship("CardRelation", foreign_keys="[CardRelation.target_card_id]", back_populates="target_card", cascade="all, delete-orphan")
    history_entries = relationship("CardHistory", back_populates="card", cascade="all, delete-orphan", order_by="CardHistory.changed_at.desc()")


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id = Column(String, primary_key=True, default=new_uuid)
    card_id = Column(String, ForeignKey("cards.id"), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    note = Column(Text, nullable=True)
    logged_at = Column(DateTime, default=utcnow)

    card = relationship("Card", back_populates="time_entries")


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id = Column(String, primary_key=True, default=new_uuid)
    card_id = Column(String, ForeignKey("cards.id", ondelete="CASCADE"), nullable=False)
    text = Column(Text, nullable=False)
    completed = Column(Boolean, default=False, nullable=False)
    position = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    card = relationship("Card", back_populates="checklist_items")


class CardAttachment(Base):
    __tablename__ = "card_attachments"

    id = Column(String, primary_key=True, default=new_uuid)
    card_id = Column(String, ForeignKey("cards.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False, default=0)
    mime_type = Column(String, nullable=False, default="application/octet-stream")
    storage_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    card = relationship("Card", back_populates="attachments")


class CardRelation(Base):
    __tablename__ = "card_relations"

    id = Column(String, primary_key=True, default=new_uuid)
    source_card_id = Column(String, ForeignKey("cards.id", ondelete="CASCADE"), nullable=False)
    target_card_id = Column(String, ForeignKey("cards.id", ondelete="CASCADE"), nullable=False)
    relation_type = Column(String, nullable=False)  # duplicates|blocks|is_blocked_by|relates_to|cloned_from
    created_at = Column(DateTime, default=utcnow)

    source_card = relationship("Card", foreign_keys=[source_card_id], back_populates="relations_as_source")
    target_card = relationship("Card", foreign_keys=[target_card_id], back_populates="relations_as_target")


class CardHistory(Base):
    __tablename__ = "card_history"

    id = Column(String, primary_key=True, default=new_uuid)
    card_id = Column(String, ForeignKey("cards.id", ondelete="CASCADE"), nullable=False)
    field_changed = Column(String, nullable=False)  # "status", "priority", "title", "assignee", etc.
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    changed_at = Column(DateTime, default=utcnow)
    changed_by = Column(String, nullable=False, default="User")

    card = relationship("Card", back_populates="history_entries")


class FocusSession(Base):
    __tablename__ = "focus_sessions"

    id = Column(String, primary_key=True, default=new_uuid)
    card_id = Column(String, ForeignKey("cards.id", ondelete="SET NULL"), nullable=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)
    duration_minutes = Column(Integer, nullable=False)
    completed = Column(Boolean, nullable=False, default=False)  # True if ran to completion, False if interrupted
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=False)

    card = relationship("Card", foreign_keys=[card_id])
    workspace = relationship("Workspace", foreign_keys=[workspace_id])


class WorkerTask(Base):
    __tablename__ = "worker_tasks"

    id = Column(String, primary_key=True, default=new_uuid)
    session_id = Column(String, nullable=False)
    workspace_id = Column(String, nullable=True)
    card_id = Column(String, nullable=True)          # optional card this task operates on
    action = Column(String, nullable=False)          # e.g. "fix_bug", "implement_feature"
    description = Column(Text, nullable=False)       # human-readable task description
    model = Column(String, nullable=False)           # haiku/sonnet/opus
    status = Column(String, nullable=False, default="pending")  # pending/running/done/failed/cancelled
    result_summary = Column(Text, nullable=True)     # short summary of what was done (set on completion)
    error = Column(Text, nullable=True)              # error message if failed
    started_at = Column(DateTime, nullable=False, default=utcnow)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(String, primary_key=True, default=new_uuid)
    endpoint = Column(String, nullable=False, unique=True)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    last_used_at = Column(DateTime, nullable=True)


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=new_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    filename = Column(String, nullable=False)
    filetype = Column(String, nullable=False)   # ".txt", ".md", etc.
    size_bytes = Column(Integer, nullable=False, default=0)
    chunk_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)
    indexed_at = Column(DateTime, nullable=True)

    workspace = relationship("Workspace", back_populates="documents")


# ---------------------------------------------------------------------------
# Knowledge Graph tables
#
# Temporal model: triples and attributes carry [valid_from, valid_to).
#   valid_to IS NULL  →  fact is current / active
#   valid_to set      →  fact was true only during [valid_from, valid_to)
# Entities are NOT temporal — they persist once created and track updated_at.
# See knowledge_graph_service.py module docstring for full semantics.
# ---------------------------------------------------------------------------

class KGEntity(Base):
    """Named thing in the KG (person, technology, component, concept, decision).

    Not temporally scoped — once created, an entity persists. updated_at
    tracks the last upsert. Unique on (name, entity_type, workspace_id).
    """
    __tablename__ = "kg_entities"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)  # person|technology|component|concept|decision
    workspace_id = Column(String, nullable=False)    # not FK — may be "system-main"
    properties = Column(Text, nullable=True)        # JSON text
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    triples_as_subject = relationship("KGTriple", foreign_keys="KGTriple.subject_id", back_populates="subject", cascade="all, delete-orphan")
    triples_as_object = relationship("KGTriple", foreign_keys="KGTriple.object_id", back_populates="object", cascade="all, delete-orphan")
    attributes = relationship("KGAttribute", back_populates="entity", cascade="all, delete-orphan")


class KGTriple(Base):
    """Directed relationship between two entities, with temporal bounds.

    [valid_from, valid_to) defines when this relationship held:
      valid_from  — set to now() on creation (when fact became true)
      valid_to    — NULL while active; set to now() by invalidate() when the
                    fact is superseded or retracted
    Queries filter on valid_to IS NULL to see current state.
    Timeline shows all rows (current + historical) for audit.
    """
    __tablename__ = "kg_triples"

    id = Column(String, primary_key=True, default=new_uuid)
    subject_id = Column(String, ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False)
    predicate = Column(String, nullable=False)       # e.g. "uses", "depends_on"
    object_id = Column(String, ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False)
    confidence = Column(Float, nullable=False, default=1.0)  # clamped [0.0, 1.0]
    source = Column(String, nullable=False, default="auto")  # auto|manual|chat
    valid_from = Column(DateTime, nullable=False, default=utcnow)
    valid_to = Column(DateTime, nullable=True)        # NULL = still valid
    created_at = Column(DateTime, nullable=False, default=utcnow)

    subject = relationship("KGEntity", foreign_keys=[subject_id], back_populates="triples_as_subject")
    object = relationship("KGEntity", foreign_keys=[object_id], back_populates="triples_as_object")


class KGAttribute(Base):
    """Time-scoped key-value property on an entity.

    Same temporal model as KGTriple: [valid_from, valid_to).
    Multiple rows with the same (entity_id, key) can coexist — each represents
    a distinct temporal assertion. To update a value, invalidate the old row
    and insert a new one (append-only history).
    Special key 'pinned' with value 'true' marks the entity for L0 context
    injection (see get_pinned_context).
    """
    __tablename__ = "kg_attributes"

    id = Column(String, primary_key=True, default=new_uuid)
    entity_id = Column(String, ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False)
    key = Column(String, nullable=False)
    value = Column(Text, nullable=True)
    valid_from = Column(DateTime, nullable=False, default=utcnow)
    valid_to = Column(DateTime, nullable=True)        # NULL = still valid
    created_at = Column(DateTime, nullable=False, default=utcnow)

    entity = relationship("KGEntity", back_populates="attributes")
