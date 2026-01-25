"""
Professional Solar PV Simulation Module
Based on industry benchmarks for utility-scale projects.
"""
import pvlib
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional

@dataclass
class PVSystemConfig:
    """Configuration for a utility-scale PV system."""
    # Site Parameters
    land_area_ha: float  # hectares
    latitude: float
    longitude: float
    grid_limit_mw: float  # MW (AC)
    
    # Module Parameters
    module_power_wp: float = 580  # Wp (TOPCon/HJT standard)
    module_efficiency: float = 0.215  # 21.5%
    temp_coefficient: float = -0.0035  # %/°C
    
    # System Design
    gcr: float = 0.40  # Ground Coverage Ratio (0.30-0.45)
    ilr: float = 1.30  # Inverter Loading Ratio (1.2-1.4)
    tilt: float = 25.0  # degrees (can be optimized for latitude)
    azimuth: float = 180.0  # South-facing
    
    # Loss Parameters (defaults based on industry benchmarks)
    loss_near_shading: float = 0.02
    loss_soiling: float = 0.05  # Higher in arid regions (0.10-0.15)
    loss_iam: float = 0.03
    loss_spectral: float = 0.01
    loss_dc_wiring: float = 0.02
    loss_mismatch: float = 0.015
    loss_inverter_efficiency: float = 0.02
    loss_transformer: float = 0.015
    loss_ac_collection: float = 0.01
    loss_availability: float = 0.01
    
    # Degradation
    annual_degradation: float = 0.005  # 0.5%/year

@dataclass
class PVSizingResult:
    """Results of the auto-sizing calculation."""
    land_area_m2: float
    dc_capacity_kwp: float
    ac_capacity_kw: float
    actual_ilr: float
    num_modules: int
    specific_area_m2_per_kwp: float

@dataclass
class LossWaterfallItem:
    """Single item in the loss waterfall."""
    stage: str
    input_energy: float
    loss_percent: float
    loss_energy: float
    output_energy: float

class PVSimulator:
    """Professional-grade utility-scale PV simulator."""
    
    def __init__(self, config: PVSystemConfig):
        self.config = config
        self.location = pvlib.location.Location(config.latitude, config.longitude)
        self.sizing_result: Optional[PVSizingResult] = None
        self.loss_waterfall: list = []
        self.hourly_results: Optional[pd.DataFrame] = None
        self.annual_results: Optional[pd.DataFrame] = None
    
    def auto_size(self) -> PVSizingResult:
        """
        Calculate DC and AC capacity from land area.
        P_DC = Land_Area × GCR × Module_Efficiency × 1000 W/m²
        P_AC = min(Grid_Limit, P_DC / ILR)
        """
        land_area_m2 = self.config.land_area_ha * 10000  # ha to m²
        
        # DC Capacity based on land and GCR
        # Active module area = Land × GCR
        # Power = Active Area × Efficiency × STC Irradiance (1000 W/m²)
        active_area_m2 = land_area_m2 * self.config.gcr
        dc_capacity_kw = active_area_m2 * self.config.module_efficiency * 1.0  # kW (1000W/m² = 1kW/m²)
        
        # AC Capacity constrained by grid and ILR
        ac_from_ilr = dc_capacity_kw / self.config.ilr
        ac_capacity_kw = min(self.config.grid_limit_mw * 1000, ac_from_ilr)
        
        # Recalculate actual ILR
        actual_ilr = dc_capacity_kw / ac_capacity_kw if ac_capacity_kw > 0 else 0
        
        # Number of modules
        num_modules = int(dc_capacity_kw * 1000 / self.config.module_power_wp)
        
        # Specific area
        specific_area = land_area_m2 / dc_capacity_kw if dc_capacity_kw > 0 else 0
        
        self.sizing_result = PVSizingResult(
            land_area_m2=land_area_m2,
            dc_capacity_kwp=dc_capacity_kw,
            ac_capacity_kw=ac_capacity_kw,
            actual_ilr=actual_ilr,
            num_modules=num_modules,
            specific_area_m2_per_kwp=specific_area
        )
        return self.sizing_result
    
    def simulate_year_one(self, weather_data: pd.DataFrame) -> pd.DataFrame:
        """
        Simulate one year of hourly production.
        weather_data: DataFrame with columns ['ghi', 'dni', 'dhi', 'temp_air', 'wind_speed']
        """
        if self.sizing_result is None:
            self.auto_size()
        
        # Solar position
        solpos = self.location.get_solarposition(weather_data.index)
        
        # POA Irradiance
        poa = pvlib.irradiance.get_total_irradiance(
            self.config.tilt, self.config.azimuth,
            solpos['zenith'], solpos['azimuth'],
            weather_data['dni'], weather_data['ghi'], weather_data['dhi']
        )
        poa_global = poa['poa_global'].fillna(0).clip(lower=0)
        
        # Cell Temperature (Faiman model)
        temp_cell = pvlib.temperature.faiman(
            poa_global, weather_data['temp_air'], weather_data['wind_speed']
        )
        
        # Temperature loss factor
        temp_loss_factor = 1 + self.config.temp_coefficient * (temp_cell - 25)
        temp_loss_factor = temp_loss_factor.clip(lower=0.5, upper=1.1)
        
        # Raw DC Power (before losses)
        # P = P_rated × (G / G_STC) × temp_factor
        raw_dc_kw = self.sizing_result.dc_capacity_kwp * (poa_global / 1000.0) * temp_loss_factor
        raw_dc_kw = raw_dc_kw.clip(lower=0)
        
        # Calculate average temperature loss for waterfall
        avg_temp_loss = 1 - temp_loss_factor.mean()
        
        # Build loss waterfall
        self.loss_waterfall = self._compute_loss_waterfall(raw_dc_kw, poa_global, avg_temp_loss)
        
        # Apply all losses sequentially
        energy = raw_dc_kw.copy()
        
        # Pre-DC losses (applied to raw DC)
        energy = energy * (1 - self.config.loss_near_shading)
        energy = energy * (1 - self.config.loss_soiling)
        energy = energy * (1 - self.config.loss_iam)
        energy = energy * (1 - self.config.loss_spectral)
        # Temperature already applied in raw_dc calculation
        energy = energy * (1 - self.config.loss_dc_wiring)
        energy = energy * (1 - self.config.loss_mismatch)
        
        # DC to AC conversion
        energy = energy * (1 - self.config.loss_inverter_efficiency)
        
        # Clipping (when DC > AC capacity)
        clipping_mask = energy > self.sizing_result.ac_capacity_kw
        clipped_energy = energy.copy()
        clipped_energy[clipping_mask] = self.sizing_result.ac_capacity_kw
        clipping_loss_total = (energy - clipped_energy).sum()
        clipping_loss_pct = clipping_loss_total / energy.sum() if energy.sum() > 0 else 0
        energy = clipped_energy
        
        # Post-inverter AC losses
        energy = energy * (1 - self.config.loss_transformer)
        energy = energy * (1 - self.config.loss_ac_collection)
        energy = energy * (1 - self.config.loss_availability)
        
        # Store clipping loss in waterfall
        self._update_clipping_loss(clipping_loss_pct)
        
        self.hourly_results = pd.DataFrame({
            'poa_global': poa_global,
            'temp_cell': temp_cell,
            'raw_dc_kw': raw_dc_kw,
            'net_ac_kw': energy
        }, index=weather_data.index)
        
        return self.hourly_results
    
    def _compute_loss_waterfall(self, raw_dc: pd.Series, poa: pd.Series, avg_temp_loss: float) -> list:
        """Compute the 12-stage loss waterfall."""
        total_raw = raw_dc.sum()
        
        stages = [
            ("Near Shading", self.config.loss_near_shading),
            ("Soiling", self.config.loss_soiling),
            ("IAM (Reflection)", self.config.loss_iam),
            ("Spectral", self.config.loss_spectral),
            ("Temperature", max(0, avg_temp_loss)),
            ("DC Wiring", self.config.loss_dc_wiring),
            ("Mismatch", self.config.loss_mismatch),
            ("Inverter Efficiency", self.config.loss_inverter_efficiency),
            ("Clipping", 0.0),  # Will be updated after simulation
            ("Transformer", self.config.loss_transformer),
            ("AC Collection", self.config.loss_ac_collection),
            ("Availability", self.config.loss_availability),
        ]
        
        waterfall = []
        current_energy = total_raw
        
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
    
    def _update_clipping_loss(self, clipping_pct: float):
        """Update the clipping loss in the waterfall."""
        for item in self.loss_waterfall:
            if item.stage == "Clipping":
                item.loss_percent = clipping_pct
                item.loss_energy = item.input_energy * clipping_pct
                item.output_energy = item.input_energy - item.loss_energy
                break
    
    def run_lifecycle(self, weather_data: pd.DataFrame, years: int = 30) -> pd.DataFrame:
        """Run 30-year simulation with degradation."""
        if self.hourly_results is None:
            self.simulate_year_one(weather_data)
        
        base_annual_kwh = self.hourly_results['net_ac_kw'].sum()
        
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
        
        annual_kwh = self.hourly_results['net_ac_kw'].sum()
        annual_mwh = annual_kwh / 1000.0
        poa_total = self.hourly_results['poa_global'].sum() / 1000.0  # kWh/m²
        raw_dc_total = self.hourly_results['raw_dc_kw'].sum()
        
        specific_yield = annual_kwh / self.sizing_result.dc_capacity_kwp if self.sizing_result.dc_capacity_kwp > 0 else 0
        pr = (annual_kwh / self.sizing_result.dc_capacity_kwp) / poa_total if poa_total > 0 else 0
        capacity_factor = annual_kwh / (self.sizing_result.ac_capacity_kw * 8760) if self.sizing_result.ac_capacity_kw > 0 else 0
        
        total_loss = 1 - (annual_kwh / raw_dc_total) if raw_dc_total > 0 else 0
        
        return {
            'DC Capacity (MWp)': self.sizing_result.dc_capacity_kwp / 1000,
            'AC Capacity (MW)': self.sizing_result.ac_capacity_kw / 1000,
            'ILR': self.sizing_result.actual_ilr,
            'Annual Energy (MWh)': annual_mwh,
            'Specific Yield (kWh/kWp)': specific_yield,
            'Performance Ratio': pr,
            'Capacity Factor (%)': capacity_factor * 100,
            'Total Losses (%)': total_loss * 100,
            'Number of Modules': self.sizing_result.num_modules
        }
