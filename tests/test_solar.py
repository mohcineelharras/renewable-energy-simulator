"""Solar energy accounting."""

import numpy as np
import pandas as pd
import pvlib
import pytest

from simulator.core.validation import SimulationInputError
from simulator.data.timeseries import integrate_power_kwh, timestep_hours
from simulator.generators.solar import SolarConfig, SolarGenerator


def _weather(hours=72, temp_air=None, ghi_scale=1.0):
    index = pd.date_range("2023-06-21", periods=hours, freq="h", tz="UTC")
    solpos = pvlib.solarposition.get_solarposition(index, 31.6, -8.0)
    elevation = (90.0 - solpos["apparent_zenith"]).clip(lower=0)
    ghi = 900.0 * ghi_scale * np.sin(np.radians(elevation.to_numpy()))
    if temp_air is None:
        temp_air = 15.0 + 20.0 * np.sin(np.linspace(0, 4 * np.pi, hours))
    return pd.DataFrame(
        {
            "ghi": ghi,
            "dni": ghi,
            "dhi": np.zeros(hours),
            "temp_air": temp_air,
            "wind_speed": np.full(hours, 2.0),
        },
        index=index,
    )


def _run(weather, **config):
    generator = SolarGenerator(SolarConfig(latitude=31.6, longitude=-8.0, land_area_ha=1.0, **config))
    return generator.simulate(weather, years=2)


def test_waterfall_net_matches_hourly_energy():
    result = _run(_weather())
    net = result.losses[-1].output_energy
    hourly = integrate_power_kwh(result.hourly["power_kw"])
    assert net == pytest.approx(hourly, rel=1e-9)
    assert result.annual.iloc[0]["energy_kwh"] == pytest.approx(hourly, rel=1e-9)


def test_temperature_loss_is_energy_weighted():
    result = _run(_weather())
    poa = result.hourly["poa_dc_kw"]
    raw = result.hourly["raw_dc_kw"]
    weighted = 1.0 - integrate_power_kwh(raw) / integrate_power_kwh(poa)
    item = next(loss for loss in result.losses if loss.stage == "Temperature")
    assert item.loss_percent == pytest.approx(weighted, rel=1e-9)
    positive = poa > 0
    unweighted = (1.0 - raw[positive] / poa[positive]).mean()
    assert abs(item.loss_percent - float(unweighted)) > 1e-4


def test_second_simulate_uses_the_new_weather():
    generator = SolarGenerator(SolarConfig(latitude=31.6, longitude=-8.0, land_area_ha=1.0))
    first = generator.simulate(_weather(), years=1)
    second = generator.simulate(_weather(ghi_scale=0.0), years=1)
    assert first.annual.iloc[0]["energy_mwh"] > 0
    assert second.annual.iloc[0]["energy_mwh"] == pytest.approx(0.0, abs=1e-6)


def test_capacity_factor_uses_series_duration():
    weather = _weather(hours=48)
    result = _run(weather)
    hours = float(timestep_hours(result.hourly.index).sum())
    assert hours == pytest.approx(48.0)
    expected = 100.0 * integrate_power_kwh(result.hourly["power_kw"]) / (
        result.metadata["sizing"]["ac_capacity_mw"] * 1000.0 * hours
    )
    assert result.kpis["capacity_factor_pct"] == pytest.approx(expected, rel=1e-9)


def test_zero_modules_rejected():
    generator = SolarGenerator(
        SolarConfig(latitude=0, longitude=0, land_area_ha=1e-8, module_efficiency=0.2, gcr=0.3)
    )
    with pytest.raises(SimulationInputError):
        generator.auto_size()
