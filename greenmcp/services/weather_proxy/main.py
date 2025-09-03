

from fastapi import FastAPI, Query, HTTPException
import httpx

app = FastAPI(title="weather-proxy")

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"


@app.get("/health")
def health():
    return {"status": "ok", "service": "weather-proxy"}


@app.get("/geocode")
async def geocode(q: str = Query(..., min_length=2), count: int = 1):
    params = {
        "name": q,
        "count": max(1, min(count, 5)),
        "language": "tr",
        "format": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(OPEN_METEO_GEOCODE, params=params)
            r.raise_for_status()
            data = r.json() or {}
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"geocode upstream error: {e}")

    results = (data or {}).get("results") or []
    if not results:
        raise HTTPException(status_code=404, detail="Eşleşen konum bulunamadı.")

    best = results[0]
    return {
        "name": best.get("name"),
        "country": best.get("country"),
        "lat": best.get("latitude"),
        "lon": best.get("longitude"),
    }


@app.get("/weather")
async def weather(lat: float = Query(...), lon: float = Query(...)):
    """
    Saatlik veriler + anlık (current_weather) döndürür.
    Nem için relative_humidity_2m eklenmiştir.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,precipitation_probability,relative_humidity_2m",
        "current_weather": True,
        "timezone": "auto",
    }
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(OPEN_METEO, params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"weather upstream error: {e}")
