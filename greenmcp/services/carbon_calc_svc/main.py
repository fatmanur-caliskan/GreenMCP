
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional, Dict

app = FastAPI(title="carbon-calc-svc")

@app.get("/health")
def health():
    return {"status": "ok", "service": "carbon-calc-svc"}

COEFFS: Dict[str, Dict[str, float]] = {
    "car": {"km": 0.192},                
    "electricity": {"kwh": 0.42},        
    "pet_bottle": {"piece": 0.082},      
    "chicken": {"portion": 1.6, "kg": 8.0},
    "beef": {"kg": 27.0},
    "milk": {"l": 1.0},
    "natural_gas": {"m3": 2.0},
    "flight": {"km": 0.15},
    "bus": {"km": 0.05},
    "rail": {"km": 0.03},
    "paper": {"kg": 1.2},
    "waste": {"kg": 0.2},
    # ihtiyaca göre genişlet
}

class Item(BaseModel):
    key: str           
    amount: float     
    unit: Optional[str] = None  

class CalcRequest(BaseModel):
    items: List[Item]

@app.post("/calc")
def calc(req: CalcRequest):
    total = 0.0
    breakdown = []
    unknown = []

    for it in req.items:
        key = (it.key or "").strip().lower()
        unit = (it.unit or "").strip().lower() if it.unit else ""
        amt = float(it.amount or 0.0)

        kgco2e = None
        if key in COEFFS:
            coeff_map = COEFFS[key]
            if unit in coeff_map:
                kgco2e = amt * coeff_map[unit]
            elif len(coeff_map) == 1:
                # tek birim tanımlıysa ve kullanıcı birim vermediyse onu varsay
                only_unit = next(iter(coeff_map))
                kgco2e = amt * coeff_map[only_unit]
            else:
                unknown.append({"item": it.dict(), "reason": "unit_mismatch"})
        else:
            unknown.append({"item": it.dict(), "reason": "unknown_key"})

        if kgco2e is not None:
            kgco2e = round(kgco2e, 3)
            total += kgco2e
            breakdown.append({
                "key": key, "amount": amt, "unit": (unit or None), "co2e_kg": kgco2e
            })

    return {
        "co2e_kg": round(total, 3),
        "items": breakdown,
        "unknown": unknown,
        "note": "Katsayılar yaklaşık/basitleştirilmiştir; COEFFS genişletilebilir."
    }
