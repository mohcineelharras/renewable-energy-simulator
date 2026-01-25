"""
LCOE (Levelized Cost of Energy) Calculator.

Professional-grade financial model for renewable energy projects with:
- LCOE, NPV, IRR calculations
- Floor PPA (break-even tariff) calculation
- Multi-year cash flow modeling
- Support for hybrid projects
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Union

from simulator.financial.capex import SolarCapex, WindCapex, BatteryCapex, HybridCapex
from simulator.financial.opex import SolarOpex, WindOpex, BatteryOpex, HybridOpex
from simulator.financial.tariffs import GridTariff, MoroccoGridTariffs
from simulator.core.types import FinancialResult


@dataclass
class FinancialConfig:
    """Configuration for financial calculations."""
    # Discount rate
    wacc: float = 0.06  # 6% default
    
    # Project parameters
    project_life_years: int = 30
    construction_period_years: int = 1
    
    # Financing structure
    debt_ratio: float = 0.70  # 70% debt / 30% equity
    cost_of_debt: float = 0.07
    cost_of_equity: float = 0.13
    
    # Inflation
    opex_inflation: float = 0.02  # 2%/year
    revenue_escalation: float = 0.0  # PPA escalation
    
    # Revenue
    ppa_tariff_usd_per_mwh: float = 50.0
    
    # Grid tariffs
    use_grid_tariffs: bool = False
    grid_tariff: Union[GridTariff, MoroccoGridTariffs] = field(default_factory=GridTariff)
    
    # Tax (simplified)
    corporate_tax_rate: float = 0.25
    depreciation_years: int = 20


class LCOECalculator:
    """
    Professional LCOE calculator for renewable energy projects.
    
    Calculates:
    - LCOE (Levelized Cost of Energy)
    - NPV (Net Present Value)
    - IRR (Internal Rate of Return)
    - Floor PPA (minimum break-even tariff)
    - Payback period
    
    Example:
        >>> calc = LCOECalculator(FinancialConfig(wacc=0.06, project_life_years=30))
        >>> result = calc.calculate_solar_lcoe(
        ...     capacity_kw=50000,
        ...     annual_energy_mwh=[100000, 99500, 99000, ...],  # 30 years
        ...     capex=SolarCapex(),
        ...     opex=SolarOpex()
        ... )
        >>> print(f"LCOE: ${result.lcoe:.2f}/MWh")
    """
    
    def __init__(self, config: Optional[FinancialConfig] = None):
        self.config = config or FinancialConfig()
        self.cash_flows: List[Dict] = []
        self.last_result: Optional[FinancialResult] = None
    
    def calculate_solar_lcoe(
        self,
        capacity_kw: float,
        annual_energy_mwh: List[float],
        capex: Optional[SolarCapex] = None,
        opex: Optional[SolarOpex] = None
    ) -> FinancialResult:
        """Calculate LCOE for a solar project."""
        if capex is None:
            capex = SolarCapex()
        if opex is None:
            opex = SolarOpex()
        
        total_capex = capex.total_for_capacity(capacity_kw)
        annual_opex_base = opex.total_for_capacity(capacity_kw)
        
        return self._calculate_lcoe(
            total_capex,
            annual_opex_base,
            annual_energy_mwh,
            capex.breakdown(),
            opex.breakdown()
        )
    
    def calculate_wind_lcoe(
        self,
        capacity_kw: float,
        annual_energy_mwh: List[float],
        capex: Optional[WindCapex] = None,
        opex: Optional[WindOpex] = None
    ) -> FinancialResult:
        """Calculate LCOE for a wind project."""
        if capex is None:
            capex = WindCapex()
        if opex is None:
            opex = WindOpex()
        
        total_capex = capex.total_for_capacity(capacity_kw)
        annual_opex_base = opex.total_for_capacity(capacity_kw)
        
        return self._calculate_lcoe(
            total_capex,
            annual_opex_base,
            annual_energy_mwh,
            capex.breakdown(),
            opex.breakdown()
        )
    
    def calculate_hybrid_lcoe(
        self,
        solar_kw: float = 0,
        wind_kw: float = 0,
        battery_kwh: float = 0,
        annual_energy_mwh: List[float] = None,
        capex: Optional[HybridCapex] = None,
        opex: Optional[HybridOpex] = None
    ) -> FinancialResult:
        """Calculate LCOE for a hybrid project."""
        if capex is None:
            capex = HybridCapex()
        if opex is None:
            opex = HybridOpex()
        
        total_capex = capex.total(solar_kw, wind_kw, battery_kwh)
        annual_opex_base = opex.annual_total(solar_kw, wind_kw, battery_kwh)
        
        capex_breakdown = capex.breakdown(solar_kw, wind_kw, battery_kwh)
        opex_breakdown = opex.breakdown(solar_kw, wind_kw, battery_kwh)
        
        return self._calculate_lcoe(
            total_capex,
            annual_opex_base,
            annual_energy_mwh or [],
            capex_breakdown,
            opex_breakdown
        )
    
    def _calculate_lcoe(
        self,
        total_capex: float,
        annual_opex_base: float,
        annual_energy_mwh: List[float],
        capex_breakdown: Dict[str, float],
        opex_breakdown: Dict[str, float]
    ) -> FinancialResult:
        """Core LCOE calculation with full cash flow model."""
        r = self.config.wacc
        n = len(annual_energy_mwh)
        
        if n == 0:
            return FinancialResult(lcoe=0, npv=0)
        
        # Initialize cash flow tracking
        self.cash_flows = []
        discounted_costs = total_capex  # Year 0
        discounted_energy = 0.0
        cumulative_cash_flow = -total_capex
        payback_year = None
        
        # Year 0 - Construction
        self.cash_flows.append({
            'year': 0,
            'capex': total_capex,
            'opex': 0,
            'energy_mwh': 0,
            'revenue': 0,
            'net_cash_flow': -total_capex,
            'cumulative_cf': cumulative_cash_flow,
            'discount_factor': 1.0,
        })
        
        # Operating years
        for t in range(1, n + 1):
            discount_factor = 1 / (1 + r) ** t
            
            # OPEX with inflation
            opex_t = annual_opex_base * (1 + self.config.opex_inflation) ** (t - 1)
            discounted_costs += opex_t * discount_factor
            
            # Energy
            energy_t = annual_energy_mwh[t - 1]
            discounted_energy += energy_t * discount_factor
            
            # Revenue with escalation
            escalated_tariff = self.config.ppa_tariff_usd_per_mwh * (
                1 + self.config.revenue_escalation
            ) ** (t - 1)
            
            # Grid tariff adjustment
            if self.config.use_grid_tariffs:
                if isinstance(self.config.grid_tariff, MoroccoGridTariffs):
                    grid_cost_per_mwh = self.config.grid_tariff.total_usd_per_mwh()
                else:
                    grid_cost_per_mwh = self.config.grid_tariff.import_rate * 1000
                revenue_t = (escalated_tariff - grid_cost_per_mwh) * energy_t
            else:
                revenue_t = escalated_tariff * energy_t
            
            # Net cash flow
            net_cf = revenue_t - opex_t
            cumulative_cash_flow += net_cf
            
            # Payback period
            if payback_year is None and cumulative_cash_flow >= 0:
                payback_year = t
            
            self.cash_flows.append({
                'year': t,
                'capex': 0,
                'opex': opex_t,
                'energy_mwh': energy_t,
                'revenue': revenue_t,
                'net_cash_flow': net_cf,
                'cumulative_cf': cumulative_cash_flow,
                'discount_factor': discount_factor,
            })
        
        # Calculate metrics
        lcoe = discounted_costs / discounted_energy if discounted_energy > 0 else 0
        npv = self._calculate_npv()
        irr = self._calculate_irr()
        
        # Totals
        total_energy = sum(annual_energy_mwh)
        total_revenue = sum(cf['revenue'] for cf in self.cash_flows)
        total_opex = sum(cf['opex'] for cf in self.cash_flows)
        
        self.last_result = FinancialResult(
            lcoe=lcoe,
            npv=npv,
            irr=irr * 100 if irr else None,
            payback_years=payback_year,
            total_capex=total_capex,
            total_opex=total_opex,
            total_revenue=total_revenue,
            cash_flows=pd.DataFrame(self.cash_flows),
            breakdown={
                'capex': capex_breakdown,
                'opex': opex_breakdown,
            }
        )
        
        return self.last_result
    
    def _calculate_npv(self) -> float:
        """Calculate Net Present Value."""
        r = self.config.wacc
        npv = 0.0
        for cf in self.cash_flows:
            t = cf['year']
            if t == 0:
                npv += cf['net_cash_flow']
            else:
                npv += cf['net_cash_flow'] / (1 + r) ** t
        return npv
    
    def _calculate_irr(
        self,
        max_iterations: int = 1000,
        tolerance: float = 1e-6
    ) -> Optional[float]:
        """Calculate Internal Rate of Return using binary search."""
        cash_flows = [cf['net_cash_flow'] for cf in self.cash_flows]
        
        # Check if IRR exists
        if sum(cash_flows) <= 0:
            return None
        
        low = -0.99
        high = 1.0
        
        for _ in range(max_iterations):
            mid = (low + high) / 2
            npv = sum(cf / (1 + mid) ** t for t, cf in enumerate(cash_flows))
            
            if abs(npv) < tolerance:
                return mid
            elif npv > 0:
                low = mid
            else:
                high = mid
        
        return (low + high) / 2
    
    def calculate_floor_ppa(
        self,
        total_capex: float,
        annual_opex_base: float,
        annual_energy_mwh: List[float]
    ) -> float:
        """
        Calculate the minimum PPA tariff needed for NPV = 0.
        
        This is the "floor price" at which the project breaks even.
        """
        r = self.config.wacc
        n = len(annual_energy_mwh)
        
        if n == 0:
            return 0.0
        
        # Calculate discounted energy and costs
        discounted_energy = 0.0
        discounted_opex = 0.0
        
        for t in range(1, n + 1):
            discount_factor = 1 / (1 + r) ** t
            
            # OPEX with inflation
            opex_t = annual_opex_base * (1 + self.config.opex_inflation) ** (t - 1)
            discounted_opex += opex_t * discount_factor
            
            # Energy
            energy_t = annual_energy_mwh[t - 1]
            discounted_energy += energy_t * discount_factor
        
        # Total discounted costs
        total_discounted_costs = total_capex + discounted_opex
        
        # Grid tariff adjustment
        grid_cost_per_mwh = 0.0
        if self.config.use_grid_tariffs:
            if isinstance(self.config.grid_tariff, MoroccoGridTariffs):
                grid_cost_per_mwh = self.config.grid_tariff.total_usd_per_mwh()
            else:
                grid_cost_per_mwh = self.config.grid_tariff.import_rate * 1000
        
        # Floor PPA calculation
        # NPV = 0 → PPA × Discounted_Energy - Grid × Discounted_Energy = Costs
        if discounted_energy > 0:
            floor_ppa = (total_discounted_costs / discounted_energy) + grid_cost_per_mwh
        else:
            floor_ppa = 0.0
        
        return floor_ppa
    
    def sensitivity_analysis(
        self,
        base_result: FinancialResult,
        parameter: str,
        variations: List[float]
    ) -> pd.DataFrame:
        """
        Run sensitivity analysis on a parameter.
        
        Args:
            base_result: Base case result
            parameter: Parameter to vary ('capex', 'opex', 'wacc', 'energy')
            variations: List of variation factors (e.g., [0.8, 0.9, 1.0, 1.1, 1.2])
        
        Returns:
            DataFrame with LCOE for each variation
        """
        results = []
        base_lcoe = base_result.lcoe
        
        for factor in variations:
            results.append({
                'factor': factor,
                'lcoe': base_lcoe * factor,  # Simplified - full implementation would recalculate
                'change_pct': (factor - 1) * 100,
            })
        
        return pd.DataFrame(results)
    
    def get_cash_flow_df(self) -> pd.DataFrame:
        """Return cash flows as DataFrame."""
        return pd.DataFrame(self.cash_flows)
