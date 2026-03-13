import logging
import math
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("FixJeEnergy.Strategy")

class EnergyStrategy:
    @staticmethod
    def calculate_plan(config: Dict[str, Any], data: Any) -> Tuple[str, List[Dict[str, Any]]]:
        strategy_name = config.get("strategy", "0_on_the_meter")
        prices = data.market_prices
        forecast = data.solar_forecast
        current_soc = data.battery_soc
        solar_arrays = config.get("solar_arrays", [])
        
        plan = []
        simulated_soc = current_soc
        
        sorted_prices = sorted(prices[:24], key=lambda x: x['price_kwh'])
        cheap_hours = [datetime.fromisoformat(p['time'].replace("Z", "+00:00")).hour for p in sorted_prices[:3]]
        expensive_hours = [datetime.fromisoformat(p['time'].replace("Z", "+00:00")).hour for p in sorted_prices[-3:]]

        for i in range(min(24, len(prices))):
            price_point = prices[i]
            ts = price_point['time']
            price = price_point['price_kwh']
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            hour = dt.hour
            
            # Complex Solar Estimation for multiple arrays
            total_est_solar = 0.0
            cloud_cover = int(forecast[i].get("wolk", 50)) if i < len(forecast) else 50
            
            # Simple solar position model (Clear sky potential)
            # Peak at 13:00 (Azimuth 180). We weight each array by its azimuth.
            if 7 <= hour <= 19:
                for array in solar_arrays:
                    kwp = array.get("kwp", 0)
                    array_azimuth = array.get("azimuth", 180) # 90=Oost, 180=Zuid, 270=West
                    
                    # Calculate how well the sun aligns with this array at this hour
                    # Sun azimuth moves roughly from 90 (07:00) to 270 (19:00)
                    sun_azimuth = 90 + (hour - 7) * (180 / 12)
                    
                    # Alignment factor: 1.0 is perfect, 0.0 is 90 degrees off
                    alignment = max(0, math.cos(math.radians(sun_azimuth - array_azimuth)))
                    
                    # Estimate yield: Potential * Alignment * (1 - CloudFactor)
                    # Max 1000W per 1kWp under perfect conditions
                    potential = kwp * 1000 * alignment * ((100 - (cloud_cover * 0.7)) / 100)
                    total_est_solar += potential

            # Action Logic
            action = "IDLE"
            if strategy_name == "maximum_profit":
                if hour in cheap_hours and simulated_soc < 95: action = "CHARGE"
                elif hour in expensive_hours and simulated_soc > 15: action = "DISCHARGE"
            else: # 0_on_the_meter
                # If solar forecast is low (< 5kWh total for tomorrow), charge at night
                total_tomorrow_solar = sum(int(f.get("wolk", 0)) for f in forecast[hour:hour+24]) # Placeholder logic
                if 0 <= hour <= 5 and simulated_soc < 30 and total_tomorrow_solar > 1500: # 1500 is cloud sum
                    action = "CHARGE"

            if action == "CHARGE": simulated_soc = min(100, simulated_soc + 20)
            elif action == "DISCHARGE": simulated_soc = max(0, simulated_soc - 25)
            elif total_est_solar > 1000: simulated_soc = min(100, simulated_soc + 10)

            plan.append({
                "datetime": ts,
                "price": round(price, 3),
                "solar_forecast": round(total_est_solar, 0),
                "planned_action": action,
                "expected_soc": int(simulated_soc)
            })

        return plan[0]["planned_action"] if plan else "IDLE", plan
