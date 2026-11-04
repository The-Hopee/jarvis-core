"""Opt-in live read-only checks. Does not print IP addresses or precise coordinates."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.config import Settings
from jarvis.ipc import KernelClient
from jarvis.services import LocalServices
from jarvis.setup import ensure_native_config


settings = Settings.load()
sys.stdout.reconfigure(encoding='utf-8')
with KernelClient(settings.executable, ensure_native_config(settings)) as kernel:
    services = LocalServices(settings, kernel)
    location = services.location()
    weather = services.weather()
    places = services.places(limit=2)
    print(json.dumps({'location_source': location['source'], 'city': location.get('city'),
                      'approximate': location['approximate'], 'weather_source': weather['source'],
                      'weather_timestamp': weather['current'].get('time'),
                      'places_status': places.get('lookup_status'),
                      'map_fallback_available': bool(places.get('search_url')),
                      'places_found': len(places['places']),
                      'place_links': [p['map_url'] for p in places['places']]}, ensure_ascii=False, indent=2))
