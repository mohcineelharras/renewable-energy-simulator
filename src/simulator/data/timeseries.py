"""
Time Series Utilities.

Helper functions for time series data manipulation.
"""

import pandas as pd
import numpy as np
from typing import List, Optional, Union


def resample_timeseries(
    data: pd.DataFrame,
    target_freq: str = "h",
    method: str = "mean"
) -> pd.DataFrame:
    """
    Resample time series to target frequency.
    
    Args:
        data: Input DataFrame with DatetimeIndex.
        target_freq: Target frequency ('h', '15min', 'D', etc.)
        method: Aggregation method ('mean', 'sum', 'max', 'min')
    
    Returns:
        Resampled DataFrame.
    """
    if method == "mean":
        return data.resample(target_freq).mean()
    elif method == "sum":
        return data.resample(target_freq).sum()
    elif method == "max":
        return data.resample(target_freq).max()
    elif method == "min":
        return data.resample(target_freq).min()
    else:
        return data.resample(target_freq).mean()


def fill_missing_data(
    data: pd.DataFrame,
    method: str = "interpolate",
    limit: int = 24
) -> pd.DataFrame:
    """
    Fill missing data in time series.
    
    Args:
        data: Input DataFrame with potential NaN values.
        method: Fill method ('interpolate', 'ffill', 'bfill', 'zero')
        limit: Maximum consecutive NaNs to fill.
    
    Returns:
        DataFrame with filled values.
    """
    if method == "interpolate":
        return data.interpolate(method='time', limit=limit)
    elif method == "ffill":
        return data.ffill(limit=limit)
    elif method == "bfill":
        return data.bfill(limit=limit)
    elif method == "zero":
        return data.fillna(0)
    else:
        return data.interpolate(limit=limit)


def align_timeseries(
    series_list: List[Union[pd.Series, pd.DataFrame]],
    method: str = "inner"
) -> List[Union[pd.Series, pd.DataFrame]]:
    """
    Align multiple time series to common index.
    
    Args:
        series_list: List of Series or DataFrames to align.
        method: Join method ('inner', 'outer', 'left', 'right')
    
    Returns:
        List of aligned Series/DataFrames.
    """
    if not series_list:
        return []
    
    # Get common index
    if method == "inner":
        common_index = series_list[0].index
        for s in series_list[1:]:
            common_index = common_index.intersection(s.index)
    elif method == "outer":
        common_index = series_list[0].index
        for s in series_list[1:]:
            common_index = common_index.union(s.index)
    else:
        common_index = series_list[0].index
    
    # Reindex all series
    return [s.reindex(common_index) for s in series_list]


def timestep_hours(index: pd.Index) -> np.ndarray:
    """Duration of each row in hours.

    Datetime indexes use the positive spacing of the series. The first row
    uses the median positive spacing. A non-datetime index is treated as
    one hour per row; callers must record that assumption.
    """
    count = len(index)
    if count == 0:
        return np.array([], dtype=float)
    if isinstance(index, pd.DatetimeIndex) and count >= 2:
        delta = index.to_series().diff().dt.total_seconds().to_numpy(dtype=float) / 3600.0
        positive = delta[np.isfinite(delta) & (delta > 0)]
        default = float(np.median(positive)) if len(positive) else 1.0
        delta = np.where(np.isfinite(delta) & (delta > 0), delta, default)
        return delta
    return np.ones(count, dtype=float)


def integrate_power_kwh(power_kw: pd.Series) -> float:
    """Integrate a power series (kW) to energy (kWh) using row durations."""
    if len(power_kw) == 0:
        return 0.0
    hours = timestep_hours(power_kw.index)
    values = np.asarray(power_kw.to_numpy(dtype=float), dtype=float)
    return float(np.nansum(values * hours))


def calculate_capacity_factor(
    generation: pd.Series,
    rated_capacity_kw: float,
    period_hours: Optional[int] = None
) -> float:
    """
    Calculate capacity factor for generation time series.
    
    Args:
        generation: Generation time series in kW.
        rated_capacity_kw: Rated capacity in kW.
        period_hours: Hours in period (auto-detected if None).
    
    Returns:
        Capacity factor as fraction (0-1).
    """
    energy_kwh = integrate_power_kwh(generation)
    if period_hours is None:
        period_hours = float(timestep_hours(generation.index).sum())
    max_possible = rated_capacity_kw * period_hours
    
    return energy_kwh / max_possible if max_possible > 0 else 0


def create_load_profile(
    peak_load_kw: float,
    profile_type: str = "commercial",
    periods: int = 8760
) -> pd.Series:
    """
    Create a synthetic load profile.
    
    Args:
        peak_load_kw: Peak load in kW.
        profile_type: Type of load profile ('residential', 'commercial', 'industrial')
        periods: Number of hourly periods.
    
    Returns:
        Load profile as Series.
    """
    times = pd.date_range('2024-01-01', periods=periods, freq='h')
    hour = times.hour
    weekday = times.weekday
    
    if profile_type == "residential":
        # Morning and evening peaks
        base = 0.3
        morning_peak = 0.2 * np.exp(-((hour - 8) ** 2) / 8)
        evening_peak = 0.5 * np.exp(-((hour - 19) ** 2) / 8)
        profile = base + morning_peak + evening_peak
        
    elif profile_type == "commercial":
        # Office hours peak
        base = 0.2
        workday = (weekday < 5).astype(float)
        work_hours = ((hour >= 8) & (hour <= 18)).astype(float)
        profile = base + 0.7 * workday * work_hours + np.random.rand(periods) * 0.1
        
    elif profile_type == "industrial":
        # Flat with slight variation
        base = 0.7
        profile = base + 0.2 * (weekday < 5).astype(float) + np.random.rand(periods) * 0.1
        
    else:
        profile = np.ones(periods) * 0.5
    
    profile = profile / profile.max() * peak_load_kw
    
    return pd.Series(profile, index=times)


def aggregate_annual(
    hourly_data: pd.DataFrame,
    columns: Optional[List[str]] = None
) -> pd.DataFrame:
    """
    Aggregate hourly data to annual summaries.
    
    Args:
        hourly_data: Hourly DataFrame.
        columns: Columns to aggregate (all numeric if None).
    
    Returns:
        Annual summary DataFrame.
    """
    if columns is None:
        columns = hourly_data.select_dtypes(include=[np.number]).columns.tolist()
    
    annual = hourly_data[columns].resample('YE').agg({
        col: ['sum', 'mean', 'max', 'min'] for col in columns
    })
    
    # Flatten column names
    annual.columns = ['_'.join(col).strip() for col in annual.columns.values]
    
    return annual
