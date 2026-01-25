"""
Core module - Base classes, protocols, and shared types.
"""

from simulator.core.base import (
    Generator,
    Storage,
    DispatchController,
    FinancialModel,
)
from simulator.core.types import (
    SimulationResult,
    SizingResult,
    LossItem,
    ProjectConfig,
    OptimizationResult,
    TimeSeriesData,
)
from simulator.core.losses import LossWaterfall

__all__ = [
    # Protocols
    "Generator",
    "Storage",
    "DispatchController",
    "FinancialModel",
    # Types
    "SimulationResult",
    "SizingResult",
    "LossItem",
    "ProjectConfig",
    "OptimizationResult",
    "TimeSeriesData",
    # Utilities
    "LossWaterfall",
]
