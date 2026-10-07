"""
Loss waterfall utilities. Stage energy is the previous stage times (1 - fraction).
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
import pandas as pd

from simulator.core.types import LossItem


class LossWaterfall:
    """
    Manages a loss waterfall for energy simulation.
    
    Tracks energy from a gross input through each fractional stage.
    
    Example:
        >>> waterfall = LossWaterfall(gross_energy=1000.0)
        >>> waterfall.add_loss("Shading", 0.02)
        >>> waterfall.add_loss("Soiling", 0.05)
        >>> waterfall.add_loss("Temperature", 0.03)
        >>> net = waterfall.get_net_energy()
        >>> print(f"Net: {net:.1f} kWh, Total Loss: {waterfall.total_loss_percent:.1%}")
    """
    
    def __init__(self, gross_energy: float = 0.0):
        """
        Initialize a loss waterfall.
        
        Args:
            gross_energy: Initial gross energy before any losses.
        """
        self._gross_energy = gross_energy
        self._losses: List[LossItem] = []
        self._computed = False
    
    @property
    def gross_energy(self) -> float:
        return self._gross_energy
    
    @gross_energy.setter
    def gross_energy(self, value: float) -> None:
        self._gross_energy = value
        self._computed = False
    
    def add_loss(self, stage: str, loss_percent: float) -> None:
        """
        Add a loss stage to the waterfall.
        
        Args:
            stage: Name of the loss stage (e.g., "Shading", "Soiling").
            loss_percent: Loss as a fraction (0.02 = 2%).
        """
        self._losses.append(LossItem(stage=stage, loss_percent=loss_percent))
        self._computed = False
    
    def add_losses(self, losses: List[Tuple[str, float]]) -> None:
        """
        Add multiple loss stages at once.
        
        Args:
            losses: List of (stage_name, loss_percent) tuples.
        """
        for stage, percent in losses:
            self.add_loss(stage, percent)
    
    def clear(self) -> None:
        """Clear all losses."""
        self._losses = []
        self._computed = False
    
    def _compute(self) -> None:
        """Compute energy values for each loss stage."""
        if self._computed:
            return
        
        current_energy = self._gross_energy
        for loss in self._losses:
            loss.input_energy = current_energy
            loss.loss_energy = current_energy * loss.loss_percent
            loss.output_energy = current_energy - loss.loss_energy
            current_energy = loss.output_energy
        
        self._computed = True
    
    def get_net_energy(self) -> float:
        """Get net energy after all losses."""
        self._compute()
        if len(self._losses) == 0:
            return self._gross_energy
        return self._losses[-1].output_energy
    
    @property
    def total_loss_percent(self) -> float:
        """Get total loss as a fraction."""
        if self._gross_energy == 0:
            return 0.0
        net = self.get_net_energy()
        return 1 - (net / self._gross_energy)
    
    @property
    def total_loss_energy(self) -> float:
        """Get total energy lost."""
        return self._gross_energy - self.get_net_energy()
    
    def get_losses(self) -> List[LossItem]:
        """Get all loss items with computed energy values."""
        self._compute()
        return self._losses.copy()
    
    def get_summary(self) -> pd.DataFrame:
        """
        Get loss waterfall as a DataFrame.
        
        Returns:
            DataFrame with columns: stage, loss_percent, input_energy, loss_energy, output_energy
        """
        self._compute()
        
        data = [
            {
                'stage': item.stage,
                'loss_percent': item.loss_percent * 100,
                'input_energy': item.input_energy,
                'loss_energy': item.loss_energy,
                'output_energy': item.output_energy,
            }
            for item in self._losses
        ]
        
        return pd.DataFrame(data)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        self._compute()
        return {
            'gross_energy': self._gross_energy,
            'net_energy': self.get_net_energy(),
            'total_loss_percent': self.total_loss_percent,
            'losses': [
                {
                    'stage': item.stage,
                    'loss_percent': item.loss_percent,
                    'input_energy': item.input_energy,
                    'loss_energy': item.loss_energy,
                    'output_energy': item.output_energy,
                }
                for item in self._losses
            ]
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'LossWaterfall':
        """Create from dictionary."""
        waterfall = cls(gross_energy=data['gross_energy'])
        for loss in data['losses']:
            waterfall.add_loss(loss['stage'], loss['loss_percent'])
        return waterfall
    
    def __repr__(self) -> str:
        return (f"LossWaterfall(gross={self._gross_energy:.1f}, "
                f"net={self.get_net_energy():.1f}, "
                f"total_loss={self.total_loss_percent:.1%})")


# Pre-defined loss templates
SOLAR_LOSS_TEMPLATE = [
    ("Near Shading", 0.02),
    ("Far Shading (Horizon)", 0.01),
    ("Soiling", 0.05),
    ("IAM (Reflection)", 0.03),
    ("Spectral", 0.01),
    ("Temperature", 0.03),  # Placeholder - calculated dynamically
    ("DC Wiring", 0.02),
    ("Module Mismatch", 0.015),
    ("Inverter Efficiency", 0.02),
    ("Clipping", 0.0),  # Placeholder - calculated dynamically
    ("Transformer", 0.015),
    ("AC Collection", 0.01),
    ("Availability", 0.01),
]

WIND_LOSS_TEMPLATE = [
    ("Wake Effects", 0.10),
    ("Turbine Availability", 0.03),
    ("Electrical Collection", 0.02),
    ("Turbine Performance", 0.015),
    ("Environmental (Icing/Temp)", 0.02),
    ("Grid Curtailment", 0.01),
]


def create_solar_waterfall(
    gross_energy: float,
    temp_loss: float = 0.03,
    clipping_loss: float = 0.0,
    custom_losses: Optional[dict] = None
) -> LossWaterfall:
    """
    Create a solar loss waterfall with standard losses.
    
    Args:
        gross_energy: Gross energy before losses.
        temp_loss: Temperature loss fraction (calculated from simulation).
        clipping_loss: Inverter clipping loss fraction.
        custom_losses: Optional dict of {stage: loss_percent} to override defaults.
    
    Returns:
        Configured LossWaterfall instance.
    """
    waterfall = LossWaterfall(gross_energy)
    
    losses = dict(SOLAR_LOSS_TEMPLATE)
    losses["Temperature"] = temp_loss
    losses["Clipping"] = clipping_loss
    
    if custom_losses:
        losses.update(custom_losses)
    
    for stage, percent in losses.items():
        waterfall.add_loss(stage, percent)
    
    return waterfall


def create_wind_waterfall(
    gross_energy: float,
    wake_loss: float = 0.10,
    custom_losses: Optional[dict] = None
) -> LossWaterfall:
    """
    Create a wind loss waterfall with standard losses.
    
    Args:
        gross_energy: Gross energy before losses.
        wake_loss: Wake effect loss fraction.
        custom_losses: Optional dict to override defaults.
    
    Returns:
        Configured LossWaterfall instance.
    """
    waterfall = LossWaterfall(gross_energy)
    
    losses = dict(WIND_LOSS_TEMPLATE)
    losses["Wake Effects"] = wake_loss
    
    if custom_losses:
        losses.update(custom_losses)
    
    for stage, percent in losses.items():
        waterfall.add_loss(stage, percent)
    
    return waterfall
