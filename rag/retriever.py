import os
import re
import chromadb
from chromadb.utils import embedding_functions

CHROMA_PATH = os.path.join(os.path.dirname(__file__), "../chroma_db")

_client = None
_collection = None
_ef = None


def _get_collection():
    global _client, _collection, _ef
    if _collection is None:
        _ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = _client.get_collection(
            name="restaurant_knowledge",
            embedding_function=_ef
        )
    return _collection


def keyword_score(query, document):
    """Simple keyword overlap score, normalised to 0-1."""
    query_tokens = set(re.findall(r'\w+', query.lower()))
    doc_tokens = set(re.findall(r'\w+', document.lower()))
    if not query_tokens:
        return 0.0
    overlap = query_tokens & doc_tokens
    return len(overlap) / len(query_tokens)


def retrieve(query, n_results=3, category_filter=None):
    """
    Hybrid search: semantic (ChromaDB cosine) + keyword overlap.
    Returns list of dicts with text, metadata, and combined score.
    """
    try:
        collection = _get_collection()

        # Fetch more candidates than needed so keyword re-ranking has room to work
        fetch_n = min(n_results * 4, collection.count())

        where_filter = None
        if category_filter:
            where_filter = {"category": {"$eq": category_filter}}

        results = collection.query(
            query_texts=[query],
            n_results=fetch_n,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )

        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        combined = []
        for doc, meta, dist in zip(documents, metadatas, distances):
            # ChromaDB cosine distance → similarity (0=identical, 2=opposite)
            semantic_sim = 1 - (dist / 2)
            kw_sim = keyword_score(query, doc)
            # Weight: 70% semantic, 30% keyword
            combined_score = 0.7 * semantic_sim + 0.3 * kw_sim
            combined.append({
                "text": doc,
                "metadata": meta,
                "semantic_score": round(semantic_sim, 4),
                "keyword_score": round(kw_sim, 4),
                "score": round(combined_score, 4)
            })

        # Sort by combined score descending, return top n
        combined.sort(key=lambda x: x["score"], reverse=True)
        return combined[:n_results]

    except Exception as e:
        print(f"[retriever] Error during retrieval: {e}")
        return []


def retrieve_for_prompt(query, n_results=3):
    """Returns a formatted string of retrieved context for use in LLM prompt."""
    results = retrieve(query, n_results=n_results)
    if not results:
        return ""
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[Context {i} | score {r['score']}]\n{r['text']}")
    return "\n\n".join(lines)
