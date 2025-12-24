import pandas as pd
import numpy as np
from simulator.wind import WindSimulation
from simulator.finance import FinancialModel

def generate_mock_weather(start_date='2024-01-01', periods=8760):
    times = pd.date_range(start_date, periods=periods, freq='h')
    # Rayleigh distribution for wind speed (approx)
    wind_speed = np.random.rayleigh(scale=6, size=periods)
    pressure = 1013 * np.ones(periods)
    temperature = 15 + 5 * np.cos(np.pi * (times.hour - 14) / 12)
    
    return pd.DataFrame({
        'wind_speed': wind_speed,
        'pressure': pressure,
        'temperature': temperature
    }, index=times)

def run_example():
    print("=== WIND FARM SIMULATION EXAMPLE ===")
    weather = generate_mock_weather()
    
    # 3MW Wind Turbine
    wind_sim = WindSimulation("North Sea Wind One", hub_height=110, capacity_kw=3000)
    
    # Run 30-year lifecycle
    annual_results = wind_sim.run_life_cycle(weather, degradation_rate=0.01)
    
    # Generate WindPro-style report for Year 1
    wind_sim.generate_windpro_report(year=1)
    
    # Financial Analysis
    fin = FinancialModel(capex=4500000, opex_annual=100000, tariff_per_mwh=55)
    metrics = fin.get_metrics(annual_results['Annual Energy (MWh)'].tolist())
    
    print("\n--- Financial Metrics (30 Years) ---")
    for k, v in metrics.items():
        print(f"{k:25}: {v:,.2f}")

if __name__ == "__main__":
    run_example()
