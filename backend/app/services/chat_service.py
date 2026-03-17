"""Chat business logic — conversation management and persistence."""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import Chat, Message, new_uuid, utcnow

logger = logging.getLogger(__name__)


class ChatService:
    """Manages chat sessions and message persistence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_chat(self, chat_id: str, title: str = "New Chat") -> Chat:
        """Get existing chat or create a new one."""
        chat = await self.db.get(Chat, chat_id)
        if not chat:
            chat = Chat(id=chat_id, title=title)
            self.db.add(chat)
            await self.db.commit()
            await self.db.refresh(chat)
        return chat

    async def add_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        model_used: Optional[str] = None,
        tokens_used: Optional[int] = None,
        latency_ms: Optional[float] = None,
        audio_url: Optional[str] = None,
    ) -> Message:
        """Persist a message to the database."""
        msg = Message(
            id=new_uuid(),
            chat_id=chat_id,
            role=role,
            content=content,
            model_used=model_used,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            audio_url=audio_url,
        )
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)
        return msg

    async def get_recent_messages(
        self, chat_id: str, limit: int = 20
    ) -> list[Message]:
        """Fetch recent messages for context window."""
        stmt = (
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        messages = list(result.scalars().all())
        messages.reverse()  # Chronological order
        return messages

    async def auto_title(self, chat_id: str) -> Optional[str]:
        """
        Generate a title from the first user message.
        Called after the first exchange in a chat.
        """
        messages = await self.get_recent_messages(chat_id, limit=1)
        if messages and messages[0].role == "user":
            # Simple: first 50 chars of first message
            title = messages[0].content[:50].strip()
            if len(messages[0].content) > 50:
                title += "..."
            chat = await self.db.get(Chat, chat_id)
            if chat and chat.title == "New Chat":
                chat.title = title
                chat.updated_at = utcnow()
                await self.db.commit()
                return title
        return None
