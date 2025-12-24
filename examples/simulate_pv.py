import pandas as pd
import numpy as np
from simulator.solar import PVSimulation
from simulator.finance import FinancialModel

def generate_mock_weather(start_date='2024-01-01', periods=8760):
    times = pd.date_range(start_date, periods=periods, freq='h')
    # Simple sine wave for GHI
    hour = times.hour
    ghi = 800 * np.maximum(0, np.sin(np.pi * (hour - 6) / 12)) 
    dni = ghi * 1.2
    dhi = ghi * 0.3
    temp_air = 20 + 10 * np.sin(np.pi * (hour - 12) / 24)
    wind_speed = 2 + np.random.rand(periods) * 5
    
    return pd.DataFrame({
        'ghi': ghi,
        'dni': dni,
        'dhi': dhi,
        'temp_air': temp_air,
        'wind_speed': wind_speed
    }, index=times)

def run_example():
    print("=== PV PARK SIMULATION EXAMPLE ===")
    weather = generate_mock_weather()
    
    # 1MW PV Plant in Marrakech (approx)
    pv_sim = PVSimulation("Marrakech Solar One", latitude=31.6, longitude=-8.0, capacity_kw=1000)
    
    # Run 30-year lifecycle
    annual_results = pv_sim.run_life_cycle(weather, degradation_rate=0.005)
    
    # Generate PVsyst-style report for Year 1
    pv_sim.generate_pvsyst_report(year=1)
    
    # Financial Analysis
    fin = FinancialModel(capex=800000, opex_annual=15000, tariff_per_mwh=60)
    metrics = fin.get_metrics(annual_results['Annual Energy (MWh)'].tolist())
    
    print("\n--- Financial Metrics (30 Years) ---")
    for k, v in metrics.items():
        print(f"{k:25}: {v:,.2f}")

if __name__ == "__main__":
    run_example()
