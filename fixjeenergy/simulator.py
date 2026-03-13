import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from strategy import EnergyStrategy

logger = logging.getLogger("FixJeEnergy.Simulator")

class MockData:
    """Structure to feed real data points into the strategy engine during simulation."""
    def __init__(self, soc, solar, prices, forecast):
        self.battery_soc = soc
        self.total_solar_power = solar
        self.market_prices = prices
        self.solar_forecast = forecast

async def run_24h_real_data_simulation(config, live_data_provider):
    """
    Fetches real API data and simulates battery behavior for the next 24 hours.
    live_data_provider is a dictionary containing fetched prices and forecast.
    """
    logger.info("--- STARTING 24H REAL-DATA SIMULATION ---")
    strategy_name = config.get("strategy", "0_on_the_meter")
    
    real_prices = live_data_provider.get("prices", [])
    real_forecast = live_data_provider.get("forecast", [])

    if not real_prices:
        logger.error("No real price data available for simulation!")
        return

    current_soc = 20.0 # Starting SOC for simulation
    
    logger.info(f"{'Hour':<6} | {'Price/kWh':<10} | {'Cloud %':<8} | {'Sim SOC':<6} | {'Decision'}")
    logger.info("-" * 60)

    # We simulate for the number of prices we have (usually 24-48)
    for i, price_point in enumerate(real_prices[:24]):
        # Extract data for this specific 'future' hour
        price = price_point['price_kwh']
        timestamp = datetime.fromisoformat(price_point['time'].replace("Z", "+00:00"))
        hour = timestamp.hour
        
        # Get cloud cover for this hour from the real forecast
        cloud_cover = 50 # Default if forecast is shorter than prices
        if i < len(real_forecast):
            cloud_cover = int(real_forecast[i].get("wolk", 50))

        # Simulate solar production based on real cloud cover (simplified model)
        # Max 4000W at clear sky (0% cloud) at 13:00
        solar_potential = 0.0
        if 7 <= hour <= 19:
            base_solar = max(0, -100 * (hour - 13)**2 + 4000)
            solar_now = base_solar * ((100 - cloud_cover) / 100)
        else:
            solar_now = 0.0
        
        # Create data object for this simulation step
        data = MockData(current_soc, solar_now, real_prices, real_forecast)
        
        # Strategy decision
        action = EnergyStrategy.decide_action(config, data)
        
        # Simulate SOC impact
        if action == "CHARGE":
            current_soc = min(100, current_soc + 20) # Assume 20% charge per hour
        elif action == "DISCHARGE":
            current_soc = max(0, current_soc - 25) # Assume 25% discharge per hour
        elif solar_now > 1000:
            current_soc = min(100, current_soc + 10) # Solar charging
            
        logger.info(f"{hour:02d}:00  | €{price:.3f}   | {cloud_cover:>7}% | {int(current_soc):>5}% | {action}")

    logger.info("-" * 60)
    logger.info("--- REAL-DATA SIMULATION COMPLETED ---")
