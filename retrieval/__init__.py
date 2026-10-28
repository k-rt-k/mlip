"""CPU vector indexing; CLAP generation and recommendation policies live elsewhere."""

from .catalog import EmbeddingCatalog, load_embeddings
from .index import IndexConfig, RetrievalIndex, SearchResult

__all__ = [
    "EmbeddingCatalog",
    "load_embeddings",
    "IndexConfig",
    "RetrievalIndex",
    "SearchResult",
]
