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
from simulator.core.types import SimulationResult, OptimizationResult, FinancialResult


@dataclass
class ProjectResult:
    """Combined result from a full project simulation."""
    solar_result: Optional[SimulationResult] = None
    wind_result: Optional[SimulationResult] = None
    storage_result: Optional[pd.DataFrame] = None
    dispatch_result: Optional[Any] = None
    financial_result: Optional[FinancialResult] = None
    
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
        """Project LCOE."""
        if self.financial_result:
            return self.financial_result.lcoe
        return 0.0


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
    
    def __init__(self, default_wacc: float = 0.06, project_life: int = 30):
        self.default_wacc = default_wacc
        self.project_life = project_life
        self._weather_cache: Dict[str, pd.DataFrame] = {}
    
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
        # Get weather data
        weather, _ = self._get_weather(latitude, longitude, 'solar')
        
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
            financial_result=fin_result
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
        # Get weather data
        weather, _ = self._get_weather(latitude, longitude, 'wind')
        
        # Configure
        config = WindConfig(
            latitude=latitude,
            longitude=longitude,
            turbine_model=turbine_model,
            **kwargs
        )
        
        if land_area_ha:
            config.land_area_ha = land_area_ha
        elif capacity_mw:
            config.grid_limit_mw = capacity_mw
        
        # Simulate
        generator = WindGenerator(config)
        sizing = generator.auto_size()
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
            financial_result=fin_result
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
        **kwargs
    ) -> ProjectResult:
        """
        Run a hybrid PV+Wind+Battery simulation.
        
        Args:
            latitude: Site latitude.
            longitude: Site longitude.
            solar_mw: Solar DC capacity in MW.
            wind_mw: Wind capacity in MW.
            battery_mwh: Battery energy capacity in MWh.
            battery_power_mw: Battery power (defaults to capacity/4).
            dispatch_strategy: Dispatch strategy name.
            grid_limit_mw: Grid export limit.
            project_life: Project lifetime in years.
            wacc: Weighted average cost of capital.
        
        Returns:
            ProjectResult with all simulation results.
        """
        result = ProjectResult()
        total_generation = None
        
        # Solar simulation
        if solar_mw > 0:
            solar_weather, _ = self._get_weather(latitude, longitude, 'solar')
            solar_config = SolarConfig(
                latitude=latitude,
                longitude=longitude,
                grid_limit_mw=solar_mw / 1.3,  # Estimate AC from DC
            )
            solar_config.land_area_ha = solar_mw * 1000 / (solar_config.gcr * solar_config.module_efficiency * 10000)
            
            solar_gen = SolarGenerator(solar_config)
            solar_gen.auto_size()
            result.solar_result = solar_gen.simulate(solar_weather, years=project_life)
            
            total_generation = result.solar_result.hourly['power_kw']
        
        # Wind simulation
        if wind_mw > 0:
            wind_weather, _ = self._get_weather(latitude, longitude, 'wind')
            wind_config = WindConfig(
                latitude=latitude,
                longitude=longitude,
                grid_limit_mw=wind_mw,
            )
            
            wind_gen = WindGenerator(wind_config)
            wind_gen.auto_size()
            result.wind_result = wind_gen.simulate(wind_weather, years=project_life)
            
            if total_generation is not None:
                # Align indices
                wind_power = result.wind_result.hourly['power_kw'].reindex(total_generation.index).fillna(0)
                total_generation = total_generation + wind_power
            else:
                total_generation = result.wind_result.hourly['power_kw']
        
        # Battery simulation
        if battery_mwh > 0 and total_generation is not None:
            battery_power = battery_power_mw or (battery_mwh / 4)
            battery_config = BatteryConfig(
                capacity_kwh=battery_mwh * 1000,
                power_kw=battery_power * 1000
            )
            
            battery = BatteryStorage(battery_config)
            
            # Create dummy load for dispatch
            load = pd.Series(0, index=total_generation.index)
            
            result.storage_result = battery.simulate(
                total_generation,
                load,
                dispatch_strategy=dispatch_strategy
            )
        
        # Financial calculation
        if solar_mw > 0 or wind_mw > 0:
            # Combine annual energy
            annual_energy = []
            for year in range(1, project_life + 1):
                year_energy = 0
                if result.solar_result:
                    year_energy += result.solar_result.annual.loc[result.solar_result.annual['year'] == year, 'energy_mwh'].values[0]
                if result.wind_result:
                    year_energy += result.wind_result.annual.loc[result.wind_result.annual['year'] == year, 'energy_mwh'].values[0]
                annual_energy.append(year_energy)
            
            fin_calc = LCOECalculator(FinancialConfig(wacc=wacc, project_life_years=project_life))
            hybrid_capex = HybridCapex()
            hybrid_opex = HybridOpex()
            
            result.financial_result = fin_calc.calculate_hybrid_lcoe(
                solar_kw=solar_mw * 1000 if solar_mw > 0 else 0,
                wind_kw=wind_mw * 1000 if wind_mw > 0 else 0,
                battery_kwh=battery_mwh * 1000 if battery_mwh > 0 else 0,
                annual_energy_mwh=annual_energy,
                capex=hybrid_capex,
                opex=hybrid_opex
            )
        
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
            return self._weather_cache[cache_key], "Using cached weather data"
        
        if source_type == 'solar':
            weather, status = fetch_pvgis_tmy(latitude, longitude)
            if weather is None:
                weather = generate_synthetic_solar_tmy(latitude)
                status = "Using synthetic solar TMY"
        else:
            weather = generate_synthetic_wind_tmy(latitude)
            status = "Using synthetic wind TMY"
        
        self._weather_cache[cache_key] = weather
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
        Calculate minimum PPA tariff for NPV = 0.
        
        Returns:
            Floor PPA in $/MWh.
        """
        result = self.run_hybrid_simulation(
            latitude=latitude,
            longitude=longitude,
            solar_mw=solar_mw,
            wind_mw=wind_mw,
            battery_mwh=battery_mwh,
            project_life=project_life,
            wacc=wacc
        )
        
        if result.financial_result:
            # LCOE approximates floor PPA
            return result.financial_result.lcoe
        return 0.0
