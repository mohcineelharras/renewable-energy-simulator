"""Wind shear, power curve, and sizing."""

import math

import pandas as pd
import pytest

from simulator.core.validation import SimulationInputError
from simulator.generators.wind import TURBINE_LIBRARY, WindConfig, WindGenerator


def test_log_law_shear_ratio():
    speeds = pd.Series([10.0])
    hub = WindGenerator.hub_height_speed(speeds, 100.0, 10.0, 0.03)
    ratio = math.log(100.0 / 0.03) / math.log(10.0 / 0.03)
    assert hub.iloc[0] == pytest.approx(10.0 * ratio)


def test_density_scales_then_clips_to_nameplate():
    spec = TURBINE_LIBRARY["Generic 3MW"]
    rated_region = pd.Series([15.0, 15.0])
    assert spec.power_curve_vectorized(rated_region, 1.2).max() == pytest.approx(spec.rated_power_kw)
    assert spec.power_curve_vectorized(rated_region, 0.8).max() == pytest.approx(0.8 * spec.rated_power_kw)
    assert spec.power_curve_vectorized(pd.Series([30.0]), 1.2).iloc[0] == 0.0


def test_named_turbines_share_the_cubic_shape():
    vestas = TURBINE_LIBRARY["Vestas V150-4.2"]
    generic = TURBINE_LIBRARY["Generic 3MW"]
    speeds = pd.Series([8.0])
    ratio = vestas.power_curve_vectorized(speeds).iloc[0] / generic.power_curve_vectorized(speeds).iloc[0]
    assert ratio == pytest.approx(vestas.rated_power_kw / generic.rated_power_kw)


def test_auto_size_does_not_force_one_turbine():
    generator = WindGenerator(
        WindConfig(latitude=35, longitude=-5, land_area_ha=500, grid_limit_mw=1.0, turbine_model="Generic 3MW")
    )
    with pytest.raises(SimulationInputError, match="No turbine fits"):
        generator.auto_size()
