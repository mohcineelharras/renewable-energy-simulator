"""Synthetic weather and PVGIS response checks."""

import json

import pandas as pd
import pytest
import requests

from simulator.core.validation import SimulationInputError
from simulator.data.weather import (
    MAX_PVGIS_BYTES,
    fetch_pvgis_tmy,
    generate_synthetic_solar_tmy,
    generate_synthetic_wind_tmy,
    load_weather_file,
)


class _Response:
    def __init__(self, url, chunks, status=200, headers=None):
        self.url = url
        self.status_code = status
        self.headers = {} if headers is None else headers
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def close(self):
        return None

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("status")

    def iter_content(self, chunk_size=65536):
        yield from self._chunks


def _hour(lat, lon, year_month_day_hour):
    frame = generate_synthetic_solar_tmy(lat, lon)
    stamp = pd.Timestamp(year_month_day_hour, tz="UTC")
    return frame.loc[stamp, "ghi"]


def test_synthetic_solar_is_reproducible_and_dark_at_night():
    first = generate_synthetic_solar_tmy(31.6, -8.0)
    second = generate_synthetic_solar_tmy(31.6, -8.0)
    pd.testing.assert_frame_equal(first, second)
    assert first.loc[pd.Timestamp("2023-01-01 00:00", tz="UTC"), "ghi"] == pytest.approx(0.0)


def test_longitude_moves_the_solar_peak():
    east = generate_synthetic_solar_tmy(0.0, 0.0)
    west = generate_synthetic_solar_tmy(0.0, 90.0)
    day = "2023-06-21"
    assert east.loc[day, "ghi"].idxmax().hour != west.loc[day, "ghi"].idxmax().hour


def test_synthetic_wind_is_seeded():
    pd.testing.assert_frame_equal(
        generate_synthetic_wind_tmy(35.0, -5.0),
        generate_synthetic_wind_tmy(35.0, -5.0),
    )


def test_pvgis_does_not_follow_a_redirect_off_host(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        assert kwargs.get("allow_redirects") is False
        return _Response(
            url,
            [b"{}"],
            status=302,
            headers={"Location": "https://evil.example/collect"},
        )

    monkeypatch.setattr(requests, "get", fake_get)
    frame, message = fetch_pvgis_tmy(31.6, -8.0)
    assert frame is None
    assert calls == ["https://re.jrc.ec.europa.eu/api/v5_2/tmy"]
    assert "not sent" in message


def test_pvgis_discards_an_oversized_body(monkeypatch):
    def fake_get(*args, **kwargs):
        return _Response(
            "https://re.jrc.ec.europa.eu/api/v5_2/tmy",
            [b"x" * (MAX_PVGIS_BYTES + 1)],
        )

    monkeypatch.setattr(requests, "get", fake_get)
    frame, message = fetch_pvgis_tmy(31.6, -8.0)
    assert frame is None
    assert "20 MB" in message


def test_pvgis_does_not_invent_a_series_for_a_short_payload(monkeypatch):
    payload = {
        "outputs": {
            "tmy_hourly": [
                {"time(UTC)": "20200101:0000", "G(h)": 0, "Gb(n)": 0, "Gd(h)": 0, "T2m": 10, "WS10m": 1}
            ]
        }
    }

    def fake_get(*args, **kwargs):
        return _Response("https://re.jrc.ec.europa.eu/api/v5_2/tmy", [json.dumps(payload).encode()])

    monkeypatch.setattr(requests, "get", fake_get)
    frame, message = fetch_pvgis_tmy(31.6, -8.0)
    assert frame is None
    assert "8760" in message


def test_pvgis_keeps_a_leap_day_february_on_2023(monkeypatch):
    stamps = pd.date_range("2012-01-01", periods=8784, freq="h")
    payload = {
        "outputs": {
            "tmy_hourly": [
                {
                    "time(UTC)": stamp.strftime("%Y%m%d:%H%M"),
                    "G(h)": 0,
                    "Gb(n)": 0,
                    "Gd(h)": 0,
                    "T2m": 10,
                    "WS10m": 1,
                }
                for stamp in stamps
            ]
        }
    }
    body = json.dumps(payload).encode()

    def fake_get(*args, **kwargs):
        return _Response("https://re.jrc.ec.europa.eu/api/v5_2/tmy", [body])

    monkeypatch.setattr(requests, "get", fake_get)
    frame, message = fetch_pvgis_tmy(31.6, -8.0)
    assert frame is not None
    assert len(frame) == 8760
    assert frame.index.year.unique().tolist() == [2023]
    assert not ((frame.index.month == 2) & (frame.index.day == 29)).any()
    assert "parsed" not in message.lower()


def test_pvgis_rejects_latitude_before_the_request(monkeypatch):
    def fake_get(*args, **kwargs):
        raise AssertionError("request should not be sent")

    monkeypatch.setattr(requests, "get", fake_get)
    with pytest.raises(SimulationInputError):
        fetch_pvgis_tmy(120, 0)


def test_weather_file_suffix_size_and_error_text(tmp_path, monkeypatch):
    rejected, message = load_weather_file(str(tmp_path / "series.epw"))
    assert rejected is None
    assert "suffix" in message.lower()

    csv_path = tmp_path / "ok.csv"
    csv_path.write_text("ghi,temp_air,wind_speed\n1,20,3\n")
    monkeypatch.setattr("simulator.data.weather.MAX_WEATHER_FILE_BYTES", 1)
    rejected, message = load_weather_file(str(csv_path))
    assert rejected is None
    assert "50 MB" in message

    monkeypatch.setattr("simulator.data.weather.MAX_WEATHER_FILE_BYTES", 50 * 1024 * 1024)

    def boom(*args, **kwargs):
        raise RuntimeError("SECRET_TOKEN")

    monkeypatch.setattr(pd, "read_csv", boom)
    rejected, message = load_weather_file(str(csv_path))
    assert rejected is None
    assert "SECRET_TOKEN" not in message
