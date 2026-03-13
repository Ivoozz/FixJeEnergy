import logging
from datetime import datetime, timedelta
from strategy import EnergyStrategy

logger = logging.getLogger("FixJeEnergy.Simulator")

class MockData:
    """Helper class to structure mock data for the strategy."""
    def __init__(self, soc, solar, prices, forecast):
        self.battery_soc = soc
        self.total_solar_power = solar
        self.market_prices = prices
        self.solar_forecast = forecast

def run_24h_simulation(config):
    """Generates 24 hours of mock data and tests the strategy."""
    logger.info("--- STARTING INTERNAL 24H SIMULATION ---")
    strategy_name = config.get("strategy", "0_on_the_meter")
    logger.info(f"Target Strategy: {strategy_name}")

    # 1. Generate Realistic Mock Nordpool Prices (Night low, morning peak, afternoon low, evening peak)
    mock_prices = []
    base_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    price_pattern = [0.15, 0.14, 0.12, 0.12, 0.13, 0.18, 0.25, 0.30, 0.28, 0.22, 0.18, 0.15, 
                     0.12, 0.11, 0.12, 0.16, 0.22, 0.35, 0.38, 0.32, 0.25, 0.20, 0.18, 0.16]
    
    for h in range(24):
        time = base_time + timedelta(hours=h)
        mock_prices.append({"time": time.isoformat(), "price_kwh": price_pattern[h]})

    # 2. Generate Mock Weather Forecast (Cloudy Day scenario)
    mock_forecast = []
    for h in range(48): # 2-day forecast
        mock_forecast.append({"wolk": 85}) # 85% cloud cover

    current_soc = 20.0 # Starting SOC
    
    logger.info(f"{'Hour':<6} | {'Price':<8} | {'Solar':<8} | {'SOC':<6} | {'Decision'}")
    logger.info("-" * 50)

    for h in range(24):
        # Simulate solar production (Bell curve peak at 13:00)
        solar_now = 0.0
        if 7 <= h <= 19:
            # Simple parabola for solar production
            solar_now = max(0, -50 * (h - 13)**2 + 2000)
        
        data = MockData(current_soc, solar_now, mock_prices, mock_forecast)
        
        # Determine action
        action = EnergyStrategy.decide_action(config, data)
        
        # Simulate battery state change based on action
        if action == "CHARGE":
            current_soc = min(100, current_soc + 15) # +15% per hour charging
        elif action == "DISCHARGE":
            current_soc = max(0, current_soc - 20) # -20% per hour discharging
        elif solar_now > 500:
            current_soc = min(100, current_soc + 5) # Slow solar charge
            
        price = mock_prices[h]['price_kwh']
        logger.info(f"{h:02d}:00  | €{price:.2f} | {int(solar_now):>5}W | {int(current_soc):>3}% | {action}")

    logger.info("-" * 50)
    logger.info("--- SIMULATION COMPLETED ---")
    logger.info("Review the log above to verify strategy behavior.")
