# Renewable Energy Simulator Pro v2.0

Professional-grade modular simulation platform for utility-scale renewable energy projects.

## ⚡ Features

| Module | Description |
|--------|-------------|
| **☀️ Solar PV** | PVsyst-style simulation with 13-stage loss waterfall, PVGIS TMY integration |
| **💨 Wind Farm** | WindPro-style simulation with turbine library, wake effects |
| **🔋 Battery Storage** | LFP/NMC sizing, SoC tracking, degradation modeling |
| **⚡ Dispatch** | Hybrid PV+Wind+BESS dispatch optimization |
| **💰 LCoE Calculator** | NPV, IRR, floor PPA, Morocco ANRE tariffs |
| **🎯 LCoE Optimizer** | Grid search, genetic algorithm optimization |

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the Streamlit app
streamlit run app/main.py
```

Open http://localhost:8501 in your browser.

## 📁 Project Structure

```
renewable-energy-simulator/
├── app/                    # Streamlit application
│   ├── main.py             # Entry point
│   └── pages/              # Multi-page UI
│       ├── 1_☀️_Solar_Simulation.py
│       ├── 2_💨_Wind_Simulation.py
│       ├── 3_🔋_Battery_Sizing.py
│       └── 4_🎯_LCoE_Optimizer.py
│
├── src/simulator/          # Core simulation engine
│   ├── api.py              # Unified API
│   ├── core/               # Base protocols & types
│   ├── generators/         # Solar & Wind simulators
│   ├── storage/            # Battery simulation
│   ├── grid/               # Dispatch controller
│   ├── financial/          # LCoE, CAPEX, OPEX
│   ├── optimizer/          # LCoE optimization
│   ├── data/               # Weather & time series
│   └── visualization/      # Charts & reports
│
├── pyproject.toml          # Modern Python packaging
└── requirements.txt
```

## 💻 Programmatic Usage

```python
from simulator import SimulationAPI

api = SimulationAPI()

# Run solar simulation
result = api.run_solar_simulation(
    latitude=31.6,
    longitude=-8.0,
    capacity_mw=50,
    project_life=30
)

print(f"Year 1 Energy: {result.solar_result.year_one_energy_mwh:,.0f} MWh")
print(f"LCoE: ${result.lcoe:.2f}/MWh")

# Optimize hybrid configuration
opt_result = api.optimize_lcoe(
    latitude=31.6,
    longitude=-8.0,
    variables={
        'solar_mw': (10, 100, 20),
        'wind_mw': (0, 50, 10),
        'battery_mwh': (0, 200, 50),
    }
)
print(f"Best LCoE: ${opt_result.best_lcoe:.2f}/MWh")
```

## 🏗️ Architecture

- **Protocol-based design**: All components implement standard interfaces
- **Modular structure**: Each module is independently testable
- **Extensible**: Easy to add new generator types, storage technologies, or optimization algorithms

## 📊 Technical Details

### Solar Simulation
- Auto-sizing from land area and GCR
- 13-stage loss waterfall (shading, soiling, IAM, thermal, clipping, etc.)
- PVGIS TMY data integration
- Fixed tilt or single-axis tracking

### Wind Simulation  
- Turbine library (Vestas, Siemens, GE, Nordex)
- Power law wind shear to hub height
- 6-stage loss waterfall (wake, availability, electrical, etc.)
- Weibull-based synthetic wind data

### Battery Storage
- LFP/NMC/NCA chemistry models
- Multiple sizing strategies (peak shaving, self-consumption, arbitrage)
- Calendar and cycle degradation
- Dispatch simulation with SoC tracking

### Financial Analysis
- LCoE calculation with discounted cash flows
- NPV, IRR, payback period
- Floor PPA (NPV=0 break-even tariff)
- Morocco ANRE grid tariffs built-in

## 📄 License

MIT
