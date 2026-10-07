"""LCOE, floor PPA, and IRR."""

import pytest

from simulator.core.validation import SimulationInputError
from simulator.financial.lcoe import FinancialConfig, LCOECalculator


def test_floor_ppa_sets_npv_to_zero_and_irr_to_wacc():
    calc = LCOECalculator(
        FinancialConfig(wacc=0.05, opex_inflation=0.0, revenue_escalation=0.0, ppa_tariff_usd_per_mwh=0)
    )
    energy = [100.0] * 5
    floor = calc.calculate_floor_ppa(100.0, 0.0, energy)
    calc.config.ppa_tariff_usd_per_mwh = floor
    result = calc._calculate_lcoe(100.0, 0.0, energy, {}, {})
    assert result.npv == pytest.approx(0.0, abs=1e-6)
    assert result.irr == pytest.approx(5.0, abs=1e-3)
    assert result.lcoe == pytest.approx(floor, rel=1e-9)


def test_year_one_escalation_does_not_change_a_single_year_floor():
    calc = LCOECalculator(FinancialConfig(wacc=0.0, revenue_escalation=0.1, opex_inflation=0.0))
    assert calc.calculate_floor_ppa(100.0, 0.0, [100.0]) == pytest.approx(100.0)


def test_escalation_applies_from_year_two():
    calc = LCOECalculator(FinancialConfig(wacc=0.0, revenue_escalation=0.1, opex_inflation=0.0))
    floor = calc.calculate_floor_ppa(100.0, 0.0, [100.0, 100.0])
    assert floor == pytest.approx(100.0 / 210.0)
    calc.config.ppa_tariff_usd_per_mwh = floor
    result = calc._calculate_lcoe(100.0, 0.0, [100.0, 100.0], {}, {})
    assert result.npv == pytest.approx(0.0, abs=1e-6)


def test_irr_can_exceed_100_percent():
    calc = LCOECalculator(FinancialConfig(wacc=0.05))
    calc.cash_flows = [
        {"year": 0, "net_cash_flow": -100.0},
        {"year": 1, "net_cash_flow": 300.0},
    ]
    assert calc._calculate_irr() == pytest.approx(2.0, rel=1e-6)


def test_zero_discounted_energy_lcoe_is_infinite():
    calc = LCOECalculator(FinancialConfig(wacc=0.05))
    result = calc._calculate_lcoe(100.0, 0.0, [0.0], {}, {})
    assert result.lcoe == float("inf")


def test_wacc_at_or_below_minus_one_is_rejected():
    with pytest.raises(SimulationInputError):
        LCOECalculator(FinancialConfig(wacc=-1))


def test_sensitivity_analysis_is_not_a_multiplier():
    calc = LCOECalculator()
    with pytest.raises(NotImplementedError):
        calc.sensitivity_analysis(None, "capex", [0.8, 1.2])
