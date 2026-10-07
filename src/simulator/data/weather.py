"""
Weather Data Module.

Fetches TMY data from PVGIS and generates synthetic weather data.
"""

import json
import zlib
from urllib.parse import urljoin, urlparse

import pandas as pd
import numpy as np
import pvlib
import requests
from typing import Optional, Tuple, Dict
from dataclasses import dataclass
from enum import Enum

from simulator.core.validation import (
    SimulationInputError,
    require_int,
    validate_latitude,
    validate_longitude,
)

PVGIS_HOSTS = {"re.jrc.ec.europa.eu"}
MAX_PVGIS_BYTES = 20 * 1024 * 1024
MAX_WEATHER_FILE_BYTES = 50 * 1024 * 1024
_ALLOWED_WEATHER_SUFFIXES = {".csv", ".xlsx", ".xls"}


def _site_seed(latitude: float, longitude: float, kind: str) -> int:
    key = f"{kind}:{latitude:.4f}:{longitude:.4f}".encode()
    return zlib.crc32(key) & 0xFFFFFFFF


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
            data = generate_synthetic_solar_tmy(latitude, longitude)
            status = "Synthetic solar series seeded from latitude and longitude. Not a climate dataset."
        else:
            data = None
            status = f"Weather source '{self.source.value}' is not implemented."
        
        if data is not None and self.cache_enabled:
            self._cache[cache_key] = data
        
        return data, status


def _move_timestamp_to_2023(stamp: pd.Timestamp) -> pd.Timestamp:
    """Place a TMY stamp on non-leap 2023. 29 February becomes 28 February."""
    try:
        return stamp.replace(year=2023)
    except ValueError:
        return stamp.replace(year=2023, day=28)


def _utc_year_index() -> pd.DatetimeIndex:
    """Non-leap 8760-hour index. 2024 is a leap year and is not used."""
    return pd.date_range("2023-01-01", periods=8760, freq="h", tz="UTC")


def fetch_pvgis_tmy(
    latitude: float,
    longitude: float,
    timeout: int = 30
) -> Tuple[Optional[pd.DataFrame], str]:
    """
    Fetch a PVGIS TMY.

    Returns (None, message) on failure. This function does not generate a
    replacement series. Responses are discarded unless the final host is
    re.jrc.ec.europa.eu and the body is at most 20 MB.
    """
    latitude = validate_latitude(latitude)
    longitude = validate_longitude(longitude)
    timeout = require_int("timeout", timeout, minimum=1, maximum=120)
    url = "https://re.jrc.ec.europa.eu/api/v5_2/tmy"
    params = {
        "lat": latitude,
        "lon": longitude,
        "outputformat": "json",
        "usehorizon": 1,
        "startyear": 2005,
        "endyear": 2020,
    }

    try:
        current_url = url
        current_params = params
        response = None
        for _ in range(5):
            host = urlparse(current_url).hostname
            if host not in PVGIS_HOSTS:
                return None, "PVGIS redirect host was not re.jrc.ec.europa.eu; request was not sent."
            response = requests.get(
                current_url,
                params=current_params,
                timeout=timeout,
                stream=True,
                allow_redirects=False,
            )
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                response.close()
                if not location:
                    return None, "PVGIS redirect had no location."
                current_url = urljoin(response.url, location)
                current_params = None
                continue
            break
        else:
            return None, "PVGIS returned too many redirects."
        with response:
            host = urlparse(response.url).hostname
            if host not in PVGIS_HOSTS:
                return None, "PVGIS response host was not re.jrc.ec.europa.eu; body discarded."
            response.raise_for_status()
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_PVGIS_BYTES:
                    return None, "PVGIS response exceeded 20 MB and was discarded."
                chunks.append(chunk)
        data = json.loads(b"".join(chunks))
    except requests.exceptions.Timeout:
        return None, "PVGIS request timed out."
    except requests.exceptions.RequestException:
        return None, "PVGIS request failed."
    except json.JSONDecodeError:
        return None, "PVGIS response was not valid JSON."

    hourly_data = data.get("outputs", {}).get("tmy_hourly", [])
    if not hourly_data:
        return None, "PVGIS returned no hourly data."

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
    try:
        df["datetime"] = pd.to_datetime(df["time"], format="%Y%m%d:%H%M", utc=True)
        df["datetime"] = df["datetime"].map(_move_timestamp_to_2023)
    except (TypeError, ValueError):
        return None, "PVGIS timestamps could not be parsed."
    df = df.set_index("datetime").drop(columns=["time"])
    if not df.index.is_unique:
        df = df[~df.index.duplicated(keep="first")]
    if len(df) < 8760:
        return None, f"PVGIS returned {len(df)} hours; 8760 were required."
    return df.iloc[:8760], (
        f"PVGIS TMY for {latitude:.2f} N, {longitude:.2f} E. "
        "Timestamps were moved onto non-leap year 2023 and labeled UTC."
    )


def generate_synthetic_solar_tmy(latitude: float, longitude: float = 0.0) -> pd.DataFrame:
    """Schematic solar year seeded from latitude and longitude.

    GHI is 900 * a latitude factor * sin(solar elevation) * small seeded noise.
    It is zero when the sun is below the horizon for that lat/lon. DNI and DHI
    are the Erbs decomposition of that GHI. This is not a climate dataset and
    not a PVGIS TMY.
    """
    latitude = validate_latitude(latitude)
    longitude = validate_longitude(longitude)
    times = _utc_year_index()
    solpos = pvlib.solarposition.get_solarposition(times, latitude, longitude)
    elevation = (90.0 - solpos["apparent_zenith"]).clip(lower=0)
    rng = np.random.default_rng(_site_seed(latitude, longitude, "solar"))
    lat_factor = float(np.clip(1.0 - abs(latitude) / 120.0, 0.35, 1.0))
    noise = 0.9 + 0.1 * rng.random(len(times))
    ghi = 900.0 * lat_factor * np.sin(np.radians(elevation.to_numpy())) * noise
    ghi = np.clip(ghi, 0, 1200)
    parts = pvlib.irradiance.erbs(ghi, solpos["apparent_zenith"], times)
    day = times.dayofyear.to_numpy()
    hour = times.hour.to_numpy()
    temp_air = (
        20.0
        - abs(latitude) * 0.15
        + 8.0 * np.sin(np.radians((360.0 / 365.0) * (day - 81)))
        + 5.0 * np.sin(np.pi * ((hour - 6) % 24) / 12.0)
        + rng.normal(0, 1.0, len(times))
    )
    wind_speed = 3.0 + rng.exponential(1.5, len(times))
    frame = pd.DataFrame(
        {
            "ghi": ghi,
            "dni": np.clip(parts["dni"].to_numpy(), 0, None),
            "dhi": np.clip(parts["dhi"].to_numpy(), 0, None),
            "temp_air": temp_air,
            "wind_speed": np.clip(wind_speed, 0, 25),
        },
        index=times,
    )
    frame.attrs["source"] = "synthetic_solar_schematic"
    return frame


def generate_synthetic_wind_tmy(latitude: float, longitude: float = 0.0) -> pd.DataFrame:
    """Schematic wind year. Weibull shape 2, scale 7 + abs(latitude - 45) / 10.

    The scale is not a wind-atlas value. The same latitude and longitude
    reproduce the same series.
    """
    latitude = validate_latitude(latitude)
    longitude = validate_longitude(longitude)
    times = _utc_year_index()
    rng = np.random.default_rng(_site_seed(latitude, longitude, "wind"))
    scale = 7.0 + abs(latitude - 45.0) / 10.0
    wind_speed = rng.weibull(2.0, len(times)) * scale
    temperature = 15.0 - abs(latitude - 45.0) * 0.2 + rng.normal(0, 3.0, len(times))
    pressure = 1013.0 + rng.normal(0, 8.0, len(times))
    frame = pd.DataFrame(
        {
            "wind_speed": np.clip(wind_speed, 0, 30),
            "temperature": temperature,
            "pressure": np.clip(pressure, 800, 1100),
        },
        index=times,
    )
    frame.attrs["source"] = "synthetic_wind_schematic"
    return frame


def load_weather_file(
    filepath: str,
    format: str = "auto"
) -> Tuple[Optional[pd.DataFrame], str]:
    """
    Load weather data from a local file.
    
    Accepts .csv, .xlsx, and .xls. The returned message does not include
    the parser exception text.
    """
    try:
        from pathlib import Path

        if "\x00" in filepath:
            return None, "Weather path is not valid."
        path = Path(filepath).expanduser().resolve()
        if path.suffix.lower() not in _ALLOWED_WEATHER_SUFFIXES:
            return None, "Weather file suffix must be .csv, .xlsx, or .xls."
        if not path.is_file():
            return None, "Weather path is not a file."
        if path.stat().st_size > MAX_WEATHER_FILE_BYTES:
            return None, "Weather file exceeds 50 MB."
        if format == "auto":
            format = "excel" if path.suffix.lower() in {".xlsx", ".xls"} else "csv"
        if format == "csv":
            df = pd.read_csv(path, parse_dates=True, index_col=0)
        elif format == "excel":
            df = pd.read_excel(path, parse_dates=True, index_col=0)
        else:
            return None, f"Unsupported format: {format}"
        
        # Validate required columns
        required = {'ghi', 'temp_air', 'wind_speed'}
        if not required.issubset(set(df.columns)):
            missing = required - set(df.columns)
            return None, f"⚠️ Missing columns: {missing}"
        
        return df, "Loaded weather data."
    except Exception:
        return None, "Weather file could not be read."
