import random
import math
import requests
import polyline
import os
from functools import lru_cache

# --- 1. Route Service ---

def _decode_gmaps_polyline(encoded):
    """Decode a Google Maps encoded polyline into [{lat, lng}] waypoints."""
    pts = polyline.decode(encoded)
    return [{"lat": lat, "lng": lng} for lat, lng in pts]


def _classify_segments_from_steps(legs):
    """
    Analyse Google Maps step-level data to identify highway vs traffic zones.
    Returns a list of 3 segment dicts with real distance, time, and road type.
    """
    all_steps = []
    for leg in legs:
        all_steps.extend(leg.get('steps', []))

    total_dist_m   = sum(s['distance']['value']  for s in all_steps) if all_steps else 1
    total_dur_s    = sum(s['duration']['value']   for s in all_steps) if all_steps else 60

    # Split steps into 3 equal-distance thirds
    third = total_dist_m / 3
    segments_raw = [[], [], []]
    running = 0
    current_seg = 0
    for step in all_steps:
        if current_seg < 2 and running + step['distance']['value'] > third * (current_seg + 1):
            current_seg += 1
        if current_seg < 3:
            segments_raw[current_seg].append(step)
        running += step['distance']['value']

    result = []
    for idx, seg_steps in enumerate(segments_raw):
        dist_km  = sum(s['distance']['value'] for s in seg_steps) / 1000 if seg_steps else total_dist_m / 3000
        dur_mins = sum(s['duration']['value'] for s in seg_steps) / 60   if seg_steps else total_dur_s / 180

        # Detect traffic zones: slow speed (<30 km/h) = urban congestion
        avg_speed_kmh = (dist_km / (dur_mins / 60)) if dur_mins > 0 else 60
        road_type = "traffic_zone" if avg_speed_kmh < 35 else "highway"

        result.append({
            "distance":  round(dist_km, 2),
            "time_mins": max(1, int(dur_mins)),
            "type":      road_type,
            "avg_speed_kmh": round(avg_speed_kmh, 1)
        })

    return result, total_dist_m / 1000, total_dur_s / 60


def get_gmaps_routes(origin, destination):
    """
    Fetch up to 3 real route alternatives from Google Maps Directions API.
    Returns a list of raw route dicts or [] on failure.
    """
    api_key = os.environ.get('Maps_API_KEY', '')
    if not api_key:
        return []

    try:
        url = (
            "https://maps.googleapis.com/maps/api/directions/json"
            f"?origin={origin['lat']},{origin['lng']}"
            f"&destination={destination['lat']},{destination['lng']}"
            f"&alternatives=true"
            f"&mode=driving"
            f"&key={api_key}"
        )
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') == 'OK':
                return data.get('routes', [])
            else:
                print(f"Google Maps Directions API status: {data.get('status')} — {data.get('error_message','')}")
    except Exception as e:
        print(f"Google Maps Directions API error: {e}")
    return []


def get_osrm_route(origin, destination, intermediate=None):
    """OSRM fallback route fetcher."""
    if intermediate:
        url = (
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{origin['lng']},{origin['lat']};"
            f"{intermediate['lng']},{intermediate['lat']};"
            f"{destination['lng']},{destination['lat']}"
            f"?alternatives=false&geometries=polyline&overview=full"
        )
    else:
        url = (
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{origin['lng']},{origin['lat']};"
            f"{destination['lng']},{destination['lat']}"
            f"?alternatives=false&geometries=polyline&overview=full"
        )
    try:
        headers = {'User-Agent': 'ColdChainHackathonProject/1.0'}
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data['code'] == 'Ok' and data['routes']:
                return data['routes'][0]
    except Exception as e:
        print(f"OSRM Error: {e}")
    return None


def get_route_options(origin, destination):
    routes_ret = []
    labels    = ["NH Primary (Fastest)", "State Expressway (Bypass)", "Rural / Inland Route"]
    route_ids = ["R1_FAST", "R2_ALT", "R3_RURAL"]

    dist_lat   = destination['lat'] - origin['lat']
    dist_lng   = destination['lng'] - origin['lng']
    base_dist  = math.sqrt(dist_lat**2 + dist_lng**2) * 111.0
    if base_dist < 10:
        base_dist = 500

    # ── Primary: Google Maps Directions API ──────────────────────────
    gmaps_routes = get_gmaps_routes(origin, destination)

    if gmaps_routes:
        # Pad or trim to exactly 3 routes
        while len(gmaps_routes) < 3:
            gmaps_routes.append(gmaps_routes[-1])   # duplicate last if < 3 alternatives
        gmaps_routes = gmaps_routes[:3]

        for i, gr in enumerate(gmaps_routes):
            overview_poly = gr.get('overview_polyline', {}).get('points', '')
            waypoints = _decode_gmaps_polyline(overview_poly) if overview_poly else [origin, destination]
            if len(waypoints) > 1000:
                waypoints = waypoints[::5]

            segments, total_dist_km, total_dur_mins = _classify_segments_from_steps(gr.get('legs', []))

            routes_ret.append({
                "id":                 route_ids[i],
                "name":               labels[i],
                "waypoints":          waypoints,
                "total_distance_km":  round(total_dist_km, 1),
                "estimated_time_mins": int(max(10, total_dur_mins)),
                "segments":           segments,
                "data_source":        "google_maps"
            })

    else:
        # ── Fallback: OSRM ───────────────────────────────────────────
        print("Google Maps unavailable — falling back to OSRM")
        mid_lat = origin['lat'] + (dist_lat / 2)
        mid_lng = origin['lng'] + (dist_lng / 2)

        raw_routes = [
            get_osrm_route(origin, destination),
            get_osrm_route(origin, destination, {"lat": mid_lat - 1.0, "lng": mid_lng + 1.0}),
            get_osrm_route(origin, destination, {"lat": mid_lat + 1.0, "lng": mid_lng - 1.0}),
        ]

        for i, r in enumerate(raw_routes):
            if r:
                pts = polyline.decode(r['geometry'])
                if len(pts) > 1000:
                    pts = pts[::5]
                waypoints    = [{"lat": lat, "lng": lng} for lat, lng in pts]
                distance_km  = r['distance'] / 1000
                duration_mins = r['duration'] / 60
            else:
                waypoints    = [origin, destination]
                distance_km  = base_dist * (1.1 ** i)
                duration_mins = distance_km / 1.5

            seg_dist = distance_km / 3
            seg_time = duration_mins / 3
            segments = [
                {"distance": seg_dist, "time_mins": int(seg_time * random.uniform(0.9, 1.1)), "type": "highway"},
                {"distance": seg_dist, "time_mins": int(seg_time * (2.0 if i == 0 else random.uniform(0.9, 1.1))), "type": "traffic_zone" if i == 0 else "highway"},
                {"distance": seg_dist, "time_mins": int(seg_time * random.uniform(0.9, 1.1)), "type": "highway"},
            ]

            routes_ret.append({
                "id":                 route_ids[i],
                "name":               labels[i],
                "waypoints":          waypoints,
                "total_distance_km":  round(distance_km, 1),
                "estimated_time_mins": int(max(10, sum(s['time_mins'] for s in segments))),
                "segments":           segments,
                "data_source":        "osrm_fallback"
            })

    return routes_ret

# --- 2. LIVE Weather Service via OpenWeatherMap ---
_weather_cache = {}

def get_live_weather(lat, lng):
    """Fetch real weather data for a coordinate. Caches results by rounded coords to avoid API spam."""
    cache_key = (round(lat, 1), round(lng, 1))  # 0.1° radius cache (~11km)
    if cache_key in _weather_cache:
        return _weather_cache[cache_key]

    api_key = os.environ.get('WEATHER_API_KEY', '')
    if not api_key:
        return _mock_weather_fallback(lat, lng)

    try:
        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?lat={lat}&lon={lng}&appid={api_key}&units=metric&timeout=4"
        )
        resp = requests.get(url, timeout=4)
        if resp.status_code == 200:
            d = resp.json()
            wind_kmh = d.get('wind', {}).get('speed', 3) * 3.6   # m/s → km/h
            humidity  = d.get('main', {}).get('humidity', 50)
            temp      = d.get('main', {}).get('temp', 30)
            feels_like = d.get('main', {}).get('feels_like', temp)
            condition = d.get('weather', [{}])[0].get('description', 'clear').title()
            weather_id = d.get('weather', [{}])[0].get('id', 800)

            # Derive radiant factor: heavy cloud (id<700) reduces solar load significantly
            is_overcast = weather_id < 700
            solar_factor = 0.4 if is_overcast else 1.0

            result = {
                'external_temp_c': round(temp, 1),
                'feels_like_c':    round(feels_like, 1),
                'humidity_pct':    humidity,
                'wind_kmh':        round(wind_kmh, 1),
                'condition':       condition,
                'solar_factor':    solar_factor,
                'is_overcast':     is_overcast,
                'source':          'live'
            }
            _weather_cache[cache_key] = result
            return result
        else:
            print(f"OpenWeatherMap API error {resp.status_code} for ({lat},{lng}) - using fallback")
    except Exception as e:
        print(f"Weather fetch failed for ({lat},{lng}): {e}")

    return _mock_weather_fallback(lat, lng)


def _mock_weather_fallback(lat, lng):
    """Latitude-aware fallback when API is unreachable."""
    # India roughly spans 8°N–37°N; hotter in the plains, cooler in far north/south coasts
    normed = max(0, min(1, (lat - 8) / 29))   # 0=far south, 1=far north
    base_temp = 38 - (normed * 12)             # 38°C in south, 26°C in far north
    temp = round(base_temp + random.uniform(-2, 2), 1)
    return {
        'external_temp_c': temp,
        'feels_like_c':    round(temp + 2, 1),
        'humidity_pct':    55,
        'wind_kmh':        12.0,
        'condition':       'Partly Cloudy (est.)',
        'solar_factor':    0.8,
        'is_overcast':     False,
        'source':          'fallback'
    }


# --- Thermodynamic Penalty Engine ---
from datetime import datetime

def calculate_asphalt_penalty() -> float:
    """
    Returns a time-of-day 'Asphalt Radiation' penalty in °C.

    Physics rationale:
      - Peak solar zenith (12:00–16:00 IST) causes asphalt to radiate
        stored thermal energy at 65–80°C, significantly above ambient air.
      - Shoulder periods (10:00–12:00, 16:00–18:00) are heating/cooling
        phases with partial but meaningful surface radiation.
      - All other hours: negligible residual radiation from asphalt.
    """
    current_hour = datetime.now().hour   # Local server time (IST)

    if 12 <= current_hour < 16:
        penalty = 8.0   # Peak asphalt radiation — direct overhead sun
    elif (10 <= current_hour < 12) or (16 <= current_hour < 18):
        penalty = 4.0   # Shoulder periods — warming/cooling phase
    else:
        penalty = 0.0   # Night/early morning — negligible radiation

    return penalty


def get_effective_road_temp(lat: float, lng: float) -> dict:
    """
    Returns the 'Effective Road Temperature' at a given coordinate by combining:
      1. Live ambient temperature from OpenWeatherMap
      2. A time-of-day 'Asphalt Radiation' thermodynamic penalty

    This value is more accurate than raw API temperature for cold-chain
    logistics because asphalt surface temperature (not air temperature)
    is the dominant heat source for a stationary or slow-moving truck.

    Returns a dict with both raw and effective temperatures for transparency.
    """
    weather = get_live_weather(lat, lng)
    raw_temp = weather['external_temp_c']
    penalty  = calculate_asphalt_penalty()

    effective_temp = round(raw_temp + penalty, 1)

    return {
        **weather,                               # all original weather fields preserved
        'raw_ambient_temp_c':  raw_temp,         # original API value
        'asphalt_penalty_c':   penalty,          # penalty applied
        'effective_road_temp': effective_temp,   # what the routing engine uses
        'penalty_reason':      (
            'Peak solar radiation (12–16h)'   if penalty == 8.0 else
            'Shoulder solar period (10–12h or 16–18h)' if penalty == 4.0 else
            'Low radiation period (night/morning)'
        )
    }


def get_segment_weather(route, segment_idx, segment_type, waypoints):
    """Sample weather at representative waypoints within the segment's portion of the route."""
    if not waypoints:
        return _mock_weather_fallback(20, 77)  # default to central India

    total_segs = 3
    n = len(waypoints)
    # Pick the waypoint range that corresponds to this segment
    start_i = int((segment_idx / total_segs) * n)
    end_i   = int(((segment_idx + 1) / total_segs) * n)
    segment_wps = waypoints[start_i:end_i] if start_i < end_i else [waypoints[start_i]]

    # Sample up to 2 representative waypoints (start + midpoint of segment)
    sample_pts = [segment_wps[0]]
    if len(segment_wps) > 1:
        sample_pts.append(segment_wps[len(segment_wps) // 2])

    readings = [get_effective_road_temp(pt['lat'], pt['lng']) for pt in sample_pts]

    # Average the readings for the segment
    avg_temp       = round(sum(r['external_temp_c']   for r in readings) / len(readings), 1)
    avg_feels      = round(sum(r['feels_like_c']      for r in readings) / len(readings), 1)
    avg_humidity   = round(sum(r['humidity_pct']      for r in readings) / len(readings))
    avg_wind       = round(sum(r['wind_kmh']          for r in readings) / len(readings), 1)
    avg_solar      = round(sum(r['solar_factor']      for r in readings) / len(readings), 2)
    avg_effective  = round(sum(r['effective_road_temp'] for r in readings) / len(readings), 1)
    penalty        = readings[0]['asphalt_penalty_c']    # same for all pts (time-based)
    penalty_reason = readings[0]['penalty_reason']
    conditions     = readings[0]['condition']
    source         = readings[0]['source']

    return {
        'external_temp_c':    avg_temp,
        'feels_like_c':       avg_feels,
        'humidity_pct':       avg_humidity,
        'wind_kmh':           avg_wind,
        'condition':          conditions,
        'solar_factor':       avg_solar,
        'effective_road_temp': avg_effective,
        'asphalt_penalty_c':  penalty,
        'penalty_reason':     penalty_reason,
        'segment_type':       segment_type,
        'source':             source
    }

# --- 3. Thermal Engine (Calibrated for Industry-Standard Reefer Trucks) ---
def calculate_thermal_risk(route, cargo_max_temp):
    """
    Simulates cargo temperature evolution using a calibrated heat-transfer model.

    Physical assumptions:
    - Vehicle: Standard refrigerated van/truck with 80mm polyurethane insulation.
    - Insulation factor (k) ≈ 0.005–0.009 per minute: derived from U-value ~0.4 W/m²K
      over ~25m² surface area, 10,000–15,000 kg of cargo mass × specific heat.
    - Active cooling: Compressor unit rated ~3.5 kW, translating to ~1.2°C/min
      of cargo temperature reduction against ambient heat intrusion.
    - Starting temp: Cargo loaded at (max_temp - 5)°C, i.e. well within safe zone.
    - Net change per minute: heat_ingress - compressor_cooling
    - If net_change < 0, compressor is winning — cargo stays cold.
    """
    starting_cargo_temp = max(-20.0, cargo_max_temp - 5.0)
    current_cargo_temp  = starting_cargo_temp

    # ── Physical constants (calibrated for class A reefer truck) ─────────────
    # k-value: fraction of (T_skin - T_cargo) that leaks in per minute
    # 0.008 for traffic zone (slow/stopped, no convective help)
    # 0.004 for highway (airflow assists insulation effectiveness)
    K_TRAFFIC  = 0.008   # per minute
    K_HIGHWAY  = 0.004   # per minute

    # Compressor cooling rate: degrees C removed from cargo per minute
    # Real reefer: ~1.0–1.5°C/min depending on ambient-to-setpoint delta
    COMPRESSOR_COOLING = 1.2  # °C / min

    # Cargo floor temperature below compressor cut-in (prevents over-cooling)
    CARGO_FLOOR = cargo_max_temp - 12.0

    waypoints    = route.get('waypoints', [])
    segment_logs = []

    for idx, seg in enumerate(route['segments']):
        weather      = get_segment_weather(route, idx, seg['type'], waypoints)
        ambient      = weather['external_temp_c']
        eff_road     = weather['effective_road_temp']   # ambient + asphalt penalty
        feels_like   = weather['feels_like_c']
        humidity     = weather['humidity_pct']
        wind_kmh     = weather['wind_kmh']
        solar        = weather['solar_factor']
        penalty      = weather['asphalt_penalty_c']
        penalty_rsn  = weather['penalty_reason']
        time_mins    = int(max(1, seg['time_mins']))

        # ── Truck outer-skin temperature ─────────────────────────────────────
        # Highway: moving air helps carry heat away from the skin surface.
        # Traffic: idling in sun, no convective benefit — full solar + road load.
        wind_cooling = min(6.0, wind_kmh * 0.08)           # max 6°C convective benefit
        humidity_load = max(0.0, (humidity - 50) * 0.02)   # humid air carries more heat

        if seg['type'] == 'traffic_zone':
            # Stopped/slow: skin reaches near effective road temp + full solar load
            skin_temp = ambient + (penalty * solar) + humidity_load
        else:
            # Moving: use ambient + partial solar, minus wind convection
            skin_temp = ambient + (4.0 * solar) - wind_cooling + humidity_load

        # Clamp skin to physical limits (asphalt can hit 60°C, shade ≈ ambient)
        skin_temp = max(ambient - 2.0, min(65.0, skin_temp))

        k = K_TRAFFIC if seg['type'] == 'traffic_zone' else K_HIGHWAY

        # ── Minute-by-minute thermal integration ─────────────────────────────
        for _ in range(time_mins):
            temp_diff    = skin_temp - current_cargo_temp
            heat_ingress = temp_diff * k                       # Fourier heat transfer
            net_change   = heat_ingress - COMPRESSOR_COOLING   # compressor fights back

            current_cargo_temp += net_change
            # Clamp below floor (compressor won't freeze cargo below safe minimum)
            current_cargo_temp = max(CARGO_FLOOR, current_cargo_temp)

        # ── Segment risk classification ───────────────────────────────────────
        if current_cargo_temp > cargo_max_temp:
            risk_level = "CRITICAL (SPOILAGE)"
        elif current_cargo_temp > cargo_max_temp - 1.5:
            risk_level = "HIGH WARNING"
        else:
            risk_level = "LOW"

        segment_logs.append({
            "segment_idx":         idx,
            "ambient_temp":        ambient,
            "effective_road_temp": eff_road,
            "asphalt_penalty_c":   penalty,
            "penalty_reason":      penalty_rsn,
            "feels_like_c":        feels_like,
            "humidity_pct":        humidity,
            "wind_kmh":            wind_kmh,
            "truck_skin_temp":     round(skin_temp, 1),
            "condition":           weather['condition'],
            "weather_source":      weather['source'],
            "time_spent":          time_mins,
            "end_cargo_temp":      round(current_cargo_temp, 2),
            "risk_level":          risk_level
        })

    # ── Final risk status ─────────────────────────────────────────────────────
    final_risk = "SAFE"
    for log in segment_logs:
        if "CRITICAL" in log['risk_level']:
            final_risk = "SPOILED"
        elif "HIGH" in log['risk_level'] and final_risk != "SPOILED":
            final_risk = "WARNING"

    # ── Risk score: smooth 0–99 scale, 100 only on actual breach ─────────────
    # Score represents how close cargo came to the thermal limit.
    # 0% = cargo stayed well below limit
    # 99% = cargo reached exactly the limit (but didn't breach)
    # 100% = cargo strictly exceeded the limit (spoiled)
    if current_cargo_temp > cargo_max_temp:
        # Breached — score based on magnitude of overshoot (caps at 100)
        overshoot = current_cargo_temp - cargo_max_temp
        score = min(100, 100 + int(overshoot * 10))  # 100+
        score = 100
    else:
        # Safe — score = proximity to limit on a 0–99 scale
        # margin_ratio: 0.0 = right at the limit, 1.0 = at starting temp
        safe_band = cargo_max_temp - starting_cargo_temp   # total safe range
        distance_from_limit = cargo_max_temp - current_cargo_temp

        if safe_band > 0:
            # Closer to limit → higher score. At limit = 99, at start = 0.
            proximity_ratio = 1.0 - (distance_from_limit / safe_band)
            score = int(min(99, max(0, proximity_ratio * 99)))
        else:
            score = 50  # fallback

    return {
        "final_cargo_temp_c":  round(current_cargo_temp, 2),
        "thermal_risk_score":  score,
        "status":              final_risk,
        "segment_logs":        segment_logs
    }
