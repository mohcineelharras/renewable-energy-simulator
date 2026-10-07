"""
Battery Energy Storage System (BESS) Module.

Professional-grade battery storage simulation with:
- Multiple sizing strategies (peak shaving, arbitrage, self-consumption)
- State of charge tracking with efficiency
- Calendar and cycle degradation modeling
- C-rate and DoD constraints
"""

import warnings

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

from simulator.core.base import BaseStorage
from simulator.core.types import SizingResult
from simulator.core.validation import (
    SimulationInputError,
    require_fraction,
    require_in_range,
    require_non_negative,
    require_positive,
)
from simulator.data.timeseries import integrate_power_kwh, timestep_hours


class BatteryChemistry(Enum):
    """Battery chemistry types."""
    LFP = "lfp"  # Lithium Iron Phosphate
    NMC = "nmc"  # Nickel Manganese Cobalt
    NCA = "nca"  # Nickel Cobalt Aluminum
    LEAD_ACID = "lead_acid"


# Chemistry-specific default parameters
CHEMISTRY_PARAMS = {
    BatteryChemistry.LFP: {
        'round_trip_efficiency': 0.92,
        'calendar_degradation_per_year': 0.015,
        'cycle_degradation_per_cycle': 0.00005,
        'max_cycles': 6000,
        'typical_dod': 0.80,
    },
    BatteryChemistry.NMC: {
        'round_trip_efficiency': 0.90,
        'calendar_degradation_per_year': 0.02,
        'cycle_degradation_per_cycle': 0.0001,
        'max_cycles': 4000,
        'typical_dod': 0.80,
    },
    BatteryChemistry.NCA: {
        'round_trip_efficiency': 0.90,
        'calendar_degradation_per_year': 0.02,
        'cycle_degradation_per_cycle': 0.00012,
        'max_cycles': 3000,
        'typical_dod': 0.80,
    },
    BatteryChemistry.LEAD_ACID: {
        'round_trip_efficiency': 0.80,
        'calendar_degradation_per_year': 0.05,
        'cycle_degradation_per_cycle': 0.0005,
        'max_cycles': 1500,
        'typical_dod': 0.50,
    },
}


@dataclass
class BatteryConfig:
    """Configuration for a battery energy storage system."""
    
    # Capacity
    capacity_kwh: float = 100.0  # Energy capacity
    power_kw: float = 50.0  # Max charge/discharge power (C-rate derived)
    
    # Chemistry
    chemistry: BatteryChemistry = BatteryChemistry.LFP
    
    # Operating Limits
    min_soc: float = 0.10  # Minimum state of charge (10%)
    max_soc: float = 0.90  # Maximum state of charge (90%)
    initial_soc: float = 0.50  # Starting state of charge
    
    # Efficiency. None uses the square root of the chemistry round-trip value.
    charge_efficiency: Optional[float] = None
    discharge_efficiency: Optional[float] = None

    # Degradation. None uses the chemistry table.
    calendar_degradation_per_year: Optional[float] = None
    cycle_degradation_per_cycle: Optional[float] = None

    # Not applied. A non-zero value warns and is ignored.
    thermal_losses_pct: float = 0.0

    def __post_init__(self):
        """Fill missing efficiency and degradation from the chemistry table."""
        if not isinstance(self.chemistry, BatteryChemistry):
            raise SimulationInputError("chemistry must be a BatteryChemistry value")
        params = CHEMISTRY_PARAMS[self.chemistry]
        one_way = float(np.sqrt(params["round_trip_efficiency"]))
        if self.charge_efficiency is None:
            self.charge_efficiency = one_way
        if self.discharge_efficiency is None:
            self.discharge_efficiency = one_way
        if self.calendar_degradation_per_year is None:
            self.calendar_degradation_per_year = params["calendar_degradation_per_year"]
        if self.cycle_degradation_per_cycle is None:
            self.cycle_degradation_per_cycle = params["cycle_degradation_per_cycle"]
        self.capacity_kwh = require_positive("capacity_kwh", self.capacity_kwh)
        self.power_kw = require_positive("power_kw", self.power_kw)
        self.min_soc = require_in_range("min_soc", self.min_soc, 0.0, 1.0)
        self.max_soc = require_in_range("max_soc", self.max_soc, 0.0, 1.0)
        if self.min_soc >= self.max_soc:
            raise SimulationInputError("min_soc must be less than max_soc")
        self.initial_soc = require_in_range("initial_soc", self.initial_soc, self.min_soc, self.max_soc)
        self.charge_efficiency = require_in_range(
            "charge_efficiency", self.charge_efficiency, 0.0, 1.0, low_inclusive=False
        )
        self.discharge_efficiency = require_in_range(
            "discharge_efficiency", self.discharge_efficiency, 0.0, 1.0, low_inclusive=False
        )
        self.calendar_degradation_per_year = require_fraction(
            "calendar_degradation_per_year", self.calendar_degradation_per_year
        )
        self.cycle_degradation_per_cycle = require_non_negative(
            "cycle_degradation_per_cycle", self.cycle_degradation_per_cycle
        )
        self.thermal_losses_pct = require_non_negative("thermal_losses_pct", self.thermal_losses_pct)
    
    @property
    def round_trip_efficiency(self) -> float:
        """Calculate round-trip efficiency."""
        return self.charge_efficiency * self.discharge_efficiency
    
    @property
    def usable_capacity_kwh(self) -> float:
        """Usable capacity considering DoD limits."""
        return self.capacity_kwh * (self.max_soc - self.min_soc)
    
    @property
    def c_rate(self) -> float:
        """C-rate (power/capacity ratio)."""
        return self.power_kw / self.capacity_kwh if self.capacity_kwh > 0 else 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'capacity_kwh': self.capacity_kwh,
            'power_kw': self.power_kw,
            'chemistry': self.chemistry.value,
            'min_soc': self.min_soc,
            'max_soc': self.max_soc,
            'round_trip_efficiency': self.round_trip_efficiency,
        }


@dataclass
class BatterySizingResult(SizingResult):
    """Extended sizing result for batteries."""
    capacity_kwh: float = 0.0
    power_kw: float = 0.0
    duration_hours: float = 0.0
    sizing_method: str = ""
    rationale: str = ""


class BatteryStorage(BaseStorage):
    """
    Battery Energy Storage System simulator.
    
    Supports multiple dispatch strategies and sizing methods.
    
    Example:
        >>> config = BatteryConfig(capacity_kwh=1000, power_kw=500)
        >>> battery = BatteryStorage(config)
        >>> result = battery.simulate(generation, load, strategy='self_consumption')
    """
    
    def __init__(self, config: Optional[BatteryConfig] = None):
        super().__init__(name="Battery Storage")
        self.config = config or BatteryConfig()
        self._capacity_kwh = self.config.capacity_kwh
        self._power_kw = self.config.power_kw
        self.sizing: Optional[BatterySizingResult] = None
        self._simulation_results: Optional[pd.DataFrame] = None
        self._total_cycles: float = 0.0
        self._simulated_hours: float = 0.0
    
    @property
    def capacity_kwh(self) -> float:
        return self._capacity_kwh
    
    @property
    def power_kw(self) -> float:
        return self._power_kw
    
    def configure(self, **kwargs: Any) -> None:
        """Update configuration parameters."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self.config.__post_init__()
        self._capacity_kwh = self.config.capacity_kwh
        self._power_kw = self.config.power_kw
    
    def size_for_application(
        self,
        generation: pd.Series,
        load: pd.Series,
        target: str = "peak_shaving",
        **kwargs
    ) -> BatterySizingResult:
        """
        Size battery for a specific application.
        
        Sizing Methods:
        - peak_shaving: Size to reduce peak demand by target_reduction_pct
        - self_consumption: Size to maximize use of on-site generation
        - time_shifting: Size to store X hours of average generation
        - arbitrage: Size based on price spread and duration
        
        Args:
            generation: Time series of generation in kW.
            load: Time series of load in kW.
            target: Sizing target method.
            **kwargs: Additional parameters for sizing.
        """
        net_load = load - generation
        
        if target == "peak_shaving":
            # Size to shave peak by reduction percentage
            reduction_pct = kwargs.get('target_reduction_pct', 0.20)
            peak_load = load.max()
            target_peak = peak_load * (1 - reduction_pct)
            
            # Energy needed to shave peaks
            peaks_above_target = (load - target_peak).clip(lower=0)
            peak_hours = timestep_hours(peaks_above_target.index)
            peak_duration = float(peak_hours[peaks_above_target.to_numpy() > 0].sum())
            peak_energy = integrate_power_kwh(peaks_above_target)
            
            capacity_kwh = peak_energy * 1.2  # 20% margin
            power_kw = peaks_above_target.max() * 1.1
            duration = capacity_kwh / power_kw if power_kw > 0 else 4
            rationale = f"Sized to reduce {peak_load:.0f}kW peak by {reduction_pct:.0%}"
            
        elif target == "self_consumption":
            if not isinstance(generation.index, pd.DatetimeIndex):
                raise SimulationInputError("self_consumption sizing requires a DatetimeIndex")
            # Size based on excess generation that would be curtailed
            excess_gen = (-net_load).clip(lower=0)  # Negative net_load = excess gen
            
            # Find typical daily excess pattern
            excess_kwh = excess_gen * timestep_hours(excess_gen.index)
            daily_excess = excess_kwh.groupby(excess_gen.index.date).sum()
            avg_daily_excess = daily_excess.mean()
            max_hourly_excess = excess_gen.max()
            
            capacity_kwh = avg_daily_excess * 0.8  # Store 80% of daily excess
            power_kw = max_hourly_excess * 0.9
            duration = capacity_kwh / power_kw if power_kw > 0 else 4
            rationale = f"Sized to capture {avg_daily_excess:.0f}kWh daily excess"
            
        elif target == "time_shifting":
            # Size for X hours of storage at average generation
            hours = kwargs.get('hours', 4)
            avg_gen = generation.mean()
            
            capacity_kwh = avg_gen * hours
            power_kw = avg_gen * 1.2  # Size power for 1.2× average
            duration = hours
            rationale = f"Sized for {hours}h time-shifting at {avg_gen:.0f}kW avg gen"
            
        elif target == "arbitrage":
            # Size based on price spread duration
            hours = kwargs.get('hours', 4)
            power_mw = kwargs.get('power_mw', generation.max() / 1000)
            
            power_kw = power_mw * 1000
            capacity_kwh = power_kw * hours
            duration = hours
            rationale = (
                f"Duration set to {hours} h and power to {power_mw:.1f} MW. "
                "This method does not read electricity prices."
            )
            
        else:
            # Default: 4-hour storage at 25% of peak generation
            power_kw = generation.max() * 0.25
            capacity_kwh = power_kw * 4
            duration = 4
            rationale = "Default sizing: 4h at 25% peak generation"
        
        self.sizing = BatterySizingResult(
            capacity_kw=power_kw,
            capacity_kwh=capacity_kwh,
            power_kw=power_kw,
            duration_hours=duration,
            sizing_method=target,
            rationale=rationale,
        )
        
        # Update config
        self.config.capacity_kwh = capacity_kwh
        self.config.power_kw = power_kw
        self.config.__post_init__()
        self._capacity_kwh = self.config.capacity_kwh
        self._power_kw = self.config.power_kw
        
        return self.sizing
    
    def simulate(
        self,
        generation: pd.Series,
        load: pd.Series,
        dispatch_strategy: str = "self_consumption",
        grid_export_limit_kw: Optional[float] = None,
    ) -> pd.DataFrame:
        """
        Simulate battery operation over the time series.
        
        Dispatch Strategies:
        - self_consumption: Charge from excess, discharge to reduce imports
        - peak_shaving: Discharge during peaks, charge during off-peak
        - grid_export: Maximize grid export during high-price periods
        
        Returns:
            DataFrame with columns: soc, charge_kw, discharge_kw, 
            grid_import_kw, grid_export_kw, curtailment_kw
        """
        if dispatch_strategy not in {"self_consumption", "peak_shaving"}:
            raise SimulationInputError(
                f"Unsupported battery dispatch strategy '{dispatch_strategy}'. "
                "Supported strategies: self_consumption, peak_shaving."
            )
        if self.config.thermal_losses_pct != 0:
            warnings.warn(
                "thermal_losses_pct is not applied in the battery energy balance",
                UserWarning,
                stacklevel=2,
            )
        if len(generation) != len(load):
            raise SimulationInputError("generation and load must have the same length")
        if len(generation) < 1:
            raise SimulationInputError("generation must not be empty")

        n = len(generation)
        hours = timestep_hours(generation.index)
        net_load = load - generation  # Positive = import, Negative = export
        
        # Initialize arrays
        soc = np.zeros(n)  # State of charge (fraction) at the start of the step
        charge = np.zeros(n)  # Charging power (kW)
        discharge = np.zeros(n)  # Discharging power (kW)
        grid_import = np.zeros(n)
        grid_export = np.zeros(n)
        curtailment = np.zeros(n)
        
        soc[0] = self.config.initial_soc
        
        usable_min = self.config.min_soc * self.config.capacity_kwh
        usable_max = self.config.max_soc * self.config.capacity_kwh
        export_limit = grid_export_limit_kw
        
        for t in range(n):
            dt = float(hours[t])
            current_energy = soc[t] * self.config.capacity_kwh
            nl = net_load.iloc[t]
            
            if dispatch_strategy == "self_consumption":
                if nl > 0:
                    # Need to import - try to discharge
                    available_kwh = max(0.0, current_energy - usable_min)
                    max_from_energy = (
                        available_kwh * self.config.discharge_efficiency / dt if dt > 0 else 0.0
                    )
                    max_discharge = min(self.config.power_kw, max_from_energy, nl)
                    max_discharge = max(0, max_discharge)
                    
                    discharge[t] = max_discharge
                    remaining_import = nl - max_discharge
                    grid_import[t] = max(0, remaining_import)
                    
                else:
                    # Excess generation - try to charge
                    excess = -nl
                    room_kwh = max(0.0, usable_max - current_energy)
                    max_from_room = room_kwh / (self.config.charge_efficiency * dt) if dt > 0 else 0.0
                    max_charge = min(self.config.power_kw, max_from_room, excess)
                    max_charge = max(0, max_charge)
                    
                    charge[t] = max_charge
                    remaining_excess = excess - max_charge
                    if remaining_excess > 0:
                        grid_export[t] = remaining_excess
            
            elif dispatch_strategy == "peak_shaving":
                # Simplified: discharge when load > threshold, charge when low
                threshold = load.quantile(0.75)
                
                if load.iloc[t] > threshold:
                    # High demand - discharge
                    target_discharge = load.iloc[t] - threshold
                    available_kwh = max(0.0, current_energy - usable_min)
                    max_from_energy = (
                        available_kwh * self.config.discharge_efficiency / dt if dt > 0 else 0.0
                    )
                    max_discharge = min(self.config.power_kw, max_from_energy, target_discharge)
                    max_discharge = max(0, max_discharge)
                    discharge[t] = max_discharge
                    
                    net_need = nl - max_discharge
                    grid_import[t] = max(0, net_need)
                    grid_export[t] = max(0, -net_need)
                    
                elif load.iloc[t] < load.quantile(0.25):
                    # Low demand - charge from excess generation only, up to rated power.
                    available = max(0, -nl)
                    room_kwh = max(0.0, usable_max - current_energy)
                    max_from_room = room_kwh / (self.config.charge_efficiency * dt) if dt > 0 else 0.0
                    max_charge = min(self.config.power_kw, max_from_room, available)
                    max_charge = max(0, max_charge)
                    charge[t] = max_charge
                    
                    net_need = nl + max_charge
                    grid_import[t] = max(0, net_need)
                    grid_export[t] = max(0, -net_need)
                else:
                    grid_import[t] = max(0, nl)
                    grid_export[t] = max(0, -nl)

            if export_limit is not None and grid_export[t] > export_limit:
                curtailment[t] = grid_export[t] - export_limit
                grid_export[t] = export_limit
            
            # Update SOC for next timestep
            if t < n - 1:
                energy_change = (
                    charge[t] * self.config.charge_efficiency
                    - discharge[t] / self.config.discharge_efficiency
                ) * dt
                new_energy = current_energy + energy_change
                new_energy = np.clip(new_energy, usable_min, usable_max)
                soc[t + 1] = new_energy / self.config.capacity_kwh
        
        charge_kwh = float(np.sum(charge * hours))
        discharge_kwh = float(np.sum(discharge * hours))
        total_throughput = (charge_kwh + discharge_kwh) / 2
        self._total_cycles = total_throughput / self.config.usable_capacity_kwh
        self._simulated_hours = float(np.sum(hours))
        
        self._simulation_results = pd.DataFrame({
            'soc': soc,
            'charge_kw': charge,
            'discharge_kw': discharge,
            'grid_import_kw': grid_import,
            'grid_export_kw': grid_export,
            'curtailment_kw': curtailment,
            'net_load_kw': net_load.values,
        }, index=generation.index)
        
        return self._simulation_results
    
    def get_degradation(self, years: int = 1) -> float:
        """
        Calculate remaining capacity after degradation.
        
        Combines calendar and cycle degradation.
        """
        # Calendar degradation
        calendar_factor = (1 - self.config.calendar_degradation_per_year) ** years

        # Cycle count from simulate() is for the simulated series, not per year.
        simulated_hours = getattr(self, "_simulated_hours", 0.0)
        if self._total_cycles > 0 and simulated_hours > 0:
            cycles_per_year = self._total_cycles / (simulated_hours / 8760.0)
            total_cycles = cycles_per_year * years
            cycle_factor = 1 - (total_cycles * self.config.cycle_degradation_per_cycle)
            cycle_factor = min(1.0, max(0.0, cycle_factor))
        else:
            cycle_factor = 1.0

        return calendar_factor * cycle_factor
    
    def get_kpis(self) -> Dict[str, float]:
        """Calculate battery performance KPIs."""
        if self._simulation_results is None:
            return {}
        
        df = self._simulation_results
        
        total_charged = integrate_power_kwh(df["charge_kw"])
        total_discharged = integrate_power_kwh(df["discharge_kw"])
        
        return {
            'capacity_kwh': self.config.capacity_kwh,
            'power_kw': self.config.power_kw,
            'duration_hours': self.config.capacity_kwh / self.config.power_kw,
            'round_trip_efficiency': self.config.round_trip_efficiency,
            'total_charged_kwh': total_charged,
            'total_discharged_kwh': total_discharged,
            'equivalent_cycles': self._total_cycles,
            'avg_soc': df['soc'].mean(),
            'utilization_pct': (
                total_discharged / (self.config.usable_capacity_kwh * self._simulated_hours) * 100
                if self._simulated_hours > 0
                else 0.0
            ),
        }
