"""
Unified Simulation API.

High-level API for running simulations with simplified interface.
"""

import pandas as pd
from dataclasses import dataclass
from typing import Dict, Optional, Any, List, Union

from simulator.generators.solar import SolarGenerator, SolarConfig
from simulator.generators.wind import WindGenerator, WindConfig
from simulator.storage.battery import BatteryStorage, BatteryConfig
from simulator.grid.dispatch import DispatchController, DispatchConfig, DispatchStrategy
from simulator.financial.lcoe import LCOECalculator, FinancialConfig
from simulator.financial.capex import SolarCapex, WindCapex, BatteryCapex, HybridCapex
from simulator.financial.opex import SolarOpex, WindOpex, BatteryOpex, HybridOpex
from simulator.optimizer.lcoe_optimizer import LCOEOptimizer, OptimizationConfig
from simulator.data.weather import fetch_pvgis_tmy, generate_synthetic_solar_tmy, generate_synthetic_wind_tmy
from simulator.data.timeseries import integrate_power_kwh
from simulator.core.types import SimulationResult, OptimizationResult, FinancialResult
from simulator.core.validation import SimulationInputError, validate_latitude, validate_longitude


@dataclass
class ProjectResult:
    """Combined result from a full project simulation."""
    solar_result: Optional[SimulationResult] = None
    wind_result: Optional[SimulationResult] = None
    storage_result: Optional[pd.DataFrame] = None
    dispatch_result: Optional[Any] = None
    financial_result: Optional[FinancialResult] = None
    notes: Dict[str, str] = None

    def __post_init__(self):
        if self.notes is None:
            self.notes = {}
    
    @property
    def total_annual_energy_mwh(self) -> float:
        """Total year-one energy from all sources."""
        total = 0.0
        if self.solar_result:
            total += self.solar_result.year_one_energy_mwh
        if self.wind_result:
            total += self.wind_result.year_one_energy_mwh
        return total
    
    @property
    def lcoe(self) -> float:
        """Project LCOE. inf when no financial result was produced."""
        if self.financial_result:
            return self.financial_result.lcoe
        return float("inf")


class SimulationAPI:
    """
    Unified API for renewable energy simulations.
    
    Provides a simplified interface for:
    - Solar PV simulation
    - Wind farm simulation
    - Battery storage simulation
    - Hybrid dispatch optimization
    - Financial analysis
    - LCOE optimization
    
    Example:
        >>> api = SimulationAPI()
        >>> 
        >>> # Simple solar simulation
        >>> result = api.run_solar_simulation(
        ...     latitude=31.6,
        ...     longitude=-8.0,
        ...     capacity_mw=50,
        ...     project_life=30
        ... )
        >>> 
        >>> # Hybrid project
        >>> result = api.run_hybrid_simulation(
        ...     latitude=31.6,
        ...     longitude=-8.0,
        ...     solar_mw=30,
        ...     wind_mw=20,
        ...     battery_mwh=50
        ... )
    """
    
    def __init__(self, default_wacc: float = 0.06, project_life: int = 30, allow_network: bool = True):
        self.default_wacc = default_wacc
        self.project_life = project_life
        self.allow_network = allow_network
        self._weather_cache: Dict[str, tuple] = {}
    
    def run_solar_simulation(
        self,
        latitude: float,
        longitude: float,
        capacity_mw: Optional[float] = None,
        land_area_ha: Optional[float] = None,
        gcr: float = 0.30,
        ilr: float = 1.30,
        project_life: int = 30,
        wacc: float = 0.06,
        weather: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> ProjectResult:
        """
        Run a complete solar PV simulation.
        
        Args:
            latitude: Site latitude.
            longitude: Site longitude.
            capacity_mw: Target DC capacity (if None, auto-size from land).
            land_area_ha: Land area for auto-sizing.
            gcr: Ground coverage ratio.
            ilr: Inverter loading ratio.
            project_life: Project lifetime in years.
            wacc: Weighted average cost of capital.
            **kwargs: Additional SolarConfig parameters.
        
        Returns:
            ProjectResult with simulation and financial results.
        """
        validate_latitude(latitude)
        validate_longitude(longitude)
        if weather is None:
            weather, weather_status = self._get_weather(latitude, longitude, "solar")
        else:
            weather_status = "caller_supplied_weather"
        
        # Configure
        config = SolarConfig(
            latitude=latitude,
            longitude=longitude,
            gcr=gcr,
            ilr=ilr,
            **kwargs
        )
        
        if land_area_ha:
            config.land_area_ha = land_area_ha
        elif capacity_mw:
            # Estimate land from capacity
            config.land_area_ha = capacity_mw * 1000 / (config.gcr * config.module_efficiency * 10000)
        
        # Simulate
        generator = SolarGenerator(config)
        sizing = generator.auto_size()
        sim_result = generator.simulate(weather, years=project_life)
        
        # Financial calculation
        annual_energy = sim_result.annual['energy_mwh'].tolist()
        fin_calc = LCOECalculator(FinancialConfig(wacc=wacc, project_life_years=project_life))
        fin_result = fin_calc.calculate_solar_lcoe(
            sizing.dc_capacity_kwp,
            annual_energy
        )
        
        return ProjectResult(
            solar_result=sim_result,
            financial_result=fin_result,
            notes={"weather": weather_status, **fin_result.notes},
        )
    
    def run_wind_simulation(
        self,
        latitude: float,
        longitude: float,
        capacity_mw: Optional[float] = None,
        land_area_ha: Optional[float] = None,
        turbine_model: str = "Generic 3MW",
        project_life: int = 30,
        wacc: float = 0.06,
        weather: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> ProjectResult:
        """
        Run a complete wind farm simulation.
        
        Args:
            latitude: Site latitude.
            longitude: Site longitude.
            capacity_mw: Target capacity (if None, auto-size from land).
            land_area_ha: Land area for auto-sizing.
            turbine_model: Turbine model from library.
            project_life: Project lifetime in years.
            wacc: Weighted average cost of capital.
            **kwargs: Additional WindConfig parameters.
        
        Returns:
            ProjectResult with simulation and financial results.
        """
        validate_latitude(latitude)
        validate_longitude(longitude)
        if weather is None:
            weather, weather_status = self._get_weather(latitude, longitude, "wind")
        else:
            weather_status = "caller_supplied_weather"
        
        # Configure
        config = WindConfig(
            latitude=latitude,
            longitude=longitude,
            turbine_model=turbine_model,
            **kwargs
        )
        
        if land_area_ha:
            config.land_area_ha = land_area_ha
        if capacity_mw is not None:
            config.grid_limit_mw = capacity_mw
        
        generator = WindGenerator(config)
        sizing = generator.auto_size(
            {"target_capacity_mw": capacity_mw} if capacity_mw is not None else None
        )
        sim_result = generator.simulate(weather, years=project_life)
        
        # Financial calculation
        annual_energy = sim_result.annual['energy_mwh'].tolist()
        fin_calc = LCOECalculator(FinancialConfig(wacc=wacc, project_life_years=project_life))
        fin_result = fin_calc.calculate_wind_lcoe(
            sizing.total_capacity_mw * 1000,
            annual_energy
        )
        
        return ProjectResult(
            wind_result=sim_result,
            financial_result=fin_result,
            notes={
                "weather": weather_status,
                "capacity_limit": ",".join(sizing.details.get("binding", [])),
                **fin_result.notes,
            },
        )
    
    def run_hybrid_simulation(
        self,
        latitude: float,
        longitude: float,
        solar_mw: float = 0,
        wind_mw: float = 0,
        battery_mwh: float = 0,
        battery_power_mw: Optional[float] = None,
        dispatch_strategy: str = "self_consumption",
        grid_limit_mw: Optional[float] = None,
        project_life: int = 30,
        wacc: float = 0.06,
        load_kw: Optional[pd.Series] = None,
        solar_weather: Optional[pd.DataFrame] = None,
        wind_weather: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> ProjectResult:
        """
        Run a hybrid PV+Wind+Battery case.

        If load_kw is omitted, no load is invented. Storage then only moves
        energy around grid_limit_mw. With neither a load nor an export limit,
        storage is left idle and its cost still enters LCOE.
        """
        validate_latitude(latitude)
        validate_longitude(longitude)
        if solar_mw < 0 or wind_mw < 0 or battery_mwh < 0:
            raise SimulationInputError("capacities must be >= 0")
        if solar_mw == 0 and wind_mw == 0:
            raise SimulationInputError("hybrid simulation needs solar_mw or wind_mw > 0")

        result = ProjectResult()
        notes: Dict[str, str] = {}
        series: Dict[str, pd.Series] = {}

        if solar_mw > 0:
            if solar_weather is None:
                solar_weather, solar_status = self._get_weather(latitude, longitude, "solar")
            else:
                solar_status = "caller_supplied_weather"
            notes["solar_weather"] = solar_status
            solar_config = SolarConfig(
                latitude=latitude,
                longitude=longitude,
                grid_limit_mw=max(solar_mw / 1.3, 0.001),
            )
            solar_config.land_area_ha = solar_mw * 1000 / (
                solar_config.gcr * solar_config.module_efficiency * 10000
            )
            solar_gen = SolarGenerator(solar_config)
            solar_gen.auto_size()
            result.solar_result = solar_gen.simulate(solar_weather, years=project_life)
            series["solar"] = result.solar_result.hourly["power_kw"]

        if wind_mw > 0:
            if wind_weather is None:
                wind_weather, wind_status = self._get_weather(latitude, longitude, "wind")
            else:
                wind_status = "caller_supplied_weather"
            notes["wind_weather"] = wind_status
            wind_config = WindConfig(
                latitude=latitude,
                longitude=longitude,
                grid_limit_mw=wind_mw,
            )
            wind_gen = WindGenerator(wind_config)
            wind_gen.auto_size({"target_capacity_mw": wind_mw})
            result.wind_result = wind_gen.simulate(wind_weather, years=project_life)
            series["wind"] = result.wind_result.hourly["power_kw"]

        names = list(series)
        index = series[names[0]].index
        if len(names) == 2:
            index = series["solar"].index.intersection(series["wind"].index)
            if len(index) < 2:
                raise SimulationInputError("solar and wind series do not share a time index")
        aligned = {name: series[name].reindex(index).fillna(0.0) for name in names}

        export_limit = None if grid_limit_mw is None else grid_limit_mw * 1000
        if load_kw is None:
            load = pd.Series(0.0, index=index)
            strategy = DispatchStrategy.MAXIMIZE_EXPORT
            notes["load"] = "no load series was provided; none was invented"
            if battery_mwh > 0 and export_limit is None:
                notes["storage_dispatch"] = "idle_no_load_and_no_export_limit"
            elif battery_mwh > 0:
                notes["storage_dispatch"] = "export_limit_shifting"
            else:
                notes["storage_dispatch"] = "no_storage"
        else:
            load = load_kw.reindex(index)
            if load.isna().any():
                raise SimulationInputError("load_kw does not cover the generation index")
            try:
                strategy = DispatchStrategy(dispatch_strategy)
            except ValueError as exc:
                raise SimulationInputError(
                    f"Unsupported dispatch strategy '{dispatch_strategy}'."
                ) from exc
            notes["load"] = "caller_supplied"
            notes["storage_dispatch"] = strategy.value

        controller = DispatchController(
            DispatchConfig(strategy=strategy, grid_export_limit_kw=export_limit)
        )
        for name, power in aligned.items():
            controller.add_generation(name, power)
        if battery_mwh > 0:
            battery_power = battery_power_mw or (battery_mwh / 4)
            controller.set_storage(
                BatteryStorage(
                    BatteryConfig(
                        capacity_kwh=battery_mwh * 1000,
                        power_kw=battery_power * 1000,
                    )
                )
            )
        dispatch = controller.optimize(load)
        result.dispatch_result = dispatch
        result.storage_result = dispatch.schedule[
            [
                "storage_charge_kw",
                "storage_discharge_kw",
                "storage_soc",
                "grid_import_kw",
                "grid_export_kw",
                "curtailment_kw",
            ]
        ]
        delivered_kw = dispatch.schedule["grid_export_kw"] + (
            dispatch.schedule["load_served_kw"] - dispatch.schedule["grid_import_kw"]
        ).clip(lower=0)
        year1_delivered_mwh = integrate_power_kwh(delivered_kw) / 1000.0

        gross = []
        for year in range(1, project_life + 1):
            year_energy = 0.0
            if result.solar_result is not None:
                year_energy += float(
                    result.solar_result.annual.loc[
                        result.solar_result.annual["year"] == year, "energy_mwh"
                    ].iloc[0]
                )
            if result.wind_result is not None:
                year_energy += float(
                    result.wind_result.annual.loc[
                        result.wind_result.annual["year"] == year, "energy_mwh"
                    ].iloc[0]
                )
            gross.append(year_energy)
        if gross[0] > 0:
            annual_energy = [year1_delivered_mwh * (value / gross[0]) for value in gross]
        else:
            annual_energy = [0.0 for _ in gross]
        notes["energy_basis"] = (
            "Year-1 delivered energy (grid export plus load served from the project, "
            "excluding grid import) is scaled by each year's gross generation divided by "
            "year-1 gross generation. Dispatch is not re-solved for later years."
        )

        hybrid_capex = HybridCapex()
        hybrid_opex = HybridOpex()
        solar_kw = 0.0
        if result.solar_result is not None:
            solar_kw = float(result.solar_result.metadata["sizing"]["dc_capacity_mwp"]) * 1000.0
            notes["solar_capacity_mw"] = f"{solar_kw / 1000.0:.6f} DC built"
        wind_kw = 0.0
        if result.wind_result is not None:
            wind_kw = float(result.wind_result.metadata["sizing"]["total_capacity_mw"]) * 1000.0
            notes["wind_capacity_mw"] = (
                f"{wind_kw / 1000.0:.6f} nameplate built from a {wind_mw:g} MW request"
            )
        battery_kwh = battery_mwh * 1000 if battery_mwh > 0 else 0
        fin_calc = LCOECalculator(FinancialConfig(wacc=wacc, project_life_years=project_life))
        result.financial_result = fin_calc.calculate_hybrid_lcoe(
            solar_kw=solar_kw,
            wind_kw=wind_kw,
            battery_kwh=battery_kwh,
            annual_energy_mwh=annual_energy,
            capex=hybrid_capex,
            opex=hybrid_opex,
        )
        floor = fin_calc.calculate_floor_ppa(
            hybrid_capex.total(solar_kw, wind_kw, battery_kwh),
            hybrid_opex.annual_total(solar_kw, wind_kw, battery_kwh),
            annual_energy,
        )
        notes["floor_ppa_usd_per_mwh"] = f"{floor:.6f}"
        notes.update(result.financial_result.notes)
        result.notes = notes
        return result
    
    def optimize_lcoe(
        self,
        latitude: float,
        longitude: float,
        variables: Dict[str, tuple],
        algorithm: str = "grid_search",
        n_iterations: int = 100,
        **kwargs
    ) -> OptimizationResult:
        """
        Optimize system configuration to minimize LCOE.
        
        Args:
            latitude: Site latitude.
            longitude: Site longitude.
            variables: Dict of {name: (min, max, step)} for each variable.
            algorithm: Optimization algorithm.
            n_iterations: Number of iterations for random/genetic.
        
        Returns:
            OptimizationResult with optimal configuration.
        
        Example:
            >>> result = api.optimize_lcoe(
            ...     latitude=31.6,
            ...     longitude=-8.0,
            ...     variables={
            ...         'solar_mw': (10, 100, 10),
            ...         'wind_mw': (0, 50, 10),
            ...         'battery_mwh': (0, 200, 50),
            ...     }
            ... )
        """
        def simulation_func(config: Dict[str, float]) -> Dict[str, float]:
            result = self.run_hybrid_simulation(
                latitude=latitude,
                longitude=longitude,
                solar_mw=config.get('solar_mw', 0),
                wind_mw=config.get('wind_mw', 0),
                battery_mwh=config.get('battery_mwh', 0),
                project_life=kwargs.get('project_life', 30),
                wacc=kwargs.get('wacc', 0.06)
            )
            
            return {
                'lcoe': result.lcoe,
                'annual_energy_mwh': result.total_annual_energy_mwh,
                'capacity_mw': config.get('solar_mw', 0) + config.get('wind_mw', 0),
            }
        
        opt_config = OptimizationConfig(n_iterations=n_iterations)
        optimizer = LCOEOptimizer(simulation_func, opt_config)
        
        for name, (min_val, max_val, step) in variables.items():
            optimizer.add_variable(name, min_val, max_val, step=step)
        
        return optimizer.run(algorithm=algorithm)
    
    def _get_weather(
        self,
        latitude: float,
        longitude: float,
        source_type: str = 'solar'
    ) -> tuple:
        """Get weather data with caching."""
        cache_key = f"{latitude:.2f}_{longitude:.2f}_{source_type}"
        
        if cache_key in self._weather_cache:
            return self._weather_cache[cache_key]

        if source_type == "solar" and self.allow_network:
            weather, status = fetch_pvgis_tmy(latitude, longitude)
            if weather is None:
                weather = generate_synthetic_solar_tmy(latitude, longitude)
                status = (
                    f"{status} Fell back to a synthetic solar series seeded from "
                    "latitude and longitude. That series is not a climate dataset."
                )
        elif source_type == "solar":
            weather = generate_synthetic_solar_tmy(latitude, longitude)
            status = (
                "Synthetic solar series seeded from latitude and longitude. "
                "Schematic sin(elevation) GHI with an Erbs DNI/DHI split. Not a climate dataset."
            )
        else:
            weather = generate_synthetic_wind_tmy(latitude, longitude)
            status = (
                "Synthetic wind series seeded from latitude and longitude. "
                "Weibull shape 2 with a schematic scale. Not a wind atlas."
            )

        self._weather_cache[cache_key] = (weather, status)
        return weather, status
    
    def calculate_floor_ppa(
        self,
        latitude: float,
        longitude: float,
        solar_mw: float = 0,
        wind_mw: float = 0,
        battery_mwh: float = 0,
        wacc: float = 0.06,
        project_life: int = 30
    ) -> float:
        """
        Year-1 PPA ($/MWh) that sets NPV to zero for this hybrid case.

        Equals LCOE when revenue escalation is zero and grid charges are off.
        """
        result = self.run_hybrid_simulation(
            latitude=latitude,
            longitude=longitude,
            solar_mw=solar_mw,
            wind_mw=wind_mw,
            battery_mwh=battery_mwh,
            project_life=project_life,
            wacc=wacc,
        )
        raw = result.notes.get("floor_ppa_usd_per_mwh")
        if raw is None:
            return float("inf")
        return float(raw)
