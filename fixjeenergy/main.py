import asyncio
import aiohttp
import json
import os
import logging
import sys
from datetime import datetime, timedelta
import pytz
from nordpool import elspot
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

# Local imports
from strategy import EnergyStrategy

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("FixJeEnergy")

OPTIONS_PATH = "/data/options.json"
SUPERVISOR_TOKEN = os.getenv("SUPERVISOR_TOKEN")
VERSION = "1.4.1"

class State:
    def __init__(self):
        self.forecast_data = []
        self.last_update = None
        self.config = {}

app_state = State()
app = FastAPI()

class EnergyData:
    def __init__(self):
        self.battery_soc = 50.0
        self.market_prices = []
        self.solar_forecast = []

async def write_to_ha(session, entity_id, value):
    if not entity_id or not SUPERVISOR_TOKEN: return
    domain = entity_id.split(".")[0]
    service = "set_value" if domain == "number" else ("turn_on" if value in [True, "on", "ON"] else "turn_off")
    url = f"http://supervisor/core/api/services/{domain}/{service}"
    payload = {"entity_id": entity_id}
    if domain == "number": payload["value"] = value
    
    try:
        async with session.post(url, headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}, json=payload) as r:
            if r.status != 200: logger.error(f"HA Write Error {entity_id}: {r.status}")
    except: pass

async def run_optimization_loop():
    while True:
        logger.info(f"FixJeEnergy v{VERSION} - Start optimalisatie cyclus...")
        try:
            if os.path.exists(OPTIONS_PATH):
                with open(OPTIONS_PATH, 'r') as f: app_state.config = json.load(f)
            
            async with aiohttp.ClientSession() as session:
                # 1. Fetch Data
                data = EnergyData()
                soc_entity = app_state.config.get('soc_sensor_entity')
                if soc_entity:
                    url = f"http://supervisor/core/api/states/{soc_entity}"
                    async with session.get(url, headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}) as r:
                        if r.status == 200: data.battery_soc = float((await r.json()).get("state", 50))
                
                p = elspot.Prices(currency='EUR')
                data.market_prices = sorted([{"time": e['start'].isoformat(), "price_kwh": float(e['value'])/1000} for e in p.hourly(areas=['NL'])['areas']['NL']['values']], key=lambda x: x["time"])
                
                # 2. Strategy Calculation (Returns 24h plan)
                current_action, plan = EnergyStrategy.calculate_plan(app_state.config, data)
                app_state.forecast_data = plan
                app_state.last_update = datetime.now()

                # 3. Smart Slot Mapping (Pick 6 most important transitions)
                if not app_state.config.get("test_mode", True) and len(plan) > 0:
                    # Zoek naar momenten waarop de actie of gewenste SOC verandert
                    important_slots = []
                    last_action = None
                    
                    for hour_data in plan:
                        if hour_data["planned_action"] != last_action:
                            important_slots.append(hour_data)
                            last_action = hour_data["planned_action"]
                        if len(important_slots) >= 6: break
                    
                    # Als er minder dan 6 transities zijn, vul aan met IDLE slots voor de rest van de dag
                    while len(important_slots) < 6:
                        important_slots.append(plan[-1])

                    logger.info(f"Dynamische planning: {len(important_slots)} transities gevonden. Schrijven naar omvormer...")
                    
                    times = app_state.config.get("prog_times", [])
                    socs = app_state.config.get("prog_socs", [])
                    grids = app_state.config.get("prog_grid_charges", [])
                    
                    for i in range(min(6, len(times), len(socs), len(grids))):
                        slot = important_slots[i]
                        time_str = datetime.fromisoformat(slot["datetime"].replace("Z", "+00:00")).strftime("%H:%M")
                        
                        logger.info(f"Programma {i+1}: {time_str} -> {slot['planned_action']} (Target SOC: {slot['expected_soc']}%)")
                        
                        await write_to_ha(session, times[i], time_str)
                        await write_to_ha(session, socs[i], slot["expected_soc"])
                        await write_to_ha(session, grids[i], "on" if slot["planned_action"] == "CHARGE" else "off")

        except Exception as e: logger.error(f"Loop error: {e}")
        await asyncio.sleep(900)

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("index.html", "r") as f: return f.read()

@app.get("/api/forecast")
async def get_forecast(): return JSONResponse(content=app_state.forecast_data)

async def main():
    logger.info(f"FixJeEnergy v{VERSION} Starting")
    asyncio.create_task(run_optimization_loop())
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
