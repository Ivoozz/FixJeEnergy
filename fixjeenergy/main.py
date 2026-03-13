import asyncio
import aiohttp
import json
import os
import logging
import sys
from datetime import datetime, timedelta
import pytz
from nordpool import elspot

# Local imports
from strategy import EnergyStrategy
from simulator import run_24h_real_data_simulation

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("FixJeEnergy")

OPTIONS_PATH = "/data/options.json"
SUPERVISOR_TOKEN = os.getenv("SUPERVISOR_TOKEN")

class EnergyData:
    def __init__(self):
        self.timestamp = datetime.now()
        self.battery_soc = 0.0
        self.total_solar_power = 0.0
        self.market_prices = []
        self.solar_forecast = []
        self.cloud_cover_forecast = 0

async def get_ha_state(session, entity_id):
    if not entity_id: return 0.0
    url = f"http://supervisor/core/api/states/{entity_id}"
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return float(data.get("state", 0.0))
    except Exception: pass
    return 0.0

async def update_status_sensor(session, config, data, action):
    url = "http://supervisor/core/api/states/sensor.fixjeenergy_status"
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}", "Content-Type": "application/json"}
    payload = {"state": action, "attributes": {"strategy": config.get("strategy"), "battery_soc": data.battery_soc, "friendly_name": "FixJeEnergy Status"}}
    try:
        async with session.post(url, headers=headers, json=payload) as resp: pass
    except Exception: pass

async def fetch_nordpool_prices():
    try:
        prices_elspot = elspot.Prices(currency='EUR')
        data = prices_elspot.hourly(areas=['NL'])
        prices = []
        for entry in data['areas']['NL']['values']:
            prices.append({"time": entry['start'].isoformat(), "price_kwh": float(entry['value']) / 1000})
        return sorted(prices, key=lambda x: x["time"])
    except Exception: return []

async def fetch_meteoserver_data(session, api_key):
    if not api_key: return {"solar": [], "cloud": 0}
    url = f"https://data.meteoserver.nl/api/uurverwachting.php?key={api_key}&locatie=Sommelsdijk"
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                forecast = data.get("data", [])
                if forecast: return {"solar": forecast, "cloud": int(forecast[0].get("wolk", 0))}
    except Exception: pass
    return {"solar": [], "cloud": 0}

async def main():
    logger.info("FixJeEnergy Add-on Initializing")
    if not os.path.exists(OPTIONS_PATH): return
    with open(OPTIONS_PATH, 'r') as f: config = json.load(f)

    # Fetch Real Data for Simulation OR Live Loop
    async with aiohttp.ClientSession() as session:
        logger.info("Fetching real market and weather data...")
        prices = await fetch_nordpool_prices()
        weather = await fetch_meteoserver_data(session, config.get("meteoserver_api"))
        
        if config.get("run_internal_simulation"):
            logger.info("SIMULATION MODE: Running 24h test with LIVE API data...")
            live_data = {"prices": prices, "forecast": weather["solar"]}
            await run_24h_real_data_simulation(config, live_data)
            logger.info("Simulation finished. Add-on exit.")
            sys.exit(0)

    # LIVE LOOP
    logger.info("Starting live loop...")
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                data = EnergyData()
                data.battery_soc = await get_ha_state(session, config.get("soc_sensor_entity"))
                data.market_prices = await fetch_nordpool_prices()
                weather_live = await fetch_meteoserver_data(session, config.get("meteoserver_api"))
                data.solar_forecast = weather_live["solar"]
                
                action = EnergyStrategy.decide_action(config, data)
                await update_status_sensor(session, config, data, action)
                # ... execute battery control ...
        except Exception as e: logger.error(f"Loop error: {e}")
        await asyncio.sleep(900)

if __name__ == "__main__":
    asyncio.run(main())
