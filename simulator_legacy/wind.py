"""
Professional Wind Farm Simulation Module
Based on industry benchmarks for utility-scale onshore wind projects.
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Optional, List
import math

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

# Common turbine models
TURBINE_LIBRARY = {
    "Vestas V150-4.2": WindTurbineSpec("Vestas V150-4.2", 4200, 150, 105),
    "Siemens SG 5.0-145": WindTurbineSpec("Siemens SG 5.0-145", 5000, 145, 102.5),
    "GE 3.4-137": WindTurbineSpec("GE 3.4-137", 3400, 137, 110),
    "Nordex N163-5.X": WindTurbineSpec("Nordex N163-5.X", 5700, 163, 118),
    "Generic 3MW": WindTurbineSpec("Generic 3MW", 3000, 120, 100),
}

@dataclass
class WindSystemConfig:
    """Configuration for a utility-scale wind farm."""
    # Site Parameters
    land_area_ha: float  # hectares
    latitude: float
    longitude: float
    grid_limit_mw: float  # MW
    
    # Turbine Selection
    turbine_spec: WindTurbineSpec = field(default_factory=lambda: TURBINE_LIBRARY["Generic 3MW"])
    
    # Spacing Rules (in Rotor Diameters)
    spacing_in_row_rd: float = 4.0  # 3-5 RD
    spacing_between_rows_rd: float = 7.0  # 5-9 RD
    
    # Loss Parameters (defaults based on industry benchmarks)
    loss_wake: float = 0.10  # 8-15%
    loss_availability: float = 0.03  # 95-98% availability
    loss_electrical: float = 0.02  # MV/HV collection
    loss_performance: float = 0.015  # Power curve deviations
    loss_environmental: float = 0.02  # Icing, temp, high-wind cutouts
    loss_grid: float = 0.01  # Grid curtailment/downtime
    
    # Degradation (blade erosion, mechanical wear)
    annual_degradation: float = 0.008  # 0.8%/year

@dataclass
class WindSizingResult:
    """Results of the auto-sizing calculation."""
    land_area_m2: float
    num_turbines: int
    total_capacity_mw: float
    grid_constrained: bool
    spacing_in_row_m: float
    spacing_between_rows_m: float
    turbines_per_row: int
    num_rows: int

@dataclass
class LossWaterfallItem:
    """Single item in the loss waterfall."""
    stage: str
    input_energy: float
    loss_percent: float
    loss_energy: float
    output_energy: float

class WindSimulator:
    """Professional-grade utility-scale wind farm simulator."""
    
    def __init__(self, config: WindSystemConfig):
        self.config = config
        self.sizing_result: Optional[WindSizingResult] = None
        self.loss_waterfall: list = []
        self.hourly_results: Optional[pd.DataFrame] = None
        self.annual_results: Optional[pd.DataFrame] = None
    
    def auto_size(self) -> WindSizingResult:
        """
        Calculate number of turbines from land area using spacing rules.
        Spacing in-row: 3-5 × Rotor Diameter
        Spacing between rows: 5-9 × Rotor Diameter
        """
        land_area_m2 = self.config.land_area_ha * 10000
        rd = self.config.turbine_spec.rotor_diameter_m
        
        # Spacing in meters
        spacing_in_row_m = self.config.spacing_in_row_rd * rd
        spacing_between_rows_m = self.config.spacing_between_rows_rd * rd
        
        # Footprint per turbine
        turbine_footprint_m2 = spacing_in_row_m * spacing_between_rows_m
        
        # Maximum turbines that fit
        max_turbines = int(land_area_m2 / turbine_footprint_m2)
        
        # Grid constraint
        turbine_power_mw = self.config.turbine_spec.rated_power_kw / 1000
        turbines_for_grid = int(self.config.grid_limit_mw / turbine_power_mw)
        
        # Final turbine count
        num_turbines = min(max_turbines, turbines_for_grid)
        grid_constrained = turbines_for_grid < max_turbines
        
        # Total capacity
        total_capacity_mw = num_turbines * turbine_power_mw
        
        # Estimate layout (simplified rectangular grid)
        land_side = math.sqrt(land_area_m2)
        turbines_per_row = max(1, int(land_side / spacing_in_row_m))
        num_rows = max(1, int(num_turbines / turbines_per_row))
        
        self.sizing_result = WindSizingResult(
            land_area_m2=land_area_m2,
            num_turbines=num_turbines,
            total_capacity_mw=total_capacity_mw,
            grid_constrained=grid_constrained,
            spacing_in_row_m=spacing_in_row_m,
            spacing_between_rows_m=spacing_between_rows_m,
            turbines_per_row=turbines_per_row,
            num_rows=num_rows
        )
        return self.sizing_result
    
    def _power_curve(self, wind_speed: float) -> float:
        """
        Calculate power output from wind speed using idealized power curve.
        P = 0 if v < v_in or v > v_out
        P = P_rated × ((v - v_in) / (v_rated - v_in))^3 if v_in <= v < v_rated
        P = P_rated if v_rated <= v <= v_out
        """
        v = wind_speed
        v_in = self.config.turbine_spec.cut_in_speed
        v_rated = self.config.turbine_spec.rated_speed
        v_out = self.config.turbine_spec.cut_out_speed
        p_rated = self.config.turbine_spec.rated_power_kw
        
        if v < v_in or v > v_out:
            return 0.0
        elif v >= v_rated:
            return p_rated
        else:
            return p_rated * ((v - v_in) / (v_rated - v_in)) ** 3
    
    def simulate_year_one(self, weather_data: pd.DataFrame) -> pd.DataFrame:
        """
        Simulate one year of hourly production.
        weather_data: DataFrame with columns ['wind_speed', 'temperature', 'pressure']
                      wind_speed at measurement height (typically 10m)
        """
        if self.sizing_result is None:
            self.auto_size()
        
        # Scale wind speed to hub height using power law
        # v_hub = v_measured × (h_hub / h_measured)^alpha
        alpha = 0.14  # Roughness exponent for open terrain
        h_measured = 10.0  # Standard measurement height
        h_hub = self.config.turbine_spec.hub_height_m
        
        v_hub = weather_data['wind_speed'] * (h_hub / h_measured) ** alpha
        
        # Air density correction (optional, simplified)
        # rho = P / (R × T) where R = 287 J/(kg·K)
        if 'pressure' in weather_data.columns and 'temperature' in weather_data.columns:
            pressure_pa = weather_data['pressure'] * 100  # hPa to Pa
            temp_k = weather_data['temperature'] + 273.15
            rho = pressure_pa / (287 * temp_k)
            rho_ratio = rho / 1.225  # Standard air density
        else:
            rho_ratio = pd.Series(1.0, index=weather_data.index)
        
        # Gross power per turbine
        gross_power_per_turbine = v_hub.apply(self._power_curve) * rho_ratio
        gross_power_per_turbine = gross_power_per_turbine.clip(lower=0)
        
        # Total gross power (all turbines)
        gross_power_kw = gross_power_per_turbine * self.sizing_result.num_turbines
        
        # Build loss waterfall
        self.loss_waterfall = self._compute_loss_waterfall(gross_power_kw)
        
        # Apply losses sequentially
        net_power = gross_power_kw.copy()
        net_power = net_power * (1 - self.config.loss_wake)
        net_power = net_power * (1 - self.config.loss_availability)
        net_power = net_power * (1 - self.config.loss_electrical)
        net_power = net_power * (1 - self.config.loss_performance)
        net_power = net_power * (1 - self.config.loss_environmental)
        net_power = net_power * (1 - self.config.loss_grid)
        
        self.hourly_results = pd.DataFrame({
            'wind_speed_hub': v_hub,
            'gross_power_kw': gross_power_kw,
            'net_power_kw': net_power
        }, index=weather_data.index)
        
        return self.hourly_results
    
    def _compute_loss_waterfall(self, gross_power: pd.Series) -> list:
        """Compute the 6-stage loss waterfall."""
        total_gross = gross_power.sum()
        
        stages = [
            ("Wake Effects", self.config.loss_wake),
            ("Turbine Availability", self.config.loss_availability),
            ("Electrical Collection", self.config.loss_electrical),
            ("Turbine Performance", self.config.loss_performance),
            ("Environmental", self.config.loss_environmental),
            ("Grid Availability", self.config.loss_grid),
        ]
        
        waterfall = []
        current_energy = total_gross
        
        for stage_name, loss_pct in stages:
            loss_energy = current_energy * loss_pct
            output_energy = current_energy - loss_energy
            waterfall.append(LossWaterfallItem(
                stage=stage_name,
                input_energy=current_energy,
                loss_percent=loss_pct,
                loss_energy=loss_energy,
                output_energy=output_energy
            ))
            current_energy = output_energy
        
        return waterfall
    
    def run_lifecycle(self, weather_data: pd.DataFrame, years: int = 30) -> pd.DataFrame:
        """Run 30-year simulation with degradation."""
        if self.hourly_results is None:
            self.simulate_year_one(weather_data)
        
        base_annual_kwh = self.hourly_results['net_power_kw'].sum()
        
        results = []
        for year in range(1, years + 1):
            degradation_factor = (1 - self.config.annual_degradation) ** (year - 1)
            annual_kwh = base_annual_kwh * degradation_factor
            annual_mwh = annual_kwh / 1000.0
            
            results.append({
                'Year': year,
                'Degradation Factor': degradation_factor,
                'Annual Energy (MWh)': annual_mwh,
                'Cumulative Energy (MWh)': sum([r['Annual Energy (MWh)'] for r in results]) + annual_mwh
            })
        
        self.annual_results = pd.DataFrame(results)
        return self.annual_results
    
    def get_loss_summary(self) -> Dict[str, float]:
        """Get summary of all losses as percentages."""
        return {item.stage: item.loss_percent * 100 for item in self.loss_waterfall}
    
    def get_kpis(self) -> Dict[str, float]:
        """Calculate key performance indicators."""
        if self.hourly_results is None or self.sizing_result is None:
            return {}
        
        annual_kwh = self.hourly_results['net_power_kw'].sum()
        annual_mwh = annual_kwh / 1000.0
        gross_kwh = self.hourly_results['gross_power_kw'].sum()
        
        total_capacity_kw = self.sizing_result.total_capacity_mw * 1000
        capacity_factor = annual_kwh / (total_capacity_kw * 8760) if total_capacity_kw > 0 else 0
        full_load_hours = annual_kwh / total_capacity_kw if total_capacity_kw > 0 else 0
        
        total_loss = 1 - (annual_kwh / gross_kwh) if gross_kwh > 0 else 0
        
        avg_wind_speed = self.hourly_results['wind_speed_hub'].mean()
        
        return {
            'Total Capacity (MW)': self.sizing_result.total_capacity_mw,
            'Number of Turbines': self.sizing_result.num_turbines,
            'Turbine Model': self.config.turbine_spec.name,
            'Annual Energy (MWh)': annual_mwh,
            'Capacity Factor (%)': capacity_factor * 100,
            'Full Load Hours': full_load_hours,
            'Total Losses (%)': total_loss * 100,
            'Avg Hub Wind Speed (m/s)': avg_wind_speed,
            'Grid Constrained': self.sizing_result.grid_constrained
        }
