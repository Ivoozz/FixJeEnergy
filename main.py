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
from simulator import run_24h_simulation

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
    """Fetch current state of an entity from HA Supervisor API."""
    if not entity_id:
        return 0.0
    url = f"http://supervisor/core/api/states/{entity_id}"
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                state = data.get("state")
                try:
                    return float(state)
                except (ValueError, TypeError):
                    return 0.0
            else:
                return 0.0
    except Exception:
        return 0.0

async def update_status_sensor(session, config, data, action):
    """Updates a virtual sensor in HA with the current status."""
    url = "http://supervisor/core/api/states/sensor.fixjeenergy_status"
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}", "Content-Type": "application/json"}
    
    payload = {
        "state": action,
        "attributes": {
            "strategy": config.get("strategy"),
            "test_mode": config.get("test_mode"),
            "battery_soc": data.battery_soc,
            "solar_power": data.total_solar_power,
            "last_update": datetime.now().isoformat(),
            "friendly_name": "FixJeEnergy Control Status"
        }
    }
    try:
        async with session.post(url, headers=headers, json=payload) as resp:
            pass
    except Exception:
        pass

async def set_battery_mode(session, config, action):
    """Executes the battery command."""
    entity_id = config.get("battery_control_entity")
    if not entity_id or config.get("test_mode", True):
        logger.info(f"[TEST/NO-ID] Skipping real command: {action}")
        return

    url = f"http://supervisor/core/api/services/select/select_option"
    payload = {"entity_id": entity_id, "option": action}
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}", "Content-Type": "application/json"}
    
    try:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status == 200:
                logger.info(f"Successfully sent {action} to {entity_id}")
    except Exception as e:
        logger.error(f"Error during battery control: {e}")

async def fetch_nordpool_prices():
    """Fetch prices from Nordpool."""
    try:
        prices_elspot = elspot.Prices(currency='EUR')
        data = prices_elspot.hourly(areas=['NL'])
        prices = []
        for entry in data['areas']['NL']['values']:
            prices.append({"time": entry['start'].isoformat(), "price_kwh": float(entry['value']) / 1000})
        return sorted(prices, key=lambda x: x["time"])
    except Exception:
        return []

async def fetch_meteoserver_data(session, api_key):
    """Fetch weather data."""
    if not api_key: return {"solar": [], "cloud": 0}
    url = f"https://data.meteoserver.nl/api/uurverwachting.php?key={api_key}&locatie=Sommelsdijk"
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                forecast = data.get("data", [])
                if forecast:
                    return {"solar": forecast, "cloud": int(forecast[0].get("wolk", 0))}
    except Exception: pass
    return {"solar": [], "cloud": 0}

async def run_optimization_cycle():
    """Main logic loop."""
    if not os.path.exists(OPTIONS_PATH): return
    with open(OPTIONS_PATH, 'r') as f:
        config = json.load(f)

    data = EnergyData()
    async with aiohttp.ClientSession() as session:
        data.battery_soc = await get_ha_state(session, config.get("soc_sensor_entity"))
        total_solar = 0.0
        for entity in config.get("solar_power_entities", []):
            total_solar += await get_ha_state(session, entity)
        data.total_solar_power = total_solar
        data.market_prices = await fetch_nordpool_prices()
        weather = await fetch_meteoserver_data(session, config.get("meteoserver_api"))
        data.solar_forecast = weather["solar"]
        data.cloud_cover_forecast = weather["cloud"]

        action = EnergyStrategy.decide_action(config, data)
        await set_battery_mode(session, config, action)
        await update_status_sensor(session, config, data, action)

async def main():
    logger.info("FixJeEnergy Add-on Initializing")
    
    if not os.path.exists(OPTIONS_PATH):
        logger.error("Options file missing!")
        return

    with open(OPTIONS_PATH, 'r') as f:
        config = json.load(f)

    # CHECK FOR SIMULATION MODE
    if config.get("run_internal_simulation"):
        logger.info("SIMULATION MODE ENABLED. Starting 24h test run...")
        run_24h_simulation(config)
        logger.info("Simulation finished. Add-on will now exit.")
        sys.exit(0)

    # NORMAL LIVE LOOP
    logger.info("Starting normal live loop (15 min interval).")
    while True:
        try:
            await run_optimization_cycle()
        except Exception as e:
            logger.error(f"Error: {e}")
        await asyncio.sleep(900)

if __name__ == "__main__":
    asyncio.run(main())
