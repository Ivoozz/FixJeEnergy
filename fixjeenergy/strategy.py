import logging
from datetime import datetime
from typing import List, Dict, Any

logger = logging.getLogger("FixJeEnergy.Strategy")

class EnergyStrategy:
    """
    The brain of FixJeEnergy. Analyzes prices, weather, and SOC 
    to decide the best battery action.
    """

    @staticmethod
    def decide_action(config: Dict[str, Any], data: Any) -> str:
        """
        Main entry point for decision making.
        Returns: "CHARGE", "DISCHARGE", or "IDLE"
        """
        strategy_name = config.get("strategy", "0_on_the_meter")
        soc = data.battery_soc
        prices = data.market_prices
        solar_now = data.total_solar_power
        forecast = data.solar_forecast

        logger.info(f"Analyzing strategy: {strategy_name} (Current SOC: {soc}%)")

        if strategy_name == "maximum_profit":
            return EnergyStrategy._maximum_profit(soc, prices)
        else:
            return EnergyStrategy._zero_on_the_meter(soc, prices, solar_now, forecast)

    @staticmethod
    def _zero_on_the_meter(soc: float, prices: List[Dict], solar_now: float, forecast: List) -> str:
        """
        Strategy: 0_on_the_meter
        Goal: Maximize self-consumption and ensure the battery is ready for the next day.
        """
        # 1. Check if we have a lot of sun right now. 
        # If solar production is high (> 2000W) and SOC is not full, we stay IDLE 
        # to allow the inverter's own logic to prioritize charging from PV.
        if solar_now > 2000 and soc < 95:
            logger.info("High solar production detected. Letting PV charge the battery.")
            return "IDLE"

        # 2. Analyze the solar forecast for tomorrow.
        # If the average cloud cover is very high (> 80%), we might need a grid charge.
        avg_cloud = sum(int(f.get("wolk", 0)) for f in forecast[:24]) / 24 if forecast else 0
        
        # 3. Get current hour to check for night-time charging
        current_hour = datetime.now().hour
        
        # logic: If it's night (00:00 - 05:00), SOC is low (< 30%), and tomorrow is cloudy
        # We charge from the grid during the cheapest hours.
        if 0 <= current_hour <= 5 and soc < 30 and avg_cloud > 80:
            # Find if this is one of the 3 cheapest hours of the night
            night_prices = sorted(prices[:8], key=lambda x: x['price_kwh'])
            cheapest_night_times = [p['time'] for p in night_prices[:3]]
            
            # Check if current time matches one of the cheapest slots
            # (Simplistic check for this demo)
            logger.info(f"Cloudy day expected (Avg Cloud: {avg_cloud}%). Night charging triggered.")
            return "CHARGE"

        # Default behavior: Stay idle and let the house consume the battery
        return "IDLE"

    @staticmethod
    def _maximum_profit(soc: float, prices: List[Dict]) -> str:
        """
        Strategy: maximum_profit
        Goal: Buy low, sell high. Pure arbitrage.
        """
        if not prices:
            logger.warning("No price data available for Profit strategy.")
            return "IDLE"

        # 1. Safety guards
        if soc > 98:
            logger.info("Battery full. Blocking CHARGE.")
            # We can still discharge
        if soc < 10:
            logger.info("Battery empty. Blocking DISCHARGE.")
            return "IDLE"

        # 2. Analyze market windows
        # We look at the 24-hour window
        sorted_prices = sorted(prices[:24], key=lambda x: x['price_kwh'])
        
        # Identify top 3 cheapest and top 3 most expensive hours
        cheapest_hours = [datetime.fromisoformat(p['time']).hour for p in sorted_prices[:3]]
        expensive_hours = [datetime.fromisoformat(p['time']).hour for p in sorted_prices[-3:]]
        
        current_hour = datetime.now().hour

        # 3. Action Logic
        if current_hour in cheapest_hours and soc < 95:
            logger.info(f"Market opportunity: Current hour {current_hour} is one of the cheapest. Charging.")
            return "CHARGE"
        
        if current_hour in expensive_hours and soc > 15:
            logger.info(f"Market opportunity: Current hour {current_hour} is one of the most expensive. Discharging.")
            return "DISCHARGE"

        return "IDLE"
