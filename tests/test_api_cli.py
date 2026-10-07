"""Hybrid energy basis and the command line entry point."""

import json

import pandas as pd
import pytest

from simulator.api import SimulationAPI
from simulator.cli import main
from simulator.core.types import LossItem
from simulator.visualization.charts import create_loss_waterfall, create_soc_chart


def _solar_weather():
    index = pd.date_range("2023-06-21", periods=48, freq="h", tz="UTC")
    hour = index.hour
    ghi = pd.Series(0.0, index=index)
    ghi[(hour >= 8) & (hour <= 16)] = 800.0
    return pd.DataFrame(
        {"ghi": ghi, "dni": ghi, "dhi": 0.0, "temp_air": 25.0, "wind_speed": 2.0},
        index=index,
    )


def test_hybrid_wind_cost_uses_built_nameplate():
    from simulator.financial.capex import HybridCapex

    api = SimulationAPI(allow_network=False)
    index = pd.date_range("2023-01-01", periods=4, freq="h", tz="UTC")
    weather = pd.DataFrame(
        {"wind_speed": [8.0] * 4, "temperature": [15.0] * 4, "pressure": [1013.0] * 4},
        index=index,
    )
    result = api.run_hybrid_simulation(
        latitude=35.0,
        longitude=-5.0,
        wind_mw=4.0,
        project_life=1,
        wind_weather=weather,
    )
    built_mw = result.wind_result.metadata["sizing"]["total_capacity_mw"]
    assert built_mw == pytest.approx(3.0)
    assert result.financial_result.total_capex == pytest.approx(HybridCapex().total(0, built_mw * 1000, 0))


def test_hybrid_without_load_reports_that_and_uses_delivered_energy():
    api = SimulationAPI(allow_network=False)
    weather = _solar_weather()
    result = api.run_hybrid_simulation(
        latitude=31.6,
        longitude=-8.0,
        solar_mw=1.0,
        battery_mwh=1.0,
        project_life=1,
        solar_weather=weather,
    )
    assert "no load" in result.notes["load"]
    assert result.notes["storage_dispatch"] == "idle_no_load_and_no_export_limit"
    year_one = result.financial_result.cash_flows.loc[
        result.financial_result.cash_flows["year"] == 1, "energy_mwh"
    ].iloc[0]
    assert year_one == pytest.approx(result.solar_result.year_one_energy_mwh, rel=1e-9)

    limited = api.run_hybrid_simulation(
        latitude=31.6,
        longitude=-8.0,
        solar_mw=1.0,
        battery_mwh=0.0,
        grid_limit_mw=0.001,
        project_life=1,
        solar_weather=weather,
    )
    limited_energy = limited.financial_result.cash_flows.loc[
        limited.financial_result.cash_flows["year"] == 1, "energy_mwh"
    ].iloc[0]
    assert limited_energy < result.solar_result.year_one_energy_mwh


def test_loss_chart_uses_stage_energy_and_soc_limits():
    figure = create_loss_waterfall(
        [LossItem("Soiling", 0.1, input_energy=1000, loss_energy=100, output_energy=900)]
    )
    assert list(figure.data[0].y)[:2] == [1000, -100]
    soc = create_soc_chart(pd.Series([0.5, 0.6]), min_soc=0.2, max_soc=0.8)
    lines = [shape.y0 for shape in soc.layout.shapes]
    assert 20 in lines
    assert 80 in lines


def test_cli_help_exits_cleanly():
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0


def test_cli_solar_json_includes_limitations(capsys):
    assert main(["solar", "--lat", "31.6", "--lon", "-8", "--capacity-mw", "0.2", "--years", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["limitations"]
    assert payload["year_one_energy_mwh"] > 0
    assert "not a climate dataset" in payload["notes"]["weather"].lower() or "synthetic" in payload["notes"]["weather"].lower()
