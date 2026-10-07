"""Optimizer bounds and non-finite objectives."""

import pytest

from simulator.core.validation import SimulationInputError
from simulator.optimizer.lcoe_optimizer import LCOEOptimizer, OptimizationConfig, OptimizationVariable


def test_grid_step_does_not_pass_the_maximum():
    assert OptimizationVariable("x", 0, 10, step=3).get_grid_values() == [0.0, 3.0, 6.0, 9.0]


def test_scipy_powell_finds_a_smooth_minimum():
    optimizer = LCOEOptimizer(
        lambda config: {"lcoe": (config["x"] - 3.0) ** 2},
        OptimizationConfig(n_iterations=40),
    )
    optimizer.add_variable("x", 0, 10)
    result = optimizer.run("scipy_minimize")
    assert result.best_config["x"] == pytest.approx(3.0, abs=1e-2)
    assert result.best_lcoe == pytest.approx(0.0, abs=1e-4)


def test_random_search_accepts_an_infinite_first_value():
    state = {"n": 0}

    def simulate(config):
        state["n"] += 1
        if state["n"] == 1:
            return {"lcoe": float("inf")}
        return {"lcoe": (config["x"] - 1.0) ** 2}

    optimizer = LCOEOptimizer(simulate, OptimizationConfig(n_iterations=8, patience=20))
    optimizer.add_variable("x", 0, 2, step=0.5)
    result = optimizer.run("random_search")
    assert result.best_lcoe < float("inf")


def test_unknown_algorithm_does_not_run_grid_search():
    optimizer = LCOEOptimizer(lambda config: {"lcoe": 1.0}, OptimizationConfig())
    optimizer.add_variable("x", 0, 1, step=1)
    with pytest.raises((SimulationInputError, ValueError)):
        optimizer.run("not_an_algorithm")
    assert optimizer.results == []
