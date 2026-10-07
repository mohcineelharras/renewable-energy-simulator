"""Battery chemistry defaults and energy balance."""

import pandas as pd
import pytest

from simulator.core.validation import SimulationInputError
from simulator.storage.battery import BatteryChemistry, BatteryConfig, BatteryStorage


def _frame(values):
    index = pd.date_range("2023-01-01", periods=len(values), freq="h", tz="UTC")
    return pd.Series(values, index=index, dtype=float)


def test_chemistry_defaults_and_explicit_efficiency():
    nmc = BatteryConfig(chemistry=BatteryChemistry.NMC)
    assert nmc.calendar_degradation_per_year == pytest.approx(0.02)
    explicit = BatteryConfig(chemistry=BatteryChemistry.NMC, charge_efficiency=0.99)
    assert explicit.charge_efficiency == pytest.approx(0.99)


def test_soc_tracks_charge_energy():
    battery = BatteryStorage(
        BatteryConfig(
            capacity_kwh=100,
            power_kw=50,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            initial_soc=0.5,
        )
    )
    result = battery.simulate(_frame([10.0, 10.0, 0.0]), _frame([0.0, 0.0, 0.0]))
    assert result["charge_kw"].iloc[0] == pytest.approx(10.0)
    assert result["soc"].iloc[1] == pytest.approx(0.6)


def test_half_hour_step_moves_half_the_energy():
    index = pd.date_range("2023-01-01", periods=2, freq="30min", tz="UTC")
    battery = BatteryStorage(
        BatteryConfig(
            capacity_kwh=100,
            power_kw=50,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            initial_soc=0.5,
        )
    )
    result = battery.simulate(
        pd.Series([10.0, 0.0], index=index),
        pd.Series([0.0, 0.0], index=index),
    )
    assert result["soc"].iloc[1] == pytest.approx(0.55)


def test_unknown_strategy_and_unused_thermal_loss():
    battery = BatteryStorage(BatteryConfig(thermal_losses_pct=0.02))
    with pytest.raises(SimulationInputError):
        battery.simulate(_frame([1.0, 1.0]), _frame([0.0, 0.0]), "grid_export")
    with pytest.warns(UserWarning, match="thermal_losses_pct"):
        battery.simulate(_frame([1.0, 1.0]), _frame([0.0, 0.0]))


def test_degradation_is_not_floored_at_half():
    battery = BatteryStorage(BatteryConfig())
    battery._total_cycles = 100000
    battery._simulated_hours = 8760
    assert battery.get_degradation(years=1) < 0.5
