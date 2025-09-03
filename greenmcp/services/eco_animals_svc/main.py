from fastapi import FastAPI
from pydantic import BaseModel

import re
import unicodedata
import httpx
from urllib.parse import quote

app = FastAPI(title="eco-animals-svc")

class AnimalQuery(BaseModel):
    intent: str
    species: str | None = None     
    biome: str | None = None
    level: str | None = None
    lang: str | None = "tr"
    text: str | None = None       

# ——— Metin yardımcıları ———
_TR = str.maketrans({"ç":"c","ğ":"g","ı":"i","ö":"o","ş":"s","ü":"u",
                     "Ç":"c","Ğ":"g","İ":"i","I":"i","Ö":"o","Ş":"s","Ü":"u"})

def _norm(s: str | None) -> str:
    z = unicodedata.normalize("NFKC", (s or "").strip()).lower()
  
    z = re.sub(r"[’'`´]", " ", z)
    z = re.sub(r"\s+", " ", z.translate(_TR)).strip()
    return z

def _strip_plurals(w: str) -> str:
   
    return re.sub(r"(lar|ler|lari|leri|ları|leri)$", "", w)

_TAIL_WORDS = (
    "hakkinda", "hakkkinda", "ile ilgili",
    "bilgi", "blgi", "bılgi", "bilgi ver", "bilgi verir misin", "bilgi verir misiniz",
    "verir misin", "verir misiniz",
    "anlat", "anlatir misin", "anlatır mısın", "anlatir misiniz",
    "bahset", "bahseder misin", "bahseder misiniz",
    "nedir", "kimdir", "ne dersin", "hakkinda ne", "hakkinda ne biliyorsun",
    "hakkinda bilgi", "hakkinda bilgi ver"
)
_TAIL_RE = re.compile(rf"\b(?:{'|'.join(map(re.escape,_TAIL_WORDS))})\b[\s\?\!]*$", re.IGNORECASE)

_STOP = {
    "bana","ban","lutfen","lütfen","biraz","bazi","bazı","bir","hakkinda","bilgi","ver",
    "anlat","bahset","nedir","kimdir","ile","ilgili","ne","dersin","hakkinda ne",
    "hakkinda bilgi","hakkinda","blgi"
}
_VERBS = {"verir","ver","anlat","bahset","paylas","paylaş","aktar","bilir","biliyor",
          "misin","mısın","misiniz","mısınız","eder","ediyor"}

def _extract_subject(txt: str | None) -> str:
    """Kullanıcı metninden hayvan öznesini çıkarır (tekilleştirir, fiilleri atar)."""
    if not txt:
        return "hayvan"

    t = _norm(txt)

    m = _TAIL_RE.search(t)
    base = t[:m.start()].strip() if m else t
    base = re.sub(r"[\?\!\.]+$", "", base).strip()

   
    if " hakkinda " in base:
        base = base.split(" hakkinda ", 1)[0].strip()

    toks = [w for w in base.split() if w and w not in _STOP]
    while toks and (toks[-1] in _VERBS):
        toks.pop()

    if not toks:
        return "hayvan"
    core = []
    for w in reversed(toks):
        if w in _STOP or w in _VERBS:
            continue
        core.append(_strip_plurals(w))
        if len(core) == 2:
            break
    core = list(reversed(core)) or [toks[-1]]
    subj = " ".join(core).strip()
    return subj or "hayvan"


def _first_sentences(text: str, max_chars: int = 700) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    
    m = re.search(r"[.!?](?:\s|$)", cut[::-1])
    if m:
        idx = max_chars - m.start()
        return t[:idx].strip()
    return cut.strip()

async def _wiki_search_title(client: httpx.AsyncClient, q: str, lang: str) -> str | None:
   
    try:
        r = await client.get(f"https://{lang}.wikipedia.org/w/rest.php/v1/search/title",
                             params={"q": q, "limit": 1, "redirect": "true"})
        r.raise_for_status()
        js = r.json() or {}
        pages = js.get("pages") or []
        if pages:
            return pages[0].get("title")
    except httpx.HTTPError:
        pass
   
    try:
        r = await client.get(f"https://{lang}.wikipedia.org/w/rest.php/v1/search/page",
                             params={"q": q, "limit": 1})
        r.raise_for_status()
        js = r.json() or {}
        pages = js.get("pages") or []
        if pages:
            return (pages[0].get("key") or pages[0].get("title"))
    except httpx.HTTPError:
        pass
    return None

async def _wiki_summary(client: httpx.AsyncClient, title: str, lang: str) -> tuple[str | None, str | None]:
    try:
        r = await client.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title)}",
                             params={"redirect": "true"})
        r.raise_for_status()
        js = r.json() or {}
        extract = (js.get("extract") or "").strip()
        page_url = js.get("content_urls", {}).get("desktop", {}).get("page")
        if extract:
            return _first_sentences(extract), (page_url or f"https://{lang}.wikipedia.org/wiki/{quote(title)}")
    except httpx.HTTPError:
        pass
    return None, None

async def _fetch_animal_summary(subject: str) -> tuple[str | None, str | None, str | None]:
    """
    Dönüş: (özet, kaynak_url, kullanılan_dil)
    Sıra: Türkçe sonra İngilizce. Birkaç aday denemesi yapar.
    """
    s = subject.strip()
    candidates = [s, s.title(), _strip_plurals(s)]
    if " " in s:
        candidates.append(" ".join(w.capitalize() for w in s.split()))
    
    candidates.extend([f"{s} (hayvan)", f"{s} hayvanı"])

    async with httpx.AsyncClient(timeout=8) as client:
        for lang in ("tr", "en"):
            # doğrudan özet
            for cand in candidates:
                txt, url = await _wiki_summary(client, cand, lang)
                if txt:
                    return txt, url, lang
            # arama → özet
            for cand in candidates:
                title = await _wiki_search_title(client, cand, lang)
                if title:
                    txt, url = await _wiki_summary(client, title, lang)
                    if txt:
                        return txt, url, lang
    return None, None, None

# ——— FastAPI ———
@app.get("/health")
def health():
    return {"status": "ok", "service": "eco-animals-svc"}

@app.post("/query")
async def query_animal(q: AnimalQuery):
  
    subject_raw = q.species or _extract_subject(q.text)
    subject = (subject_raw or "hayvan").strip()

    
    text, src, used_lang = await _fetch_animal_summary(subject)

    if text:
        src_note = f"\n(Kaynak: {src})" if src else ""
        return {
            "id": "animal_wiki",
            "type": "eco_animal",
            "species": subject.replace(" ", "_"),
            "text": f"{text}{src_note}",
            "eco_role": None,
            "biome": None,
            "level": q.level or "general",
            "lang": used_lang or (q.lang or "tr"),
            "tags": ["wiki","animal"]
        }

    return {
        "id": "animal_not_found",
        "type": "eco_animal",
        "species": subject.replace(" ", "_"),
        "text": f"“{subject}” için güvenilir ansiklopedi özeti bulunamadı. Yazımı farklı deneyebilir veya daha spesifik bir ad verebilirsin.",
        "eco_role": None,
        "biome": None,
        "level": q.level or "general",
        "lang": q.lang or "tr",
        "tags": ["not_found"]
    }
