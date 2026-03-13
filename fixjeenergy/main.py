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
from fastapi.staticfiles import StaticFiles
import uvicorn

# Local imports
from strategy import EnergyStrategy

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("FixJeEnergy")

OPTIONS_PATH = "/data/options.json"
SUPERVISOR_TOKEN = os.getenv("SUPERVISOR_TOKEN")

# Application State
class State:
    def __init__(self):
        self.forecast_data = []
        self.last_update = None
        self.config = {}

app_state = State()
app = FastAPI()

class EnergyData:
    def __init__(self):
        self.battery_soc = 0.0
        self.total_solar_power = 0.0
        self.market_prices = []
        self.solar_forecast = []

async def fetch_ha_data(session, config):
    data = EnergyData()
    # Fetch SOC
    try:
        url = f"http://supervisor/core/api/states/{config.get('soc_sensor_entity')}"
        async with session.get(url, headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}) as r:
            if r.status == 200:
                js = await r.json()
                data.battery_soc = float(js.get("state", 0))
    except Exception as e:
        logger.error(f"Error fetching SOC: {e}")
    
    # Nordpool
    try:
        prices_elspot = elspot.Prices(currency='EUR')
        raw = prices_elspot.hourly(areas=['NL'])
        data.market_prices = sorted([{"time": e['start'].isoformat(), "price_kwh": float(e['value'])/1000} for e in raw['areas']['NL']['values']], key=lambda x: x["time"])
    except Exception as e:
        logger.error(f"Error fetching Nordpool: {e}")
    
    # Meteoserver
    api_key = config.get("meteoserver_api")
    if api_key:
        try:
            url = f"https://data.meteoserver.nl/api/uurverwachting.php?key={api_key}&locatie=Sommelsdijk"
            async with session.get(url) as r:
                if r.status == 200:
                    js = await r.json()
                    data.solar_forecast = js.get("data", [])
        except Exception as e:
            logger.error(f"Error fetching Meteoserver: {e}")
    
    return data

async def run_optimization_loop():
    """Background task for the 15-minute control cycle."""
    while True:
        logger.info("Starting optimization cycle...")
        try:
            if os.path.exists(OPTIONS_PATH):
                with open(OPTIONS_PATH, 'r') as f:
                    app_state.config = json.load(f)
            
            async with aiohttp.ClientSession() as session:
                data = await fetch_ha_data(session, app_state.config)
                current_action, plan = EnergyStrategy.calculate_plan(app_state.config, data)
                
                # Update global state for web UI
                app_state.forecast_data = plan
                app_state.last_update = datetime.now()
                
                logger.info(f"Cycle completed. Action: {current_action}")
        except Exception as e:
            logger.error(f"Error in optimization loop: {e}")
        
        await asyncio.sleep(900)

# --- Web API Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open("index.html", "r") as f:
        return f.read()

@app.get("/api/forecast")
async def get_forecast():
    return JSONResponse(content=app_state.forecast_data)

@app.get("/api/status")
async def get_status():
    return {
        "last_update": app_state.last_update.isoformat() if app_state.last_update else None,
        "strategy": app_state.config.get("strategy")
    }

async def main():
    # Start the optimization loop in the background
    asyncio.create_task(run_optimization_loop())
    
    # Start the web server
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
