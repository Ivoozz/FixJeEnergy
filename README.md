# ⚡ FixJeEnergy Home Assistant Add-on

Professional battery energy management using real-time market prices and weather forecasting.

## 🚀 Installation

Follow these steps to add FixJeEnergy to your Home Assistant instance:

1. **Add Repository**:
   - Navigate to **Settings** > **Add-ons** > **Add-on Store**.
   - Click the three dots (vertical ellipsis) in the top-right corner.
   - Select **Repositories**.
   - Paste the following URL: `https://github.com/ivoozz/FixJeEnergy`
   - Click **Add** and then **Close**.

2. **Install Add-on**:
   - Scroll down to find the **FixJeEnergy** category.
   - Click on the **FixJeEnergy** add-on and click **Install**.

3. **Configure**:
   - Go to the **Configuration** tab.
   - Enter your **Meteoserver API Key**.
   - Map your **Battery SOC** and **Solar Power** entities.
   - Select your preferred **Strategy**.
   - Click **Save**.

4. **Start**:
   - Go to the **Info** tab and click **Start**.
   - Check the **Logs** tab to see the magic happen!

## 🧪 Simulation Mode
Want to see how your battery would react over 24 hours without actually sending commands? 
Enable `run_internal_simulation` in the configuration and check the logs. It uses live Nordpool and Meteoserver data for a realistic test run.

---
*Maintained by FixjeICT*
