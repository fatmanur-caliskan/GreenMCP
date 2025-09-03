

import os
import re
import difflib
import unicodedata
from typing import List, Tuple

from .agents.all_agents import AGENTS
from .agents.load_configs import DISPATCHER_CONFIG
from .agents.llm_runner import query_chat_model  

print(" [DEBUG] dispatcher_agent.py YÜKLENDİ")

# ----------------------------- Yardımcılar -----------------------------

def _format_history_for_dispatcher(history: list, limit: int = 6) -> str:
    """Log için kısa özet (yönlendirme kararını etkilemez)."""
    if not history:
        return ""
    trimmed = history[-limit:]
    lines = []
    for msg in trimmed:
        role = msg.get("role", "user")
        content = (msg.get("content", "") or "").strip()
        if not content:
            continue
        role = "KULLANICI" if role == "user" else ("ASİSTAN" if role == "assistant" else "SİSTEM")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)

# ---------------------- LLM destekli cümle bölme ----------------------

_NUM_PREFIX = re.compile(r"^\s*(?:\d+[\)\.\-:]|\(\d+\))\s*")  # "1) ", "1. ", "1- ", "(1) " vb.
_TRAIL_TRIM = re.compile(r"[ \t\u200b]+$")
_ERR_MARKERS = re.compile(r"(hata|error|not found|404|getaddrinfo failed|connection refused|client error)", re.IGNORECASE)

def _clean_lines(lines: List[str]) -> List[str]:
    out = []
    for ln in lines:
        s = (ln or "").strip()
        if not s:
            continue
        if _ERR_MARKERS.search(s):
            continue

        s = _NUM_PREFIX.sub("", s)
        s = s.strip(" ;•·–—*-")
        s = _TRAIL_TRIM.sub("", s)
        if len(s.split()) >= 2:
            out.append(s)
    return out

def _regex_fallback_split(text: str) -> List[str]:
    
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return []
  
    parts = re.split(r"(?<=[.!?])\s+", t)
    refined = []
 
    and_like = re.compile(r"\s+(?=\b(ve|ayrıca|ama|ancak|fakat|lakin)\b)", re.IGNORECASE)
    for p in parts:
        if not p:
            continue
        segs = and_like.split(p)
        for s in segs:
            s = s.strip(" ,;")
            if len(s.split()) >= 2:
                refined.append(s)
    return refined if refined else [t]

def split_into_sentences(text: str) -> List[str]:
    """
    1) LLM ile böl.
    2) Güvenlik filtresi:
       - Orijinal metnin alt dizgesi (boşluk/noktalama/aksan duyarsız) ise KABUL.
       - Aksi halde token örtüşmesi ≥ %70 ise (küçük düzeltmeleri tolere eder) KABUL.
    3) Hiç güvenli satır kalmazsa regex fallback.
    """
    print(f" [DEBUG] split_into_sentences() çağrıldı → input: {text}")
    if not text or not isinstance(text, str):
        return []

    model = DISPATCHER_CONFIG.get("model", "gemma3n:e4b")

    sys_msg = (
        "Aşağıdaki metni SADECE cümle sınırlarına göre böl. "
        "Girdide YAZMAYAN yeni cümle ekleme, yeniden yazma veya genişletme yapma. "
        "Her cümleyi TEK SATIRA koy. Numaralandırma, madde işareti veya ek açıklama ekleme."
    )
    user_msg = f"Metin:\n{text.strip()}\n\nCümleler:\n"

    def _clean_lines(lines: List[str]) -> List[str]:
        out = []
        for ln in lines:
            s = (ln or "").strip()
            if not s:
                continue
            s = re.sub(r"^\s*(?:\d+[\)\.\-:]|\(\d+\)|[-•*·–—])\s*", "", s)  
            s = s.strip()
            if len(s.split()) >= 1:
                out.append(s)
        return out

    # ——— normalize yardımcıları ———
    def _norm_loose(s: str) -> str:
        
        z = unicodedata.normalize("NFKC", s or "").lower()
        z = z.translate(_TR_MAP)  
        z = re.sub(r"\s+", "", z)
        z = re.sub(r"[^\w]", "", z, flags=re.UNICODE)
        return z

    def _tokens(s: str) -> List[str]:
        z = unicodedata.normalize("NFKC", s or "").lower()
        z = z.translate(_TR_MAP)
        return [t for t in re.findall(r"[a-z0-9]+", z) if len(t) >= 2]

    try:
        llm_out = query_chat_model(model, [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}
        ])

        if _ERR_MARKERS.search(llm_out or ""):
            raise RuntimeError(f"LLM error surface: {llm_out[:200]}")

        lines = [ln for ln in (llm_out or "").splitlines() if ln.strip()]
        cleaned = _clean_lines(lines)

        
        orig_norm = _norm_loose(text)
        orig_toks = set(_tokens(text))
        safe = []
        for s in cleaned:
            sn = _norm_loose(s)
            if sn and sn in orig_norm:
                safe.append(s)
                continue
            stoks = _tokens(s)
            if stoks:
                overlap = len(orig_toks.intersection(stoks)) / max(1, len(set(stoks)))
                if overlap >= 0.70:
                    safe.append(s)

        if safe:
            print(f" [DEBUG] split_into_sentences() (LLM→SAFE) sonuçları: {safe}")
            return safe

        print(" [WARN] LLM cümle genişletti/uydurdu; regex fallback kullanılacak.")
        return _regex_fallback_split(text)

    except Exception as e:
        print(f" [WARN] LLM bölme hatası: {e}; regex fallback kullanılacak.")
        return _regex_fallback_split(text)


# ---------------------- dispatcher.txt örneklerini yükleme ----------------------

def _load_examples_from_prompt(prompt_text: str) -> List[Tuple[str, str]]:
    """
    Şu kalıpları yakalar:
      Mesaj: "...."   (tırnaklı veya tırnaksız)
      Seçilen ajan|ar(a/â)ç|hedef: <target>
    Dönen: [(mesaj, target), ...]
    """
    pairs: List[Tuple[str, str]] = []
    msg_re = re.compile(r'^\s*Mesaj:\s*"(.*?)"\s*$|^\s*Mesaj:\s*(.+?)\s*$', re.IGNORECASE)
    sel_re = re.compile(r"^\s*Seçilen\s*(?:ajan|ar[aâ]ç|hedef)\s*:\s*([A-Za-z0-9_]+)\s*$", re.IGNORECASE)

    lines = [ln.rstrip() for ln in (prompt_text or "").splitlines()]
    cur_msg = None
    for ln in lines:
        m_msg = msg_re.match(ln)
        if m_msg:
            cur_msg = (m_msg.group(1) or m_msg.group(2) or "").strip().strip('"')
            continue
        m_sel = sel_re.match(ln)
        if m_sel and cur_msg:
            target = m_sel.group(1).strip()
            pairs.append((cur_msg, target))
            cur_msg = None
    return pairs

# ---------------------- Benzerlik ve normalize ----------------------

_TR_MAP = str.maketrans({
    "ç": "c", "ğ": "g", "ı": "i", "i": "i", "ö": "o", "ş": "s", "ü": "u",
    "Ç": "c", "Ğ": "g", "İ": "i", "I": "i", "Ö": "o", "Ş": "s", "Ü": "u",
})
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = s.translate(_TR_MAP)
    s = s.replace("’", "'").replace("´", "'").replace("`", "'")
    s = re.sub(r"[^\w\s']+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _similarity(a: str, b: str) -> float:
    a = _norm(a)
    b = _norm(b)
    return difflib.SequenceMatcher(None, a, b).ratio()

def _best_example_target(sent: str, examples: List[Tuple[str, str]]) -> Tuple[str | None, float]:
    best_target, best_score = None, -1.0
    for ex_msg, ex_target in examples:
        sc = _similarity(sent, ex_msg)
        if sc > best_score:
            best_score, best_target = sc, ex_target
    print(f" [DEBUG] example-match '{sent}' → {best_target} (score={best_score:.3f})")
    return best_target, best_score

# --------------------------- Ana karar verici ---------------------------

def multi_decide_agents(prompt: str, history: list | None = None, valid_names: set[str] | None = None) -> list:
    
    base_dir = os.path.abspath(os.path.dirname(__file__))
    prompt_path = os.path.join(base_dir, DISPATCHER_CONFIG.get("prompt_path", "prompts/dispatcher.txt"))

    # dispatcher.txt oku
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            example_prompt = f.read()
    except FileNotFoundError:
        print(f"[HATA] Dispatcher prompt dosyası bulunamadı: {prompt_path}")
        example_prompt = ""

    # Örnekleri yükle
    examples = _load_examples_from_prompt(example_prompt)
    print(f"[DISPATCHER] {len(examples)} örnek yüklendi.")

    # Cümlelere ayır
    sentences = split_into_sentences(prompt)
    if not sentences:
        sentences = [prompt]

    # agents ∪ dispatcher.txt’teki tüm hedefler (tool’lar dahil)
    agent_names = set(AGENTS.keys())
    tool_names  = {ex_target for _, ex_target in examples}
    valid_targets = valid_names if valid_names is not None else (agent_names | tool_names)


    # (Sadece log amaçlı) kısa bağlam yaz
    history_str = _format_history_for_dispatcher(history or [], limit=6)
    if history_str:
        print(" [DEBUG] history context enjekte edildi")

    results = []

    for sentence in sentences:
        sent = sentence.strip()
        picked, score = _best_example_target(sent, examples)

        # dispatcher.txt'den çıkan hedef valid_targets içinde değilse güvenli varsayılan qa_agent
        if not picked or (valid_targets and picked not in valid_targets):
            print(f" Hedef geçersiz veya bulunamadı. Varsayılan: qa_agent (score={score:.3f})")
            results.append({"agent": "qa_agent", "input": sent})
            continue

        task = {"agent": picked, "input": sent}
        # Hedef AGENTS’te değilse bunu “tool” kabul ediyoruz ve source_agent veriyoruz
        if picked not in AGENTS:
            task["source_agent"] = "qa_agent"
        print(f"Dispatcher (örnek): '{sent}' → {picked} (score={score:.3f})")
        results.append(task)

    return results
