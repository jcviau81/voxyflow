"""Document Pydantic schemas for the documents API.

``DocumentResponse`` is generated from the ORM ``Document`` model via
``_generated.DocumentBase``.
"""

from pydantic import BaseModel

from app.models._generated import DocumentBase


class DocumentResponse(DocumentBase):
    """Wire representation of a Document — pure column-backed."""
    pass


class DocumentListResponse(BaseModel):
    """List of documents for a project.

    ``total`` is synthesized by the route handler (COUNT query, not a column).
    """
    documents: list[DocumentResponse]
    total: int
