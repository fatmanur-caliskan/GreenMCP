
import requests
import asyncio
import json
import re

CHAT_URL = "http://localhost:8000/chat"
ASK_URL = "http://localhost:8000/ask"  

history = []

def build_chat_payload(history, message):
    return {
        "history": history,
        "message": message,
        "user_id": "demo",
        "session_id": "demo"
    }

def build_ask_payload(input_text, tool):
    return {
        "input": input_text,
        "tool": tool,
        "history": [],
        "user_id": "demo",
        "session_id": "demo"
    }


def parse_calc_args(cmd: str):
   
    defaults = {
        "transport_km": 0.0,
        "electricity_kwh": 0.0,
        "bottles_pet": 0,
        "chicken_portion": 0,
    }
    for k in list(defaults.keys()):
        m = re.search(rf"{k}\s*=\s*([0-9]+(?:\.[0-9]+)?)", cmd)
        if m:
            val = m.group(1)
            if k in ("bottles_pet", "chicken_portion"):
                defaults[k] = int(float(val))
            else:
                defaults[k] = float(val)
    return defaults

def calc_args_to_items(args: dict):
    """
    carbon-calc-svc /calc endpoint'i için beklenen şemaya çevirir:
    {"items":[{"key":"car","amount":12,"unit":"km"}, ...]}
    """
    items = []
    if args.get("transport_km", 0) > 0:
        items.append({"key": "car", "amount": float(args["transport_km"]), "unit": "km"})
    if args.get("electricity_kwh", 0) > 0:
        items.append({"key": "electricity", "amount": float(args["electricity_kwh"]), "unit": "kwh"})
    if args.get("bottles_pet", 0) > 0:
        items.append({"key": "pet_bottle", "amount": int(args["bottles_pet"]), "unit": "piece"})
    if args.get("chicken_portion", 0) > 0:
        items.append({"key": "chicken", "amount": int(args["chicken_portion"]), "unit": "portion"})
    return {"items": items} if items else {"items": []}


def parse_weather_args(cmd: str):
    """
    /weather lat=41.0 lon=29.0 gibi.
    Değer gelmezse İstanbul approx: 41.01, 28.97
    """
    lat = re.search(r"lat\s*=\s*([\-0-9\.]+)", cmd)
    lon = re.search(r"lon\s*=\s*([\-0-9\.]+)", cmd)
    lat_v = float(lat.group(1)) if lat else 41.01
    lon_v = float(lon.group(1)) if lon else 28.97
    return lat_v, lon_v

async def chat_loop():
    print("GreenMCP Chat'e hoş geldiniz! Çıkmak için 'q' yazın.")
    print("ℹMikroservis kısayolları:")
    print("   • /calc transport_km=12 electricity_kwh=3 bottles_pet=2 chicken_portion=1")
    print("   • /weather lat=41.0 lon=39.75\n")

    while True:
        try:
            user_input = input("👤 Siz: ").strip()
            user_input = " ".join(user_input.splitlines())

            if not user_input:
                continue
            if user_input.lower() in ["q", "quit", "exit"]:
                print("🚪 Sohbet sonlandırıldı.")
                break

            if user_input.startswith("/calc"):
                args = parse_calc_args(user_input)
                payload_json = calc_args_to_items(args)  
                payload = build_ask_payload(json.dumps(payload_json), tool="calc_tool")
                r = requests.post(ASK_URL, json=payload, timeout=30)
                r.raise_for_status()
                resp = r.json().get("response", {})
                print("\n🧰 Mikroservis yanıtı (calc_tool):")
                for item in resp.get("responses", []):
                    print(f"\n📦 {item.get('agent','calc_tool')}:\n{item.get('output') or item.get('error')}")
                print()
                continue

            if user_input.startswith("/weather"):
                lat, lon = parse_weather_args(user_input)
               
                payload = build_ask_payload(f"lat={lat}; lon={lon}", tool="weather_tool")
                r = requests.post(ASK_URL, json=payload, timeout=30)
                r.raise_for_status()
                resp = r.json().get("response", {})
                print("\nMikroservis yanıtı (weather_tool):")
                for item in resp.get("responses", []):
                    print(f"\n{item.get('agent','weather_tool')}:\n{item.get('output') or item.get('error')}")
                print()
                continue

            history.append({"role": "user", "content": user_input})
            payload = build_chat_payload(history, message=user_input)
            r = requests.post(CHAT_URL, json=payload, timeout=6000)
            r.raise_for_status()

            data = r.json()
            response_data = data.get("response", {})
            response_items = response_data.get("responses", [])

            if response_items:
                print("\nGreenMCP çoklu yanıtlar:")
                for item in response_items:
                    agent = item.get("agent", "bilinmeyen")
                    output = item.get("output", item.get("error", "Yanıt alınamadı."))
                    print(f"\n{agent}:\n{output}")
                    history.append({"role": "assistant", "content": output})
                print()
            else:
                print("❌ Hiçbir yanıt alınamadı.\n")

        except Exception as e:
            print(f"[HATA] API isteği başarısız oldu:\n{e}\n")

if __name__ == "__main__":
    asyncio.run(chat_loop())
