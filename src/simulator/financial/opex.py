"""
OPEX (Operating Expenditure) Models.

Industry-standard OPEX breakdowns for solar, wind, and battery projects.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class SolarOpex:
    """OPEX breakdown for utility-scale solar PV ($/kW/year)."""
    scheduled_maintenance: float = 12.0  # $10-15
    unscheduled_repairs: float = 4.0  # $3-5
    insurance: float = 3.0  # $2-4
    land_lease: float = 2.0  # $1-3
    administrative: float = 1.5  # $1-2
    
    def total_per_kw_year(self) -> float:
        """Calculate total OPEX per kW per year."""
        return (self.scheduled_maintenance + self.unscheduled_repairs +
                self.insurance + self.land_lease + self.administrative)
    
    def total_for_capacity(self, capacity_kw: float) -> float:
        """Calculate annual OPEX for given capacity."""
        return self.total_per_kw_year() * capacity_kw
    
    def breakdown(self) -> Dict[str, float]:
        """Get OPEX breakdown in $/kW/year."""
        return {
            'Scheduled Maintenance': self.scheduled_maintenance,
            'Unscheduled Repairs': self.unscheduled_repairs,
            'Insurance': self.insurance,
            'Land Lease': self.land_lease,
            'Administrative': self.administrative,
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
        """Calculate total OPEX per kW per year."""
        return (self.scheduled_maintenance + self.unscheduled_repairs +
                self.insurance + self.land_lease + self.administrative)
    
    def total_for_capacity(self, capacity_kw: float) -> float:
        """Calculate annual OPEX for given capacity."""
        return self.total_per_kw_year() * capacity_kw
    
    def breakdown(self) -> Dict[str, float]:
        """Get OPEX breakdown in $/kW/year."""
        return {
            'Scheduled Maintenance': self.scheduled_maintenance,
            'Unscheduled Repairs': self.unscheduled_repairs,
            'Insurance': self.insurance,
            'Land Lease': self.land_lease,
            'Administrative': self.administrative,
        }


@dataclass
class BatteryOpex:
    """OPEX breakdown for battery storage ($/kWh/year)."""
    maintenance: float = 8.0  # $6-10
    capacity_warranty: float = 5.0  # $4-6
    insurance: float = 2.0  # $1-3
    administrative: float = 1.5  # $1-2
    
    def total_per_kwh_year(self) -> float:
        """Calculate total OPEX per kWh per year."""
        return self.maintenance + self.capacity_warranty + self.insurance + self.administrative
    
    def total_for_capacity(self, capacity_kwh: float) -> float:
        """Calculate annual OPEX for given capacity."""
        return self.total_per_kwh_year() * capacity_kwh
    
    def breakdown(self) -> Dict[str, float]:
        """Get OPEX breakdown in $/kWh/year."""
        return {
            'Maintenance': self.maintenance,
            'Capacity Warranty': self.capacity_warranty,
            'Insurance': self.insurance,
            'Administrative': self.administrative,
        }


@dataclass
class HybridOpex:
    """Combined OPEX for hybrid PV+Wind+Battery projects."""
    solar: SolarOpex = None
    wind: WindOpex = None
    battery: BatteryOpex = None
    shared_overhead: float = 0.10  # 10% additional for shared O&M
    
    def __post_init__(self):
        if self.solar is None:
            self.solar = SolarOpex()
        if self.wind is None:
            self.wind = WindOpex()
        if self.battery is None:
            self.battery = BatteryOpex()
    
    def annual_total(
        self,
        solar_kw: float = 0,
        wind_kw: float = 0,
        battery_kwh: float = 0
    ) -> float:
        """Calculate total annual OPEX for hybrid system."""
        solar_opex = self.solar.total_for_capacity(solar_kw) if solar_kw > 0 else 0
        wind_opex = self.wind.total_for_capacity(wind_kw) if wind_kw > 0 else 0
        battery_opex = self.battery.total_for_capacity(battery_kwh) if battery_kwh > 0 else 0
        
        subtotal = solar_opex + wind_opex + battery_opex
        overhead = subtotal * self.shared_overhead
        
        return subtotal + overhead
    
    def breakdown(
        self,
        solar_kw: float = 0,
        wind_kw: float = 0,
        battery_kwh: float = 0
    ) -> Dict[str, float]:
        """Get annual OPEX breakdown by component."""
        breakdown = {}
        
        if solar_kw > 0:
            breakdown['Solar PV'] = self.solar.total_for_capacity(solar_kw)
        if wind_kw > 0:
            breakdown['Wind'] = self.wind.total_for_capacity(wind_kw)
        if battery_kwh > 0:
            breakdown['Battery Storage'] = self.battery.total_for_capacity(battery_kwh)
        
        subtotal = sum(breakdown.values())
        if subtotal > 0:
            breakdown['Shared Overhead'] = subtotal * self.shared_overhead
        
        return breakdown
