"""
Solar PV Generator Module - PVsyst-style simulation.

Professional-grade utility-scale solar PV simulation with:
- Auto-sizing from land area and GCR
- 12-stage loss waterfall
- Multi-year degradation modeling
- Temperature and clipping calculations
"""

import pvlib
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from simulator.core.base import BaseGenerator
from simulator.core.types import SimulationResult, SizingResult, LossItem
from simulator.core.losses import LossWaterfall


@dataclass
class SolarConfig:
    """Configuration for a utility-scale solar PV system."""
    
    # Site Parameters
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0
    
    # Land/Sizing
    land_area_ha: float = 100.0
    grid_limit_mw: float = 50.0
    
    # Module Parameters
    module_power_wp: float = 580  # Wp (TOPCon/HJT)
    module_efficiency: float = 0.215  # 21.5%
    temp_coefficient: float = -0.0035  # %/°C
    
    # System Design
    gcr: float = 0.30  # Ground Coverage Ratio
    ilr: float = 1.30  # Inverter Loading Ratio (DC:AC)
    tilt: float = 25.0  # degrees
    azimuth: float = 180.0  # South-facing
    tracking: str = "fixed"  # 'fixed' or 'single_axis'
    
    # Pre-DC Losses
    loss_near_shading: float = 0.02
    loss_far_shading: float = 0.01
    loss_soiling: float = 0.05
    loss_iam: float = 0.03
    loss_spectral: float = 0.01
    
    # DC Losses
    loss_dc_wiring: float = 0.02
    loss_mismatch: float = 0.015
    
    # Conversion Losses
    loss_inverter: float = 0.02
    
    # AC Losses
    loss_transformer: float = 0.015
    loss_ac_collection: float = 0.01
    loss_availability: float = 0.01
    
    # Degradation
    annual_degradation: float = 0.005  # 0.5%/year
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'land_area_ha': self.land_area_ha,
            'grid_limit_mw': self.grid_limit_mw,
            'module_power_wp': self.module_power_wp,
            'module_efficiency': self.module_efficiency,
            'gcr': self.gcr,
            'ilr': self.ilr,
            'tilt': self.tilt,
            'azimuth': self.azimuth,
            'tracking': self.tracking,
            'annual_degradation': self.annual_degradation,
        }


@dataclass
class SolarSizingResult(SizingResult):
    """Extended sizing result for solar PV."""
    dc_capacity_kwp: float = 0.0
    ac_capacity_kw: float = 0.0
    actual_ilr: float = 1.0
    num_modules: int = 0
    num_inverters: int = 0
    specific_area_m2_per_kwp: float = 0.0


class SolarGenerator(BaseGenerator):
    """
    Professional-grade utility-scale solar PV generator.
    
    Implements the Generator protocol with PVsyst-style simulation.
    
    Example:
        >>> config = SolarConfig(latitude=31.6, longitude=-8.0, land_area_ha=100)
        >>> gen = SolarGenerator(config)
        >>> sizing = gen.auto_size()
        >>> result = gen.simulate(weather_data, years=30)
    """
    
    def __init__(self, config: Optional[SolarConfig] = None):
        super().__init__(name="Solar PV")
        self.config = config or SolarConfig()
        self.location = pvlib.location.Location(
            self.config.latitude,
            self.config.longitude,
            altitude=self.config.altitude
        )
        self.sizing: Optional[SolarSizingResult] = None
        self._waterfall: Optional[LossWaterfall] = None
        self._temp_loss_avg: float = 0.0
        self._clipping_loss: float = 0.0
    
    @property
    def capacity_kw(self) -> float:
        if self.sizing:
            return self.sizing.dc_capacity_kwp
        return 0.0
    
    def configure(self, **kwargs: Any) -> None:
        """Update configuration parameters."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        
        # Update location if coordinates changed
        if 'latitude' in kwargs or 'longitude' in kwargs:
            self.location = pvlib.location.Location(
                self.config.latitude,
                self.config.longitude,
                altitude=self.config.altitude
            )
    
    def auto_size(self, constraints: Optional[Dict[str, Any]] = None) -> SolarSizingResult:
        """
        Calculate DC and AC capacity from land area.
        
        Formula:
            P_DC = Land_Area × GCR × Module_Efficiency × 1000 W/m²
            P_AC = min(Grid_Limit, P_DC / ILR)
        """
        if constraints:
            for key, value in constraints.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)
        
        land_area_m2 = self.config.land_area_ha * 10000
        
        # DC Capacity from land and GCR
        active_area_m2 = land_area_m2 * self.config.gcr
        dc_capacity_kw = active_area_m2 * self.config.module_efficiency * 1.0
        
        # AC Capacity constrained by grid and ILR
        ac_from_ilr = dc_capacity_kw / self.config.ilr
        ac_capacity_kw = min(self.config.grid_limit_mw * 1000, ac_from_ilr)
        
        # Recalculate actual ILR
        actual_ilr = dc_capacity_kw / ac_capacity_kw if ac_capacity_kw > 0 else 0
        
        # Number of modules
        num_modules = int(dc_capacity_kw * 1000 / self.config.module_power_wp)
        
        # Specific area
        specific_area = land_area_m2 / dc_capacity_kw if dc_capacity_kw > 0 else 0
        
        self.sizing = SolarSizingResult(
            capacity_kw=dc_capacity_kw,
            area_m2=land_area_m2,
            num_units=num_modules,
            grid_constrained=(self.config.grid_limit_mw * 1000 < ac_from_ilr),
            dc_capacity_kwp=dc_capacity_kw,
            ac_capacity_kw=ac_capacity_kw,
            actual_ilr=actual_ilr,
            num_modules=num_modules,
            specific_area_m2_per_kwp=specific_area,
        )
        
        self._capacity_kw = dc_capacity_kw
        return self.sizing
    
    def _simulate_year_one(self, weather: pd.DataFrame) -> pd.DataFrame:
        """
        Simulate one year of hourly production.
        
        Args:
            weather: DataFrame with columns ['ghi', 'dni', 'dhi', 'temp_air', 'wind_speed']
        """
        if self.sizing is None:
            self.auto_size()
        
        # Solar position
        solpos = self.location.get_solarposition(weather.index)
        
        # POA Irradiance
        if self.config.tracking == 'single_axis':
            # Simple single-axis tracking approximation
            tracking = pvlib.tracking.singleaxis(
                solpos['apparent_zenith'],
                solpos['azimuth'],
                axis_tilt=0,
                axis_azimuth=180,
                max_angle=60,
                backtrack=True,
                gcr=self.config.gcr
            )
            tilt = tracking['surface_tilt'].fillna(0)
            azimuth = tracking['surface_azimuth'].fillna(180)
        else:
            tilt = self.config.tilt
            azimuth = self.config.azimuth
        
        poa = pvlib.irradiance.get_total_irradiance(
            tilt, azimuth,
            solpos['zenith'], solpos['azimuth'],
            weather['dni'], weather['ghi'], weather['dhi']
        )
        poa_global = poa['poa_global'].fillna(0).clip(lower=0)
        
        # Cell Temperature (Faiman model)
        temp_cell = pvlib.temperature.faiman(
            poa_global, weather['temp_air'], weather['wind_speed']
        )
        
        # Temperature loss factor
        temp_loss_factor = 1 + self.config.temp_coefficient * (temp_cell - 25)
        temp_loss_factor = temp_loss_factor.clip(lower=0.5, upper=1.1)
        
        # Average temperature loss for waterfall
        self._temp_loss_avg = max(0, 1 - temp_loss_factor.mean())
        
        # Raw DC Power (before losses)
        raw_dc_kw = self.sizing.dc_capacity_kwp * (poa_global / 1000.0) * temp_loss_factor
        raw_dc_kw = raw_dc_kw.clip(lower=0)
        
        # Apply pre-DC losses
        energy = raw_dc_kw.copy()
        energy *= (1 - self.config.loss_near_shading)
        energy *= (1 - self.config.loss_far_shading)
        energy *= (1 - self.config.loss_soiling)
        energy *= (1 - self.config.loss_iam)
        energy *= (1 - self.config.loss_spectral)
        
        # Apply DC losses
        energy *= (1 - self.config.loss_dc_wiring)
        energy *= (1 - self.config.loss_mismatch)
        
        # Inverter conversion
        energy *= (1 - self.config.loss_inverter)
        
        # Clipping
        clipping_mask = energy > self.sizing.ac_capacity_kw
        clipped_energy = energy.copy()
        clipped_energy[clipping_mask] = self.sizing.ac_capacity_kw
        clipping_loss_total = (energy - clipped_energy).sum()
        self._clipping_loss = clipping_loss_total / energy.sum() if energy.sum() > 0 else 0
        energy = clipped_energy
        
        # AC losses
        energy *= (1 - self.config.loss_transformer)
        energy *= (1 - self.config.loss_ac_collection)
        energy *= (1 - self.config.loss_availability)
        
        # Build loss waterfall
        self._build_waterfall(raw_dc_kw.sum())
        
        self._hourly_results = pd.DataFrame({
            'poa_global': poa_global,
            'temp_cell': temp_cell,
            'raw_dc_kw': raw_dc_kw,
            'power_kw': energy,
        }, index=weather.index)
        
        return self._hourly_results
    
    def _build_waterfall(self, gross_energy: float) -> None:
        """Build the loss waterfall from simulation."""
        self._waterfall = LossWaterfall(gross_energy)
        
        losses = [
            ("Near Shading", self.config.loss_near_shading),
            ("Far Shading", self.config.loss_far_shading),
            ("Soiling", self.config.loss_soiling),
            ("IAM (Reflection)", self.config.loss_iam),
            ("Spectral", self.config.loss_spectral),
            ("Temperature", self._temp_loss_avg),
            ("DC Wiring", self.config.loss_dc_wiring),
            ("Mismatch", self.config.loss_mismatch),
            ("Inverter", self.config.loss_inverter),
            ("Clipping", self._clipping_loss),
            ("Transformer", self.config.loss_transformer),
            ("AC Collection", self.config.loss_ac_collection),
            ("Availability", self.config.loss_availability),
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
                    'dc_capacity_mwp': self.sizing.dc_capacity_kwp / 1000,
                    'ac_capacity_mw': self.sizing.ac_capacity_kw / 1000,
                    'num_modules': self.sizing.num_modules,
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
        poa_total = self._hourly_results['poa_global'].sum() / 1000.0
        raw_dc_total = self._hourly_results['raw_dc_kw'].sum()
        
        specific_yield = annual_kwh / self.sizing.dc_capacity_kwp if self.sizing.dc_capacity_kwp > 0 else 0
        pr = (annual_kwh / self.sizing.dc_capacity_kwp) / poa_total if poa_total > 0 else 0
        capacity_factor = annual_kwh / (self.sizing.ac_capacity_kw * 8760) if self.sizing.ac_capacity_kw > 0 else 0
        
        total_loss = 1 - (annual_kwh / raw_dc_total) if raw_dc_total > 0 else 0
        
        return {
            'dc_capacity_mwp': self.sizing.dc_capacity_kwp / 1000,
            'ac_capacity_mw': self.sizing.ac_capacity_kw / 1000,
            'ilr': self.sizing.actual_ilr,
            'annual_energy_mwh': annual_mwh,
            'specific_yield_kwh_kwp': specific_yield,
            'performance_ratio': pr,
            'capacity_factor_pct': capacity_factor * 100,
            'total_losses_pct': total_loss * 100,
            'num_modules': self.sizing.num_modules,
            'poa_irradiation_kwh_m2': poa_total,
        }
