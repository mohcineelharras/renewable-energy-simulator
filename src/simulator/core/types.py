"""
Shared types and dataclasses used across the simulation framework.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
import pandas as pd


class GeneratorType(Enum):
    """Types of power generators."""
    SOLAR_PV = "solar_pv"
    WIND_ONSHORE = "wind_onshore"
    WIND_OFFSHORE = "wind_offshore"
    HYBRID = "hybrid"


class StorageType(Enum):
    """Types of energy storage."""
    LITHIUM_ION = "lithium_ion"
    LEAD_ACID = "lead_acid"
    FLOW_BATTERY = "flow_battery"
    PUMPED_HYDRO = "pumped_hydro"


class DispatchStrategy(Enum):
    """Dispatch optimization strategies."""
    SELF_CONSUMPTION = "self_consumption"  # Maximize self-consumption
    GRID_EXPORT = "grid_export"  # Maximize grid export
    PEAK_SHAVING = "peak_shaving"  # Reduce peak demand
    ARBITRAGE = "arbitrage"  # Buy low, sell high
    MINIMIZE_LCOE = "minimize_lcoe"  # Minimize levelized cost


@dataclass
class LossItem:
    """Single item in a loss waterfall."""
    stage: str
    loss_percent: float
    input_energy: float = 0.0
    loss_energy: float = 0.0
    output_energy: float = 0.0
    
    def __post_init__(self):
        if self.input_energy > 0 and self.loss_energy == 0:
            self.loss_energy = self.input_energy * self.loss_percent
            self.output_energy = self.input_energy - self.loss_energy


@dataclass
class SizingResult:
    """Result of auto-sizing calculation."""
    capacity_kw: float
    capacity_kwh: Optional[float] = None  # For storage
    num_units: int = 1
    area_m2: float = 0.0
    grid_constrained: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationResult:
    """Result of a simulation run."""
    hourly: pd.DataFrame
    annual: pd.DataFrame
    kpis: Dict[str, float]
    losses: List[LossItem]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def total_energy_mwh(self) -> float:
        """Total energy over simulation period in MWh."""
        return self.annual['energy_mwh'].sum()
    
    @property
    def year_one_energy_mwh(self) -> float:
        """Year one energy in MWh."""
        return self.annual.iloc[0]['energy_mwh'] if len(self.annual) > 0 else 0.0


@dataclass
class DispatchResult:
    """Result of dispatch optimization."""
    schedule: pd.DataFrame  # Hourly dispatch schedule
    generation: pd.DataFrame  # Generation from each source
    storage: Optional[pd.DataFrame] = None  # Storage operations
    grid_exchange: Optional[pd.DataFrame] = None  # Grid import/export
    curtailment: Optional[pd.Series] = None
    kpis: Dict[str, float] = field(default_factory=dict)


@dataclass
class FinancialResult:
    """Result of financial analysis."""
    lcoe: float  # $/MWh
    npv: float  # $
    irr: Optional[float] = None  # %
    payback_years: Optional[float] = None
    total_capex: float = 0.0
    total_opex: float = 0.0
    total_revenue: float = 0.0
    cash_flows: Optional[pd.DataFrame] = None
    breakdown: Dict[str, Dict[str, float]] = field(default_factory=dict)


@dataclass
class OptimizationVariable:
    """Variable to optimize."""
    name: str
    min_value: float
    max_value: float
    step: Optional[float] = None
    unit: str = ""
    description: str = ""


@dataclass
class OptimizationConstraint:
    """Constraint for optimization."""
    name: str
    expression: str  # e.g., "pv_capacity + wind_capacity <= 100"
    description: str = ""


@dataclass
class OptimizationResult:
    """Result of LCoE optimization."""
    best_config: Dict[str, float]
    best_lcoe: float
    all_results: pd.DataFrame  # All evaluated configurations
    pareto_front: Optional[pd.DataFrame] = None  # For multi-objective
    convergence: Optional[pd.Series] = None  # Convergence history
    runtime_seconds: float = 0.0
    algorithm: str = ""
    n_evaluations: int = 0


@dataclass
class ProjectConfig:
    """Configuration for a renewable energy project."""
    name: str = "Unnamed Project"
    latitude: float = 0.0
    longitude: float = 0.0
    timezone: str = "UTC"
    
    # Project parameters
    project_life_years: int = 30
    discount_rate: float = 0.06  # WACC
    
    # Generator configs
    solar_config: Optional[Dict[str, Any]] = None
    wind_config: Optional[Dict[str, Any]] = None
    
    # Storage config
    storage_config: Optional[Dict[str, Any]] = None
    
    # Grid config
    grid_limit_mw: float = 0.0
    grid_tariffs: Optional[Dict[str, float]] = None
    
    # Financial config
    ppa_tariff: float = 0.0  # $/MWh
    use_local_tariffs: bool = False


@dataclass
class TimeSeriesData:
    """Container for time series data with metadata."""
    data: pd.DataFrame
    source: str = "unknown"
    resolution: str = "hourly"  # hourly, 15min, daily
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.start_date is None and len(self.data) > 0:
            self.start_date = str(self.data.index[0])
        if self.end_date is None and len(self.data) > 0:
            self.end_date = str(self.data.index[-1])


@dataclass
class WeatherData(TimeSeriesData):
    """Weather data with specific columns for renewable energy simulation."""
    
    @property
    def has_solar_data(self) -> bool:
        """Check if data has required columns for solar simulation."""
        required = {'ghi', 'dni', 'dhi', 'temp_air'}
        return required.issubset(set(self.data.columns))
    
    @property
    def has_wind_data(self) -> bool:
        """Check if data has required columns for wind simulation."""
        required = {'wind_speed'}
        return required.issubset(set(self.data.columns))
