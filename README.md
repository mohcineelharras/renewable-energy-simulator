# Renewable Energy Simulator Pro

Professional-grade simulator for utility-scale Solar PV and Wind projects with 30-year lifecycle analysis and Morocco-specific financial modeling.

## Features

- **Auto-Sizing**: Calculate DC/AC capacity from land area, GCR, and grid limits
- **PVGIS Integration**: Fetches real TMY data from EU PVGIS API
- **12-Stage Solar Loss Waterfall**: Shading → Soiling → IAM → Temperature → Wiring → Inverter → Grid
- **6-Stage Wind Loss Waterfall**: Wake → Availability → Electrical → Environmental → Grid
- **Floor PPA Calculation**: Minimum tariff for NPV=0
- **Morocco Financials**: ANRE grid tariffs, local CAPEX/OPEX benchmarks

## Installation

```bash
pip install pvlib windpowerlib pandas numpy streamlit plotly requests
```

## Usage

```bash
streamlit run app.py
```

Then open http://localhost:8501 in your browser.

## Project Structure

```
├── app.py                 # Streamlit frontend
├── simulator/
│   ├── __init__.py
│   ├── solar.py           # PV simulation with pvlib
│   ├── wind.py            # Wind simulation with power curves
│   ├── finance.py         # LCOE, NPV, IRR, Floor PPA
│   └── weather.py         # PVGIS API integration
└── examples/
    ├── simulate_pv.py     # CLI example for solar
    └── simulate_wind.py   # CLI example for wind
```

## License

MIT
