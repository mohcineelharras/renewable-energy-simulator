"""
Professional Financial Model for Utility-Scale Renewable Energy Projects
Includes Morocco-specific grid tariffs and fiscal parameters.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, Optional, List

@dataclass
class SolarCapex:
    """CAPEX breakdown for utility-scale solar PV ($/kWdc)."""
    modules: float = 115.0  # $100-130
    inverters: float = 40.0  # $30-50
    mounting_trackers: float = 100.0  # $80-120 (single-axis)
    bop_electrical: float = 160.0  # $120-200 (cables, combiners, civils)
    epc_percent: float = 0.12  # 10-15% of equipment
    grid_connection: float = 75.0  # $50-100
    development: float = 40.0  # $25-50 (permits, legal, environmental)
    
    def total_per_kwdc(self) -> float:
        equipment = self.modules + self.inverters + self.mounting_trackers + self.bop_electrical
        epc = equipment * self.epc_percent
        return equipment + epc + self.grid_connection + self.development
    
    def breakdown(self) -> Dict[str, float]:
        equipment = self.modules + self.inverters + self.mounting_trackers + self.bop_electrical
        epc = equipment * self.epc_percent
        return {
            'Modules': self.modules,
            'Inverters': self.inverters,
            'Mounting/Trackers': self.mounting_trackers,
            'BOP/Electrical': self.bop_electrical,
            'EPC': epc,
            'Grid Connection': self.grid_connection,
            'Development': self.development
        }

@dataclass
class WindCapex:
    """CAPEX breakdown for utility-scale onshore wind ($/kW)."""
    turbine_tower: float = 1048.0  # Turbine + tower
    foundations: float = 96.0
    installation: float = 124.0  # Cranes, heavy lifting
    grid_connection: float = 94.0
    development_bos: float = 157.0  # Site prep, roads
    contingency: float = 118.0  # Risk, insurance, commissioning
    
    def total_per_kw(self) -> float:
        return (self.turbine_tower + self.foundations + self.installation + 
                self.grid_connection + self.development_bos + self.contingency)
    
    def breakdown(self) -> Dict[str, float]:
        return {
            'Turbine & Tower': self.turbine_tower,
            'Foundations': self.foundations,
            'Installation': self.installation,
            'Grid Connection': self.grid_connection,
            'Development/BOS': self.development_bos,
            'Contingency': self.contingency
        }

@dataclass
class SolarOpex:
    """OPEX breakdown for utility-scale solar PV ($/kW/year)."""
    scheduled_maintenance: float = 12.0  # $10-15
    unscheduled_repairs: float = 4.0  # $3-5
    insurance: float = 3.0  # $2-4
    land_lease: float = 2.0  # $1-3
    administrative: float = 1.5  # $1-2
    
    def total_per_kw_year(self) -> float:
        return (self.scheduled_maintenance + self.unscheduled_repairs + 
                self.insurance + self.land_lease + self.administrative)
    
    def breakdown(self) -> Dict[str, float]:
        return {
            'Scheduled Maintenance': self.scheduled_maintenance,
            'Unscheduled Repairs': self.unscheduled_repairs,
            'Insurance': self.insurance,
            'Land Lease': self.land_lease,
            'Administrative': self.administrative
        }

@dataclass
class WindOpex:
    """OPEX breakdown for utility-scale onshore wind ($/kW/year)."""
    scheduled_maintenance: float = 32.0  # $30-35
    unscheduled_repairs: float = 12.0  # $10-15
    insurance: float = 4.0  # $3-6
    land_lease: float = 3.0  # $2-5
    administrative: float = 3.0  # $2-4
    
    def total_per_kw_year(self) -> float:
        return (self.scheduled_maintenance + self.unscheduled_repairs + 
                self.insurance + self.land_lease + self.administrative)
    
    def breakdown(self) -> Dict[str, float]:
        return {
            'Scheduled Maintenance': self.scheduled_maintenance,
            'Unscheduled Repairs': self.unscheduled_repairs,
            'Insurance': self.insurance,
            'Land Lease': self.land_lease,
            'Administrative': self.administrative
        }

@dataclass
class MoroccoGridTariffs:
    """Morocco ANRE grid usage tariffs (2025-2027)."""
    turt_transmission: float = 6.68  # MAD centimes/kWh
    turd_distribution: float = 5.92  # MAD centimes/kWh
    tss_system_services: float = 6.64  # MAD centimes/kWh
    mad_to_usd: float = 0.10  # Approximate MAD to USD rate
    
    def total_centimes_per_kwh(self) -> float:
        return self.turt_transmission + self.turd_distribution + self.tss_system_services
    
    def total_usd_per_mwh(self) -> float:
        """Convert to USD/MWh for PPA modeling."""
        total_centimes = self.total_centimes_per_kwh()
        total_mad = total_centimes / 100  # centimes to MAD
        total_usd = total_mad * self.mad_to_usd
        return total_usd * 1000  # $/kWh to $/MWh

@dataclass
class FinancialConfig:
    """Financial configuration for LCOE calculation."""
    wacc: float = 0.06  # 6% default (can be 6-10% depending on risk)
    project_life_years: int = 30
    debt_ratio: float = 0.70  # 70% debt / 30% equity
    cost_of_debt: float = 0.07  # 6-8%
    cost_of_equity: float = 0.13  # 12-15%
    opex_inflation: float = 0.02  # 2%/year
    
    # Revenue parameters
    ppa_tariff_usd_per_mwh: float = 50.0  # $/MWh
    use_morocco_grid_tariffs: bool = False
    morocco_tariffs: MoroccoGridTariffs = field(default_factory=MoroccoGridTariffs)

class FinancialModel:
    """
    Professional financial model for renewable energy projects.
    Calculates LCOE, NPV, IRR, and payback period.
    """
    
    def __init__(self, config: FinancialConfig):
        self.config = config
        self.cash_flows: list = []
        self.results: Dict = {}
    
    def calculate_solar_lcoe(self, 
                             capacity_kwdc: float, 
                             annual_energy_mwh_list: List[float],
                             capex: SolarCapex = None,
                             opex: SolarOpex = None) -> Dict:
        """
        Calculate LCOE for a solar project.
        
        LCOE = Σ(CAPEX_t + OPEX_t) / (1+r)^t  ÷  Σ(Energy_t × (1-d)^t) / (1+r)^t
        """
        if capex is None:
            capex = SolarCapex()
        if opex is None:
            opex = SolarOpex()
        
        # Total CAPEX
        total_capex = capex.total_per_kwdc() * capacity_kwdc
        
        # Annual OPEX (with inflation)
        annual_opex_base = opex.total_per_kw_year() * capacity_kwdc
        
        return self._calculate_lcoe(total_capex, annual_opex_base, annual_energy_mwh_list, capex.breakdown(), opex.breakdown())
    
    def calculate_wind_lcoe(self,
                            capacity_kw: float,
                            annual_energy_mwh_list: List[float],
                            capex: WindCapex = None,
                            opex: WindOpex = None) -> Dict:
        """Calculate LCOE for a wind project."""
        if capex is None:
            capex = WindCapex()
        if opex is None:
            opex = WindOpex()
        
        # Total CAPEX
        total_capex = capex.total_per_kw() * capacity_kw
        
        # Annual OPEX (with inflation)
        annual_opex_base = opex.total_per_kw_year() * capacity_kw
        
        return self._calculate_lcoe(total_capex, annual_opex_base, annual_energy_mwh_list, capex.breakdown(), opex.breakdown())
    
    def _calculate_lcoe(self, 
                        total_capex: float, 
                        annual_opex_base: float, 
                        annual_energy_mwh_list: List[float],
                        capex_breakdown: Dict,
                        opex_breakdown: Dict) -> Dict:
        """Core LCOE calculation."""
        r = self.config.wacc
        n = len(annual_energy_mwh_list)
        
        # Cash flow arrays
        self.cash_flows = []
        discounted_costs = total_capex  # Year 0
        discounted_energy = 0.0
        cumulative_cash_flow = -total_capex
        payback_year = None
        
        self.cash_flows.append({
            'Year': 0,
            'CAPEX': total_capex,
            'OPEX': 0,
            'Energy (MWh)': 0,
            'Revenue': 0,
            'Net Cash Flow': -total_capex,
            'Cumulative Cash Flow': cumulative_cash_flow,
            'Discount Factor': 1.0
        })
        
        for t in range(1, n + 1):
            discount_factor = 1 / (1 + r) ** t
            
            # OPEX with inflation
            opex_t = annual_opex_base * (1 + self.config.opex_inflation) ** (t - 1)
            discounted_costs += opex_t * discount_factor
            
            # Energy
            energy_t = annual_energy_mwh_list[t - 1]
            discounted_energy += energy_t * discount_factor
            
            # Revenue
            if self.config.use_morocco_grid_tariffs:
                # Net revenue after grid tariffs
                grid_cost = self.config.morocco_tariffs.total_usd_per_mwh() * energy_t
                revenue_t = self.config.ppa_tariff_usd_per_mwh * energy_t - grid_cost
            else:
                revenue_t = self.config.ppa_tariff_usd_per_mwh * energy_t
            
            # Net cash flow
            net_cf = revenue_t - opex_t
            cumulative_cash_flow += net_cf
            
            # Payback period
            if payback_year is None and cumulative_cash_flow >= 0:
                payback_year = t
            
            self.cash_flows.append({
                'Year': t,
                'CAPEX': 0,
                'OPEX': opex_t,
                'Energy (MWh)': energy_t,
                'Revenue': revenue_t,
                'Net Cash Flow': net_cf,
                'Cumulative Cash Flow': cumulative_cash_flow,
                'Discount Factor': discount_factor
            })
        
        # LCOE
        lcoe = discounted_costs / discounted_energy if discounted_energy > 0 else 0
        
        # NPV
        npv = self._calculate_npv()
        
        # IRR
        irr = self._calculate_irr()
        
        # Total metrics
        total_energy = sum(annual_energy_mwh_list)
        total_revenue = sum([cf['Revenue'] for cf in self.cash_flows])
        total_opex = sum([cf['OPEX'] for cf in self.cash_flows])
        
        self.results = {
            'LCOE ($/MWh)': lcoe,
            'NPV ($)': npv,
            'IRR (%)': irr * 100 if irr else 0,
            'Payback Period (years)': payback_year if payback_year else '>30',
            'Total CAPEX ($)': total_capex,
            'Total OPEX ($)': total_opex,
            'Total Revenue ($)': total_revenue,
            'Total Energy (MWh)': total_energy,
            'WACC (%)': self.config.wacc * 100,
            'CAPEX Breakdown': capex_breakdown,
            'OPEX Breakdown': opex_breakdown
        }
        
        return self.results
    
    def _calculate_npv(self) -> float:
        """Calculate Net Present Value."""
        r = self.config.wacc
        npv = 0.0
        for cf in self.cash_flows:
            t = cf['Year']
            if t == 0:
                npv += cf['Net Cash Flow']
            else:
                npv += cf['Net Cash Flow'] / (1 + r) ** t
        return npv
    
    def _calculate_irr(self, max_iterations: int = 1000, tolerance: float = 1e-6) -> Optional[float]:
        """Calculate Internal Rate of Return using binary search."""
        cash_flows = [cf['Net Cash Flow'] for cf in self.cash_flows]
        
        # Initial bounds
        low = -0.99
        high = 1.0
        
        for _ in range(max_iterations):
            mid = (low + high) / 2
            npv = sum([cf / (1 + mid) ** t for t, cf in enumerate(cash_flows)])
            
            if abs(npv) < tolerance:
                return mid
            elif npv > 0:
                low = mid
            else:
                high = mid
        
        return (low + high) / 2
    
    def get_cash_flow_df(self) -> pd.DataFrame:
        """Return cash flows as DataFrame."""
        return pd.DataFrame(self.cash_flows)
    
    def calculate_floor_ppa(self, 
                            total_capex: float,
                            annual_opex_base: float,
                            annual_energy_mwh_list: List[float],
                            max_iterations: int = 100,
                            tolerance: float = 0.01) -> float:
        """
        Calculate the minimum PPA tariff needed for NPV = 0.
        This is the "floor price" at which the project breaks even.
        
        Uses binary search to find the tariff.
        """
        r = self.config.wacc
        n = len(annual_energy_mwh_list)
        
        # Calculate discounted energy and costs
        discounted_energy = 0.0
        discounted_opex = 0.0
        
        for t in range(1, n + 1):
            discount_factor = 1 / (1 + r) ** t
            
            # OPEX with inflation
            opex_t = annual_opex_base * (1 + self.config.opex_inflation) ** (t - 1)
            discounted_opex += opex_t * discount_factor
            
            # Energy
            energy_t = annual_energy_mwh_list[t - 1]
            discounted_energy += energy_t * discount_factor
        
        # Total discounted costs
        total_discounted_costs = total_capex + discounted_opex
        
        # Grid tariff adjustment
        grid_cost_per_mwh = 0.0
        if self.config.use_morocco_grid_tariffs:
            grid_cost_per_mwh = self.config.morocco_tariffs.total_usd_per_mwh()
        
        # For NPV = 0:
        # Total Revenue = Total Costs
        # PPA × Discounted Energy - Grid Cost × Discounted Energy = Total Costs
        # PPA = (Total Costs + Grid Cost × Discounted Energy) / Discounted Energy
        
        if discounted_energy > 0:
            floor_ppa = (total_discounted_costs / discounted_energy) + grid_cost_per_mwh
        else:
            floor_ppa = 0.0
        
        return floor_ppa
