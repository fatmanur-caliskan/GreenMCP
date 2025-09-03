from __future__ import annotations
from functools import lru_cache
import os
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM


torch.set_num_threads(int(os.getenv("HF_CPU_THREADS", "2")))

@lru_cache(maxsize=2)
def _load(model_id: str):
    tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=False)

    dtype = torch.bfloat16
    try:
        _ = torch.zeros(1, dtype=dtype)
    except Exception:
        dtype = torch.float32

    mdl = AutoModelForCausalLM.from_pretrained(
        model_id,
        device_map="cpu",
        torch_dtype=dtype,
        low_cpu_mem_usage=True,   # yükleme sırasında RAM tasarrufu
        trust_remote_code=False,
    )
    return tok, mdl

def _fallback_prompt(system: str, user: str) -> str:
    return f"{(system or '').strip()}\nUser: {user.strip()}\nAssistant:"

def chat(model_id: str, system: str, user: str,
         temperature: float = 0.2, max_new_tokens: int = 128) -> str:
    
    print(f"[DEBUG] transformers_backend.chat() called")
    print(f"[DEBUG] system: {system}")
    print(f"[DEBUG] user: {user}")

    tok, mdl = _load(model_id)
    mdl.eval()  

    
    messages = []
    if (system or "").strip():
        messages.append({"role": "system", "content": system.strip()})
    messages.append({"role": "user", "content": user.strip()})

    if hasattr(tok, "apply_chat_template") and getattr(tok, "chat_template", None):
        input_ids = tok.apply_chat_template(
            messages,
            add_generation_prompt=True,
            return_tensors="pt"         
        )
        attention_mask = torch.ones_like(input_ids)
    else:
        prompt = _fallback_prompt(system, user)
        enc = tok(prompt, return_tensors="pt")
        input_ids = enc["input_ids"]
        attention_mask = enc.get("attention_mask", torch.ones_like(input_ids))

    print(f"[DEBUG] input_ids.shape: {input_ids.shape}")
    print(f"[DEBUG] attention_mask.shape: {attention_mask.shape}")

   
    eos_id = getattr(mdl.config, "eos_token_id", None)
    if isinstance(eos_id, list):
        eos_id = eos_id[0] if eos_id else None
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id

    print(f"[DEBUG] eos_token_id: {eos_id}")
    print(f"[DEBUG] pad_token_id: {pad_id}")

    with torch.inference_mode():
        out = mdl.generate(
            input_ids=input_ids,
            attention_mask=attention_mask,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            do_sample=(temperature > 0),
            pad_token_id=pad_id,
            eos_token_id=eos_id,
            use_cache=True,        
        )

    print(f"[DEBUG] output shape: {out.shape}")

 
    gen_ids = out[0, input_ids.shape[1]:]

    print(f"[DEBUG] generated token IDs: {gen_ids}")

    text = tok.decode(gen_ids, skip_special_tokens=True)

    print(f"[DEBUG] decoded text: '{text}'")

    return text.strip()
