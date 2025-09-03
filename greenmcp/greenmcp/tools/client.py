import httpx

async def call_tool(url: str, payload: dict | None = None, method: str = "POST", timeout: int = 10):
    async with httpx.AsyncClient(timeout=timeout) as c:
        if method.upper() == "GET":
            r = await c.get(url, params=payload or {})
        else:
            r = await c.post(url, json=payload or {})
        r.raise_for_status()
        return r.json()
