"""Chat & message endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db, Chat, Message, new_uuid, utcnow
from app.models.chat import (
    ChatCreate,
    ChatResponse,
    ChatListItem,
    MessageCreate,
    MessageResponse,
)

router = APIRouter(prefix="/chats", tags=["chats"])


# ---------------------------------------------------------------------------
# Chat CRUD
# ---------------------------------------------------------------------------

@router.post("", response_model=ChatResponse, status_code=201)
async def create_chat(body: ChatCreate, db: AsyncSession = Depends(get_db)):
    chat = Chat(id=new_uuid(), title=body.title, project_id=body.project_id)
    db.add(chat)
    await db.commit()

    # Eager-load messages to prevent MissingGreenlet on serialization
    stmt = select(Chat).options(selectinload(Chat.messages)).where(Chat.id == chat.id)
    result = await db.execute(stmt)
    return result.scalar_one()


@router.get("", response_model=list[ChatListItem])
async def list_chats(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(
            Chat,
            func.count(Message.id).label("message_count"),
        )
        .outerjoin(Message)
        .group_by(Chat.id)
        .order_by(Chat.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = []
    for chat, msg_count in result.all():
        items.append(
            ChatListItem(
                id=chat.id,
                title=chat.title,
                project_id=chat.project_id,
                created_at=chat.created_at,
                message_count=msg_count,
            )
        )
    return items


@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(chat_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Chat).options(selectinload(Chat.messages)).where(Chat.id == chat_id)
    result = await db.execute(stmt)
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(404, "Chat not found")
    return chat


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@router.post("/{chat_id}/messages", response_model=MessageResponse, status_code=201)
async def add_message(
    chat_id: str,
    body: MessageCreate,
    db: AsyncSession = Depends(get_db),
):
    # Verify chat exists
    chat = await db.get(Chat, chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")

    msg = Message(
        id=new_uuid(),
        chat_id=chat_id,
        role=body.role,
        content=body.content,
        audio_url=body.audio_url,
    )
    db.add(msg)

    # Touch chat updated_at
    chat.updated_at = utcnow()

    await db.commit()
    await db.refresh(msg)
    return msg
