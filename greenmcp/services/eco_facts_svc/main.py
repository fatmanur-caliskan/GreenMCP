
from fastapi import FastAPI
from pydantic import BaseModel
import random

app = FastAPI(title="eco-facts-svc")

class FactQuery(BaseModel):
    intent: str
    topic: str | None = None
    level: str | None = None
    lang: str | None = "tr"

FACTS = [
    {"id":"fact_0001","text":"1 ağaç yılda yaklaşık 20 kg CO₂ emer.","topic":"biodiversity","level":"general","lang":"tr","tags":["trees","co2"]},
    {"id":"fact_0002","text":"LED ampuller akkor ampullere göre ~%75 daha az enerji tüketir.","topic":"energy","level":"general","lang":"tr","tags":["lighting","efficiency"]},
    {"id":"fact_0003","text":"Gıda israfı küresel sera gazı emisyonlarına önemli ölçüde katkı yapar.","topic":"waste","level":"general","lang":"tr","tags":["food","waste"]},
]

@app.get("/health")
def health():
    return {"status":"ok","service":"eco-facts-svc"}

@app.post("/query")
def query_fact(q: FactQuery):
    pool = [f for f in FACTS if (q.topic in (None, "any") or f["topic"] == q.topic)]
    if not pool:
        pool = FACTS
    f = random.choice(pool)
    return {
        "id": f["id"], "type":"eco_fact", "text": f["text"],
        "topic": f["topic"], "level": q.level or f["level"], "lang": q.lang or f["lang"],
        "tags": f["tags"]
    }
