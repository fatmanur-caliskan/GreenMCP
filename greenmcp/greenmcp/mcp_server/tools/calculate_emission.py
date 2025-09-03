import httpx
import json
import re
import unicodedata

_NUM = r"(\d+(?:[.,]\d+)?)"

# —— Varsayımlar / sabitler ——
NG_M3_PER_HOUR = 1.5  # Doğalgaz kullanımında varsayılan dönüşüm: 1 saat ≈ 1.5 m³

# —— Esnek doğal dil desenleri ——
RE_KM        = re.compile(_NUM + r"\s*(?:km|kilometre)\b", re.IGNORECASE)
RE_KWH       = re.compile(_NUM + r"\s*(?:k\s*w\s*h|kwh|kilovat\s*saat|kilovatsaat)\b", re.IGNORECASE)
RE_BOTTLE = re.compile(r"(\d+)\s*(?:tane\s*)?(?:pet(?:\s*şişe)?|şişe)\b", re.IGNORECASE)

RE_CHICK_PORT_A = re.compile(r"(\d+)\s*(?:porsiyon|persiyon)(?:\s*tavuk)?\b", re.IGNORECASE)
RE_CHICK_PORT_B = re.compile(r"tavuk\s*(\d+)\s*(?:porsiyon|persiyon)\b", re.IGNORECASE)
RE_CHICK_G_A    = re.compile(_NUM + r"\s*(?:g|gr|gram)\s*(?:tavuk)?\b", re.IGNORECASE)
RE_CHICK_G_B    = re.compile(r"tavuk\s*"+_NUM+r"\s*(?:g|gr|gram)\b", re.IGNORECASE)
RE_CHICK_KG     = re.compile(_NUM + r"\s*kg\s*(?:tavuk)?\b", re.IGNORECASE)

RE_BEEF_KG      = re.compile(_NUM + r"\s*kg\s*(?:dana|sığır|sigir|biftek|kırmızı\s*et)\b", re.IGNORECASE)
RE_MILK_L       = re.compile(_NUM + r"\s*(?:l|lt|litre)\s*süt\b", re.IGNORECASE)
RE_NG_M3        = re.compile(_NUM + r"\s*(?:m3|metreküp)\s*(?:doğalgaz|dogalgaz)\b", re.IGNORECASE)

# Doğalgaz “saat” → m³ (iki yönlü yazım)
RE_NG_HOUR_A    = re.compile(_NUM + r"\s*saat\s*(?:doğalgaz|dogalgaz)\b", re.IGNORECASE)
RE_NG_HOUR_B    = re.compile(r"(?:doğalgaz|dogalgaz)\s*"+_NUM+r"\s*saat\b", re.IGNORECASE)

RE_FLIGHT_KM    = re.compile(_NUM + r"\s*km\s*(?:uçuş|ucus|uçak)\b", re.IGNORECASE)
RE_BUS_KM       = re.compile(_NUM + r"\s*km\s*otobüs\b", re.IGNORECASE)
RE_RAIL_KM      = re.compile(_NUM + r"\s*km\s*(?:tren|raylı|rayli)\b", re.IGNORECASE)
RE_PAPER_KG     = re.compile(_NUM + r"\s*kg\s*(?:kâğıt|kağıt|kagit)\b", re.IGNORECASE)
RE_WASTE_KG     = re.compile(_NUM + r"\s*kg\s*(?:çöp|cop|atık|atik)\b", re.IGNORECASE)

def _to_float(s: str) -> float:
    s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0

def _normalize_text(t: str) -> str:
    # Unicode normalize + fazla boşlukları sadeleştir
    t = unicodedata.normalize("NFKC", t or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t

def _fix_common_split_words(t: str) -> str:
    """
    Kullanıcı yazım hataları: 'ta vuk' → 'tavuk', 'do ğal gaz' → 'doğalgaz' vb.
    Harfler arasına sıkışmış boşlukları toparlayan basit düzeltmeler.
    """
    # tavuk (ta vuk, t a v u k, t a   v   u  k, ...)
    t = re.sub(r"t\s*a\s*v\s*u\s*k", "tavuk", t, flags=re.IGNORECASE)
    # doğalgaz (do ğal gaz / do gal gaz / dog al gaz ...)
    t = re.sub(r"d\s*o\s*ğ?\s*a\s*l\s*g\s*a\s*z", "doğalgaz", t, flags=re.IGNORECASE)
    # metreküp (metre küp vs.)
    t = re.sub(r"m\s*e\s*t\s*r\s*e\s*k\s*ü\s*p", "metreküp", t, flags=re.IGNORECASE)
    return t

def _iter_nums(pattern, text):
    """pattern.finditer() ile tüm eşleşmelerin sayısal değerlerini döndürür."""
    for m in pattern.finditer(text):
        try:
            yield float(_to_float(m.group(1)))
        except Exception:
            continue

def _has_transport_keyword(ctx: str) -> bool:
   
    ctx = (ctx or "").lower()
    return any(kw in ctx for kw in ["otobüs", "otobus", "tren", "uçuş", "ucus", "uçak", "ucak"])

def _parse_natural_language(text: str) -> dict:
    
    t = _normalize_text((text or "").lower())
    t = _fix_common_split_words(t)  # 'ta vuk' vb. düzelt

    items = []

    # Araç / km  (bus/train/flight bağlamı varsa atla)
    for m in RE_KM.finditer(t):
        try:
            ctx = t[max(0, m.start() - 16): m.start()]
            if _has_transport_keyword(ctx):
                continue
            val = _to_float(m.group(1))
            if val > 0:
                items.append({"key": "car", "amount": val, "unit": "km"})
        except Exception:
            pass

    # Elektrik / kWh
    for val in _iter_nums(RE_KWH, t):
        items.append({"key": "electricity", "amount": val, "unit": "kwh"})

    # Pet şişe / adet
    for m in RE_BOTTLE.finditer(t):
        try:
            n = int(_to_float(m.group(1)))
            items.append({"key": "pet_bottle", "amount": float(n), "unit": "piece"})
        except Exception:
            pass

    # ——— TAVUK ———
    # 1) porsiyon yazımları
    port_total = 0
    for m in RE_CHICK_PORT_A.finditer(t):
        port_total += int(_to_float(m.group(1)))
    for m in RE_CHICK_PORT_B.finditer(t):
        port_total += int(_to_float(m.group(1)))
    if port_total > 0:
        items.append({"key": "chicken", "amount": float(port_total), "unit": "portion"})

    # 2) gram yazımları (200 g ≈ 1 porsiyon)
    grams_total = 0.0
    for mg in RE_CHICK_G_A.finditer(t):
        grams_total += _to_float(mg.group(1))
    for mg in RE_CHICK_G_B.finditer(t):
        grams_total += _to_float(mg.group(1))
    
    if "tavuk" in t and grams_total > 0:
        portions = max(1, int(round(grams_total / 200.0)))
        items.append({"key": "chicken", "amount": float(portions), "unit": "portion"})

    # 3) kg yazımı
    for mk in RE_CHICK_KG.finditer(t):
        kg = _to_float(mk.group(1))
        if kg > 0:
            items.append({"key": "chicken", "amount": kg, "unit": "kg"})

    # Dana eti (kg)
    for mk in RE_BEEF_KG.finditer(t):
        kg = _to_float(mk.group(1))
        if kg > 0:
            items.append({"key": "beef", "amount": kg, "unit": "kg"})

    # Süt (L)
    for ml in RE_MILK_L.finditer(t):
       liters = _to_float(ml.group(1))   
       if liters > 0:
            items.append({"key": "milk", "amount": liters, "unit": "l"})

    # Doğalgaz (m3)
    for m3 in RE_NG_M3.finditer(t):
        v = _to_float(m3.group(1))
        if v > 0:
            items.append({"key": "natural_gas", "amount": v, "unit": "m3"})

    # Doğalgaz (saat) → m³ (varsayım: NG_M3_PER_HOUR)
    for mh in RE_NG_HOUR_A.finditer(t):
        h = _to_float(mh.group(1))
        if h > 0:
            items.append({"key": "natural_gas", "amount": round(h * NG_M3_PER_HOUR, 3), "unit": "m3"})
    for mh in RE_NG_HOUR_B.finditer(t):
        h = _to_float(mh.group(1))
        if h > 0:
            items.append({"key": "natural_gas", "amount": round(h * NG_M3_PER_HOUR, 3), "unit": "m3"})

    # Uçuş / km
    for v in _iter_nums(RE_FLIGHT_KM, t):
        items.append({"key": "flight", "amount": v, "unit": "km"})

    # Otobüs / km
    for v in _iter_nums(RE_BUS_KM, t):
        items.append({"key": "bus", "amount": v, "unit": "km"})

    # Tren / km
    for v in _iter_nums(RE_RAIL_KM, t):
        items.append({"key": "rail", "amount": v, "unit": "km"})

    # Kağıt / kg
    for v in _iter_nums(RE_PAPER_KG, t):
        items.append({"key": "paper", "amount": v, "unit": "kg"})

    # Atık / kg
    for v in _iter_nums(RE_WASTE_KG, t):
        items.append({"key": "waste", "amount": v, "unit": "kg"})

    return {"items": items}


class CalcTool:
    def __init__(self, base_url: str = "http://localhost:8001", timeout: int = 8):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def run(self, user_input: str, history=None) -> str:
        """
        Şema:
        - JSON içinde "items" varsa doğrudan /calc
        - Yoksa doğal dilden çıkar, /calc
        """
        payload = None
        if isinstance(user_input, str):
            try:
                payload = json.loads(user_input)
            except Exception:
                payload = None
        elif isinstance(user_input, dict):
            payload = user_input

        if payload and isinstance(payload.get("items"), list):
            items_payload = {"items": payload["items"]}
        else:
            items_payload = _parse_natural_language(user_input or "")

        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.post(f"{self.base_url}/calc", json=items_payload)
                r.raise_for_status()
                data = r.json()

            total = data.get("co2e_kg")
            items = data.get("items", [])
            unknown = data.get("unknown", [])
            parts = [
                f"{it['key']}={it['amount']}{('/'+it['unit']) if it.get('unit') else ''}→{it['co2e_kg']} kg"
                for it in items
            ]
            msg = f"Toplam ~{total} kgCO₂e. Kalemler: " + ", ".join(parts) if parts else f"Toplam ~{total} kgCO₂e."
            if unknown:
                msg += f" | Bilinmeyen: {unknown}"
            return msg

        except httpx.HTTPError as e:
            return f"[HATA] carbon_calc_svc isteği başarısız: {e}"
