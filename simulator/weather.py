"""
Weather Data Module
Fetches TMY data from PVGIS and generates synthetic wind data.
"""
import pandas as pd
import numpy as np
import requests
from typing import Optional, Tuple
import io

def fetch_pvgis_tmy(latitude: float, longitude: float) -> Tuple[Optional[pd.DataFrame], str]:
    """
    Fetch TMY (Typical Meteorological Year) data from PVGIS API.
    
    Returns:
        Tuple of (DataFrame or None, status message)
    """
    # PVGIS API endpoint for TMY data
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
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Extract hourly data
        hourly_data = data.get("outputs", {}).get("tmy_hourly", [])
        
        if not hourly_data:
            return None, "No hourly data returned from PVGIS"
        
        # Parse to DataFrame
        records = []
        for hour in hourly_data:
            records.append({
                "time": hour.get("time(UTC)"),
                "ghi": hour.get("G(h)", 0),  # Global horizontal irradiance
                "dni": hour.get("Gb(n)", 0),  # Direct normal irradiance
                "dhi": hour.get("Gd(h)", 0),  # Diffuse horizontal irradiance
                "temp_air": hour.get("T2m", 20),  # Air temperature at 2m
                "wind_speed": hour.get("WS10m", 3),  # Wind speed at 10m
                "rh": hour.get("RH", 50),  # Relative humidity
            })
        
        df = pd.DataFrame(records)
        
        # Parse time and create proper index
        # PVGIS format: "20050101:0010" -> YYYYMMDD:HHMM
        df["datetime"] = pd.to_datetime(df["time"], format="%Y%m%d:%H%M")
        
        # Set to a standard year (2024) for consistency
        df["datetime"] = df["datetime"].apply(lambda x: x.replace(year=2024))
        df = df.set_index("datetime")
        df = df.drop(columns=["time"])
        
        # Ensure we have 8760 hours
        if len(df) < 8760:
            return None, f"PVGIS returned only {len(df)} hours, expected 8760"
        
        df = df.iloc[:8760]  # Take first 8760 hours
        
        return df, f"✅ Fetched TMY data from PVGIS ({latitude:.2f}°N, {longitude:.2f}°E)"
        
    except requests.exceptions.Timeout:
        return None, "⚠️ PVGIS request timed out. Using synthetic data."
    except requests.exceptions.RequestException as e:
        return None, f"⚠️ PVGIS request failed: {str(e)[:50]}. Using synthetic data."
    except Exception as e:
        return None, f"⚠️ Error parsing PVGIS data: {str(e)[:50]}. Using synthetic data."

def generate_synthetic_solar_tmy(latitude: float) -> pd.DataFrame:
    """Generate synthetic TMY data for solar simulation (fallback)."""
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
    
    # Temperature (seasonal)
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
