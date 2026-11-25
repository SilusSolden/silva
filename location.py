"""Location detection for Silva."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from silva.config import CONFIG_DIR, load_config, save_config

LocationResult = tuple[str, float, float]
LocationProvider = Callable[[], LocationResult | None]

REQUEST_TIMEOUT = 10
_offline_providers: list[LocationProvider] = []


@dataclass
class ResolvedLocation:
    city: str
    latitude: float
    longitude: float
    source: str


def register_offline_provider(provider: LocationProvider) -> None:
    """Register a custom offline geolocation provider."""
    _offline_providers.append(provider)


def is_wifi_connected() -> bool:
    """Return True when a Wi-Fi interface is connected."""
    if sys.platform != "win32":
        return False

    result = subprocess.run(
        ["netsh", "wlan", "show", "interfaces"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        return False

    for line in result.stdout.splitlines():
        if line.strip().lower().startswith("state"):
            return "connected" in line.lower()
    return False


def _scan_wifi_access_points() -> list[dict]:
    if sys.platform != "win32":
        return []

    result = subprocess.run(
        ["netsh", "wlan", "show", "networks", "mode=bssid"],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    if result.returncode != 0:
        return []

    access_points: list[dict] = []
    current: dict = {}

    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("SSID"):
            if current.get("macAddress"):
                access_points.append(current)
            ssid = line.split(":", 1)[1].strip()
            current = {"ssid": ssid} if ssid else {}
        elif "BSSID" in line and ":" in line:
            mac = line.split(":", 1)[1].strip().replace("-", ":").lower()
            current["macAddress"] = mac
        elif line.startswith("Signal"):
            match = re.search(r"(\d+)", line)
            if match:
                current["signalStrength"] = int(match.group(1))

    if current.get("macAddress"):
        access_points.append(current)

    return access_points


def _geolocate_windows() -> LocationResult | None:
    if sys.platform != "win32":
        return None

    script = CONFIG_DIR / "scripts" / "windows_geo.ps1"
    script.parent.mkdir(parents=True, exist_ok=True)
    if not script.exists():
        script.write_text(
            'Add-Type -AssemblyName System.Device\n'
            "$watcher = New-Object System.Device.Location.GeoCoordinateWatcher\n"
            "$null = $watcher.TryStart($false, [TimeSpan]::FromSeconds(10))\n"
            "$deadline = (Get-Date).AddSeconds(10)\n"
            "while ($watcher.Status -ne 'Ready' -and (Get-Date) -lt $deadline) {\n"
            "    Start-Sleep -Milliseconds 200\n"
            "}\n"
            "if ($watcher.Status -eq 'Ready') {\n"
            "    $loc = $watcher.Position.Location\n"
            '    Write-Output "OK $($loc.Latitude) $($loc.Longitude)"\n'
            "} else {\n"
            '    Write-Output "FAILED"\n'
            "}\n",
            encoding="utf-8",
        )

    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("OK "):
            parts = line.split()
            if len(parts) >= 3:
                return "Current location", float(parts[1]), float(parts[2])
    return None


def _geolocate_wifi_scan() -> LocationResult | None:
    access_points = _scan_wifi_access_points()
    if not access_points:
        return None

    payload = {
        "wifiAccessPoints": [
            {
                "macAddress": ap["macAddress"],
                "signalStrength": ap.get("signalStrength", 50),
            }
            for ap in access_points[:25]
        ]
    }

    try:
        resp = requests.post(
            "https://location.services.mozilla.com/v1/geolocate?key=test",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        location = data.get("location", {})
        lat = location.get("lat")
        lon = location.get("lng")
        if lat is None or lon is None:
            return None
        return "Current location", float(lat), float(lon)
    except requests.RequestException:
        return None


def _geolocate_ip() -> LocationResult | None:
    try:
        resp = requests.get(
            "http://ip-api.com/json/?fields=status,city,lat,lon",
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            return None
        return data["city"], float(data["lat"]), float(data["lon"])
    except requests.RequestException:
        return None


def _reverse_geocode(lat: float, lon: float) -> str | None:
    try:
        resp = requests.get(
            f"http://wttr.in/{lat},{lon}?format=j1",
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "Silva/0.1"},
        )
        resp.raise_for_status()
        area = resp.json()["nearest_area"][0]["areaName"][0]["value"]
        return area
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None


def _load_plugin_location(module_path: str) -> LocationResult | None:
    path = Path(module_path).expanduser()
    if not path.exists():
        return None

    spec = importlib.util.spec_from_file_location("silva_geo_plugin", path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "get_location"):
        return None

    result = module.get_location()
    if result is None:
        return None

    city, lat, lon = result
    return str(city), float(lat), float(lon)


def _saved_location() -> LocationResult | None:
    config = load_config()
    lat = config.get("latitude")
    lon = config.get("longitude")
    if lat is None or lon is None:
        return None
    city = config.get("city", "").strip() or f"{lat}, {lon}"
    return city, float(lat), float(lon)


def resolve_location(*, require_wifi: bool = False, prefer_fresh: bool = False) -> ResolvedLocation:
    """
    Resolve the best available location.

    Priority when prefer_fresh is True (live weather on Wi-Fi):
    1. Offline plugin
    2. Windows location / Wi-Fi scan / IP geolocation
    3. Saved config coordinates

    Priority when offline or prefer_fresh is False:
    1. Offline plugin
    2. Saved config coordinates
    3. Wi-Fi based location methods
    """
    config = load_config()

    plugin_path = config.get("offline_geolocation_module", "").strip()
    if plugin_path:
        plugin_loc = _load_plugin_location(plugin_path)
        if plugin_loc:
            city, lat, lon = plugin_loc
            return ResolvedLocation(city, lat, lon, "offline_plugin")

    for provider in _offline_providers:
        provider_loc = provider()
        if provider_loc:
            city, lat, lon = provider_loc
            return ResolvedLocation(city, lat, lon, "offline_provider")

    on_wifi = is_wifi_connected()
    if require_wifi and not on_wifi:
        saved = _saved_location()
        if saved:
            city, lat, lon = saved
            return ResolvedLocation(city, lat, lon, "saved_config_offline")
        raise RuntimeError(
            "Not connected to Wi-Fi. Connect to Wi-Fi for live weather, "
            "save a location in ~/.silva/config.json, or add an offline "
            "geolocation plugin via offline_geolocation_module."
        )

    if not prefer_fresh and config.get("use_saved_location", True):
        saved = _saved_location()
        if saved:
            city, lat, lon = saved
            return ResolvedLocation(city, lat, lon, "saved_config")

    if on_wifi:
        for source_name, resolver in (
            ("windows_location", _geolocate_windows),
            ("wifi_scan", _geolocate_wifi_scan),
            ("ip_geolocation", _geolocate_ip),
        ):
            located = resolver()
            if located:
                city, lat, lon = located
                if city == "Current location":
                    resolved_city = _reverse_geocode(lat, lon)
                    if resolved_city:
                        city = resolved_city

                config["city"] = city
                config["latitude"] = lat
                config["longitude"] = lon
                save_config(config)
                return ResolvedLocation(city, lat, lon, source_name)

    saved = _saved_location()
    if saved:
        city, lat, lon = saved
        return ResolvedLocation(city, lat, lon, "saved_config")

    raise RuntimeError(
        "Could not determine your location. Connect to Wi-Fi or configure "
        "latitude/longitude in ~/.silva/config.json."
    )
