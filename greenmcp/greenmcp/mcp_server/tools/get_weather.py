import httpx
import re
import unicodedata
from typing import Optional, Tuple

class WeatherTool:
   
    def __init__(self, base_url: str = "http://localhost:8002", timeout: int = 8):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    _LAT_RE = re.compile(r"\blat(?:itude)?\s*[:=]\s*([\-0-9\.]+)", re.IGNORECASE)
    _LON_RE = re.compile(r"\blo(?:n|ng|ngitude)?\s*[:=]\s*([\-0-9\.]+)", re.IGNORECASE)

    _TR_MAP = str.maketrans({
        "ç": "c", "ğ": "g", "ı": "i", "i": "i", "ö": "o", "ş": "s", "ü": "u",
        "Ç": "C", "Ğ": "G", "İ": "I", "I": "I", "Ö": "O", "Ş": "S", "Ü": "U",
    })

    _STOP_WORDS = {
        "hava", "durumu", "nedir", "bugün", "şimdi", "yağış", "olasılığı", "var", "mı",
        "nasıl", "kaç", "derece", "icin", "için", "yakın", "nerede",
        "hava?", "durumu?", "nedir?", "yağış?", "var?", "mi", "mı", "mu", "mü",
        "tr", "türkiye",
    }

    # ——— Yardımcılar ———
    def _extract_latlon(self, text: str) -> Optional[Tuple[float, float]]:
        t = (text or "")
        mlat = self._LAT_RE.search(t)
        mlon = self._LON_RE.search(t)
        if mlat and mlon:
            try:
                return float(mlat.group(1)), float(mlon.group(1))
            except ValueError:
                return None
        return None

    def _normalize(self, s: str) -> str:
        s = (s or "").strip()
        s = unicodedata.normalize("NFKC", s)
        s = s.translate(self._TR_MAP)
        s = re.sub(r"[’'`´]", " ", s)
        s = re.sub(r"[^A-Za-z0-9\s\.-]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _candidate_queries(self, text: str) -> list:
        candidates = []
        orig = (text or "").strip()
        if orig:
            candidates.append(orig)

        norm = self._normalize(orig)
        if norm and norm not in candidates:
            candidates.append(norm)

        tokens = [w for w in norm.split() if len(w) > 2 and w.lower() not in self._STOP_WORDS]
        base_tokens = []
        for w in tokens:
            base = re.sub(r"(?:da|de|ta|te)$", "", w, flags=re.IGNORECASE).strip(".- ")
            if base:
                base_tokens.append(base)

        for w in sorted(set(base_tokens or tokens), key=len, reverse=True)[:2]:
            if w and w not in candidates:
                candidates.append(w)

        for q in list(candidates):
            if q and q.lower() not in ("turkey", "türkiye"):
                ext = f"{q}, turkey"
                if ext not in candidates:
                    candidates.append(ext)

        return candidates

    # ——— Upstream çağrıları ———
    def _call_geocode(self, q: str) -> Optional[dict]:
        url = f"{self.base_url}/geocode"
        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.get(url, params={"q": q, "count": 1})
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                data = r.json() or {}
        except httpx.HTTPError:
            return None

        name = data.get("name")
        country = data.get("country")
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is None or lon is None:
            return None
        try:
            return {"name": name, "country": country, "lat": float(lat), "lon": float(lon)}
        except (TypeError, ValueError):
            return None

    def _call_weather(self, lat: float, lon: float) -> Optional[dict]:
        url = f"{self.base_url}/weather"
        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.get(url, params={"lat": lat, "lon": lon})
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return None

    # ——— Ana akış ———
    def run(self, user_input: str, history=None) -> str:
        text = user_input or ""

        pair = self._extract_latlon(text)
        resolved_name = None
        resolved_country = None

        if pair:
            lat, lon = pair
        else:
            lat = lon = None
            for q in self._candidate_queries(text):
                hit = self._call_geocode(q)
                if hit:
                    resolved_name = hit.get("name")
                    resolved_country = hit.get("country")
                    lat, lon = hit["lat"], hit["lon"]
                    break
            if lat is None or lon is None:
                return ("Konumu çözemiyorum. Kısa bir yer adı yazmayı deneyin (örn. 'Muğla') "
                        "ya da koordinat verin: `lat=37.2 lon=28.36`.")

        data = self._call_weather(lat, lon)
        if not data:
            return "[HATA] Hava verisi alınamadı (upstream)."

        cw = (data or {}).get("current_weather") or {}
        hourly = (data or {}).get("hourly", {})

        temps = hourly.get("temperature_2m", []) or []
        probs = hourly.get("precipitation_probability", []) or []
        rhum = hourly.get("relative_humidity_2m", []) or []
        times = hourly.get("time", []) or []

        # Varsayılanlar
        now_temp = None
        now_time = None
        now_prec = None
        now_rh = None
        now_wind = None

        if "temperature" in cw and "time" in cw:
            now_temp = cw["temperature"]
            now_time = str(cw["time"]).replace("T", " ")
            now_wind = cw.get("windspeed")  # km/h
            
            try:
                idx = times.index(cw["time"]) if times else -1
                if idx >= 0:
                    if idx < len(probs):
                        now_prec = probs[idx]
                    if idx < len(rhum):
                        now_rh = rhum[idx]
            except ValueError:
                pass

       
        if now_temp is None or now_time is None:
            if not temps or not times:
                return "Hava verisi eksik görünüyor."
            now_temp = temps[0]
            now_time = str(times[0]).replace("T", " ")
            now_prec = probs[0] if probs else None
            now_rh = rhum[0] if rhum else None

        loc_prefix = ""
        if resolved_name:
            loc_prefix = f"{resolved_name}" + (f", {resolved_country}" if resolved_country else "")
            loc_prefix += " için "

        parts = [f"{loc_prefix}{now_time} itibarıyla sıcaklık ~{now_temp}°C"]

        if now_prec is not None:
            parts.append(f"yağış olasılığı ~%{now_prec}")
        if now_rh is not None:
            parts.append(f"nem ~%{now_rh}")
        if now_wind is not None:
            parts.append(f"rüzgâr ~{now_wind} km/sa")

        out = ", ".join(parts) + f". (lat={lat}, lon={lon})"
        return out
