import os
from typing import List, Dict, Any, Optional

from .llm_runner import query_model, query_chat_model

# Tüm ajanlarda ortak dil politikası (tek system mesajında birleştirilecek)
LANG_SYSTEM = (
    "Cevabını YALNIZCA Türkçe ver. İngilizce hiçbir kelime, başlık veya kalıp kullanma. "
    "Eğer Türkçe dışı bir kelime üretirsen, tüm yanıtı baştan Türkçe olarak yeniden yaz ve sadece Türkçeyi gönder. "
    "Markdown başlıklarında da Türkçe kullan; 'First Step', 'Note', 'Example' gibi kalıpları kullanma. "
    "Net, motive edici ve saygılı bir üslup kullan. Gereksiz süslemelerden kaçın."
)

class Agent:
    """
    Config-driven ajanın temel sınıfı.
    YAML'daki anahtarlar __init__'a doğrudan geçilir:
      - model (zorunlu)
      - type: "template" | "chat"   (varsayılan: "template")
      - prompt_path: "prompts/xxx.txt" (opsiyonel)
      - backend: "ollama" | "transformers" ... (opsiyonel, varsayılan: "ollama")
      - temperature: float (opsiyonel)
      - max_tokens: int (opsiyonel)
      - system_prompt: str (opsiyonel; prompt dosyasına ek olarak birleşir)
      - description vb. fazladan alanlar görmezden gelinir.
    """
    def __init__(
        self,
        model: str,
        prompt_path: Optional[str] = None,
        type: str = "template",
        backend: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        **_: Any,  # YAML'dan gelebilecek kullanılmayan anahtarlar için
    ):
        self.model = model
        self.prompt_path = prompt_path
        self.type = type  # "template" veya "chat"
        self.backend = backend or os.getenv("DEFAULT_BACKEND", "ollama")
        self.temperature = 0.2 if temperature is None else float(temperature)
        self.max_tokens = 512 if max_tokens is None else int(max_tokens)
        self.extra_system_prompt = system_prompt or ""

    # --------------------------- Yardımcılar ---------------------------

    def _prompt_file_path(self) -> Optional[str]:
        if not self.prompt_path:
            return None
        return os.path.join(os.path.dirname(__file__), "..", self.prompt_path)

    def load_prompt(self, input_text: str) -> str:
        """
        TEMPLATE tipinde, prompt dosyasını okuyup {input}/{history} yerlerine değer basar.
        CHAT tipinde prompt dosyası system prompt olarak kullanılır (aşağıda birleşir).
        """
        path = self._prompt_file_path()
        if not path:
            return input_text
        with open(path, "r", encoding="utf-8") as f:
            template = f.read()
        return template.replace("{{input}}", input_text).replace("{input}", input_text)

    def _load_system_prompt(self) -> str:
        """
        CHAT modunda system prompt olarak kullanılacak metni döndürür.
        Dosya + LANG_SYSTEM + (varsa) config.system_prompt birleştirilir.
        """
        file_text = ""
        path = self._prompt_file_path()
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                file_text = f.read()
        
        file_text = (file_text or "").replace("{input}", "").replace("{{input}}", "") \
                                     .replace("{history}", "").replace("{{history}}", "")
        parts = []
        if self.extra_system_prompt is not None:
           
            if self.extra_system_prompt.strip():
                parts.append(self.extra_system_prompt.strip())
        else:
          
            parts.append(LANG_SYSTEM)

        if file_text.strip():
            parts.append(file_text.strip())
        return "\n\n".join(parts).strip()

    def _format_history_for_template(self, history: List[Dict[str, str]], limit: int = 8) -> str:
        if not history:
            return ""
        trimmed = history[-limit:]
        lines = []
        for msg in trimmed:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            lines.append(f"{role.upper()}: {content}")
        return "\n".join(lines)

   

    def run(self, user_input: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        if not isinstance(user_input, str):
            return "[HATA] Yalnızca metin (str) destekleniyor."

        history = history or []

      
        if self.type == "chat":
            system_text = self._load_system_prompt()

            messages: List[Dict[str, str]] = []
            messages.append({"role": "system", "content": system_text})

            for msg in history[-8:]:
                role = msg.get("role", "user")
                if role not in ("user", "assistant", "system"):
                    role = "user"
                
                if role == "system":
                    continue
                messages.append({"role": role, "content": msg.get("content", "")})

            messages.append({"role": "user", "content": user_input})

         
            return query_chat_model(
                self.model,
                messages,
                system_prompt="",               
                backend=self.backend,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

      
        prompt = self.load_prompt(user_input)
        hist_str = self._format_history_for_template(history, limit=8)
        if "{history}" in prompt or "{{history}}" in prompt:
            prompt = prompt.replace("{history}", hist_str).replace("{{history}}", hist_str)

        return query_model(
            self.model,
            prompt,
            backend=self.backend,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
