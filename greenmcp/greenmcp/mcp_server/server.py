
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any
import re
import os

from ..dispatcher_agent import multi_decide_agents
from .tool_registry import build_tool_registry, get_allow_map
from ..tools.memory_manager import (
    add_message_to_memory, search_memory, add_pair_to_memory, get_full_memory,
    add_summary, get_recent_pairs, get_recent_summary
)
from ..agents.llm_runner import query_model
from ..agents.load_configs import AGENT_CONFIGS, DISPATCHER_CONFIG 
from ..agents.all_agents import AGENTS  
from ..utils.agent_exec import run_agent_safe


PAIR_RE = re.compile(r"\[Soru\]\s*(.*?)\s*\[Yanıt\]\s*(.*)", re.DOTALL)

def _extract_pair(text: str) -> str | None:
    m = PAIR_RE.search(text or "")
    if not m:
        return None
    q = (m.group(1) or "").strip()
    a = (m.group(2) or "").strip()
    if len(q) > 300:
        q = q[:300] + "…"
    if len(a) > 300:
        a = a[:300] + "…"
    return f"SON KONU — Kullanıcı: {q}\nAsistan: {a}"


class MCPServer:
    def __init__(self, name, tools):
        self.name = name
        self.tools = tools  
        self.allow_map = get_allow_map()  
    
    def _coalesce_tasks(self, tasks: list) -> list:
        merged = []
        for t in tasks:
            agent = t.get("agent")
            if merged and merged[-1].get("agent") == agent:
                # AJAN + TOOL fark etmeksizin birleştir
                prev = merged[-1]
                prev["input"] = (prev.get("input", "") + " " + t.get("input", "")).strip()
                if "source_agent" not in prev and "source_agent" in t:
                    prev["source_agent"] = t["source_agent"]
            else:
                merged.append(dict(t))
        return merged


    def _maybe_store_summary(self, user_id: str, rolling_history: list, session_id: str | None = None):

        try:
            if len(rolling_history) < 8:
                return

            last_chunk = rolling_history[-8:]
            text = "\n".join(f"{m['role']}: {m['content']}" for m in last_chunk if m.get("content"))

         
            model_for_summary = (DISPATCHER_CONFIG or {}).get("model") \
                or next((cfg.get("model") for cfg in (AGENT_CONFIGS or {}).values() if cfg.get("model")), None)
            backend_for_summary = (DISPATCHER_CONFIG or {}).get("backend")

            if not model_for_summary:
                return  

            summary = query_model(
                model_for_summary,
                "Aşağıdaki sohbeti 2 cümlede, konu ve alınan karar/öneri odaklı özetle:\n\n" + text,
                options={"temperature": 0.2, "num_predict": 200},
                backend=backend_for_summary or "ollama",
            )
            add_summary(user_id, summary.strip(), session_id=session_id or "global")

        except Exception:
            pass


    def _enrich_history_for_agents(self, user_id: str, session_id: str | None, input_data: str, history: list) -> list:
        """Yalnızca LLM ajanları için geçmiş/özet/ilgili bağlamı system mesajı olarak enjekte eder."""
        new_hist = history[:] if history else []

       
        sys_lines = []
        last_sum = get_recent_summary(user_id)
        if last_sum:
            sys_lines.append("Önceki sohbet özeti: " + last_sum.strip())

        recent_pairs = get_recent_pairs(user_id, k=2)
        for p in recent_pairs:
            pair_line = _extract_pair(p)
            if pair_line:
                sys_lines.append(pair_line)

        # — Genel (oturumdan bağımsız) benzerlik —
        hits = search_memory(user_id, input_data or "önceki konular", top_k=2, session_id=None)
        for h in hits:
            if h and not str(h).startswith("[Soru]"):
                sys_lines.append("İlgili geçmiş: " + str(h).strip())

        if not sys_lines:
           
            full_mem = get_full_memory(user_id)
            if full_mem:
                joined = " • ".join(x.strip() for x in full_mem if x and x.strip())
                if len(joined) > 1500:
                    joined = joined[:1500] + "…"
                sys_lines.append("Önceki sohbetlerden öne çıkan içerikler: " + joined)

        if sys_lines:
            new_hist.insert(0, {"role": "system", "content": "\n".join(sys_lines)})

        # — Oturum içi benzerlik —
        memory_hits = search_memory(user_id, input_data, top_k=3, session_id=session_id)
        print(f"[MEM] user_id={user_id} | session_id={session_id} | input='{input_data}' | hit_sayısı={len(memory_hits)} | hits={memory_hits}")
        if memory_hits:
            ctx = " • ".join(str(hit).strip() for hit in memory_hits if hit and str(hit).strip())
            if ctx:
                new_hist.insert(0, {"role": "system", "content": f"Önceki sohbetlerden ilgili bağlam: {ctx}"})

        return new_hist

    async def run(self, query: dict):
        input_data = query.get("input") or ""
        tool_name = query.get("tool")
        history = query.get("history", []) or []
        user_id = query.get("user_id", "default")
        session_id = query.get("session_id") or "global"

        
        raw_history = history or []

        # ——— Dispatcher: hedef seçimi (ajan veya tool) ———
        valid_targets = set(self.tools.keys())
        if not tool_name:
       
            sub_tasks = multi_decide_agents(input_data, history=raw_history, valid_names=valid_targets)
        else:
            sub_tasks = [{"agent": tool_name, "input": input_data}]

        
        sub_tasks = self._coalesce_tasks(sub_tasks)

      
        has_agent = any(t.get("agent") in AGENTS for t in sub_tasks)
        agent_history = self._enrich_history_for_agents(user_id, session_id, input_data, raw_history) if has_agent else raw_history

        response_list = []
        
        rolling_history = (agent_history if has_agent else raw_history)[:]

        for task in sub_tasks:
            agent_name = task["agent"]
            input_text = task["input"]

            # --- LLM mi, tool mu? ---
            is_llm_agent = agent_name in AGENTS

            
            obj = (AGENTS.get(agent_name) if is_llm_agent else self.tools.get(agent_name))
            if not obj:
                response_list.append({
                    "agent": agent_name,
                    "input": input_text,
                    "error": f"'{agent_name}' kayıtlı değil."
                })
                continue

            if not is_llm_agent:
                source_agent = task.get("source_agent") or "qa_agent"
                allowed = self.allow_map.get(source_agent)
                if isinstance(allowed, list) and allowed and agent_name not in allowed:
                    response_list.append({
                        "agent": agent_name,
                        "input": input_text,
                        "error": f"'{source_agent}' bu aracı kullanamaz (allow-list)."
                    })
                    add_message_to_memory(user_id, "user", input_text, session_id=session_id)
                    continue

           
            minimal_history = (agent_history if is_llm_agent else raw_history)[-12:]

            try:
              
                text, meta = run_agent_safe(obj, input_text, history=minimal_history)

                # hafıza
                add_message_to_memory(user_id, "user", input_text, session_id=session_id)
                add_message_to_memory(user_id, "assistant", text, session_id=session_id)
                add_pair_to_memory(user_id, input_text, text, session_id=session_id)

                # yanıt
                response_list.append({"agent": agent_name, "input": input_text, "output": text, "meta": meta})
                rolling_history.append({"role": "user", "content": input_text})
                rolling_history.append({"role": "assistant", "content": text})

            except Exception as e:
              response_list.append({
                "agent": agent_name,
                "input": input_text,
                "error": f"[HATA] Çalıştırma hatası: {e}"
        })


        # ——— Tekrarlı çıktıları tekilleştirip özetle ———
        seen, uniq = set(), []
        for r in response_list:
            out = r.get("output")
            if out and out not in seen:
                seen.add(out)
                uniq.append(out)

        self._maybe_store_summary(user_id, rolling_history, session_id=session_id)
        return {"responses": response_list, "summary": "\n\n---\n\n".join(uniq)}


# ——— FastAPI uygulaması ———
app = FastAPI(title="GreenMCP Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

server = MCPServer(name="GreenMCP", tools=build_tool_registry())

@app.on_event("startup")
def warm_up_models():
    if os.getenv("DISABLE_WARMUP","0") == "1":
        return
    # Dispatcher modelini ısıt
    try:
        d_model = (DISPATCHER_CONFIG or {}).get("model")
        if d_model:
            query_model(d_model, "ping", options={"num_predict": 1})
    except Exception:
        pass

    # Tüm agent modellerini sırayla ısıt
    for agent_name, cfg in (AGENT_CONFIGS or {}).items():
        try:
            model = cfg.get("model")
            if model:
                query_model(model, "ping", options={"num_predict": 1})
        except Exception:
            pass


class ChatRequest(BaseModel):
    history: List[Dict[str, Any]] = Field(default_factory=list)
    message: str | None = None
    tool: str | None = None
    user_id: str | None = "default"
    session_id: str | None = None


@app.get("/health")
def health():
    return {"status": "ok", "service": "greenmcp"}

@app.post("/ask")
async def ask_mcp(query: dict):
    response = await server.run({
        "input": query.get("input"),
        "tool": query.get("tool"),
        "history": query.get("history", []),
        "user_id": query.get("user_id", "default"),
        "session_id": query.get("session_id")
    })
    return {"response": response}

@app.post("/chat")
async def chat_endpoint(chat_req: ChatRequest):
    if not chat_req.history and chat_req.message:
        response = await server.run({
            "input": chat_req.message,
            "tool": chat_req.tool,
            "history": [],
            "user_id": chat_req.user_id or "default",
            "session_id": chat_req.session_id
        })
        return {"response": response}

    if not chat_req.history:
        return {"response": {"summary": "⚠️ Geçmiş veri boş. Lütfen bir mesaj girin."}}

    latest_message = chat_req.history[-1]["content"]
    response = await server.run({
        "input": latest_message,
        "tool": chat_req.tool,
        "history": chat_req.history,
        "user_id": chat_req.user_id or "default",
        "session_id": chat_req.session_id
    })
    return {"response": response}
