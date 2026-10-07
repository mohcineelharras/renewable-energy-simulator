"""
Grid Tariff Models.

Electricity tariff structures including Morocco-specific rates.
"""

from dataclasses import dataclass
from typing import Dict, Optional
import pandas as pd


@dataclass
class GridTariff:
    """Generic grid tariff model."""
    name: str = "Generic Tariff"
    import_rate: float = 0.10  # $/kWh import
    export_rate: float = 0.05  # $/kWh export (feed-in tariff)
    peak_rate: float = 0.15  # $/kWh during peak hours
    off_peak_rate: float = 0.08  # $/kWh during off-peak
    demand_charge: float = 10.0  # $/kW/month for peak demand
    
    # Time-of-use periods
    peak_hours: tuple = (17, 21)  # 5 PM to 9 PM
    
    def import_cost(self, consumption_kwh: float, peak_fraction: float = 0.3) -> float:
        """Calculate import cost with TOU rates."""
        peak_kwh = consumption_kwh * peak_fraction
        off_peak_kwh = consumption_kwh * (1 - peak_fraction)
        return peak_kwh * self.peak_rate + off_peak_kwh * self.off_peak_rate
    
    def export_revenue(self, export_kwh: float) -> float:
        """Calculate export revenue."""
        return export_kwh * self.export_rate
    
    def demand_cost(self, peak_demand_kw: float, months: int = 12) -> float:
        """Calculate annual demand charges."""
        return peak_demand_kw * self.demand_charge * months


@dataclass
class MoroccoGridTariffs:
    """
    Stored Morocco grid-charge constants.

    The centime figures and mad_to_usd=0.10 are assumptions held in this
    class. This module does not fetch a tariff feed.
    """
    # Transport and distribution (MAD centimes/kWh)
    turt_transmission: float = 6.68  # Transport très haute tension
    turd_distribution: float = 5.92  # Distribution haute/moyenne tension
    tss_system_services: float = 6.64  # Services système
    
    # Exchange rate
    mad_to_usd: float = 0.10  # Approximate MAD to USD rate
    
    # PPA rates by technology (if applicable)
    solar_ppa_cap: float = 0.45  # MAD/kWh cap for solar PPAs
    wind_ppa_cap: float = 0.40  # MAD/kWh cap for wind PPAs
    
    def total_centimes_per_kwh(self) -> float:
        """Total grid tariff in MAD centimes/kWh."""
        return self.turt_transmission + self.turd_distribution + self.tss_system_services
    
    def total_mad_per_kwh(self) -> float:
        """Total grid tariff in MAD/kWh."""
        return self.total_centimes_per_kwh() / 100
    
    def total_usd_per_kwh(self) -> float:
        """Total grid tariff in USD/kWh."""
        return self.total_mad_per_kwh() * self.mad_to_usd
    
    def total_usd_per_mwh(self) -> float:
        """Total grid tariff in USD/MWh for PPA modeling."""
        return self.total_usd_per_kwh() * 1000
    
    def net_ppa_revenue(self, ppa_tariff_usd_mwh: float) -> float:
        """Calculate net revenue per MWh after grid tariffs."""
        return ppa_tariff_usd_mwh - self.total_usd_per_mwh()
    
    def breakdown(self) -> Dict[str, float]:
        """Get tariff breakdown in MAD centimes/kWh."""
        return {
            'TURT (Transmission)': self.turt_transmission,
            'TURD (Distribution)': self.turd_distribution,
            'TSS (System Services)': self.tss_system_services,
        }
    
    def breakdown_usd_mwh(self) -> Dict[str, float]:
        """Get tariff breakdown in USD/MWh."""
        factor = self.mad_to_usd * 10  # centimes to MAD to USD to MWh
        return {
            'TURT (Transmission)': self.turt_transmission * factor,
            'TURD (Distribution)': self.turd_distribution * factor,
            'TSS (System Services)': self.tss_system_services * factor,
        }
    
    def to_grid_tariff(self) -> GridTariff:
        """Convert to generic GridTariff object."""
        usd_kwh = self.total_usd_per_kwh()
        return GridTariff(
            name="Stored Morocco grid-charge assumption",
            import_rate=usd_kwh * 1.5,  # Approximate retail import
            export_rate=usd_kwh * 0.8,  # Approximate FIT
            peak_rate=usd_kwh * 1.8,
            off_peak_rate=usd_kwh * 1.2,
        )


# Stored constants. The historical name is kept as an alias and is not a tariff publication.
MOROCCO_GRID_CHARGE = MoroccoGridTariffs()
MOROCCO_ANRE_2025 = MOROCCO_GRID_CHARGE

UAE_TARIFF = GridTariff(
    name="UAE Industrial",
    import_rate=0.08,
    export_rate=0.04,
    peak_rate=0.12,
    off_peak_rate=0.06,
    demand_charge=8.0,
)

SAUDI_TARIFF = GridTariff(
    name="Saudi Industrial",
    import_rate=0.05,
    export_rate=0.03,
    peak_rate=0.08,
    off_peak_rate=0.04,
    demand_charge=5.0,
)

EUROPE_AVERAGE = GridTariff(
    name="Europe Average",
    import_rate=0.20,
    export_rate=0.10,
    peak_rate=0.28,
    off_peak_rate=0.15,
    demand_charge=15.0,
)
