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
from simulator.core.validation import SimulationInputError
from simulator.data.timeseries import timestep_hours


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
        
        supported = {
            DispatchStrategy.SELF_CONSUMPTION,
            DispatchStrategy.MAXIMIZE_EXPORT,
            DispatchStrategy.PEAK_SHAVING,
        }
        if self.config.strategy not in supported:
            raise SimulationInputError(
                f"Dispatch strategy '{self.config.strategy.value}' is not implemented. "
                "Supported strategies: self_consumption, maximize_export, peak_shaving."
            )
        if self.config.strategy == DispatchStrategy.SELF_CONSUMPTION:
            self._dispatch_self_consumption(results, index)
        elif self.config.strategy == DispatchStrategy.MAXIMIZE_EXPORT:
            self._dispatch_maximize_export(results, index)
        else:
            self._dispatch_peak_shaving(results, index)
        
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
        
        hours = timestep_hours(index)
        for t in range(n):
            dt = float(hours[t])
            net = generation[t] - load[t]  # Positive = excess generation
            
            if net >= 0:
                excess = net
                if self._storage and storage_soc < max_soc and dt > 0:
                    energy_to_max = (max_soc - storage_soc) * storage_capacity
                    max_charge = min(storage_power, energy_to_max / (charge_eff * dt), excess)
                    max_charge = max(0, max_charge)
                    results['storage_charge_kw'][t] = max_charge
                    storage_soc += (max_charge * charge_eff * dt) / storage_capacity
                    excess -= max_charge
                
                if self.config.grid_export_limit_kw is not None:
                    exportable = min(excess, self.config.grid_export_limit_kw)
                    results['grid_export_kw'][t] = exportable
                    results['curtailment_kw'][t] = excess - exportable
                else:
                    results['grid_export_kw'][t] = excess
                results['load_served_kw'][t] = load[t]
            else:
                shortfall = -net
                if self._storage and storage_soc > min_soc and dt > 0:
                    energy_available = (storage_soc - min_soc) * storage_capacity
                    max_discharge = min(
                        storage_power, energy_available * discharge_eff / dt, shortfall
                    )
                    max_discharge = max(0, max_discharge)
                    results['storage_discharge_kw'][t] = max_discharge
                    storage_soc -= (max_discharge / discharge_eff * dt) / storage_capacity
                    shortfall -= max_discharge
                
                if self.config.grid_import_limit_kw is not None:
                    importable = min(shortfall, self.config.grid_import_limit_kw)
                    results['grid_import_kw'][t] = importable
                    results['unserved_load_kw'][t] = shortfall - importable
                else:
                    results['grid_import_kw'][t] = shortfall
                results['load_served_kw'][t] = load[t] - results['unserved_load_kw'][t]
            
            if self._storage:
                storage_soc = float(np.clip(storage_soc, min_soc, max_soc))
            results['storage_soc'][t] = storage_soc
    
    def _storage_state(self):
        if not self._storage:
            return None
        return {
            "soc": self._storage.config.initial_soc,
            "capacity": self._storage.config.capacity_kwh,
            "power": self._storage.config.power_kw,
            "min_soc": self._storage.config.min_soc,
            "max_soc": self._storage.config.max_soc,
            "charge_eff": self._storage.config.charge_efficiency,
            "discharge_eff": self._storage.config.discharge_efficiency,
        }

    def _dispatch_maximize_export(
        self,
        results: Dict[str, np.ndarray],
        index: pd.DatetimeIndex
    ) -> None:
        """Export generation and import the whole load.

        Storage is used only when an export limit is set: energy above the
        limit can be charged, and stored energy can be discharged while
        generation is below the limit. With no export limit the storage
        schedule stays at zero.
        """
        n = len(index)
        load = results["load_kw"]
        generation = results["total_generation_kw"]
        hours = timestep_hours(index)
        state = self._storage_state()
        limit = self.config.grid_export_limit_kw

        for t in range(n):
            dt = float(hours[t])
            gen = float(generation[t])
            charge = 0.0
            discharge = 0.0
            if state is not None and limit is not None and dt > 0:
                soc = state["soc"]
                if gen > limit and soc < state["max_soc"]:
                    room = (state["max_soc"] - soc) * state["capacity"]
                    charge = min(state["power"], room / (state["charge_eff"] * dt), gen - limit)
                    charge = max(0.0, charge)
                    soc += (charge * state["charge_eff"] * dt) / state["capacity"]
                    gen -= charge
                elif gen < limit and soc > state["min_soc"]:
                    available = (soc - state["min_soc"]) * state["capacity"]
                    discharge = min(
                        state["power"],
                        available * state["discharge_eff"] / dt,
                        limit - gen,
                    )
                    discharge = max(0.0, discharge)
                    soc -= (discharge / state["discharge_eff"] * dt) / state["capacity"]
                    gen += discharge
                state["soc"] = float(np.clip(soc, state["min_soc"], state["max_soc"]))
                results["storage_soc"][t] = state["soc"]
            results["storage_charge_kw"][t] = charge
            results["storage_discharge_kw"][t] = discharge
            if limit is not None and gen > limit:
                results["grid_export_kw"][t] = limit
                results["curtailment_kw"][t] = gen - limit
            else:
                results["grid_export_kw"][t] = gen
            if self.config.grid_import_limit_kw is not None:
                importable = min(float(load[t]), self.config.grid_import_limit_kw)
                results["grid_import_kw"][t] = importable
                results["unserved_load_kw"][t] = float(load[t]) - importable
                results["load_served_kw"][t] = importable
            else:
                results["grid_import_kw"][t] = load[t]
                results["load_served_kw"][t] = load[t]

    def _dispatch_peak_shaving(
        self,
        results: Dict[str, np.ndarray],
        index: pd.DatetimeIndex
    ) -> None:
        """Discharge only while net load is above the 75th percentile of positive net load.

        Charging uses surplus generation only. This is a heuristic. It is not
        an optimal peak-shaving schedule.
        """
        n = len(index)
        load = results["load_kw"]
        generation = results["total_generation_kw"]
        net = load - generation
        positive = net[net > 0]
        threshold = float(np.quantile(positive, 0.75)) if len(positive) else 0.0
        self._peak_shave_threshold_kw = threshold
        hours = timestep_hours(index)
        state = self._storage_state()

        for t in range(n):
            dt = float(hours[t])
            nl = float(load[t] - generation[t])
            charge = 0.0
            discharge = 0.0
            if state is not None and dt > 0:
                soc = state["soc"]
                if nl > threshold and soc > state["min_soc"]:
                    available = (soc - state["min_soc"]) * state["capacity"]
                    discharge = min(
                        state["power"],
                        available * state["discharge_eff"] / dt,
                        nl - threshold,
                    )
                    discharge = max(0.0, discharge)
                    soc -= (discharge / state["discharge_eff"] * dt) / state["capacity"]
                    nl -= discharge
                elif nl < 0 and soc < state["max_soc"]:
                    room = (state["max_soc"] - soc) * state["capacity"]
                    charge = min(state["power"], room / (state["charge_eff"] * dt), -nl)
                    charge = max(0.0, charge)
                    soc += (charge * state["charge_eff"] * dt) / state["capacity"]
                    nl += charge
                state["soc"] = float(np.clip(soc, state["min_soc"], state["max_soc"]))
                results["storage_soc"][t] = state["soc"]
            results["storage_charge_kw"][t] = charge
            results["storage_discharge_kw"][t] = discharge
            if nl >= 0:
                if self.config.grid_import_limit_kw is not None:
                    importable = min(nl, self.config.grid_import_limit_kw)
                    results["grid_import_kw"][t] = importable
                    results["unserved_load_kw"][t] = nl - importable
                else:
                    results["grid_import_kw"][t] = nl
                results["load_served_kw"][t] = float(load[t]) - results["unserved_load_kw"][t]
            else:
                excess = -nl
                if self.config.grid_export_limit_kw is not None:
                    exportable = min(excess, self.config.grid_export_limit_kw)
                    results["grid_export_kw"][t] = exportable
                    results["curtailment_kw"][t] = excess - exportable
                else:
                    results["grid_export_kw"][t] = excess
                results["load_served_kw"][t] = load[t]
    
    def _calculate_kpis(self, schedule: pd.DataFrame) -> Dict[str, float]:
        """Calculate dispatch performance KPIs."""
        hours = timestep_hours(schedule.index)

        def _kwh(column: str) -> float:
            return float(np.sum(schedule[column].to_numpy(dtype=float) * hours))

        total_load = _kwh("load_kw")
        total_gen = _kwh("total_generation_kw")
        total_import = _kwh("grid_import_kw")
        total_export = _kwh("grid_export_kw")
        total_curtailment = _kwh("curtailment_kw")
        load_served = _kwh("load_served_kw")

        # Generation that was not exported and not curtailed. Storage discharge
        # can make export larger than generation, so the remainder is floored at 0.
        onsite_kw = (
            schedule["total_generation_kw"] - schedule["grid_export_kw"] - schedule["curtailment_kw"]
        ).clip(lower=0)
        onsite_kwh = float(np.sum(onsite_kw.to_numpy(dtype=float) * hours))
        served_without_import = (
            schedule["load_served_kw"] - schedule["grid_import_kw"]
        ).clip(lower=0)
        served_onsite_kwh = float(np.sum(served_without_import.to_numpy(dtype=float) * hours))
        self_consumption_ratio = min(1.0, onsite_kwh / total_gen) if total_gen > 0 else 0
        self_sufficiency_ratio = min(1.0, served_onsite_kwh / total_load) if total_load > 0 else 0
        
        # Curtailment ratio
        curtailment_ratio = total_curtailment / total_gen if total_gen > 0 else 0
        
        kpis = {
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
        if self.config.strategy == DispatchStrategy.PEAK_SHAVING:
            kpis["peak_shave_threshold_kw"] = float(getattr(self, "_peak_shave_threshold_kw", 0.0))
        return kpis
    
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
