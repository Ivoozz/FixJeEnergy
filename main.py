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

async def update_status_sensor(session, config, data, action):
    """Updates a virtual sensor in HA with the current status and attributes."""
    url = "http://supervisor/core/api/states/sensor.fixjeenergy_status"
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}", "Content-Type": "application/json"}
    
    # Extract cheap/expensive hours for attributes
    sorted_prices = sorted(data.market_prices[:24], key=lambda x: x['price_kwh'])
    cheap = [datetime.fromisoformat(p['time']).hour for p in sorted_prices[:3]]
    expensive = [datetime.fromisoformat(p['time']).hour for p in sorted_prices[-3:]]

    payload = {
        "state": action,
        "attributes": {
            "strategy": config.get("strategy"),
            "test_mode": config.get("test_mode"),
            "battery_soc": data.battery_soc,
            "solar_power": data.total_solar_power,
            "cheapest_hours": cheap,
            "expensive_hours": expensive,
            "last_update": datetime.now().isoformat(),
            "friendly_name": "FixJeEnergy Control Status",
            "icon": "mdi:battery-charging" if action == "CHARGE" else "mdi:battery-arrow-down" if action == "DISCHARGE" else "mdi:battery"
        }
    }
    
    try:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status in [200, 201]:
                logger.info("Feedback sensor updated in HA Dashboard.")
            else:
                logger.error(f"Failed to update feedback sensor: HTTP {resp.status}")
    except Exception as e:
        logger.error(f"Error updating status sensor: {e}")

async def set_battery_mode(session, config, action):
    """Safely executes the battery command based on test_mode."""
    entity_id = config.get("battery_control_entity")
    if not entity_id:
        logger.error("No battery_control_entity configured!")
        return

    test_mode = config.get("test_mode", True)
    
    if test_mode:
        logger.info(f"--- TEST MODE ACTIVE ---")
        logger.info(f"Would have sent [{action}] to [{entity_id}]")
        return

    # Real execution logic
    # We assume the entity is a select or a custom service based on your specific inverter.
    # Standard approach: call a service to set the mode.
    domain = entity_id.split(".")[0]
    
    # Mapping actions to standard HA service calls (adjust based on your specific integration)
    url = f"http://supervisor/core/api/services/select/select_option"
    payload = {"entity_id": entity_id, "option": action}
    
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}", "Content-Type": "application/json"}
    
    try:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status == 200:
                logger.info(f"Successfully sent {action} command to {entity_id}")
            else:
                logger.error(f"Failed to send command: HTTP {resp.status}")
    except Exception as e:
        logger.error(f"Error during battery control: {e}")

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
    """The complete brain loop with execution and feedback."""
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

        # 3. Execution
        await set_battery_mode(session, config, action)
        
        # 4. Feedback to HA Dashboard
        await update_status_sensor(session, config, data, action)

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
