"""Index available knowledge in Qdrant; explicitly opt into remote backend."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.knowledge.rag_engine import load_documents
from src.knowledge.vector_store import VectorStore
from src.models.embedding_model import EmbeddingModel


def main() -> None:
    """Batch-index real source records without inventing missing records."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["memory", "qdrant"], default="memory")
    parser.add_argument("--embedding", choices=["local", "bge"], default="local")
    args = parser.parse_args()
    documents = load_documents()
    store = VectorStore(EmbeddingModel(args.embedding), backend=args.backend)
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = lambda items, **kwargs: items
    for start in tqdm(range(0, len(documents), 32), desc="Indexing"):
        store.add_documents(documents[start:start + 32])
    print(f"Indexed {len(documents)} documents ({args.backend}/{args.embedding})")
    if len(documents) < 5000:
        print("Target 5000+ not met: supply verified source records before claiming production coverage.")


if __name__ == "__main__":
    main()
