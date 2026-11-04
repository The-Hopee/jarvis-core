"""Location, weather and places: live sources, explicit precision and bounded results."""
import math
import time
from urllib.parse import urlencode

from .http import ServiceError, request_json
from .ipc import KernelError


def coordinates(latitude, longitude):
    lat, lon = float(latitude), float(longitude)
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ServiceError("Сервис вернул некорректные координаты")
    return lat, lon


class LocalServices:
    def __init__(self, settings, kernel, http=request_json):
        self.settings, self.kernel, self.http = settings, kernel, http
        self._cache = {}

    def _cached(self, key, seconds, fetch):
        entry = self._cache.get(key)
        if entry and time.monotonic() - entry[0] < seconds:
            return entry[1]
        value = fetch()
        self._cache[key] = (time.monotonic(), value)
        return value

    def _city(self, city):
        params = urlencode({"name": city, "count": 1, "language": "ru", "format": "json"})
        data = self.http("https://geocoding-api.open-meteo.com/v1/search?" + params)
        if not data.get("results"):
            raise ServiceError(f"Город «{city}» не найден. Уточните название.")
        place = data["results"][0]
        lat, lon = coordinates(place["latitude"], place["longitude"])
        return {"latitude": lat, "longitude": lon, "city": place["name"],
                "country": place.get("country"), "source": "configured_city",
                "approximate": True, "accuracy_meters": None,
                "precision_note": "Координаты центра выбранного города, не адрес пользователя."}

    def location(self, city: str = ""):
        key = ("location", city.casefold())
        return self._cached(key, 600, lambda: self._location(city))

    def _location(self, city):
        if city:
            return self._city(city)
        settings = self.settings
        if settings.latitude is not None:
            return {"latitude": settings.latitude, "longitude": settings.longitude,
                    "city": settings.city or None, "source": "configured_coordinates",
                    "approximate": False, "accuracy_meters": None,
                    "precision_note": "Координаты заданы пользователем; точность не измерена."}
        if settings.city:
            return self._city(settings.city)
        try:
            position = self.kernel.call("get_location", {"timeout_seconds": 3})["result"]
            coordinates(position["latitude"], position["longitude"])
            position["city"] = None
            position["precision_note"] = "Местоположение Windows; смотрите accuracy_meters и sample_age_seconds."
            return position
        except KernelError:
            pass
        try:
            data = self.http("https://ipapi.co/json/", timeout=8)
            if data.get("error"):
                raise ServiceError("IP-геолокация недоступна")
            lat, lon = coordinates(data["latitude"], data["longitude"])
            # Deliberately discard public IP, postal address and network metadata.
            return {"latitude": lat, "longitude": lon, "city": data.get("city"),
                    "country": data.get("country_name"), "source": "ip_city",
                    "approximate": True, "accuracy_meters": None,
                    "precision_note": "Приблизительно по IP: VPN/провайдер могут указывать другой город. Это не точный адрес."}
        except (ServiceError, KeyError, TypeError, ValueError) as exc:
            raise ServiceError("Не удалось определить местоположение. Включите геолокацию Windows или задайте JARVIS_CITY в .env.") from exc

    def weather(self, city: str = ""):
        return self._cached(("weather", city.casefold()), 300, lambda: self._weather(city))

    def _weather(self, city):
        location = self.location(city)
        params = urlencode({"latitude": location["latitude"], "longitude": location["longitude"],
                            "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
                            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                            "timezone": "auto", "forecast_days": 2})
        data = self.http("https://api.open-meteo.com/v1/forecast?" + params)
        if not isinstance(data.get("current"), dict) or data["current"].get("temperature_2m") is None:
            raise ServiceError("Сервис погоды не вернул текущую температуру")
        return {"location": location, "current": data["current"], "current_units": data.get("current_units", {}),
                "daily": data.get("daily", {}), "timezone": data.get("timezone"),
                "source": "Open-Meteo", "source_url": "https://open-meteo.com/",
                "note": "Модельная оценка погоды; время измерения — current.time. Прогноз не является гарантией."}

    def places(self, category="parks", city="", radius_m=5000, limit=5):
        return self._cached(("places", category, city.casefold(), radius_m, limit), 600,
                            lambda: self._places(category, city, radius_m, limit))

    def _places(self, category, city, radius_m, limit):
        filters = {"parks": '["leisure"="park"]', "cafes": '["amenity"="cafe"]',
                   "restaurants": '["amenity"="restaurant"]', "museums": '["tourism"="museum"]'}
        location = self.location(city)
        lat, lon = coordinates(location["latitude"], location["longitude"])
        query = (f'[out:json][timeout:6];nwr(around:{radius_m},{lat:.6f},{lon:.6f})'
                 f'{filters[category]}["name"];out center 60;')
        payload = urlencode({"data": query}).encode("utf-8")
        data = None
        for endpoint in ("https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass.private.coffee/api/interpreter"):
            try:
                data = self.http(endpoint, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"},
                                 timeout=9, max_bytes=1024 * 1024)
                if data.get("remark"):
                    raise ServiceError("Overpass вернул неполный результат")
                break
            except ServiceError:
                data = None
        if data is None:
            labels = {"parks": "парки", "cafes": "кафе", "restaurants": "рестораны", "museums": "музеи"}
            search = urlencode({"text": labels[category], "ll": f"{lon:.6f},{lat:.6f}", "z": "13"})
            return {"location": location, "category": category, "radius_m": radius_m, "places": [],
                    "lookup_status": "unavailable", "search_url": "https://yandex.ru/maps/?" + search,
                    "note": "Серверы списка мест недоступны. Доступна ссылка на поиск по карте; конкретные заведения не проверены."}
        items = []
        for element in data.get("elements", []):
            tags = element.get("tags", {})
            center = element.get("center", element)
            if not tags.get("name") or "lat" not in center or "lon" not in center:
                continue
            place_lat, place_lon = coordinates(center["lat"], center["lon"])
            a = (math.sin(math.radians(place_lat-lat)/2)**2 + math.cos(math.radians(lat))*
                 math.cos(math.radians(place_lat))*math.sin(math.radians(place_lon-lon)/2)**2)
            distance = round(6371000 * 2 * math.asin(math.sqrt(min(1, a))))
            element_type, element_id = element.get("type"), element.get("id")
            if element_type not in {"node", "way", "relation"} or not isinstance(element_id, int):
                continue
            items.append({"name": tags["name"][:200], "distance_from_estimated_point_m": distance,
                          "address": " ".join(str(tags.get(k, "")) for k in ("addr:street", "addr:housenumber")).strip(),
                          "opening_hours_raw": tags.get("opening_hours"),
                          "map_url": f"https://www.openstreetmap.org/{element_type}/{element_id}"})
        items.sort(key=lambda item: item["distance_from_estimated_point_m"])
        return {"location": location, "category": category, "radius_m": radius_m, "places": items[:limit], "lookup_status": "ok",
                "attribution": "© OpenStreetMap contributors (ODbL)", "source_url": "https://www.openstreetmap.org/copyright",
                "note": "Расстояние по прямой от определённой точки; при IP/городе это не расстояние от дома. Часы работы и наличие мест не проверены."}
