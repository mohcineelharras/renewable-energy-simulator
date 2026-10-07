"""Input checks shared by the simulation, finance, and weather code.

These checks reject values the implemented equations do not define.
They do not judge whether a value is a good design choice.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


class SimulationInputError(ValueError):
    """Raised when an input is outside the domain of the implemented model."""


def require_finite(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.floating, np.integer)):
        raise SimulationInputError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise SimulationInputError(f"{name} must be a finite number")
    return number


def require_in_range(
    name: str,
    value: Any,
    low: float,
    high: float,
    *,
    low_inclusive: bool = True,
    high_inclusive: bool = True,
) -> float:
    number = require_finite(name, value)
    if low_inclusive:
        if number < low:
            raise SimulationInputError(f"{name} must be >= {low}")
    elif number <= low:
        raise SimulationInputError(f"{name} must be > {low}")
    if math.isfinite(high):
        if high_inclusive:
            if number > high:
                raise SimulationInputError(f"{name} must be <= {high}")
        elif number >= high:
            raise SimulationInputError(f"{name} must be < {high}")
    return number


def require_fraction(name: str, value: Any) -> float:
    """A loss fraction in [0, 1). One would zero the energy at that stage."""
    return require_in_range(name, value, 0.0, 1.0, high_inclusive=False)


def require_positive(name: str, value: Any) -> float:
    return require_in_range(name, value, 0.0, math.inf, low_inclusive=False)


def require_non_negative(name: str, value: Any) -> float:
    return require_in_range(name, value, 0.0, math.inf)


def require_int(
    name: str,
    value: Any,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool):
        raise SimulationInputError(f"{name} must be an integer")
    number = require_finite(name, value)
    if abs(number - round(number)) > 1e-9:
        raise SimulationInputError(f"{name} must be an integer")
    parsed = int(round(number))
    if minimum is not None and parsed < minimum:
        raise SimulationInputError(f"{name} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise SimulationInputError(f"{name} must be <= {maximum}")
    return parsed


def validate_latitude(latitude: Any) -> float:
    return require_in_range("latitude", latitude, -90.0, 90.0)


def validate_longitude(longitude: Any) -> float:
    return require_in_range("longitude", longitude, -180.0, 180.0)


def validate_wacc(wacc: Any) -> float:
    """Discount rate must keep (1 + r) positive so discount factors are defined."""
    return require_in_range("wacc", wacc, -1.0, math.inf, low_inclusive=False)
