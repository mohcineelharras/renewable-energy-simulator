"""Dispatch strategies that used to be silent no-ops."""

import pandas as pd
import pytest

from simulator.core.validation import SimulationInputError
from simulator.grid.dispatch import DispatchConfig, DispatchController, DispatchStrategy
from simulator.storage.battery import BatteryConfig, BatteryStorage


def _battery():
    return BatteryStorage(
        BatteryConfig(
            capacity_kwh=20,
            power_kw=50,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            initial_soc=0.9,
            min_soc=0.1,
            max_soc=0.9,
        )
    )


def _run(strategy, generation, load, export_limit=None, storage=True):
    controller = DispatchController(
        DispatchConfig(strategy=strategy, grid_export_limit_kw=export_limit)
    )
    controller.add_generation("solar", generation)
    if storage is True:
        controller.set_storage(_battery())
    elif storage is not None:
        controller.set_storage(storage)
    return controller.optimize(load)


def test_peak_shaving_holds_energy_for_the_spike():
    index = pd.RangeIndex(9)
    load = pd.Series([10.0] * 8 + [100.0], index=index)
    generation = pd.Series(0.0, index=index)
    self_use = _run(DispatchStrategy.SELF_CONSUMPTION, generation, load)
    shaved = _run(DispatchStrategy.PEAK_SHAVING, generation, load)
    assert shaved.kpis["peak_import_kw"] < self_use.kpis["peak_import_kw"]
    assert "peak_shave_threshold_kw" in shaved.kpis


def test_maximize_export_shifts_around_the_limit():
    index = pd.RangeIndex(4)
    generation = pd.Series([100.0, 100.0, 10.0, 10.0], index=index)
    load = pd.Series(0.0, index=index)
    room = BatteryStorage(
        BatteryConfig(
            capacity_kwh=100,
            power_kw=50,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            initial_soc=0.5,
            min_soc=0.1,
            max_soc=0.9,
        )
    )
    limited = _run(DispatchStrategy.MAXIMIZE_EXPORT, generation, load, export_limit=40, storage=room)
    assert limited.schedule["storage_charge_kw"].iloc[0] > 0
    assert limited.schedule["storage_discharge_kw"].iloc[2] > 0
    assert limited.schedule["curtailment_kw"].iloc[0] < 60
    idle = _run(DispatchStrategy.MAXIMIZE_EXPORT, generation, load, export_limit=None)
    assert idle.schedule["storage_charge_kw"].sum() == 0
    assert idle.schedule["storage_discharge_kw"].sum() == 0


def test_energy_kpis_use_the_timestep():
    index = pd.date_range("2023-01-01", periods=2, freq="30min", tz="UTC")
    generation = pd.Series([10.0, 10.0], index=index)
    load = pd.Series([0.0, 0.0], index=index)
    result = _run(DispatchStrategy.SELF_CONSUMPTION, generation, load, storage=None)
    assert result.kpis["total_generation_kwh"] == pytest.approx(10.0)
    assert result.kpis["grid_export_kwh"] == pytest.approx(10.0)


def test_unimplemented_strategy_raises():
    index = pd.RangeIndex(2)
    controller = DispatchController(DispatchConfig(strategy=DispatchStrategy.MINIMIZE_IMPORT))
    controller.add_generation("solar", pd.Series([1.0, 1.0], index=index))
    with pytest.raises(SimulationInputError):
        controller.optimize(pd.Series([1.0, 1.0], index=index))
