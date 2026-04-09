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
        if "sprint_id" not in existing_columns:
            await conn.execute(text("ALTER TABLE cards ADD COLUMN sprint_id TEXT REFERENCES sprints(id)"))
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
        # Migrate: remove 'idea' status — cards go to 'card' (backlog)
        await conn.execute(text("UPDATE cards SET status='card' WHERE status='idea'"))
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
                project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
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
        # Migrate: add is_system / deletable columns to projects if missing
        proj_result = await conn.execute(text("PRAGMA table_info(projects)"))
        proj_columns = {row[1] for row in proj_result.fetchall()}
        if "is_system" not in proj_columns:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT 0"))
        if "deletable" not in proj_columns:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN deletable BOOLEAN NOT NULL DEFAULT 1"))
        if "is_favorite" not in proj_columns:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN is_favorite BOOLEAN NOT NULL DEFAULT 0"))
        if "inherit_main_context" not in proj_columns:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN inherit_main_context BOOLEAN NOT NULL DEFAULT 1"))

        # Ensure the system "Main" project exists
        SYSTEM_MAIN_ID = "system-main"
        existing = await conn.execute(text("SELECT id FROM projects WHERE id = :id"), {"id": SYSTEM_MAIN_ID})
        if existing.fetchone() is None:
            await conn.execute(text(
                "INSERT INTO projects (id, title, description, status, context, is_system, deletable, is_favorite, inherit_main_context, created_at, updated_at) "
                "VALUES (:id, :title, :desc, 'active', '', 1, 0, 0, 1, :now, :now)"
            ), {"id": SYSTEM_MAIN_ID, "title": "Main", "desc": "Default workspace", "now": utcnow().isoformat()})

        # Migrate all cards with project_id = NULL → system-main
        await conn.execute(text(
            "UPDATE cards SET project_id = :pid WHERE project_id IS NULL"
        ), {"pid": SYSTEM_MAIN_ID})

        # Ensure worker_tasks table exists (Worker Ledger)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS worker_tasks (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                project_id TEXT,
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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_MAIN_PROJECT_ID = "system-main"

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

class Chat(Base):
    __tablename__ = "chats"

    id = Column(String, primary_key=True, default=new_uuid)
    title = Column(String, default="New Chat")
    project_id = Column(String, ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan", order_by="Message.created_at")
    project = relationship("Project", back_populates="chats")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=new_uuid)
    chat_id = Column(String, ForeignKey("chats.id"), nullable=False)
    role = Column(String, nullable=False)  # user | assistant | system | analyzer
    content = Column(Text, nullable=False)
    audio_url = Column(String, nullable=True)
    model_used = Column(String, nullable=True)
    tokens_used = Column(Integer, nullable=True)
    latency_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    chat = relationship("Chat", back_populates="messages")


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=new_uuid)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    status = Column(String, default="active")  # active | archived
    context = Column(Text, default="")  # relevant docs, requirements summary
    is_system = Column(Boolean, default=False)  # True for the built-in "Main" project
    deletable = Column(Boolean, default=True)   # False for system projects
    github_repo = Column(String, nullable=True)      # "owner/repo"
    github_url = Column(String, nullable=True)        # "https://github.com/owner/repo"
    github_branch = Column(String, nullable=True)     # "main"
    github_language = Column(String, nullable=True)    # "TypeScript"
    local_path = Column(String, nullable=True)         # "~/projects/voxyflow"
    is_favorite = Column(Boolean, default=False, nullable=False)  # User-pinned favorite
    inherit_main_context = Column(Boolean, default=True, nullable=False)  # Include Main project RAG context
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    chats = relationship("Chat", back_populates="project")
    cards = relationship("Card", back_populates="project", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")
    wiki_pages = relationship("WikiPage", back_populates="project", cascade="all, delete-orphan")
    sprints = relationship("Sprint", back_populates="project", cascade="all, delete-orphan")


class WikiPage(Base):
    __tablename__ = "wiki_pages"

    id = Column(String, primary_key=True, default=new_uuid)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False, default="Untitled Page")
    content = Column(Text, default="")  # markdown content
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    project = relationship("Project", back_populates="wiki_pages")


class Sprint(Base):
    __tablename__ = "sprints"

    id = Column(String, primary_key=True, default=new_uuid)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)        # "Sprint 1", "Sprint 2", etc.
    goal = Column(Text, nullable=True)           # Sprint goal description
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    status = Column(String, default="planning")  # planning | active | completed
    created_at = Column(DateTime, default=utcnow)

    project = relationship("Project", back_populates="sprints")
    cards = relationship("Card", back_populates="sprint", foreign_keys="[Card.sprint_id]")


class Card(Base):
    __tablename__ = "cards"

    id = Column(String, primary_key=True, default=new_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=True)  # system-main = Main Board
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    status = Column(String, default="card")  # card | todo | in-progress | done | archived
    priority = Column(Integer, default=0)  # 0=none, 1=low, 2=medium, 3=high, 4=critical
    color = Column(String, nullable=True)  # yellow|blue|green|pink|purple|orange (for Main Board notes)
    position = Column(Integer, default=0)  # ordering within status column
    source_message_id = Column(String, ForeignKey("messages.id"), nullable=True)
    auto_generated = Column(Boolean, default=False)
    agent_assigned = Column(String, nullable=True)
    agent_type = Column(String, nullable=True)  # ember|researcher|coder|designer|architect|writer|qa
    agent_context = Column(Text, nullable=True)  # relevant docs/requirements for the agent
    assignee = Column(String, nullable=True)  # display name of assigned person
    watchers = Column(String, nullable=False, default="")  # comma-separated watcher names
    votes = Column(Integer, nullable=False, default=0)  # upvote count
    sprint_id = Column(String, ForeignKey("sprints.id"), nullable=True)  # sprint assignment
    recurring = Column(Boolean, default=False, nullable=False)  # reset to todo after board run
    recurrence = Column(String, nullable=True)  # "daily" | "weekly" | "monthly" | None
    recurrence_next = Column(DateTime, nullable=True)  # next occurrence datetime
    preferred_model = Column(String, nullable=True)  # haiku | sonnet | opus — override worker model for this card
    files = Column(Text, nullable=False, default="[]")  # JSON array of relative file paths
    archived_at = Column(DateTime, nullable=True)  # set when archived, NULL = active
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    project = relationship("Project", back_populates="cards")
    source_message = relationship("Message", foreign_keys=[source_message_id])
    sprint = relationship("Sprint", back_populates="cards", foreign_keys="[Card.sprint_id]")
    dependencies = relationship(
        "Card",
        secondary=card_dependencies,
        primaryjoin=(id == card_dependencies.c.card_id),
        secondaryjoin=(id == card_dependencies.c.depends_on_id),
        backref="dependents",
    )
    time_entries = relationship("TimeEntry", back_populates="card", cascade="all, delete-orphan")
    comments = relationship("CardComment", back_populates="card", cascade="all, delete-orphan")
    checklist_items = relationship("ChecklistItem", back_populates="card", cascade="all, delete-orphan", order_by="ChecklistItem.position")
    attachments = relationship("CardAttachment", back_populates="card", cascade="all, delete-orphan", order_by="CardAttachment.created_at")
    relations_as_source = relationship("CardRelation", foreign_keys="[CardRelation.source_card_id]", back_populates="source_card", cascade="all, delete-orphan")
    relations_as_target = relationship("CardRelation", foreign_keys="[CardRelation.target_card_id]", back_populates="target_card", cascade="all, delete-orphan")
    history_entries = relationship("CardHistory", back_populates="card", cascade="all, delete-orphan", order_by="CardHistory.changed_at.desc()")


class CardComment(Base):
    __tablename__ = "card_comments"

    id = Column(String, primary_key=True, default=new_uuid)
    card_id = Column(String, ForeignKey("cards.id"), nullable=False)
    author = Column(String, nullable=False, default="User")
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    card = relationship("Card", back_populates="comments")


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
    project_id = Column(String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    duration_minutes = Column(Integer, nullable=False)
    completed = Column(Boolean, nullable=False, default=False)  # True if ran to completion, False if interrupted
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=False)

    card = relationship("Card", foreign_keys=[card_id])
    project = relationship("Project", foreign_keys=[project_id])


class WorkerTask(Base):
    __tablename__ = "worker_tasks"

    id = Column(String, primary_key=True, default=new_uuid)
    session_id = Column(String, nullable=False)
    project_id = Column(String, nullable=True)
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


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=new_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    filename = Column(String, nullable=False)
    filetype = Column(String, nullable=False)   # ".txt", ".md", etc.
    size_bytes = Column(Integer, nullable=False, default=0)
    chunk_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)
    indexed_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="documents")
