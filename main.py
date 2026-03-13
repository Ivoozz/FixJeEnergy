import asyncio
import aiohttp
import json
import os
import logging
import sys
from datetime import datetime, timedelta
import pytz
from nordpool import elspot

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

    def to_dict(self):
        return {
            "timestamp": self.timestamp.isoformat(),
            "battery_soc": self.battery_soc,
            "total_solar_power": self.total_solar_power,
            "market_prices_count": len(self.market_prices),
            "cloud_cover": self.cloud_cover_forecast
        }

async def get_ha_state(session, entity_id):
    """Fetch current state of an entity from HA Supervisor API."""
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

async def fetch_nordpool_prices():
    """Fetch electricity prices for NL from Nordpool."""
    try:
        prices_elspot = elspot.Prices(currency='EUR')
        data = prices_elspot.hourly(areas=['NL'])
        prices = []
        for entry in data['areas']['NL']['values']:
            prices.append({
                "time": entry['start'].isoformat(),
                "price_kwh": float(entry['value']) / 1000  # Convert MWh to kWh
            })
        return sorted(prices, key=lambda x: x["time"])
    except Exception as e:
        logger.error(f"Nordpool API Error: {e}")
        return []

async def fetch_meteoserver_data(session, api_key):
    """Fetch weather/solar forecast for Sommelsdijk from Meteoserver.nl."""
    if not api_key:
        return {"solar": [], "cloud": 0}
    
    # Sommelsdijk coords/location check usually via 'Sommelsdijk' name
    url = f"https://data.meteoserver.nl/api/uurverwachting.php?key={api_key}&locatie=Sommelsdijk"
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                forecast = data.get("data", [])
                if forecast:
                    current = forecast[0]
                    return {
                        "solar": forecast,
                        "cloud": int(current.get("wolk", 0))
                    }
            else:
                logger.error(f"Meteoserver API Error: {resp.status}")
    except Exception as e:
        logger.error(f"Meteoserver Connection Error: {e}")
    return {"solar": [], "cloud": 0}

async def run_optimization_cycle():
    """The main data gathering loop."""
    logger.info("--- Starting Optimization Cycle ---")
    
    if not os.path.exists(OPTIONS_PATH):
        logger.error("Options file not found!")
        return

    with open(OPTIONS_PATH, 'r') as f:
        config = json.load(f)

    data = EnergyData()
    
    async with aiohttp.ClientSession() as session:
        # 1. Gather HA Sensor Data
        logger.info("Fetching HA sensor states...")
        data.battery_soc = await get_ha_state(session, config.get("soc_sensor_entity"))
        
        solar_entities = config.get("solar_power_entities", [])
        total_solar = 0.0
        for entity in solar_entities:
            val = await get_ha_state(session, entity)
            total_solar += val
        data.total_solar_power = total_solar
        
        # 2. Gather Nordpool Prices
        logger.info("Fetching Nordpool prices...")
        data.market_prices = await fetch_nordpool_prices()
        
        # 3. Gather Meteoserver Data
        logger.info("Fetching Meteoserver forecast...")
        weather = await fetch_meteoserver_data(session, config.get("meteoserver_api"))
        data.solar_forecast = weather["solar"]
        data.cloud_cover_forecast = weather["cloud"]

    # Log Summary
    logger.info(f"Summary: SOC={data.battery_soc}%, SolarNow={data.total_solar_power}W, Cloud={data.cloud_cover_forecast}%")
    logger.info(f"Market prices count: {len(data.market_prices)}")
    
    if config.get("test_mode"):
        logger.info("[TEST MODE] Data gathered successfully. No control actions taken.")
    
    logger.info("--- Cycle Completed ---")

async def main():
    logger.info("FixJeEnergy Add-on Started")
    while True:
        try:
            await run_optimization_cycle()
        except Exception as e:
            logger.error(f"Critical error in main loop: {e}")
        
        logger.info("Sleeping for 15 minutes...")
        await asyncio.sleep(900)

if __name__ == "__main__":
    asyncio.run(main())
