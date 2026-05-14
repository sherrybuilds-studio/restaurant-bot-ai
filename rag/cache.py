import json
import os
import time
from sentence_transformers import SentenceTransformer, util

CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache.json")
SIMILARITY_THRESHOLD = 0.95

_model = None
_cache_entries = []  # list of {query, embedding, response, timestamp}


def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _load_cache():
    global _cache_entries
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # Re-hydrate embeddings as lists (stored as lists in JSON)
            _cache_entries = raw
            print(f"[cache] Loaded {len(_cache_entries)} cached entries")
        except Exception as e:
            print(f"[cache] Failed to load cache, starting fresh: {e}")
            _cache_entries = []
    else:
        _cache_entries = []


def _save_cache():
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_cache_entries, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[cache] Failed to save cache: {e}")


def _ensure_loaded():
    if not _cache_entries and os.path.exists(CACHE_PATH):
        _load_cache()


def cache_lookup(query):
    """
    Returns cached response string if a semantically similar query exists
    (cosine similarity >= 0.95), else returns None.
    """
    _ensure_loaded()
    if not _cache_entries:
        return None

    try:
        model = _get_model()
        query_emb = model.encode(query, convert_to_tensor=True)

        for entry in _cache_entries:
            cached_emb = model.encode(entry["query"], convert_to_tensor=True)
            similarity = float(util.cos_sim(query_emb, cached_emb)[0][0])
            if similarity >= SIMILARITY_THRESHOLD:
                print(f"[cache] HIT (similarity={similarity:.4f}) for: {query[:60]}")
                return entry["response"]

        return None

    except Exception as e:
        print(f"[cache] Lookup error: {e}")
        return None


def cache_store(query, response):
    """Saves a query-response pair to the cache."""
    _ensure_loaded()
    try:
        entry = {
            "query": query,
            "response": response,
            "timestamp": time.time()
        }
        _cache_entries.append(entry)
        _save_cache()
        print(f"[cache] Stored new entry. Total entries: {len(_cache_entries)}")
    except Exception as e:
        print(f"[cache] Store error: {e}")


def cache_clear():
    """Wipes the cache entirely."""
    global _cache_entries
    _cache_entries = []
    if os.path.exists(CACHE_PATH):
        os.remove(CACHE_PATH)
    print("[cache] Cache cleared")


def cache_stats():
    _ensure_loaded()
    return {"entries": len(_cache_entries), "path": CACHE_PATH}


# Load on import so first request doesn't pay the I/O cost
_load_cache()
