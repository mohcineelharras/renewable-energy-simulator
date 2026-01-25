"""
Battery Energy Storage System (BESS) Module.

Professional-grade battery storage simulation with:
- Multiple sizing strategies (peak shaving, arbitrage, self-consumption)
- State of charge tracking with efficiency
- Calendar and cycle degradation modeling
- C-rate and DoD constraints
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

from simulator.core.base import BaseStorage
from simulator.core.types import SizingResult


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
    
    # Efficiency
    charge_efficiency: float = 0.96  # One-way charging efficiency
    discharge_efficiency: float = 0.96  # One-way discharging efficiency
    
    # Degradation
    calendar_degradation_per_year: float = 0.015  # 1.5%/year
    cycle_degradation_per_cycle: float = 0.00005  # Per full cycle
    
    # Thermal (simplified)
    thermal_losses_pct: float = 0.02  # 2% thermal losses
    
    def __post_init__(self):
        """Apply chemistry-specific defaults if not overridden."""
        if self.chemistry in CHEMISTRY_PARAMS:
            params = CHEMISTRY_PARAMS[self.chemistry]
            # Only apply if using default values
            if self.charge_efficiency == 0.96:
                rte = params['round_trip_efficiency']
                self.charge_efficiency = np.sqrt(rte)
                self.discharge_efficiency = np.sqrt(rte)
    
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
            peak_duration = (peaks_above_target > 0).sum()  # hours
            peak_energy = peaks_above_target.sum()  # kWh
            
            capacity_kwh = peak_energy * 1.2  # 20% margin
            power_kw = peaks_above_target.max() * 1.1
            duration = capacity_kwh / power_kw if power_kw > 0 else 4
            rationale = f"Sized to reduce {peak_load:.0f}kW peak by {reduction_pct:.0%}"
            
        elif target == "self_consumption":
            # Size based on excess generation that would be curtailed
            excess_gen = (-net_load).clip(lower=0)  # Negative net_load = excess gen
            
            # Find typical daily excess pattern
            daily_excess = excess_gen.groupby(excess_gen.index.date).sum()
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
            rationale = f"Sized for {hours}h arbitrage at {power_mw:.1f}MW"
            
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
        self._capacity_kwh = capacity_kwh
        self._power_kw = power_kw
        
        return self.sizing
    
    def simulate(
        self,
        generation: pd.Series,
        load: pd.Series,
        dispatch_strategy: str = "self_consumption"
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
        n = len(generation)
        net_load = load - generation  # Positive = import, Negative = export
        
        # Initialize arrays
        soc = np.zeros(n)  # State of charge (fraction)
        charge = np.zeros(n)  # Charging power (kW)
        discharge = np.zeros(n)  # Discharging power (kW)
        grid_import = np.zeros(n)
        grid_export = np.zeros(n)
        curtailment = np.zeros(n)
        
        soc[0] = self.config.initial_soc
        
        usable_min = self.config.min_soc * self.config.capacity_kwh
        usable_max = self.config.max_soc * self.config.capacity_kwh
        
        for t in range(n):
            current_energy = soc[t] * self.config.capacity_kwh
            nl = net_load.iloc[t]
            
            if dispatch_strategy == "self_consumption":
                if nl > 0:
                    # Need to import - try to discharge
                    max_discharge = min(
                        self.config.power_kw,
                        (current_energy - usable_min) * self.config.discharge_efficiency,
                        nl
                    )
                    max_discharge = max(0, max_discharge)
                    
                    discharge[t] = max_discharge
                    remaining_import = nl - max_discharge
                    grid_import[t] = max(0, remaining_import)
                    
                else:
                    # Excess generation - try to charge
                    excess = -nl
                    max_charge = min(
                        self.config.power_kw,
                        (usable_max - current_energy) / self.config.charge_efficiency,
                        excess
                    )
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
                    max_discharge = min(
                        self.config.power_kw,
                        (current_energy - usable_min) * self.config.discharge_efficiency,
                        target_discharge
                    )
                    max_discharge = max(0, max_discharge)
                    discharge[t] = max_discharge
                    
                    net_need = nl - max_discharge
                    grid_import[t] = max(0, net_need)
                    grid_export[t] = max(0, -net_need)
                    
                elif load.iloc[t] < load.quantile(0.25):
                    # Low demand - charge from grid if cheap, or from excess gen
                    available = max(0, -nl) + self.config.power_kw * 0.5  # Limit grid charging
                    max_charge = min(
                        self.config.power_kw,
                        (usable_max - current_energy) / self.config.charge_efficiency,
                        available
                    )
                    max_charge = max(0, max_charge)
                    charge[t] = max_charge
                    
                    net_need = nl + max_charge
                    grid_import[t] = max(0, net_need)
                    grid_export[t] = max(0, -net_need)
                else:
                    grid_import[t] = max(0, nl)
                    grid_export[t] = max(0, -nl)
            
            else:  # Default similar to self_consumption
                if nl > 0:
                    grid_import[t] = nl
                else:
                    grid_export[t] = -nl
            
            # Update SOC for next timestep
            if t < n - 1:
                energy_change = (
                    charge[t] * self.config.charge_efficiency - 
                    discharge[t] / self.config.discharge_efficiency
                )
                new_energy = current_energy + energy_change
                new_energy = np.clip(new_energy, usable_min, usable_max)
                soc[t + 1] = new_energy / self.config.capacity_kwh
        
        # Calculate cycles
        total_throughput = (charge.sum() + discharge.sum()) / 2  # kWh
        self._total_cycles = total_throughput / self.config.usable_capacity_kwh
        
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
        
        # Cycle degradation (if simulation was run)
        if self._total_cycles > 0:
            cycles_per_year = self._total_cycles
            total_cycles = cycles_per_year * years
            cycle_factor = 1 - (total_cycles * self.config.cycle_degradation_per_cycle)
            cycle_factor = max(0.5, cycle_factor)  # Minimum 50% capacity
        else:
            cycle_factor = 1.0
        
        return calendar_factor * cycle_factor
    
    def get_kpis(self) -> Dict[str, float]:
        """Calculate battery performance KPIs."""
        if self._simulation_results is None:
            return {}
        
        df = self._simulation_results
        
        total_charged = df['charge_kw'].sum()
        total_discharged = df['discharge_kw'].sum()
        
        return {
            'capacity_kwh': self.config.capacity_kwh,
            'power_kw': self.config.power_kw,
            'duration_hours': self.config.capacity_kwh / self.config.power_kw,
            'round_trip_efficiency': self.config.round_trip_efficiency,
            'total_charged_kwh': total_charged,
            'total_discharged_kwh': total_discharged,
            'equivalent_cycles': self._total_cycles,
            'avg_soc': df['soc'].mean(),
            'utilization_pct': (total_discharged / (self.config.usable_capacity_kwh * len(df))) * 100,
        }
