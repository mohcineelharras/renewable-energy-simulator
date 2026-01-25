"""
Wind Generator Module - WindPro-style simulation.

Professional-grade utility-scale wind farm simulation with:
- Turbine library with power curves
- Auto-sizing based on land and spacing rules
- 6-stage loss waterfall
- Multi-year degradation modeling
"""

import pandas as pd
import numpy as np
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from simulator.core.base import BaseGenerator
from simulator.core.types import SimulationResult, SizingResult, LossItem
from simulator.core.losses import LossWaterfall


@dataclass
class WindTurbineSpec:
    """Specification for a wind turbine model."""
    name: str
    rated_power_kw: float
    rotor_diameter_m: float
    hub_height_m: float
    cut_in_speed: float = 3.0  # m/s
    rated_speed: float = 12.0  # m/s
    cut_out_speed: float = 25.0  # m/s
    
    def power_curve(self, wind_speed: float) -> float:
        """
        Calculate power output from wind speed using idealized cubic power curve.
        
        P = 0 if v < v_in or v > v_out
        P = P_rated × ((v - v_in) / (v_rated - v_in))^3 if v_in <= v < v_rated
        P = P_rated if v_rated <= v <= v_out
        """
        v = wind_speed
        if v < self.cut_in_speed or v > self.cut_out_speed:
            return 0.0
        elif v >= self.rated_speed:
            return self.rated_power_kw
        else:
            return self.rated_power_kw * ((v - self.cut_in_speed) / (self.rated_speed - self.cut_in_speed)) ** 3
    
    def power_curve_vectorized(self, wind_speeds: pd.Series) -> pd.Series:
        """Vectorized version of power curve calculation."""
        power = pd.Series(0.0, index=wind_speeds.index)
        
        # Below rated
        mask_partial = (wind_speeds >= self.cut_in_speed) & (wind_speeds < self.rated_speed)
        power[mask_partial] = self.rated_power_kw * (
            (wind_speeds[mask_partial] - self.cut_in_speed) / 
            (self.rated_speed - self.cut_in_speed)
        ) ** 3
        
        # At or above rated
        mask_rated = (wind_speeds >= self.rated_speed) & (wind_speeds <= self.cut_out_speed)
        power[mask_rated] = self.rated_power_kw
        
        return power


# Common turbine library
TURBINE_LIBRARY: Dict[str, WindTurbineSpec] = {
    "Vestas V150-4.2": WindTurbineSpec("Vestas V150-4.2", 4200, 150, 105),
    "Vestas V162-6.2": WindTurbineSpec("Vestas V162-6.2", 6200, 162, 119),
    "Siemens SG 5.0-145": WindTurbineSpec("Siemens SG 5.0-145", 5000, 145, 102.5),
    "Siemens SG 6.6-170": WindTurbineSpec("Siemens SG 6.6-170", 6600, 170, 115),
    "GE 3.4-137": WindTurbineSpec("GE 3.4-137", 3400, 137, 110),
    "GE Cypress 5.3-158": WindTurbineSpec("GE Cypress 5.3-158", 5300, 158, 101),
    "Nordex N163-5.X": WindTurbineSpec("Nordex N163-5.X", 5700, 163, 118),
    "Goldwind GW155-4.5": WindTurbineSpec("Goldwind GW155-4.5", 4500, 155, 100),
    "Generic 3MW": WindTurbineSpec("Generic 3MW", 3000, 120, 100),
    "Generic 5MW": WindTurbineSpec("Generic 5MW", 5000, 150, 110),
}


@dataclass
class WindConfig:
    """Configuration for a utility-scale wind farm."""
    
    # Site Parameters
    latitude: float = 0.0
    longitude: float = 0.0
    
    # Land/Sizing
    land_area_ha: float = 500.0
    grid_limit_mw: float = 50.0
    
    # Turbine Selection
    turbine_model: str = "Generic 3MW"
    
    # Spacing Rules (in Rotor Diameters)
    spacing_in_row_rd: float = 4.0  # 3-5 RD
    spacing_between_rows_rd: float = 7.0  # 5-9 RD
    
    # Loss Parameters
    loss_wake: float = 0.10  # 8-15%
    loss_availability: float = 0.03
    loss_electrical: float = 0.02
    loss_performance: float = 0.015
    loss_environmental: float = 0.02
    loss_grid: float = 0.01
    
    # Wind shear
    roughness_length: float = 0.03  # m (open terrain)
    measurement_height: float = 10.0  # m
    
    # Degradation
    annual_degradation: float = 0.008  # 0.8%/year
    
    @property
    def turbine(self) -> WindTurbineSpec:
        """Get the selected turbine specification."""
        return TURBINE_LIBRARY.get(self.turbine_model, TURBINE_LIBRARY["Generic 3MW"])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'land_area_ha': self.land_area_ha,
            'grid_limit_mw': self.grid_limit_mw,
            'turbine_model': self.turbine_model,
            'spacing_in_row_rd': self.spacing_in_row_rd,
            'spacing_between_rows_rd': self.spacing_between_rows_rd,
            'annual_degradation': self.annual_degradation,
        }


@dataclass
class WindSizingResult(SizingResult):
    """Extended sizing result for wind farms."""
    total_capacity_mw: float = 0.0
    num_turbines: int = 0
    turbine_model: str = ""
    spacing_in_row_m: float = 0.0
    spacing_between_rows_m: float = 0.0


class WindGenerator(BaseGenerator):
    """
    Professional-grade utility-scale wind farm generator.
    
    Implements the Generator protocol with WindPro-style simulation.
    
    Example:
        >>> config = WindConfig(latitude=35.0, longitude=-5.0, land_area_ha=500)
        >>> gen = WindGenerator(config)
        >>> sizing = gen.auto_size()
        >>> result = gen.simulate(weather_data, years=30)
    """
    
    def __init__(self, config: Optional[WindConfig] = None):
        super().__init__(name="Wind Farm")
        self.config = config or WindConfig()
        self.sizing: Optional[WindSizingResult] = None
        self._waterfall: Optional[LossWaterfall] = None
    
    @property
    def capacity_kw(self) -> float:
        if self.sizing:
            return self.sizing.total_capacity_mw * 1000
        return 0.0
    
    def configure(self, **kwargs: Any) -> None:
        """Update configuration parameters."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
    
    def auto_size(self, constraints: Optional[Dict[str, Any]] = None) -> WindSizingResult:
        """
        Calculate number of turbines from land area using spacing rules.
        
        Spacing in-row: 3-5 × Rotor Diameter
        Spacing between rows: 5-9 × Rotor Diameter
        """
        if constraints:
            for key, value in constraints.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)
        
        turbine = self.config.turbine
        land_area_m2 = self.config.land_area_ha * 10000
        rd = turbine.rotor_diameter_m
        
        # Spacing in meters
        spacing_in_row_m = self.config.spacing_in_row_rd * rd
        spacing_between_rows_m = self.config.spacing_between_rows_rd * rd
        
        # Footprint per turbine
        turbine_footprint_m2 = spacing_in_row_m * spacing_between_rows_m
        
        # Maximum turbines that fit
        max_turbines = int(land_area_m2 / turbine_footprint_m2)
        
        # Grid constraint
        turbine_power_mw = turbine.rated_power_kw / 1000
        turbines_for_grid = int(self.config.grid_limit_mw / turbine_power_mw)
        
        # Final turbine count
        num_turbines = min(max_turbines, turbines_for_grid)
        num_turbines = max(1, num_turbines)  # At least 1 turbine
        grid_constrained = turbines_for_grid < max_turbines
        
        # Total capacity
        total_capacity_mw = num_turbines * turbine_power_mw
        
        self.sizing = WindSizingResult(
            capacity_kw=total_capacity_mw * 1000,
            area_m2=land_area_m2,
            num_units=num_turbines,
            grid_constrained=grid_constrained,
            total_capacity_mw=total_capacity_mw,
            num_turbines=num_turbines,
            turbine_model=self.config.turbine_model,
            spacing_in_row_m=spacing_in_row_m,
            spacing_between_rows_m=spacing_between_rows_m,
        )
        
        self._capacity_kw = total_capacity_mw * 1000
        return self.sizing
    
    def _simulate_year_one(self, weather: pd.DataFrame) -> pd.DataFrame:
        """
        Simulate one year of hourly production.
        
        Args:
            weather: DataFrame with columns ['wind_speed'] at measurement height,
                     optionally ['temperature', 'pressure'] for air density correction.
        """
        if self.sizing is None:
            self.auto_size()
        
        turbine = self.config.turbine
        
        # Scale wind speed to hub height using power law
        # v_hub = v_measured × (h_hub / h_measured)^alpha
        # alpha ≈ ln(z/z0) relationship
        alpha = 1 / np.log(turbine.hub_height_m / self.config.roughness_length)
        alpha = np.clip(alpha, 0.10, 0.25)  # Typical range
        
        h_hub = turbine.hub_height_m
        h_measured = self.config.measurement_height
        
        v_hub = weather['wind_speed'] * (h_hub / h_measured) ** alpha
        
        # Air density correction
        if 'pressure' in weather.columns and 'temperature' in weather.columns:
            pressure_pa = weather['pressure'] * 100  # hPa to Pa
            temp_k = weather['temperature'] + 273.15
            rho = pressure_pa / (287 * temp_k)
            rho_ratio = rho / 1.225  # Standard air density
        else:
            rho_ratio = pd.Series(1.0, index=weather.index)
        
        # Gross power per turbine
        gross_power_per_turbine = turbine.power_curve_vectorized(v_hub) * rho_ratio
        gross_power_per_turbine = gross_power_per_turbine.clip(lower=0)
        
        # Total gross power (all turbines)
        gross_power_kw = gross_power_per_turbine * self.sizing.num_turbines
        
        # Apply losses
        net_power = gross_power_kw.copy()
        net_power *= (1 - self.config.loss_wake)
        net_power *= (1 - self.config.loss_availability)
        net_power *= (1 - self.config.loss_electrical)
        net_power *= (1 - self.config.loss_performance)
        net_power *= (1 - self.config.loss_environmental)
        net_power *= (1 - self.config.loss_grid)
        
        # Build loss waterfall
        self._build_waterfall(gross_power_kw.sum())
        
        self._hourly_results = pd.DataFrame({
            'wind_speed_hub': v_hub,
            'gross_power_kw': gross_power_kw,
            'power_kw': net_power,
        }, index=weather.index)
        
        return self._hourly_results
    
    def _build_waterfall(self, gross_energy: float) -> None:
        """Build the loss waterfall from simulation."""
        self._waterfall = LossWaterfall(gross_energy)
        
        losses = [
            ("Wake Effects", self.config.loss_wake),
            ("Turbine Availability", self.config.loss_availability),
            ("Electrical Collection", self.config.loss_electrical),
            ("Turbine Performance", self.config.loss_performance),
            ("Environmental", self.config.loss_environmental),
            ("Grid Curtailment", self.config.loss_grid),
        ]
        
        self._waterfall.add_losses(losses)
        self._losses = self._waterfall.get_losses()
    
    def simulate(self, weather: pd.DataFrame, years: int = 30) -> SimulationResult:
        """Run multi-year simulation with degradation."""
        if self._hourly_results is None:
            self._simulate_year_one(weather)
        
        base_annual_kwh = self._hourly_results['power_kw'].sum()
        
        annual_data = []
        cumulative = 0.0
        for year in range(1, years + 1):
            factor = (1 - self.config.annual_degradation) ** (year - 1)
            annual_kwh = base_annual_kwh * factor
            annual_mwh = annual_kwh / 1000
            cumulative += annual_mwh
            
            annual_data.append({
                'year': year,
                'degradation_factor': factor,
                'energy_kwh': annual_kwh,
                'energy_mwh': annual_mwh,
                'cumulative_mwh': cumulative,
            })
        
        self._annual_results = pd.DataFrame(annual_data)
        
        return SimulationResult(
            hourly=self._hourly_results,
            annual=self._annual_results,
            kpis=self.get_kpis(),
            losses=self.get_losses(),
            metadata={
                'config': self.config.to_dict(),
                'sizing': {
                    'total_capacity_mw': self.sizing.total_capacity_mw,
                    'num_turbines': self.sizing.num_turbines,
                    'turbine_model': self.sizing.turbine_model,
                }
            }
        )
    
    def get_losses(self) -> List[LossItem]:
        """Get loss waterfall items."""
        return self._losses if self._losses else []
    
    def get_kpis(self) -> Dict[str, float]:
        """Calculate key performance indicators."""
        if self._hourly_results is None or self.sizing is None:
            return {}
        
        annual_kwh = self._hourly_results['power_kw'].sum()
        annual_mwh = annual_kwh / 1000.0
        gross_kwh = self._hourly_results['gross_power_kw'].sum()
        
        total_capacity_kw = self.sizing.total_capacity_mw * 1000
        capacity_factor = annual_kwh / (total_capacity_kw * 8760) if total_capacity_kw > 0 else 0
        full_load_hours = annual_kwh / total_capacity_kw if total_capacity_kw > 0 else 0
        
        total_loss = 1 - (annual_kwh / gross_kwh) if gross_kwh > 0 else 0
        
        avg_wind_speed = self._hourly_results['wind_speed_hub'].mean()
        
        return {
            'total_capacity_mw': self.sizing.total_capacity_mw,
            'num_turbines': self.sizing.num_turbines,
            'turbine_model': self.config.turbine_model,
            'annual_energy_mwh': annual_mwh,
            'capacity_factor_pct': capacity_factor * 100,
            'full_load_hours': full_load_hours,
            'total_losses_pct': total_loss * 100,
            'avg_hub_wind_speed_ms': avg_wind_speed,
            'grid_constrained': self.sizing.grid_constrained,
        }
