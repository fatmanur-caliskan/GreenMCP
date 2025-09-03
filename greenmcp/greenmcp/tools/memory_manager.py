
import os
import uuid
from collections import defaultdict
from difflib import get_close_matches

_FALLBACK_STORE = defaultdict(list)

_CHROMA_OK = False
try:
    import chromadb
    from chromadb.utils import embedding_functions

    _CHROMA_OK = True
    _CHROMA_DIR = os.path.join(os.path.dirname(__file__), "..", "memory_store")
    _client = chromadb.PersistentClient(path=_CHROMA_DIR)
    _ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    _col = _client.get_or_create_collection(
        name="chat_memory",
        embedding_function=_ef
    )
except Exception:
    _CHROMA_OK = False

def _flat_list(maybe_list):
    if not maybe_list:
        return []
    out = []
    for x in maybe_list:
        if isinstance(x, list):
            out.extend(x)
        elif isinstance(x, str):
            out.append(x)
    return out

def _mk_where(user_id: str | None = None, session_id: str | None = None, role: str | None = None):
    clauses = []
    if user_id is not None:
        clauses.append({"user_id": user_id})
    if session_id is not None:
        clauses.append({"session_id": session_id})
    if role is not None:
        clauses.append({"role": role})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}

def add_message_to_memory(user_id: str, role: str, content: str, session_id: str | None = None):
    if not content:
        return
    sid = session_id or "global"
    if _CHROMA_OK:
        _col.add(
            documents=[content],
            metadatas=[{"user_id": user_id, "role": role, "session_id": sid}],
            ids=[str(uuid.uuid4())]
        )
    else:
        tag = f"__SID__:{sid}__ROLE__:{role}__"
        _FALLBACK_STORE[user_id].append(tag + content)

def add_pair_to_memory(user_id: str, user_text: str, assistant_text: str, session_id: str | None = None):
    if not user_text and not assistant_text:
        return
    sid = session_id or "global"
    doc = f"[Soru]\n{user_text}\n\n[Yanıt]\n{assistant_text}"
    if _CHROMA_OK:
        _col.add(
            documents=[doc],
            metadatas=[{"user_id": user_id, "role": "pair", "session_id": sid}],
            ids=[str(uuid.uuid4())]
        )
    else:
        tag = f"__SID__:{sid}__ROLE__:pair__"
        _FALLBACK_STORE[user_id].append(tag + doc)

def search_memory(user_id: str, query: str, top_k: int = 3, session_id: str | None = None):
    if not query:
        return []

    if _CHROMA_OK:
        where = _mk_where(user_id=user_id, session_id=session_id)
        res = _col.query(
            query_texts=[query],
            n_results=top_k,
            where=where
        )
        docs = res.get("documents", [[]])[0]
        return _flat_list(docs)
    else:
        pool = _FALLBACK_STORE.get(user_id, [])
        if session_id:
            sid = session_id or "global"
            pool = [x for x in pool if x.startswith(f"__SID__:{sid}")]
        texts = [x.split("__", 2)[-1] if x.startswith("__SID__") else x for x in pool]
        return get_close_matches(query, texts, n=top_k, cutoff=0.3)

def get_full_memory(user_id: str) -> list[str]:
    if _CHROMA_OK:
        try:
            res = _col.get(where=_mk_where(user_id=user_id))
            docs = res.get("documents") or []
            return _flat_list(docs)
        except Exception:
            return []
    else:
        items = _FALLBACK_STORE.get(user_id, [])
        return [x.split("__", 2)[-1] if x.startswith("__SID__") else x for x in items]

def add_summary(user_id: str, text: str, session_id: str | None = None):
    if not text:
        return
    sid = session_id or "global"
    if _CHROMA_OK:
        add_message_to_memory(user_id, "summary", text, session_id=sid)
    else:
        tag = f"__SID__:{sid}__ROLE__:summary__"
        _FALLBACK_STORE[user_id].append(tag + text)

def get_recent_pairs(user_id: str, k: int = 3) -> list[str]:
    if _CHROMA_OK:
        try:
            res = _col.get(where=_mk_where(user_id=user_id))
            docs = res.get("documents") or []
            metas = res.get("metadatas") or []
            pairs = []
            for d, m in zip(docs, metas):
                role = (m or {}).get("role")
                if role == "pair":
                    pairs.append(d if isinstance(d, str) else (d[0] if d else ""))
            return [p for p in pairs if p][-k:]
        except Exception:
            return []
    else:
        items = _FALLBACK_STORE.get(user_id, [])
        pairs = [x for x in items if ("__ROLE__:pair__" in x) or (isinstance(x, str) and x.startswith("[Soru]"))]
        pairs = [p.split("__", 2)[-1] if p.startswith("__SID__") else p for p in pairs]
        return pairs[-k:]

def get_recent_summary(user_id: str, session_id: str | None = None) -> str | None:
    if _CHROMA_OK:
        try:
            res = _col.get(where=_mk_where(user_id=user_id, session_id=session_id))
            docs = res.get("documents") or []
            metas = res.get("metadatas") or []
            sums = []
            for d, m in zip(docs, metas):
                role = (m or {}).get("role")
                if role == "summary":
                    sums.append(d if isinstance(d, str) else (d[0] if d else ""))
            return sums[-1] if sums else None
        except Exception:
            return None
    else:
        items = _FALLBACK_STORE.get(user_id, [])
        if session_id:
            items = [x for x in items if x.startswith(f"__SID__:{session_id}")]
        sums = [x for x in items if "__ROLE__:summary__" in x]
        return sums[-1].split("__", 2)[-1] if sums else None

def clear_session_memory(user_id: str, session_id: str):
    if _CHROMA_OK:
        try:
            res = _col.get(where=_mk_where(user_id=user_id, session_id=session_id))
            ids = res.get("ids") or []
            ids = _flat_list(ids)
            if ids:
                _col.delete(ids=ids)
        except Exception:
            pass
    else:
        items = _FALLBACK_STORE.get(user_id, [])
        _FALLBACK_STORE[user_id] = [x for x in items if not x.startswith(f"__SID__:{session_id}")]

def clear_user_memory(user_id: str):
    if _CHROMA_OK:
        try:
            res = _col.get(where=_mk_where(user_id=user_id))
            ids = res.get("ids") or []
            ids = _flat_list(ids)
            if ids:
                _col.delete(ids=ids)
        except Exception:
            pass
    else:
        _FALLBACK_STORE[user_id].clear()
