"""
Shared sentence-transformer embedding function singleton.

Both RAGService and MemoryService import from here so the model
is only loaded once into memory instead of twice.
"""

import logging

logger = logging.getLogger(__name__)

_CHROMADB_AVAILABLE = False
_ef = None

try:
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction as _STEF

    _CHROMADB_AVAILABLE = True
except ImportError:
    pass


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def get_embedding_function():
    """Return the shared SentenceTransformerEmbeddingFunction instance (lazy init)."""
    global _ef
    if not _CHROMADB_AVAILABLE:
        return None
    if _ef is None:
        _ef = _STEF(model_name=MODEL_NAME)
        logger.info(f"Embedding function loaded: {MODEL_NAME}")
    return _ef
