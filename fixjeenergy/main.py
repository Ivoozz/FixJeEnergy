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
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("FixJeEnergy")

OPTIONS_PATH = "/data/options.json"
SUPERVISOR_TOKEN = os.getenv("SUPERVISOR_TOKEN")

class EnergyData:
    def __init__(self):
        self.battery_soc = 0.0
        self.total_solar_power = 0.0
        self.market_prices = []
        self.solar_forecast = []

async def update_ha_sensor(session, sensor_id, state, attributes):
    """Universal function to update HA sensor states/attributes."""
    url = f"http://supervisor/core/api/states/{sensor_id}"
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}", "Content-Type": "application/json"}
    payload = {"state": state, "attributes": attributes}
    try:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status not in [200, 201]:
                logger.error(f"Error updating {sensor_id}: {resp.status}")
    except Exception as e:
        logger.error(f"Failed to push sensor {sensor_id}: {e}")

async def fetch_data(session, config):
    data = EnergyData()
    # Fetch SOC
    url = f"http://supervisor/core/api/states/{config.get('soc_sensor_entity')}"
    async with session.get(url, headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}) as r:
        if r.status == 200:
            js = await r.json()
            data.battery_soc = float(js.get("state", 0))
    
    # Nordpool
    prices_elspot = elspot.Prices(currency='EUR')
    raw = prices_elspot.hourly(areas=['NL'])
    data.market_prices = sorted([{"time": e['start'].isoformat(), "price_kwh": float(e['value'])/1000} for e in raw['areas']['NL']['values']], key=lambda x: x["time"])
    
    # Meteoserver
    api_key = config.get("meteoserver_api")
    if api_key:
        url = f"https://data.meteoserver.nl/api/uurverwachting.php?key={api_key}&locatie=Sommelsdijk"
        async with session.get(url) as r:
            if r.status == 200:
                js = await r.json()
                data.solar_forecast = js.get("data", [])
    
    return data

async def run_cycle():
    logger.info("Cycle start...")
    with open(OPTIONS_PATH, 'r') as f: config = json.load(f)
    
    async with aiohttp.ClientSession() as session:
        data = await fetch_data(session, config)
        
        # Calculate Plan
        current_action, plan = EnergyStrategy.calculate_plan(config, data)
        
        # 1. Update Status Sensor
        await update_ha_sensor(session, "sensor.fixjeenergy_status", current_action, {
            "strategy": config.get("strategy"),
            "battery_soc": data.battery_soc,
            "friendly_name": "FixJeEnergy Action"
        })
        
        # 2. Update Forecast Sensor
        await update_ha_sensor(session, "sensor.fixjeenergy_forecast", "Active", {
            "forecast": plan,
            "friendly_name": "FixJeEnergy 24h Plan",
            "unit_of_measurement": "Plan",
            "icon": "mdi:chart-timeline-variant"
        })
        
        logger.info(f"Action: {current_action}. Forecast updated with {len(plan)} points.")

async def main():
    logger.info("FixJeEnergy Started")
    while True:
        try: await run_cycle()
        except Exception as e: logger.error(f"Loop error: {e}")
        await asyncio.sleep(900)

if __name__ == "__main__":
    asyncio.run(main())
