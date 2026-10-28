"""CPU vector indexing; CLAP generation and recommendation policies live elsewhere."""

from .catalog import EmbeddingCatalog, load_embeddings


def __getattr__(name):
    """Keep data preparation importable in the separate encoder environment."""
    if name in {"IndexConfig", "RetrievalIndex", "SearchResult"}:
        from importlib import import_module
        value = getattr(import_module(".index", __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(name)

__all__ = [
    "EmbeddingCatalog",
    "load_embeddings",
    "IndexConfig",
    "RetrievalIndex",
    "SearchResult",
]
