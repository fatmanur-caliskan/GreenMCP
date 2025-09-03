
import requests
import re
from typing import List, Dict, Any, Union, Optional

# ---------------------- Ortak Yardımcılar ----------------------

def remove_think_blocks(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

_EN_TRIGGERS = re.compile(
    r"\b(what|why|how|when|where|which|first|second|step|note|example|perfect|let's|"
    r"how to|why it matters|public transportation|by|using|reduce|approximately|"
    r"please|ready|are you|your|you)\b",
    re.IGNORECASE
)

def _looks_english(text: str) -> bool:
    if not text:
        return False
    return bool(_EN_TRIGGERS.search(text))

REQ_TIMEOUT = 240  # saniye


# ---------------------- Ollama yardımcıları (mevcut davranış) ----------------------

def _rewrite_turkish_ollama(model_name: str, text: str) -> str:
    """Gerekirse İngilizceye kayan çıktıyı tekrar Türkçeye çevirir (yalnızca Ollama yolunda)."""
    payload = {
        "model": model_name,
        "prompt": (
            "Aşağıdaki metni SADECE TÜRKÇE olacak şekilde yeniden yaz. "
            "İngilizce hiçbir kelime kullanma. Kısa, net ve motive edici olsun.\n\n"
            "METİN:\n" + (text or "")
        ),
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 384}
    }
    try:
        r = requests.post("http://localhost:11434/api/generate", json=payload, timeout=REQ_TIMEOUT)
        r.raise_for_status()
        return remove_think_blocks(r.json().get("response", "").strip())
    except requests.exceptions.RequestException:
        return text or ""


def _ollama_generate(model_name: str, prompt: str, temperature: float, num_predict: int) -> str:
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": num_predict}
    }
    r = requests.post("http://localhost:11434/api/generate", json=payload, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    return remove_think_blocks(r.json().get("response", "").strip())


def _ollama_chat(model_name: str, messages: List[Dict[str, str]], temperature: float, num_predict: int) -> str:
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": num_predict}
    }
    r = requests.post("http://localhost:11434/api/chat", json=payload, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    return remove_think_blocks(r.json().get("message", {}).get("content", "").strip())


# ---------------------- Transformers (HF) yolu — YENİ ----------------------

def _hf_chat(model_id: str, system: str, user: str, temperature: float, max_new_tokens: int) -> str:
    """Transformers backend: tek çağrıda (system + user) sohbet."""
    from .backends.transformers_backend import chat as hf_chat
    text = hf_chat(model_id, system or "", user or "",
                   temperature=temperature, max_new_tokens=max_new_tokens)
    return remove_think_blocks(text)


# ====================== GENEL KAMU API’SI ======================

def query_model(model_name: str,
                prompt: str,
                purpose: str = "default",
                options: Optional[Dict[str, Any]] = None,
                backend: str = "ollama",
                temperature: Optional[float] = None,
                max_tokens: Optional[int] = None) -> str:
    """
    Tek seferlik 'prompt' çağrısı.
      - backend="ollama" → localhost:11434 /api/generate (mevcut davranış)
      - backend="transformers" → HF/Transformers ile yerel inference (system boş)
    """
    # Varsayılanlar
    temperature = 0.2 if temperature is None else float(temperature)
    num_predict = int(options.get("num_predict", 128) if options else (max_tokens or 128))

    if backend in ("transformers", "hf", "huggingface"):
      
        system = "" if purpose == "dispatcher" else (
            "Cevabını yalnızca Türkçe ver. İngilizce hiçbir kelime KULLANMA.\n"
            "Yanıtların açık, anlaşılır ve motive edici olsun."
        )
        out = _hf_chat(model_name, system, prompt, temperature, max_new_tokens=num_predict)
        
        return out

    if purpose == "dispatcher":
        full_prompt = prompt
    else:
        full_prompt = (
            "Cevabını yalnızca Türkçe ver. İngilizce hiçbir kelime KULLANMA.\n"
            "Yanıtların açık, anlaşılır ve motive edici olsun.\n"
            f"{prompt}"
        )

    try:
        out = _ollama_generate(model_name, full_prompt, temperature, num_predict)
        if purpose != "dispatcher" and _looks_english(out):
            out = _rewrite_turkish_ollama(model_name, out)
        return out
    except requests.exceptions.RequestException as e:
        return f"[HATA] Model isteği başarısız oldu: {e}"


def query_chat_model(model_name: str,
                     history: Union[List[Dict[str, str]], str],
                     system_prompt: str = "",
                     backend: str = "ollama",
                     temperature: Optional[float] = None,
                     max_tokens: Optional[int] = None) -> str:
    """
    Chat tarzı çağrı.
      - history ya tam 'messages' listesi (role/content) ya da düz kullanıcı metni olabilir.
      - backend:
          * "ollama"       → /api/chat (mevcut davranış korunur)
          * "transformers" → messages → (system,user) birleştirilip HF/Transformers ile çalışır
    """
    temperature = 0.2 if temperature is None else float(temperature)
    num_predict = 256 if max_tokens is None else int(max_tokens)

    if backend in ("transformers", "hf", "huggingface"):
        # messages -> (system, user) dönüştür
        sys = system_prompt or ""
        user = ""
        if isinstance(history, list):
            for m in history:
                role = (m.get("role") or "").lower()
                content = m.get("content", "")
                if role == "system" and not sys and content:
                    sys = content
                elif role == "user" and content:
                    user += content + "\n"
        else:
            user = str(history or "")
        user = user.strip()
        return _hf_chat(model_name, sys, user, temperature, max_new_tokens=num_predict)

    # ---- OLLAMA (varsayılan) ----
    try:
        if isinstance(history, list):
            messages = history
        else:
            # Kullanıcı tek metin verdiyse sistem promptunu ekleyip messages oluştur
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": str(history or "")})

        out = _ollama_chat(model_name, messages, temperature, num_predict)
        if _looks_english(out):
            out = _rewrite_turkish_ollama(model_name, out)
        return out
    except requests.exceptions.RequestException as e:
        return f"[HATA] Chat modeli isteği başarısız oldu: {e}"
