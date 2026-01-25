"""
Weather Data Module.

Fetches TMY data from PVGIS and generates synthetic weather data.
"""

import pandas as pd
import numpy as np
import requests
from typing import Optional, Tuple, Dict
from dataclasses import dataclass
from enum import Enum


class WeatherSource(Enum):
    """Available weather data sources."""
    PVGIS = "pvgis"
    SYNTHETIC = "synthetic"
    NASA_POWER = "nasa_power"
    LOCAL_FILE = "local_file"


@dataclass
class WeatherProvider:
    """Weather data provider configuration."""
    source: WeatherSource = WeatherSource.PVGIS
    cache_enabled: bool = True
    timeout_seconds: int = 30
    
    _cache: Dict[str, pd.DataFrame] = None
    
    def __post_init__(self):
        if self._cache is None:
            self._cache = {}
    
    def get_tmy(
        self,
        latitude: float,
        longitude: float,
        use_cache: bool = True
    ) -> Tuple[Optional[pd.DataFrame], str]:
        """Get TMY data for a location."""
        cache_key = f"{latitude:.2f}_{longitude:.2f}_{self.source.value}"
        
        if use_cache and self.cache_enabled and cache_key in self._cache:
            return self._cache[cache_key], "✅ Using cached data"
        
        if self.source == WeatherSource.PVGIS:
            data, status = fetch_pvgis_tmy(latitude, longitude, self.timeout_seconds)
        elif self.source == WeatherSource.SYNTHETIC:
            data = generate_synthetic_solar_tmy(latitude)
            status = "✅ Generated synthetic TMY data"
        else:
            data = generate_synthetic_solar_tmy(latitude)
            status = "⚠️ Source not implemented, using synthetic data"
        
        if data is not None and self.cache_enabled:
            self._cache[cache_key] = data
        
        return data, status


def fetch_pvgis_tmy(
    latitude: float,
    longitude: float,
    timeout: int = 30
) -> Tuple[Optional[pd.DataFrame], str]:
    """
    Fetch TMY (Typical Meteorological Year) data from PVGIS API.
    
    Args:
        latitude: Site latitude in degrees.
        longitude: Site longitude in degrees.
        timeout: Request timeout in seconds.
    
    Returns:
        Tuple of (DataFrame or None, status message)
    """
    url = "https://re.jrc.ec.europa.eu/api/v5_2/tmy"
    
    params = {
        "lat": latitude,
        "lon": longitude,
        "outputformat": "json",
        "usehorizon": 1,
        "startyear": 2005,
        "endyear": 2020
    }
    
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        
        hourly_data = data.get("outputs", {}).get("tmy_hourly", [])
        
        if not hourly_data:
            return None, "⚠️ No hourly data returned from PVGIS"
        
        # Parse to DataFrame
        records = []
        for hour in hourly_data:
            records.append({
                "time": hour.get("time(UTC)"),
                "ghi": hour.get("G(h)", 0),
                "dni": hour.get("Gb(n)", 0),
                "dhi": hour.get("Gd(h)", 0),
                "temp_air": hour.get("T2m", 20),
                "wind_speed": hour.get("WS10m", 3),
                "rh": hour.get("RH", 50),
            })
        
        df = pd.DataFrame(records)
        
        # Parse time and create proper index
        df["datetime"] = pd.to_datetime(df["time"], format="%Y%m%d:%H%M")
        df["datetime"] = df["datetime"].apply(lambda x: x.replace(year=2024))
        df = df.set_index("datetime")
        df = df.drop(columns=["time"])
        
        if len(df) < 8760:
            return None, f"⚠️ PVGIS returned only {len(df)} hours, expected 8760"
        
        df = df.iloc[:8760]
        
        return df, f"✅ Fetched TMY data from PVGIS ({latitude:.2f}°N, {longitude:.2f}°E)"
        
    except requests.exceptions.Timeout:
        return None, "⚠️ PVGIS request timed out. Using synthetic data."
    except requests.exceptions.RequestException as e:
        return None, f"⚠️ PVGIS request failed: {str(e)[:50]}. Using synthetic data."
    except Exception as e:
        return None, f"⚠️ Error parsing PVGIS data: {str(e)[:50]}. Using synthetic data."


def generate_synthetic_solar_tmy(latitude: float) -> pd.DataFrame:
    """Generate synthetic TMY data for solar simulation."""
    times = pd.date_range('2024-01-01', periods=8760, freq='h')
    hour = times.hour
    day_of_year = times.dayofyear
    
    # Seasonal variation
    declination = 23.45 * np.sin(np.radians((360/365) * (day_of_year - 81)))
    
    # Latitude-based intensity
    lat_factor = 1.0 - abs(latitude - 25) / 100
    lat_factor = np.clip(lat_factor, 0.6, 1.0)
    
    # GHI model with randomness
    ghi_base = 1000 * lat_factor * np.maximum(0, np.sin(np.pi * (hour - 6) / 12))
    ghi = ghi_base * (0.7 + 0.3 * np.random.rand(8760))
    
    # DNI and DHI
    clearness = 0.6 + 0.2 * np.random.rand(8760)
    dni = np.where(ghi > 50, ghi * clearness * 1.2, 0)
    dhi = np.where(ghi > 50, ghi * (1 - clearness) * 0.8, 0)
    
    # Temperature
    temp_base = 25 - abs(latitude - 25) * 0.3
    temp_seasonal = 10 * np.sin(np.radians((360/365) * (day_of_year - 81)))
    temp_daily = 5 * np.sin(np.pi * (hour - 6) / 12)
    temp_air = temp_base + temp_seasonal + temp_daily + np.random.randn(8760) * 2
    
    wind_speed = 3 + np.random.exponential(2, 8760)
    
    return pd.DataFrame({
        'ghi': np.clip(ghi, 0, 1200),
        'dni': np.clip(dni, 0, 1000),
        'dhi': np.clip(dhi, 0, 400),
        'temp_air': temp_air,
        'wind_speed': np.clip(wind_speed, 0, 20)
    }, index=times)


def generate_synthetic_wind_tmy(latitude: float) -> pd.DataFrame:
    """Generate synthetic TMY data for wind simulation."""
    times = pd.date_range('2024-01-01', periods=8760, freq='h')
    
    # Weibull distribution for wind speed
    scale = 7 + (abs(latitude - 45) / 10)
    wind_speed = np.random.weibull(2, 8760) * scale
    
    temperature = 15 - abs(latitude - 45) * 0.2 + np.random.randn(8760) * 5
    pressure = 1013 + np.random.randn(8760) * 10
    
    return pd.DataFrame({
        'wind_speed': np.clip(wind_speed, 0, 30),
        'temperature': temperature,
        'pressure': pressure
    }, index=times)


def load_weather_file(
    filepath: str,
    format: str = "auto"
) -> Tuple[Optional[pd.DataFrame], str]:
    """
    Load weather data from a local file.
    
    Supports CSV, Excel, and EPW formats.
    """
    try:
        if format == "auto":
            if filepath.endswith('.csv'):
                format = "csv"
            elif filepath.endswith('.xlsx') or filepath.endswith('.xls'):
                format = "excel"
            elif filepath.endswith('.epw'):
                format = "epw"
            else:
                format = "csv"
        
        if format == "csv":
            df = pd.read_csv(filepath, parse_dates=True, index_col=0)
        elif format == "excel":
            df = pd.read_excel(filepath, parse_dates=True, index_col=0)
        else:
            return None, f"⚠️ Unsupported format: {format}"
        
        # Validate required columns
        required = {'ghi', 'temp_air', 'wind_speed'}
        if not required.issubset(set(df.columns)):
            missing = required - set(df.columns)
            return None, f"⚠️ Missing columns: {missing}"
        
        return df, f"✅ Loaded weather data from {filepath}"
        
    except Exception as e:
        return None, f"⚠️ Error loading file: {str(e)}"
