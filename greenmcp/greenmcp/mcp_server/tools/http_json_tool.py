import httpx
import json
from typing import Any, Dict, Optional

class HttpJsonTool:
    def __init__(self, base_url: str, path: str, method: str = "POST",
                 query_map: Optional[Dict[str, str]] = None,
                 body_mode: str = "json", body_map: Optional[Dict[str, str]] = None,
                 template: Optional[str] = None, response_key: Optional[str] = None,
                 timeout: int = 10, headers: Optional[Dict[str, str]] = None):
        self.base_url = base_url.rstrip("/")
        self.path = path if path.startswith("/") else "/" + path
        self.method = method.upper()
        self.query_map = query_map or {}
        self.body_mode = body_mode
        self.body_map = body_map or {}
        self.template = template or ""
        self.response_key = response_key
        self.timeout = timeout
        self.headers = headers or {"Content-Type": "application/json"}

    def _dot_get(self, obj: Any, path: Optional[str]) -> Any:
        if not path: 
            return obj
        cur = obj
        for p in path.split("."):
            if isinstance(cur, dict) and p in cur: 
                cur = cur[p]
            else: 
                return None
        return cur

    def _build_query(self, user_input: str) -> Dict[str, Any]:
        out = {}
        for k, src in self.query_map.items():
            out[k] = user_input if src == "input" else src.split("literal:",1)[1] if src.startswith("literal:") else None
        return {k:v for k,v in out.items() if v is not None}

    def _build_body(self, user_input: str):
        mode = (self.body_mode or "json").lower()
        if mode == "raw": 
            return user_input
        if mode == "template": 
            return (self.template or "").replace("{{input}}", user_input)
        if not self.body_map: 
            return {"input": user_input}
        body: Dict[str, Any] = {}
        for k, src in self.body_map.items():
            body[k] = user_input if src == "input" else src.split("literal:",1)[1] if src.startswith("literal:") else None
        return {k:v for k,v in body.items() if v is not None}

    def run(self, user_input: str, history=None) -> str:
        url = f"{self.base_url}{self.path}"
        try:
            with httpx.Client(timeout=self.timeout, headers=self.headers) as c:
                if self.method == "GET":
                    r = c.get(url, params=self._build_query(user_input))
                else:
                    params = self._build_query(user_input)
                    body = self._build_body(user_input)
                    r = c.post(url, params=params, json=body) if isinstance(body,(dict,list)) else c.post(url, params=params, content=body)
                r.raise_for_status()
                data = r.json() if "application/json" in r.headers.get("content-type","") else {"text": r.text}
        except httpx.HTTPError as e:
            return f"[HATA] HttpJsonTool isteği başarısız: {e}"

        val = self._dot_get(data, self.response_key) if isinstance(data, dict) else None
        if val is None:
            try: 
                return json.dumps(data, ensure_ascii=False)
            except Exception: 
                return str(data)
        if isinstance(val, (dict, list)):
            try:
                return json.dumps(val, ensure_ascii=False)
            except Exception: 
                return str(val)
        return str(val)
