"""
CAPEX (Capital Expenditure) Models.

Industry-standard CAPEX breakdowns for solar, wind, and battery projects.
"""

from dataclasses import dataclass
from typing import Dict


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
        """Calculate total CAPEX per kWdc installed."""
        equipment = self.modules + self.inverters + self.mounting_trackers + self.bop_electrical
        epc = equipment * self.epc_percent
        return equipment + epc + self.grid_connection + self.development
    
    def total_for_capacity(self, capacity_kwdc: float) -> float:
        """Calculate total CAPEX for given capacity."""
        return self.total_per_kwdc() * capacity_kwdc
    
    def breakdown(self) -> Dict[str, float]:
        """Get CAPEX breakdown in $/kWdc."""
        equipment = self.modules + self.inverters + self.mounting_trackers + self.bop_electrical
        epc = equipment * self.epc_percent
        return {
            'Modules': self.modules,
            'Inverters': self.inverters,
            'Mounting/Trackers': self.mounting_trackers,
            'BOP/Electrical': self.bop_electrical,
            'EPC': epc,
            'Grid Connection': self.grid_connection,
            'Development': self.development,
        }
    
    def breakdown_pct(self) -> Dict[str, float]:
        """Get CAPEX breakdown as percentages."""
        total = self.total_per_kwdc()
        return {k: v / total * 100 for k, v in self.breakdown().items()}


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
        """Calculate total CAPEX per kW installed."""
        return (self.turbine_tower + self.foundations + self.installation +
                self.grid_connection + self.development_bos + self.contingency)
    
    def total_for_capacity(self, capacity_kw: float) -> float:
        """Calculate total CAPEX for given capacity."""
        return self.total_per_kw() * capacity_kw
    
    def breakdown(self) -> Dict[str, float]:
        """Get CAPEX breakdown in $/kW."""
        return {
            'Turbine & Tower': self.turbine_tower,
            'Foundations': self.foundations,
            'Installation': self.installation,
            'Grid Connection': self.grid_connection,
            'Development/BOS': self.development_bos,
            'Contingency': self.contingency,
        }
    
    def breakdown_pct(self) -> Dict[str, float]:
        """Get CAPEX breakdown as percentages."""
        total = self.total_per_kw()
        return {k: v / total * 100 for k, v in self.breakdown().items()}


@dataclass
class BatteryCapex:
    """CAPEX breakdown for battery energy storage ($/kWh)."""
    cells: float = 120.0  # Battery cells
    bms: float = 25.0  # Battery management system
    enclosure: float = 30.0  # Container/enclosure
    pcs: float = 80.0  # Power conversion system ($/kW, converted)
    bop_electrical: float = 40.0  # BOP electrical
    installation: float = 35.0  # Installation & commissioning
    development: float = 20.0  # Development, permits
    
    def total_per_kwh(self) -> float:
        """Calculate total CAPEX per kWh installed."""
        return (self.cells + self.bms + self.enclosure + self.pcs +
                self.bop_electrical + self.installation + self.development)
    
    def total_for_capacity(self, capacity_kwh: float) -> float:
        """Calculate total CAPEX for given capacity."""
        return self.total_per_kwh() * capacity_kwh
    
    def breakdown(self) -> Dict[str, float]:
        """Get CAPEX breakdown in $/kWh."""
        return {
            'Battery Cells': self.cells,
            'BMS': self.bms,
            'Enclosure': self.enclosure,
            'Power Conversion': self.pcs,
            'BOP/Electrical': self.bop_electrical,
            'Installation': self.installation,
            'Development': self.development,
        }


@dataclass
class HybridCapex:
    """Combined CAPEX for hybrid PV+Wind+Battery projects."""
    solar: SolarCapex = None
    wind: WindCapex = None
    battery: BatteryCapex = None
    integration: float = 0.05  # 5% additional for integration
    
    def __post_init__(self):
        if self.solar is None:
            self.solar = SolarCapex()
        if self.wind is None:
            self.wind = WindCapex()
        if self.battery is None:
            self.battery = BatteryCapex()
    
    def total(
        self,
        solar_kw: float = 0,
        wind_kw: float = 0,
        battery_kwh: float = 0
    ) -> float:
        """Calculate total CAPEX for hybrid system."""
        solar_cost = self.solar.total_for_capacity(solar_kw) if solar_kw > 0 else 0
        wind_cost = self.wind.total_for_capacity(wind_kw) if wind_kw > 0 else 0
        battery_cost = self.battery.total_for_capacity(battery_kwh) if battery_kwh > 0 else 0
        
        subtotal = solar_cost + wind_cost + battery_cost
        integration_cost = subtotal * self.integration
        
        return subtotal + integration_cost
    
    def breakdown(
        self,
        solar_kw: float = 0,
        wind_kw: float = 0,
        battery_kwh: float = 0
    ) -> Dict[str, float]:
        """Get CAPEX breakdown by component."""
        breakdown = {}
        
        if solar_kw > 0:
            breakdown['Solar PV'] = self.solar.total_for_capacity(solar_kw)
        if wind_kw > 0:
            breakdown['Wind'] = self.wind.total_for_capacity(wind_kw)
        if battery_kwh > 0:
            breakdown['Battery Storage'] = self.battery.total_for_capacity(battery_kwh)
        
        subtotal = sum(breakdown.values())
        if subtotal > 0:
            breakdown['Integration'] = subtotal * self.integration
        
        return breakdown
