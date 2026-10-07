"""
Renewable Energy Simulator
===========================

Screening models for solar, wind, storage, dispatch, and LCOE.

These are not PVsyst or WindPro models, and numeric results from 2.0.0
are not comparable: energy is integrated with the timestep, and several
loss and dispatch calculations changed in 2.1.0.

Modules:
- generators: solar screening model and idealized wind power curve
- storage: Battery energy storage system simulation and sizing
- grid: Dispatch controller and grid connection models
- financial: LCoE, CAPEX, OPEX, and tariff calculations
- optimizer: LCoE optimization with multiple algorithms
- data: Weather data providers and time series utilities
- visualization: Charts, reports, and optimization result visualization

Example:
    >>> from simulator import SimulationAPI
    >>> api = SimulationAPI()
    >>> result = api.run_solar_simulation(latitude=31.6, longitude=-8.0, capacity_mw=50)
"""

__version__ = "2.1.0"
__author__ = "Mohcine"

# Convenience imports
from simulator.api import SimulationAPI
from simulator.core.types import (
    SimulationResult,
    OptimizationResult,
    ProjectConfig,
)

__all__ = [
    "SimulationAPI",
    "SimulationResult",
    "OptimizationResult",
    "ProjectConfig",
    "__version__",
]
