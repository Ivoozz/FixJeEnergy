import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("FixJeEnergy.Strategy")

class EnergyStrategy:
    @staticmethod
    def calculate_plan(config: Dict[str, Any], data: Any) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Calculates the immediate action AND a 24-hour forecast plan.
        Returns: (current_action, forecast_list)
        """
        strategy_name = config.get("strategy", "0_on_the_meter")
        prices = data.market_prices
        forecast = data.solar_forecast
        current_soc = data.battery_soc
        
        plan = []
        simulated_soc = current_soc
        
        # Determine windows for Profit strategy
        sorted_prices = sorted(prices[:24], key=lambda x: x['price_kwh'])
        cheap_hours = [datetime.fromisoformat(p['time'].replace("Z", "+00:00")).hour for p in sorted_prices[:3]]
        expensive_hours = [datetime.fromisoformat(p['time'].replace("Z", "+00:00")).hour for p in sorted_prices[-3:]]

        # Loop through the next 24 hours to build the plan
        for i in range(min(24, len(prices))):
            price_point = prices[i]
            ts = price_point['time']
            price = price_point['price_kwh']
            hour = datetime.fromisoformat(ts.replace("Z", "+00:00")).hour
            
            # Solar estimation for this hour (simplified from cloud cover)
            cloud_cover = 50
            if i < len(forecast):
                cloud_cover = int(forecast[i].get("wolk", 50))
            
            # Simulated solar: max 4000W at 13:00, adjusted by clouds
            est_solar = 0.0
            if 7 <= hour <= 19:
                base = max(0, -100 * (hour - 13)**2 + 4000)
                est_solar = base * ((100 - cloud_cover) / 100)

            # Determine action for this specific hour in the future
            action = "IDLE"
            if strategy_name == "maximum_profit":
                if hour in cheap_hours and simulated_soc < 95:
                    action = "CHARGE"
                elif hour in expensive_hours and simulated_soc > 15:
                    action = "DISCHARGE"
            else: # 0_on_the_meter
                # Very simple: charge if cheap and cloudy tomorrow
                avg_cloud = sum(int(f.get("wolk", 0)) for f in forecast[:24]) / 24 if forecast else 0
                if 0 <= hour <= 5 and simulated_soc < 30 and avg_cloud > 80:
                    action = "CHARGE"

            # Update simulated SOC for the NEXT hour in the plan
            if action == "CHARGE": simulated_soc = min(100, simulated_soc + 20)
            elif action == "DISCHARGE": simulated_soc = max(0, simulated_soc - 25)
            elif est_solar > 1000: simulated_soc = min(100, simulated_soc + 10)

            plan.append({
                "datetime": ts,
                "price": round(price, 3),
                "solar_forecast": round(est_solar, 0),
                "planned_action": action,
                "expected_soc": int(simulated_soc)
            })

        current_action = plan[0]["planned_action"] if plan else "IDLE"
        return current_action, plan
