"""
Dispatch Controller Module.

Optimizes dispatch decisions for hybrid PV+Wind+BESS systems with:
- Multiple dispatch strategies
- Grid export limits and curtailment
- Priority-based dispatch ordering
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from enum import Enum

from simulator.core.types import DispatchResult


class DispatchStrategy(Enum):
    """Available dispatch optimization strategies."""
    SELF_CONSUMPTION = "self_consumption"  # Maximize on-site use
    MAXIMIZE_EXPORT = "maximize_export"  # Maximize grid export
    MINIMIZE_IMPORT = "minimize_import"  # Minimize grid import
    PEAK_SHAVING = "peak_shaving"  # Reduce peak demand
    LOAD_FOLLOWING = "load_following"  # Match generation to load


@dataclass
class DispatchConfig:
    """Configuration for dispatch optimization."""
    
    strategy: DispatchStrategy = DispatchStrategy.SELF_CONSUMPTION
    
    # Grid constraints
    grid_export_limit_kw: Optional[float] = None  # Max export to grid
    grid_import_limit_kw: Optional[float] = None  # Max import from grid
    
    # Curtailment settings
    allow_curtailment: bool = True
    curtailment_priority: List[str] = field(default_factory=lambda: ["wind", "solar"])
    
    # Storage priority
    storage_charge_priority: str = "excess"  # 'excess' or 'grid'
    storage_discharge_priority: str = "self_consumption"
    
    # Price signals (optional)
    use_price_signals: bool = False
    import_price: Optional[pd.Series] = None  # $/kWh time series
    export_price: Optional[pd.Series] = None  # $/kWh time series


class DispatchController:
    """
    Dispatch controller for hybrid renewable energy systems.
    
    Coordinates dispatch between multiple generators, storage, and grid
    to optimize for the selected strategy.
    
    Example:
        >>> controller = DispatchController()
        >>> controller.add_generation("solar", solar_gen_kw, priority=1)
        >>> controller.add_generation("wind", wind_gen_kw, priority=2)
        >>> controller.set_storage(battery)
        >>> result = controller.optimize(load_kw)
    """
    
    def __init__(self, config: Optional[DispatchConfig] = None):
        self.config = config or DispatchConfig()
        self._generations: Dict[str, pd.Series] = {}
        self._generation_priorities: Dict[str, int] = {}
        self._storage = None
        self._load: Optional[pd.Series] = None
        self._result: Optional[DispatchResult] = None
    
    def add_generation(
        self,
        name: str,
        generation: pd.Series,
        priority: int = 1
    ) -> None:
        """
        Add a generation source to the dispatch.
        
        Args:
            name: Identifier for the generation source.
            generation: Time series of generation in kW.
            priority: Dispatch priority (1 = highest, used first).
        """
        self._generations[name] = generation
        self._generation_priorities[name] = priority
    
    def set_storage(self, storage: Any) -> None:
        """
        Set the storage system for dispatch.
        
        Args:
            storage: BatteryStorage instance or compatible storage object.
        """
        self._storage = storage
    
    def set_load(self, load: pd.Series) -> None:
        """Set the load profile."""
        self._load = load
    
    def optimize(
        self,
        load: Optional[pd.Series] = None,
        strategy: Optional[DispatchStrategy] = None
    ) -> DispatchResult:
        """
        Optimize dispatch for the given load profile.
        
        Args:
            load: Time series of load in kW (optional if already set).
            strategy: Override dispatch strategy (optional).
        
        Returns:
            DispatchResult with optimized dispatch schedule.
        """
        if load is not None:
            self._load = load
        if strategy is not None:
            self.config.strategy = strategy
        
        if self._load is None:
            raise ValueError("Load profile must be set before optimization")
        
        if not self._generations:
            raise ValueError("At least one generation source must be added")
        
        # Get common index
        index = self._load.index
        n = len(index)
        
        # Initialize result arrays
        results = {
            'load_kw': self._load.values,
            'total_generation_kw': np.zeros(n),
            'grid_import_kw': np.zeros(n),
            'grid_export_kw': np.zeros(n),
            'curtailment_kw': np.zeros(n),
            'storage_charge_kw': np.zeros(n),
            'storage_discharge_kw': np.zeros(n),
            'storage_soc': np.zeros(n),
            'load_served_kw': np.zeros(n),
            'unserved_load_kw': np.zeros(n),
        }
        
        # Add generation columns sorted by priority
        sorted_gens = sorted(
            self._generations.keys(),
            key=lambda x: self._generation_priorities.get(x, 99)
        )
        
        for gen_name in sorted_gens:
            gen_series = self._generations[gen_name].reindex(index).fillna(0)
            results[f'{gen_name}_kw'] = gen_series.values
            results['total_generation_kw'] += gen_series.values
        
        # Run dispatch based on strategy
        if self.config.strategy == DispatchStrategy.SELF_CONSUMPTION:
            self._dispatch_self_consumption(results, index)
        elif self.config.strategy == DispatchStrategy.MAXIMIZE_EXPORT:
            self._dispatch_maximize_export(results, index)
        elif self.config.strategy == DispatchStrategy.PEAK_SHAVING:
            self._dispatch_peak_shaving(results, index)
        else:
            # Default to self-consumption
            self._dispatch_self_consumption(results, index)
        
        # Create result DataFrame
        schedule = pd.DataFrame(results, index=index)
        
        # Calculate KPIs
        kpis = self._calculate_kpis(schedule)
        
        self._result = DispatchResult(
            schedule=schedule,
            generation=pd.DataFrame({
                name: schedule.get(f'{name}_kw', 0) for name in sorted_gens
            }, index=index),
            storage=schedule[['storage_charge_kw', 'storage_discharge_kw', 'storage_soc']] if self._storage else None,
            grid_exchange=schedule[['grid_import_kw', 'grid_export_kw']],
            curtailment=pd.Series(schedule['curtailment_kw'].values, index=index),
            kpis=kpis,
        )
        
        return self._result
    
    def _dispatch_self_consumption(
        self,
        results: Dict[str, np.ndarray],
        index: pd.DatetimeIndex
    ) -> None:
        """Self-consumption dispatch: maximize on-site use of generation."""
        n = len(index)
        load = results['load_kw']
        generation = results['total_generation_kw']
        
        # Initialize storage if available
        if self._storage:
            storage_soc = self._storage.config.initial_soc
            storage_capacity = self._storage.config.capacity_kwh
            storage_power = self._storage.config.power_kw
            min_soc = self._storage.config.min_soc
            max_soc = self._storage.config.max_soc
            charge_eff = self._storage.config.charge_efficiency
            discharge_eff = self._storage.config.discharge_efficiency
        else:
            storage_soc = 0
            storage_capacity = 0
            storage_power = 0
        
        for t in range(n):
            net = generation[t] - load[t]  # Positive = excess generation
            
            if net >= 0:
                # Excess generation
                excess = net
                
                # Try to charge storage
                if self._storage and storage_soc < max_soc:
                    energy_to_max = (max_soc - storage_soc) * storage_capacity
                    max_charge = min(storage_power, energy_to_max / charge_eff, excess)
                    max_charge = max(0, max_charge)
                    
                    results['storage_charge_kw'][t] = max_charge
                    storage_soc += (max_charge * charge_eff) / storage_capacity
                    excess -= max_charge
                
                # Export remaining to grid
                if self.config.grid_export_limit_kw is not None:
                    exportable = min(excess, self.config.grid_export_limit_kw)
                    results['grid_export_kw'][t] = exportable
                    results['curtailment_kw'][t] = excess - exportable
                else:
                    results['grid_export_kw'][t] = excess
                
                results['load_served_kw'][t] = load[t]
                
            else:
                # Generation shortfall
                shortfall = -net
                
                # Try to discharge storage
                if self._storage and storage_soc > min_soc:
                    energy_available = (storage_soc - min_soc) * storage_capacity
                    max_discharge = min(storage_power, energy_available * discharge_eff, shortfall)
                    max_discharge = max(0, max_discharge)
                    
                    results['storage_discharge_kw'][t] = max_discharge
                    storage_soc -= (max_discharge / discharge_eff) / storage_capacity
                    shortfall -= max_discharge
                
                # Import remaining from grid
                if self.config.grid_import_limit_kw is not None:
                    importable = min(shortfall, self.config.grid_import_limit_kw)
                    results['grid_import_kw'][t] = importable
                    results['unserved_load_kw'][t] = shortfall - importable
                else:
                    results['grid_import_kw'][t] = shortfall
                
                results['load_served_kw'][t] = load[t] - results['unserved_load_kw'][t]
            
            results['storage_soc'][t] = storage_soc
    
    def _dispatch_maximize_export(
        self,
        results: Dict[str, np.ndarray],
        index: pd.DatetimeIndex
    ) -> None:
        """Maximize export: prioritize grid export over self-consumption."""
        n = len(index)
        load = results['load_kw']
        generation = results['total_generation_kw']
        
        for t in range(n):
            # Export all generation, import for load
            if self.config.grid_export_limit_kw is not None:
                exportable = min(generation[t], self.config.grid_export_limit_kw)
                results['grid_export_kw'][t] = exportable
                results['curtailment_kw'][t] = generation[t] - exportable
            else:
                results['grid_export_kw'][t] = generation[t]
            
            results['grid_import_kw'][t] = load[t]
            results['load_served_kw'][t] = load[t]
    
    def _dispatch_peak_shaving(
        self,
        results: Dict[str, np.ndarray],
        index: pd.DatetimeIndex
    ) -> None:
        """Peak shaving: use storage to reduce peak demand."""
        # First, run self-consumption to initialize
        self._dispatch_self_consumption(results, index)
        
        # Then optimize storage for peak reduction if storage available
        if self._storage:
            # Calculate target peak (e.g., 80% of max import)
            max_import = results['grid_import_kw'].max()
            target_peak = max_import * 0.80
            
            # Re-dispatch with peak target
            # (Simplified - full implementation would re-run dispatch)
            pass
    
    def _calculate_kpis(self, schedule: pd.DataFrame) -> Dict[str, float]:
        """Calculate dispatch performance KPIs."""
        total_load = schedule['load_kw'].sum()
        total_gen = schedule['total_generation_kw'].sum()
        total_import = schedule['grid_import_kw'].sum()
        total_export = schedule['grid_export_kw'].sum()
        total_curtailment = schedule['curtailment_kw'].sum()
        load_served = schedule['load_served_kw'].sum()
        
        # Self-consumption ratio: generation used on-site / total generation
        gen_used_onsite = total_gen - total_export - total_curtailment
        self_consumption_ratio = gen_used_onsite / total_gen if total_gen > 0 else 0
        
        # Self-sufficiency ratio: generation used on-site / total load
        self_sufficiency_ratio = gen_used_onsite / total_load if total_load > 0 else 0
        
        # Curtailment ratio
        curtailment_ratio = total_curtailment / total_gen if total_gen > 0 else 0
        
        return {
            'total_load_kwh': total_load,
            'total_generation_kwh': total_gen,
            'grid_import_kwh': total_import,
            'grid_export_kwh': total_export,
            'curtailment_kwh': total_curtailment,
            'load_served_kwh': load_served,
            'self_consumption_ratio': self_consumption_ratio,
            'self_sufficiency_ratio': self_sufficiency_ratio,
            'curtailment_ratio': curtailment_ratio,
            'peak_import_kw': schedule['grid_import_kw'].max(),
            'peak_export_kw': schedule['grid_export_kw'].max(),
        }
    
    def get_curtailment(self) -> pd.Series:
        """Get curtailment time series from last optimization."""
        if self._result:
            return self._result.curtailment
        return pd.Series()
    
    def get_grid_exchange(self) -> pd.DataFrame:
        """Get grid import/export time series."""
        if self._result:
            return self._result.grid_exchange
        return pd.DataFrame()
