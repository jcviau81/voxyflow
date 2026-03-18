"""Document Pydantic schemas for the documents API."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class DocumentResponse(BaseModel):
    """Response schema for a document record."""
    id: str
    project_id: str
    filename: str
    filetype: str
    size_bytes: int
    chunk_count: int
    created_at: datetime
    indexed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    """List of documents for a project."""
    documents: list[DocumentResponse]
    total: int
