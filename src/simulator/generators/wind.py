"""
Wind farm screening model.

Nameplate rated power, rotor diameter, and hub height are stored per entry.
Every entry uses the same idealized cubic power curve unless that entry sets
its own cut-in, rated, and cut-out speeds. There is no manufacturer power curve
and no spatial wake model: wake and the other loss terms are flat user fractions.

Hub-height wind speed uses the neutral logarithmic profile ratio. Air density
scales power and the result is clipped to nameplate. This is not a WindPro model.
"""

import pandas as pd
import numpy as np
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union

from simulator.core.base import BaseGenerator
from simulator.core.types import SimulationResult, SizingResult, LossItem
from simulator.core.losses import LossWaterfall
from simulator.core.validation import (
    SimulationInputError,
    require_fraction,
    require_int,
    require_positive,
    validate_latitude,
    validate_longitude,
)
from simulator.data.timeseries import integrate_power_kwh, timestep_hours


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
    
    def power_curve_vectorized(
        self,
        wind_speeds: pd.Series,
        density_ratio: Union[float, pd.Series] = 1.0,
    ) -> pd.Series:
        """Idealized cubic curve, scaled by density and clipped to nameplate.

        Density is applied at every operating speed, including the rated region,
        and the result is then clipped to rated power. Above-rated output
        therefore falls below nameplate when the air is less dense and does not
        exceed nameplate when the air is denser. Speeds outside cut-in/cut-out
        stay at zero.
        """
        power = pd.Series(0.0, index=wind_speeds.index)

        mask_partial = (wind_speeds >= self.cut_in_speed) & (wind_speeds < self.rated_speed)
        power.loc[mask_partial] = self.rated_power_kw * (
            (wind_speeds.loc[mask_partial] - self.cut_in_speed)
            / (self.rated_speed - self.cut_in_speed)
        ) ** 3

        mask_rated = (wind_speeds >= self.rated_speed) & (wind_speeds <= self.cut_out_speed)
        power.loc[mask_rated] = self.rated_power_kw
        power = (power * density_ratio).clip(lower=0, upper=self.rated_power_kw)
        outside = (wind_speeds < self.cut_in_speed) | (wind_speeds > self.cut_out_speed)
        power.loc[outside] = 0.0
        return power


# Nameplate fields only. The power curve is WindTurbineSpec.power_curve.
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
    Screening wind-farm generator.

    Nameplate and an idealized cubic curve. Wake is a flat fraction.
    
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
        self._validate_config()
    
    @property
    def capacity_kw(self) -> float:
        if self.sizing:
            return self.sizing.total_capacity_mw * 1000
        return 0.0
    
    def _validate_config(self) -> None:
        cfg = self.config
        validate_latitude(cfg.latitude)
        validate_longitude(cfg.longitude)
        cfg.land_area_ha = require_positive("land_area_ha", cfg.land_area_ha)
        cfg.grid_limit_mw = require_positive("grid_limit_mw", cfg.grid_limit_mw)
        if cfg.turbine_model not in TURBINE_LIBRARY:
            raise SimulationInputError(
                f"Unknown turbine_model '{cfg.turbine_model}'. Choose one of {sorted(TURBINE_LIBRARY)}."
            )
        cfg.spacing_in_row_rd = require_positive("spacing_in_row_rd", cfg.spacing_in_row_rd)
        cfg.spacing_between_rows_rd = require_positive(
            "spacing_between_rows_rd", cfg.spacing_between_rows_rd
        )
        cfg.roughness_length = require_positive("roughness_length", cfg.roughness_length)
        cfg.measurement_height = require_positive("measurement_height", cfg.measurement_height)
        if cfg.measurement_height <= cfg.roughness_length:
            raise SimulationInputError("measurement_height must be greater than roughness_length")
        if cfg.turbine.hub_height_m <= cfg.roughness_length:
            raise SimulationInputError("hub height must be greater than roughness_length")
        for name in (
            "loss_wake",
            "loss_availability",
            "loss_electrical",
            "loss_performance",
            "loss_environmental",
            "loss_grid",
            "annual_degradation",
        ):
            setattr(cfg, name, require_fraction(name, getattr(cfg, name)))

    def configure(self, **kwargs: Any) -> None:
        """Update configuration parameters and drop results from the previous config."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self._validate_config()
        self.sizing = None
        self._hourly_results = None
        self._losses = []

    def auto_size(self, constraints: Optional[Dict[str, Any]] = None) -> WindSizingResult:
        """
        Calculate number of turbines from land area using spacing rules.
        
        Spacing in-row: 3-5 × Rotor Diameter
        Spacing between rows: 5-9 × Rotor Diameter
        """
        target_capacity_mw = None
        if constraints:
            for key, value in constraints.items():
                if key == "target_capacity_mw":
                    target_capacity_mw = require_positive("target_capacity_mw", value)
                elif hasattr(self.config, key):
                    setattr(self.config, key, value)
        self._validate_config()

        turbine = self.config.turbine
        land_area_m2 = self.config.land_area_ha * 10000
        rd = turbine.rotor_diameter_m
        
        # Spacing in meters
        spacing_in_row_m = self.config.spacing_in_row_rd * rd
        spacing_between_rows_m = self.config.spacing_between_rows_rd * rd
        
        # Footprint per turbine
        turbine_footprint_m2 = spacing_in_row_m * spacing_between_rows_m
        
        if turbine_footprint_m2 <= 0:
            raise SimulationInputError("turbine footprint is zero")
        max_by_land = int(math.floor(land_area_m2 / turbine_footprint_m2))
        turbine_power_mw = turbine.rated_power_kw / 1000
        if turbine_power_mw <= 0:
            raise SimulationInputError("turbine rated power must be positive")
        max_by_grid = int(math.floor(self.config.grid_limit_mw / turbine_power_mw))
        max_by_target = (
            max_by_land
            if target_capacity_mw is None
            else int(math.floor(target_capacity_mw / turbine_power_mw))
        )
        num_turbines = min(max_by_land, max_by_grid, max_by_target)
        if num_turbines < 1:
            raise SimulationInputError(
                "No turbine fits the constraints: "
                f"land allows {max_by_land}, grid allows {max_by_grid}, "
                f"target allows {max_by_target}. "
                f"One {turbine.name} is {turbine_power_mw:.3f} MW."
            )
        binding = []
        if num_turbines == max_by_land:
            binding.append("land")
        if num_turbines == max_by_grid:
            binding.append("grid")
        if target_capacity_mw is not None and num_turbines == max_by_target:
            binding.append("target")
        grid_constrained = max_by_grid < max_by_land and max_by_grid <= max_by_target
        
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
            details={
                "binding": binding,
                "max_by_land": max_by_land,
                "max_by_grid": max_by_grid,
                "max_by_target": max_by_target,
                "power_curve": "idealized_cubic",
            },
        )
        
        self._capacity_kw = total_capacity_mw * 1000
        return self.sizing
    
    @staticmethod
    def hub_height_speed(
        wind_speed: pd.Series,
        hub_height_m: float,
        measurement_height_m: float,
        roughness_length_m: float,
    ) -> pd.Series:
        """Neutral logarithmic profile ratio. No stability correction."""
        ratio = math.log(hub_height_m / roughness_length_m) / math.log(
            measurement_height_m / roughness_length_m
        )
        return wind_speed * ratio

    def _simulate_year_one(self, weather: pd.DataFrame) -> pd.DataFrame:
        """Simulate the supplied wind series once."""
        self.auto_size()
        if "wind_speed" not in weather.columns:
            raise SimulationInputError("wind weather is missing column 'wind_speed'")
        if len(weather) < 2 or not weather.index.is_monotonic_increasing or not weather.index.is_unique:
            raise SimulationInputError("weather index must contain at least 2 sorted unique timestamps")

        turbine = self.config.turbine
        wind_speed = pd.to_numeric(weather["wind_speed"], errors="coerce")
        self._nan_counts = {"wind_speed": int(wind_speed.isna().sum())}
        if self._nan_counts["wind_speed"] == len(wind_speed):
            raise SimulationInputError("wind_speed is entirely missing")
        wind_speed = wind_speed.fillna(0).clip(lower=0)
        v_hub = self.hub_height_speed(
            wind_speed,
            turbine.hub_height_m,
            self.config.measurement_height,
            self.config.roughness_length,
        )

        if "pressure" in weather.columns and "temperature" in weather.columns:
            pressure_hpa = pd.to_numeric(weather["pressure"], errors="coerce")
            temperature_c = pd.to_numeric(weather["temperature"], errors="coerce")
            if pressure_hpa.isna().any() or temperature_c.isna().any():
                raise SimulationInputError("pressure and temperature must be numeric when provided")
            if (pressure_hpa <= 0).any() or (temperature_c <= -273.15).any():
                raise SimulationInputError("pressure must be positive and temperature must be above absolute zero")
            rho = (pressure_hpa * 100) / (287 * (temperature_c + 273.15))
            rho_ratio = rho / 1.225
            density_basis = "pressure_hpa_and_temperature_c"
        else:
            rho_ratio = 1.0
            density_basis = "standard_1.225_kg_m3"

        gross_power_per_turbine = turbine.power_curve_vectorized(v_hub, rho_ratio)
        gross_power_kw = gross_power_per_turbine * self.sizing.num_turbines

        stages = []
        net_power = gross_power_kw
        for name, fraction in (
            ("Wake flat factor", self.config.loss_wake),
            ("Turbine Availability", self.config.loss_availability),
            ("Electrical Collection", self.config.loss_electrical),
            ("Turbine Performance", self.config.loss_performance),
            ("Environmental flat factor", self.config.loss_environmental),
            ("Grid flat factor", self.config.loss_grid),
        ):
            updated = net_power * (1.0 - fraction)
            stages.append((name, net_power, updated))
            net_power = updated
        self._density_basis = density_basis
        self._build_waterfall(stages)

        self._hourly_results = pd.DataFrame(
            {
                "wind_speed_hub": v_hub,
                "gross_power_kw": gross_power_kw,
                "power_kw": net_power,
            },
            index=weather.index,
        )
        return self._hourly_results

    def _build_waterfall(self, stages: List[tuple]) -> None:
        gross = integrate_power_kwh(stages[0][1])
        self._waterfall = LossWaterfall(gross)
        for name, before, after in stages:
            energy_in = integrate_power_kwh(before)
            energy_out = integrate_power_kwh(after)
            fraction = 1.0 - (energy_out / energy_in) if energy_in > 0 else 0.0
            self._waterfall.add_loss(name, fraction)
        self._losses = self._waterfall.get_losses()

    def simulate(self, weather: pd.DataFrame, years: int = 30) -> SimulationResult:
        """Run the weather series once, then scale that energy by compound degradation."""
        years = require_int("years", years, minimum=1, maximum=100)
        self._simulate_year_one(weather)
        base_annual_kwh = integrate_power_kwh(self._hourly_results["power_kw"])
        
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
                "config": self.config.to_dict(),
                "sizing": {
                    "total_capacity_mw": self.sizing.total_capacity_mw,
                    "num_turbines": self.sizing.num_turbines,
                    "turbine_model": self.sizing.turbine_model,
                    "binding": self.sizing.details.get("binding", []),
                },
                "model": {
                    "power_curve": "idealized cubic between cut-in and rated; nameplate above rated until cut-out",
                    "power_curve_source": "not a manufacturer curve; cut-in/rated/cut-out use the spec defaults unless overridden",
                    "wind_shear": "neutral logarithmic profile ratio from measurement height to hub height",
                    "density": self._density_basis,
                    "wake": "flat user fraction, not a spatial wake calculation",
                    "grid_loss": "flat user fraction; hourly output is not clipped to the grid limit",
                    "degradation": "year 1 energy is scaled by (1 - annual_degradation) ** (year - 1)",
                },
                "nan_counts_filled_with_zero": self._nan_counts,
            }
        )
    
    def get_losses(self) -> List[LossItem]:
        """Get loss waterfall items."""
        return self._losses if self._losses else []
    
    def get_kpis(self) -> Dict[str, float]:
        """Calculate key performance indicators."""
        if self._hourly_results is None or self.sizing is None:
            return {}
        
        annual_kwh = integrate_power_kwh(self._hourly_results["power_kw"])
        annual_mwh = annual_kwh / 1000.0
        gross_kwh = integrate_power_kwh(self._hourly_results["gross_power_kw"])
        hours = float(timestep_hours(self._hourly_results.index).sum())

        total_capacity_kw = self.sizing.total_capacity_mw * 1000
        capacity_factor = (
            annual_kwh / (total_capacity_kw * hours) if total_capacity_kw > 0 and hours > 0 else 0
        )
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
