"""
Solar PV screening model.

The hourly AC power is:
plane-of-array irradiance from pvlib (isotropic sky, albedo 0.25),
Faiman cell temperature with pvlib's default coefficients (u0=25, u1=6.84),
a user temperature coefficient, then user flat loss fractions, then an AC clip.

This is not a PVsyst model and it has not been compared to PVsyst.
The loss waterfall is the annual energy at each of those stages.
"""

import pvlib
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from simulator.core.base import BaseGenerator
from simulator.core.types import SimulationResult, SizingResult, LossItem
from simulator.core.losses import LossWaterfall
from simulator.core.validation import (
    SimulationInputError,
    require_fraction,
    require_in_range,
    require_int,
    require_positive,
    validate_latitude,
    validate_longitude,
)
from simulator.data.timeseries import integrate_power_kwh, timestep_hours


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
    Utility-scale solar PV screening generator.

    Example:
        >>> config = SolarConfig(latitude=31.6, longitude=-8.0, land_area_ha=100)
        >>> gen = SolarGenerator(config)
        >>> sizing = gen.auto_size()
        >>> result = gen.simulate(weather_data, years=30)
    """
    
    def __init__(self, config: Optional[SolarConfig] = None):
        super().__init__(name="Solar PV")
        self.config = config or SolarConfig()
        self.sizing: Optional[SolarSizingResult] = None
        self._waterfall: Optional[LossWaterfall] = None
        self._temp_loss_avg: float = 0.0
        self._clipping_loss: float = 0.0
        self._nan_counts: Dict[str, int] = {}
        self._validate_config()
        self.location = pvlib.location.Location(
            self.config.latitude,
            self.config.longitude,
            altitude=self.config.altitude,
        )
    
    @property
    def capacity_kw(self) -> float:
        if self.sizing:
            return self.sizing.dc_capacity_kwp
        return 0.0
    
    def _validate_config(self) -> None:
        cfg = self.config
        validate_latitude(cfg.latitude)
        validate_longitude(cfg.longitude)
        require_finite_altitude = require_in_range("altitude", cfg.altitude, -500.0, 9000.0)
        cfg.altitude = require_finite_altitude
        cfg.land_area_ha = require_positive("land_area_ha", cfg.land_area_ha)
        cfg.grid_limit_mw = require_positive("grid_limit_mw", cfg.grid_limit_mw)
        cfg.module_power_wp = require_positive("module_power_wp", cfg.module_power_wp)
        cfg.module_efficiency = require_in_range(
            "module_efficiency", cfg.module_efficiency, 0.0, 1.0, low_inclusive=False
        )
        cfg.temp_coefficient = require_in_range("temp_coefficient", cfg.temp_coefficient, -0.02, 0.0)
        cfg.gcr = require_in_range("gcr", cfg.gcr, 0.0, 1.0, low_inclusive=False)
        cfg.ilr = require_positive("ilr", cfg.ilr)
        cfg.tilt = require_in_range("tilt", cfg.tilt, 0.0, 90.0)
        cfg.azimuth = require_in_range("azimuth", cfg.azimuth, 0.0, 360.0)
        if cfg.tracking not in {"fixed", "single_axis"}:
            raise SimulationInputError("tracking must be 'fixed' or 'single_axis'")
        for name in (
            "loss_near_shading",
            "loss_far_shading",
            "loss_soiling",
            "loss_iam",
            "loss_spectral",
            "loss_dc_wiring",
            "loss_mismatch",
            "loss_inverter",
            "loss_transformer",
            "loss_ac_collection",
            "loss_availability",
            "annual_degradation",
        ):
            setattr(cfg, name, require_fraction(name, getattr(cfg, name)))

    def configure(self, **kwargs: Any) -> None:
        """Update configuration parameters and drop results from the previous config."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self._validate_config()
        self.location = pvlib.location.Location(
            self.config.latitude,
            self.config.longitude,
            altitude=self.config.altitude,
        )
        self.sizing = None
        self._hourly_results = None
        self._losses = []

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
        self._validate_config()

        land_area_m2 = self.config.land_area_ha * 10000

        # Continuous DC from land, then the integer module count that fits.
        # Energy uses the module-rounded DC so it matches the reported count.
        active_area_m2 = land_area_m2 * self.config.gcr
        continuous_dc_kw = active_area_m2 * self.config.module_efficiency
        num_modules = int(continuous_dc_kw * 1000 / self.config.module_power_wp)
        if num_modules < 1:
            raise SimulationInputError(
                "Land area, GCR, efficiency, and module rating produce zero modules"
            )
        dc_capacity_kw = num_modules * self.config.module_power_wp / 1000.0

        ac_from_ilr = dc_capacity_kw / self.config.ilr
        ac_capacity_kw = min(self.config.grid_limit_mw * 1000, ac_from_ilr)
        if ac_capacity_kw <= 0:
            raise SimulationInputError("AC capacity is zero")
        actual_ilr = dc_capacity_kw / ac_capacity_kw
        specific_area = land_area_m2 / dc_capacity_kw
        
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
    
    def _prepare_weather(self, weather: pd.DataFrame) -> pd.DataFrame:
        required = ("ghi", "dni", "dhi", "temp_air", "wind_speed")
        missing = [name for name in required if name not in weather.columns]
        if missing:
            raise SimulationInputError(f"solar weather is missing columns: {missing}")
        if len(weather) < 2:
            raise SimulationInputError("weather series must contain at least 2 rows")
        if not weather.index.is_monotonic_increasing or not weather.index.is_unique:
            raise SimulationInputError("weather index must be sorted and unique")
        frame = weather.loc[:, required].apply(pd.to_numeric, errors="coerce")
        self._nan_counts = {name: int(frame[name].isna().sum()) for name in required}
        if any(count == len(frame) for count in self._nan_counts.values()):
            raise SimulationInputError("a required weather column is entirely missing")
        return frame.fillna(0.0)

    def _apply_flat_loss(self, power: pd.Series, fraction: float) -> pd.Series:
        return power * (1.0 - fraction)

    def _simulate_year_one(self, weather: pd.DataFrame) -> pd.DataFrame:
        """Simulate the weather series once. Later years scale this energy."""
        self.auto_size()
        weather = self._prepare_weather(weather)

        # pvlib treats a timezone-naive index as UTC.
        solpos = self.location.get_solarposition(weather.index)

        if self.config.tracking == "single_axis":
            tracking = pvlib.tracking.singleaxis(
                solpos["apparent_zenith"],
                solpos["azimuth"],
                axis_tilt=0,
                axis_azimuth=180,
                max_angle=60,
                backtrack=True,
                gcr=self.config.gcr,
            )
            tilt = tracking["surface_tilt"].fillna(0)
            azimuth = tracking["surface_azimuth"].fillna(180)
        else:
            tilt = self.config.tilt
            azimuth = self.config.azimuth

        poa = pvlib.irradiance.get_total_irradiance(
            tilt,
            azimuth,
            solpos["apparent_zenith"],
            solpos["azimuth"],
            weather["dni"].clip(lower=0),
            weather["ghi"].clip(lower=0),
            weather["dhi"].clip(lower=0),
            albedo=0.25,
            model="isotropic",
        )
        poa_global = poa["poa_global"].fillna(0).clip(lower=0)

        temp_cell = pvlib.temperature.faiman(
            poa_global,
            weather["temp_air"],
            weather["wind_speed"].clip(lower=0),
            u0=25.0,
            u1=6.84,
        )
        temp_factor = (1 + self.config.temp_coefficient * (temp_cell - 25)).clip(lower=0.5, upper=1.1)

        # STC-equivalent DC, before temperature. Waterfall gross is this sum.
        poa_dc_kw = (self.sizing.dc_capacity_kwp * (poa_global / 1000.0)).clip(lower=0)
        temp_dc_kw = (poa_dc_kw * temp_factor).clip(lower=0)
        stages: List[tuple] = [("Temperature", poa_dc_kw, temp_dc_kw)]

        energy = temp_dc_kw
        flat_before_clip = (
            ("Near Shading", self.config.loss_near_shading),
            ("Far Shading", self.config.loss_far_shading),
            ("Soiling", self.config.loss_soiling),
            ("IAM flat factor", self.config.loss_iam),
            ("Spectral flat factor", self.config.loss_spectral),
            ("DC Wiring", self.config.loss_dc_wiring),
            ("Mismatch", self.config.loss_mismatch),
            ("Inverter flat factor", self.config.loss_inverter),
        )
        for name, fraction in flat_before_clip:
            updated = self._apply_flat_loss(energy, fraction)
            stages.append((name, energy, updated))
            energy = updated

        clipped = energy.clip(upper=self.sizing.ac_capacity_kw)
        stages.append(("Clipping", energy, clipped))
        energy = clipped

        flat_after_clip = (
            ("Transformer", self.config.loss_transformer),
            ("AC Collection", self.config.loss_ac_collection),
            ("Availability", self.config.loss_availability),
        )
        for name, fraction in flat_after_clip:
            updated = self._apply_flat_loss(energy, fraction)
            stages.append((name, energy, updated))
            energy = updated

        self._build_waterfall(stages)
        poa_dc_kwh = integrate_power_kwh(poa_dc_kw)
        temp_dc_kwh = integrate_power_kwh(temp_dc_kw)
        self._temp_loss_avg = 1.0 - (temp_dc_kwh / poa_dc_kwh) if poa_dc_kwh > 0 else 0.0
        pre_clip = next(before for name, before, _after in stages if name == "Clipping")
        pre_clip_kwh = integrate_power_kwh(pre_clip)
        clip_kwh = integrate_power_kwh(clipped)
        self._clipping_loss = 1.0 - (clip_kwh / pre_clip_kwh) if pre_clip_kwh > 0 else 0.0

        self._hourly_results = pd.DataFrame(
            {
                "poa_global": poa_global,
                "temp_cell": temp_cell,
                "poa_dc_kw": poa_dc_kw,
                "raw_dc_kw": temp_dc_kw,
                "power_kw": energy,
            },
            index=weather.index,
        )
        return self._hourly_results

    def _build_waterfall(self, stages: List[tuple]) -> None:
        """Annual stage fractions taken from the hourly power series."""
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
            annual_data.append(
                {
                    "year": year,
                    "degradation_factor": factor,
                    "energy_kwh": annual_kwh,
                    "energy_mwh": annual_mwh,
                    "cumulative_mwh": cumulative,
                }
            )
        self._annual_results = pd.DataFrame(annual_data)
        naive_clock = not isinstance(weather.index, pd.DatetimeIndex) or weather.index.tz is None
        return SimulationResult(
            hourly=self._hourly_results,
            annual=self._annual_results,
            kpis=self.get_kpis(),
            losses=self.get_losses(),
            metadata={
                "config": self.config.to_dict(),
                "sizing": {
                    "dc_capacity_mwp": self.sizing.dc_capacity_kwp / 1000,
                    "ac_capacity_mw": self.sizing.ac_capacity_kw / 1000,
                    "num_modules": self.sizing.num_modules,
                },
                "model": {
                    "poa": "pvlib.get_total_irradiance model=isotropic albedo=0.25, solar zenith=apparent_zenith",
                    "temperature": "pvlib.temperature.faiman u0=25 u1=6.84, then the user temperature coefficient",
                    "iam": "flat user fraction, not an incidence-angle curve",
                    "inverter": "flat user fraction, then a hard clip at AC capacity",
                    "degradation": "year 1 energy is scaled by (1 - annual_degradation) ** (year - 1); the hourly shape is not resimulated",
                    "clock": (
                        "timezone-naive timestamps are passed through; pvlib interprets them as UTC"
                        if naive_clock
                        else "timestamps keep their timezone"
                    ),
                },
                "nan_counts_filled_with_zero": self._nan_counts,
            },
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
        hours = float(timestep_hours(self._hourly_results.index).sum())
        poa_wh_m2 = integrate_power_kwh(self._hourly_results["poa_global"])
        poa_total = poa_wh_m2 / 1000.0
        poa_dc_kwh = integrate_power_kwh(self._hourly_results["poa_dc_kw"])

        specific_yield = annual_kwh / self.sizing.dc_capacity_kwp if self.sizing.dc_capacity_kwp > 0 else 0
        pr = (annual_kwh / self.sizing.dc_capacity_kwp) / poa_total if poa_total > 0 else 0
        capacity_factor = (
            annual_kwh / (self.sizing.ac_capacity_kw * hours) if self.sizing.ac_capacity_kw > 0 and hours > 0 else 0
        )
        total_loss = 1 - (annual_kwh / poa_dc_kwh) if poa_dc_kwh > 0 else 0
        
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
