"""
Example offline geolocation plugin for Silva.

Copy this file anywhere and set offline_geolocation_module in ~/.silva/config.json:

  "offline_geolocation_module": "C:/path/to/offline_geo_example.py"

The plugin must define:

    def get_location() -> tuple[str, float, float] | None:
        return ("My City", 35.123, -84.456)  # city, latitude, longitude
"""


def get_location() -> tuple[str, float, float] | None:
    # Return None to let Silva fall back to other location methods.
    return None
