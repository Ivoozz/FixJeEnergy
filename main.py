import json
import os
import sys

def main():
    print("FixJeEnergy - Initializing...")
    
    # Standard location for Home Assistant Add-on options
    options_path = "/data/options.json"
    
    if not os.path.exists(options_path):
        print(f"Error: Options file not found at {options_path}")
        sys.exit(1)
        
    try:
        with open(options_path, 'r') as f:
            config = json.load(f)
    except Exception as e:
        print(f"Error loading options: {e}")
        sys.exit(1)
        
    # Get Supervisor Token
    supervisor_token = os.getenv("SUPERVISOR_TOKEN")
    
    print("--- Configuration Loaded ---")
    print(f"Meteoserver API: {'[SET]' if config.get('meteoserver_api') else '[NOT SET]'}")
    print(f"SOC Sensor: {config.get('soc_sensor_entity')}")
    print(f"Solar Power Entities: {config.get('solar_power_entities')}")
    print(f"Battery Control Entity: {config.get('battery_control_entity')}")
    print(f"Strategy: {config.get('strategy')}")
    print(f"Test Mode: {config.get('test_mode')}")
    print(f"Supervisor Token detected: {'Yes' if supervisor_token else 'No'}")
    print("----------------------------")
    
    if config.get("test_mode"):
        print("System is running in TEST MODE. No real commands will be sent.")
    else:
        print("System is running in ACTIVE MODE.")

if __name__ == "__main__":
    main()
