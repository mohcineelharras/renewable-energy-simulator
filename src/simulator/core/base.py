"""
Base protocols and abstract classes for the simulation framework.

This module defines the interfaces that all simulation components must implement,
enabling a modular and extensible architecture.
"""

from abc import ABC, abstractmethod
from typing import Protocol, Dict, List, Any, Optional, runtime_checkable
import pandas as pd

from simulator.core.types import (
    SimulationResult,
    SizingResult,
    LossItem,
    DispatchResult,
)
from simulator.data.timeseries import integrate_power_kwh


@runtime_checkable
class Generator(Protocol):
    """
    Protocol for power generation assets (Solar PV, Wind, etc.).
    
    All generator implementations must provide these methods to ensure
    consistent behavior across different generation technologies.
    """
    
    @property
    def name(self) -> str:
        """Human-readable name of the generator."""
        ...
    
    @property
    def capacity_kw(self) -> float:
        """Rated capacity in kW."""
        ...
    
    def configure(self, **kwargs: Any) -> None:
        """
        Configure the generator with the given parameters.
        
        Args:
            **kwargs: Configuration parameters specific to the generator type.
        """
        ...
    
    def auto_size(self, constraints: Optional[Dict[str, Any]] = None) -> SizingResult:
        """
        Automatically size the system based on constraints.
        
        Args:
            constraints: Optional dict with constraints like land_area, grid_limit, etc.
            
        Returns:
            SizingResult with calculated capacities and counts.
        """
        ...
    
    def simulate(self, weather: pd.DataFrame, years: int = 1) -> SimulationResult:
        """
        Run simulation for the specified number of years.
        
        Args:
            weather: DataFrame with weather data (columns depend on generator type).
            years: Number of years to simulate (default: 1).
            
        Returns:
            SimulationResult with hourly/annual production data.
        """
        ...
    
    def get_losses(self) -> List[LossItem]:
        """
        Get the loss waterfall for the simulation.
        
        Returns:
            List of LossItem representing each stage in the loss waterfall.
        """
        ...
    
    def get_kpis(self) -> Dict[str, float]:
        """
        Calculate and return key performance indicators.
        
        Returns:
            Dict with KPIs like annual_energy, capacity_factor, performance_ratio, etc.
        """
        ...


@runtime_checkable
class Storage(Protocol):
    """
    Protocol for energy storage assets (Battery, Pumped Hydro, etc.).
    """
    
    @property
    def name(self) -> str:
        """Human-readable name of the storage system."""
        ...
    
    @property
    def capacity_kwh(self) -> float:
        """Energy capacity in kWh."""
        ...
    
    @property
    def power_kw(self) -> float:
        """Power capacity in kW."""
        ...
    
    def configure(self, **kwargs: Any) -> None:
        """Configure the storage system."""
        ...
    
    def size_for_application(
        self,
        generation: pd.Series,
        load: pd.Series,
        target: str = "peak_shaving"
    ) -> Dict[str, float]:
        """
        Size storage for a specific application.
        
        Args:
            generation: Time series of generation in kW.
            load: Time series of load in kW.
            target: Sizing target ('peak_shaving', 'arbitrage', 'self_consumption').
            
        Returns:
            Dict with recommended capacity_kwh, power_kw, and sizing rationale.
        """
        ...
    
    def simulate(
        self,
        generation: pd.Series,
        load: pd.Series,
        dispatch_strategy: str = "self_consumption"
    ) -> pd.DataFrame:
        """
        Simulate storage operation.
        
        Args:
            generation: Time series of generation in kW.
            load: Time series of load in kW.
            dispatch_strategy: Strategy for charge/discharge decisions.
            
        Returns:
            DataFrame with columns: soc, charge_kw, discharge_kw, grid_import, grid_export.
        """
        ...
    
    def get_degradation(self, years: int = 1) -> float:
        """
        Calculate cumulative degradation over time.
        
        Args:
            years: Number of years of operation.
            
        Returns:
            Remaining capacity as fraction (0-1).
        """
        ...


@runtime_checkable
class DispatchController(Protocol):
    """
    Protocol for dispatch optimization and control.
    """
    
    def configure(
        self,
        generators: List[Generator],
        storage: Optional[Storage] = None,
        grid_limit_kw: Optional[float] = None
    ) -> None:
        """
        Configure the dispatch controller with assets.
        
        Args:
            generators: List of generator assets.
            storage: Optional storage asset.
            grid_limit_kw: Optional grid export limit.
        """
        ...
    
    def optimize(
        self,
        load: pd.Series,
        weather: pd.DataFrame,
        strategy: str = "minimize_cost"
    ) -> DispatchResult:
        """
        Optimize dispatch for the given load and weather.
        
        Args:
            load: Time series of load in kW.
            weather: Weather data for generation simulation.
            strategy: Optimization objective.
            
        Returns:
            DispatchResult with optimized dispatch schedule.
        """
        ...
    
    def get_curtailment(self) -> pd.Series:
        """Get curtailment time series from last optimization."""
        ...
    
    def get_grid_exchange(self) -> pd.DataFrame:
        """Get grid import/export time series."""
        ...


@runtime_checkable
class FinancialModel(Protocol):
    """
    Protocol for financial calculations.
    """
    
    def calculate_lcoe(
        self,
        capex: float,
        opex_annual: float,
        energy_annual: List[float],
        discount_rate: float
    ) -> float:
        """
        Calculate Levelized Cost of Energy.
        
        Args:
            capex: Total capital expenditure.
            opex_annual: Annual operating expenditure (base year).
            energy_annual: List of annual energy production for each year.
            discount_rate: Discount rate (WACC).
            
        Returns:
            LCOE in $/MWh.
        """
        ...
    
    def calculate_npv(
        self,
        capex: float,
        revenues: List[float],
        opex: List[float],
        discount_rate: float
    ) -> float:
        """Calculate Net Present Value."""
        ...
    
    def calculate_irr(
        self,
        capex: float,
        cash_flows: List[float]
    ) -> Optional[float]:
        """Calculate Internal Rate of Return."""
        ...
    
    def calculate_payback(
        self,
        capex: float,
        annual_savings: float
    ) -> float:
        """Calculate simple payback period in years."""
        ...


class BaseGenerator(ABC):
    """
    Abstract base class for generators with common functionality.
    
    Provides default implementations for common methods while requiring
    subclasses to implement technology-specific logic.
    """
    
    def __init__(self, name: str):
        self._name = name
        self._capacity_kw: float = 0.0
        self._hourly_results: Optional[pd.DataFrame] = None
        self._annual_results: Optional[pd.DataFrame] = None
        self._losses: List[LossItem] = []
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def capacity_kw(self) -> float:
        return self._capacity_kw
    
    @abstractmethod
    def configure(self, **kwargs: Any) -> None:
        """Configure the generator - must be implemented by subclasses."""
        pass
    
    @abstractmethod
    def auto_size(self, constraints: Optional[Dict[str, Any]] = None) -> SizingResult:
        """Auto-size the system - must be implemented by subclasses."""
        pass
    
    @abstractmethod
    def _simulate_year_one(self, weather: pd.DataFrame) -> pd.DataFrame:
        """Simulate first year production - must be implemented by subclasses."""
        pass
    
    def simulate(self, weather: pd.DataFrame, years: int = 1) -> SimulationResult:
        """
        Run multi-year simulation with degradation.
        
        Default implementation applies linear degradation to year-one results.
        """
        self._hourly_results = self._simulate_year_one(weather)
        base_annual_kwh = integrate_power_kwh(self._hourly_results["power_kw"])
        degradation_rate = getattr(self, 'annual_degradation', 0.005)
        
        annual_data = []
        for year in range(1, years + 1):
            factor = (1 - degradation_rate) ** (year - 1)
            annual_kwh = base_annual_kwh * factor
            annual_data.append({
                'year': year,
                'degradation_factor': factor,
                'energy_kwh': annual_kwh,
                'energy_mwh': annual_kwh / 1000,
            })
        
        self._annual_results = pd.DataFrame(annual_data)
        
        return SimulationResult(
            hourly=self._hourly_results,
            annual=self._annual_results,
            kpis=self.get_kpis(),
            losses=self.get_losses(),
        )
    
    def get_losses(self) -> List[LossItem]:
        """Return the loss waterfall from the last simulation."""
        return self._losses
    
    @abstractmethod
    def get_kpis(self) -> Dict[str, float]:
        """Calculate KPIs - must be implemented by subclasses."""
        pass


class BaseStorage(ABC):
    """
    Abstract base class for storage systems with common functionality.
    """
    
    def __init__(self, name: str):
        self._name = name
        self._capacity_kwh: float = 0.0
        self._power_kw: float = 0.0
        self._efficiency: float = 0.90  # Round-trip efficiency
        self._soc: float = 0.5  # Initial state of charge
        self._min_soc: float = 0.1
        self._max_soc: float = 0.9
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def capacity_kwh(self) -> float:
        return self._capacity_kwh
    
    @property
    def power_kw(self) -> float:
        return self._power_kw
    
    @abstractmethod
    def configure(self, **kwargs: Any) -> None:
        pass
    
    @abstractmethod
    def size_for_application(
        self,
        generation: pd.Series,
        load: pd.Series,
        target: str = "peak_shaving"
    ) -> Dict[str, float]:
        pass
    
    @abstractmethod
    def simulate(
        self,
        generation: pd.Series,
        load: pd.Series,
        dispatch_strategy: str = "self_consumption"
    ) -> pd.DataFrame:
        pass
    
    def get_degradation(self, years: int = 1) -> float:
        """Default degradation model - 2% per year."""
        return (1 - 0.02) ** years
