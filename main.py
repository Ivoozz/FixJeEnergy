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
                    logger.warning(f"Entity {entity_id} has non-numeric state: {state}")
                    return 0.0
            else:
                logger.error(f"Failed to fetch {entity_id}: HTTP {resp.status}")
                return 0.0
    except Exception as e:
        logger.error(f"Error fetching {entity_id}: {e}")
        return 0.0

async def set_ha_state(session, entity_id, action):
    """Placeholder for sending the control command back to HA."""
    # This will be expanded in the next step
    logger.info(f"SETTING {entity_id} to {action}")

async def fetch_nordpool_prices():
    """Fetch electricity prices for NL from Nordpool."""
    try:
        prices_elspot = elspot.Prices(currency='EUR')
        data = prices_elspot.hourly(areas=['NL'])
        prices = []
        for entry in data['areas']['NL']['values']:
            prices.append({
                "time": entry['start'].isoformat(),
                "price_kwh": float(entry['value']) / 1000
            })
        return sorted(prices, key=lambda x: x["time"])
    except Exception as e:
        logger.error(f"Nordpool API Error: {e}")
        return []

async def fetch_meteoserver_data(session, api_key):
    """Fetch weather/solar forecast from Meteoserver.nl."""
    if not api_key:
        return {"solar": [], "cloud": 0}
    
    url = f"https://data.meteoserver.nl/api/uurverwachting.php?key={api_key}&locatie=Sommelsdijk"
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                forecast = data.get("data", [])
                if forecast:
                    current = forecast[0]
                    return {"solar": forecast, "cloud": int(current.get("wolk", 0))}
    except Exception as e:
        logger.error(f"Meteoserver Connection Error: {e}")
    return {"solar": [], "cloud": 0}

async def run_optimization_cycle():
    """The main brain loop."""
    logger.info("--- Starting Optimization Cycle ---")
    
    if not os.path.exists(OPTIONS_PATH):
        logger.error("Options file not found!")
        return

    with open(OPTIONS_PATH, 'r') as f:
        config = json.load(f)

    data = EnergyData()
    
    async with aiohttp.ClientSession() as session:
        # 1. Data Acquisition
        data.battery_soc = await get_ha_state(session, config.get("soc_sensor_entity"))
        
        total_solar = 0.0
        for entity in config.get("solar_power_entities", []):
            total_solar += await get_ha_state(session, entity)
        data.total_solar_power = total_solar
        
        data.market_prices = await fetch_nordpool_prices()
        weather = await fetch_meteoserver_data(session, config.get("meteoserver_api"))
        data.solar_forecast = weather["solar"]
        data.cloud_cover_forecast = weather["cloud"]

        # 2. Decision Making
        action = EnergyStrategy.decide_action(config, data)
        logger.info(f"STRATEGY DECISION: {action}")

        # 3. Execution (if not in test mode)
        if config.get("test_mode"):
            logger.info(f"[TEST MODE] Would have sent {action} to {config.get('battery_control_entity')}")
        else:
            await set_ha_state(session, config.get("battery_control_entity"), action)

    logger.info("--- Cycle Completed ---")

async def main():
    logger.info("FixJeEnergy Add-on Starting Main Loop")
    while True:
        try:
            await run_optimization_cycle()
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
        
        await asyncio.sleep(900)

if __name__ == "__main__":
    asyncio.run(main())
