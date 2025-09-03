

def _ensure_text_meta(res, agent_obj):
    """
    Her tür .run() çıktısını (string/tuple/dict/None) -> (text:str, meta:dict) dönüştür.
    """
    # (text, meta)
    if isinstance(res, tuple) and len(res) == 2:
        text, meta = res
        return str(text), (meta if isinstance(meta, dict) else {})

    # dict
    if isinstance(res, dict):
        text = res.get("output") or res.get("text") or res.get("content") or ""
        meta = {k: v for k, v in res.items() if k not in ("output", "text", "content")}
        meta.setdefault("agent", getattr(agent_obj, "name", lambda: None)() if hasattr(agent_obj, "name") else None)
        meta.setdefault("model", getattr(agent_obj, "model", None))
        meta.setdefault("backend", getattr(agent_obj, "backend", None))
        return str(text), meta

    # None / diğer tipler
    text = "" if res is None else str(res)
    meta = {
        "agent": getattr(agent_obj, "name", lambda: None)() if hasattr(agent_obj, "name") else None,
        "model": getattr(agent_obj, "model", None),
        "backend": getattr(agent_obj, "backend", None),
    }
    return text, meta


def run_agent_safe(agent_obj, user_text, history=None):
    """
    Ajanı güvenli çalıştır: çökmeden (text, meta) döndür.
    """
    try:
        raw = agent_obj.run(user_text, history=history or [])
        return _ensure_text_meta(raw, agent_obj)
    except Exception as e:
        text = f"[HATA] Ajan çalıştırma hatası: {e}"
        meta = {
            "agent": getattr(agent_obj, "name", lambda: None)() if hasattr(agent_obj, "name") else None,
            "model": getattr(agent_obj, "model", None),
            "backend": getattr(agent_obj, "backend", None),
            "error": True,
            "exception": repr(e),
        }
        return text, meta
