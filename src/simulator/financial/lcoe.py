"""
LCOE (Levelized Cost of Energy) Calculator.

Professional-grade financial model for renewable energy projects with:
- LCOE, NPV, IRR calculations
- Floor PPA (break-even tariff) calculation
- Multi-year cash flow modeling
- Support for hybrid projects
"""

import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Union

from simulator.financial.capex import SolarCapex, WindCapex, BatteryCapex, HybridCapex
from simulator.financial.opex import SolarOpex, WindOpex, BatteryOpex, HybridOpex
from simulator.financial.tariffs import GridTariff, MoroccoGridTariffs
from simulator.core.types import FinancialResult
from simulator.core.validation import (
    SimulationInputError,
    require_non_negative,
    validate_wacc,
)


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
        self.config.wacc = validate_wacc(self.config.wacc)
        if self.config.project_life_years < 1:
            raise SimulationInputError("project_life_years must be >= 1")
        self.cash_flows: List[Dict] = []
        self.last_result: Optional[FinancialResult] = None

    @staticmethod
    def _model_notes() -> Dict[str, str]:
        return {
            "discounting": "Single user-supplied WACC. debt_ratio, cost_of_debt, and cost_of_equity are not used.",
            "tax": "corporate_tax_rate and depreciation_years are not applied. Cash flows are pre-tax.",
            "construction": "construction_period_years is not applied. The full capital spend is in year 0.",
            "payback": "payback_years is the first operating year in which undiscounted cumulative cash flow is >= 0.",
            "lcoe": "LCOE is discounted capex and inflated opex divided by discounted energy. It does not subtract grid charges.",
        }
    
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
        r = validate_wacc(self.config.wacc)
        n = len(annual_energy_mwh)
        if n == 0:
            raise SimulationInputError("annual_energy_mwh must contain at least one year")
        total_capex = require_non_negative("total_capex", total_capex)
        annual_opex_base = require_non_negative("annual_opex", annual_opex_base)
        annual_energy_mwh = [require_non_negative("annual_energy_mwh", value) for value in annual_energy_mwh]
        
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
        
        lcoe = discounted_costs / discounted_energy if discounted_energy > 0 else float("inf")
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
            },
            notes=self._model_notes(),
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
    
    @staticmethod
    def _npv_at(rate: float, cash_flows: List[float]) -> float:
        return sum(cf / (1 + rate) ** t for t, cf in enumerate(cash_flows))

    def _calculate_irr(
        self,
        max_iterations: int = 100,
        tolerance: float = 1e-8
    ) -> Optional[float]:
        """Single-root IRR by bisection. Returns None when no sign change is found.

        The search assumes one sign change. It does not return a rate merely
        because the search interval ran out.
        """
        cash_flows = [cf['net_cash_flow'] for cf in self.cash_flows]
        low = -0.9
        high = 1.0
        npv_low = self._npv_at(low, cash_flows)
        npv_high = self._npv_at(high, cash_flows)
        expands = 0
        while npv_low * npv_high > 0 and expands < 30 and high < 1e6:
            high = high * 2 + 0.5
            npv_high = self._npv_at(high, cash_flows)
            expands += 1
        if npv_low == 0:
            return low
        if npv_high == 0:
            return high
        if npv_low * npv_high > 0:
            return None

        for _ in range(max_iterations):
            mid = (low + high) / 2
            npv = self._npv_at(mid, cash_flows)
            if abs(npv) < tolerance:
                return mid
            if npv_low * npv > 0:
                low = mid
                npv_low = npv
            else:
                high = mid
                npv_high = npv
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
        r = validate_wacc(self.config.wacc)
        n = len(annual_energy_mwh)
        if n == 0:
            raise SimulationInputError("annual_energy_mwh must contain at least one year")
        total_capex = require_non_negative("total_capex", total_capex)
        annual_opex_base = require_non_negative("annual_opex", annual_opex_base)

        discounted_energy = 0.0
        discounted_escalated_energy = 0.0
        discounted_opex = 0.0

        for t in range(1, n + 1):
            discount_factor = 1 / (1 + r) ** t
            escalation = (1 + self.config.revenue_escalation) ** (t - 1)
            opex_t = annual_opex_base * (1 + self.config.opex_inflation) ** (t - 1)
            discounted_opex += opex_t * discount_factor
            energy_t = require_non_negative("annual_energy_mwh", annual_energy_mwh[t - 1])
            discounted_energy += energy_t * discount_factor
            discounted_escalated_energy += energy_t * escalation * discount_factor

        grid_cost_per_mwh = 0.0
        if self.config.use_grid_tariffs:
            if isinstance(self.config.grid_tariff, MoroccoGridTariffs):
                grid_cost_per_mwh = self.config.grid_tariff.total_usd_per_mwh()
            else:
                grid_cost_per_mwh = self.config.grid_tariff.import_rate * 1000

        # Year-1 tariff such that discounted (tariff * escalation - grid charge) covers costs.
        if discounted_escalated_energy <= 0:
            return float("inf")
        return (total_capex + discounted_opex + grid_cost_per_mwh * discounted_energy) / discounted_escalated_energy
    
    def sensitivity_analysis(
        self,
        base_result: FinancialResult,
        parameter: str,
        variations: List[float]
    ) -> pd.DataFrame:
        """Not implemented.

        The previous body multiplied the base LCOE by each factor. That is not
        a recalculation of capex, opex, WACC, or energy, so the method raises.
        """
        raise NotImplementedError(
            "sensitivity_analysis used to multiply the base LCOE by each factor. "
            "That is not a recalculation, so it no longer returns those values."
        )
    
    def get_cash_flow_df(self) -> pd.DataFrame:
        """Return cash flows as DataFrame."""
        return pd.DataFrame(self.cash_flows)
