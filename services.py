import random
import math
import requests
import polyline
import os
from functools import lru_cache

# --- 1. Route Service via OSRM ---
def get_osrm_route(origin, destination, intermediate=None):
    if intermediate:
        url = f"http://router.project-osrm.org/route/v1/driving/{origin['lng']},{origin['lat']};{intermediate['lng']},{intermediate['lat']};{destination['lng']},{destination['lat']}?alternatives=false&geometries=polyline&overview=full"
    else:
        url = f"http://router.project-osrm.org/route/v1/driving/{origin['lng']},{origin['lat']};{destination['lng']},{destination['lat']}?alternatives=false&geometries=polyline&overview=full"
    
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
    
    r1 = get_osrm_route(origin, destination)
    
    # Calculate a midpoint with offsets for Alternatives
    dist_lat = destination['lat'] - origin['lat']
    dist_lng = destination['lng'] - origin['lng']
    mid_lat = origin['lat'] + (dist_lat / 2)
    mid_lng = origin['lng'] + (dist_lng / 2)
    
    r2 = get_osrm_route(origin, destination, {"lat": mid_lat - 1.0, "lng": mid_lng + 1.0})
    r3 = get_osrm_route(origin, destination, {"lat": mid_lat + 1.0, "lng": mid_lng - 1.0})
    
    raw_routes = [r1, r2, r3]
    labels = ["NH Primary (Fastest)", "State Expressway (Bypass)", "Rural/Inland Route"]
    route_ids = ["R1_FAST", "R2_ALT", "R3_RURAL"]
    
    # Fallback math if OSRM is blocked entirely
    base_dist = math.sqrt(dist_lat**2 + dist_lng**2) * 111.0 # rough km
    if base_dist < 10: base_dist = 500 # Just in case it's same city, make up a number
    
    for i, r in enumerate(raw_routes):
        if r:
            pts = polyline.decode(r['geometry'])
            if len(pts) > 1000: pts = pts[::5]
            waypoints = [{"lat": lat, "lng": lng} for lat, lng in pts]
            distance_km = r['distance'] / 1000
            duration_mins = r['duration'] / 60
        else:
            # Generate a mock straight line
            waypoints = [origin]
            if i == 1: waypoints.append({"lat": origin['lat'] - 1.0, "lng": origin['lng'] + 1.0})
            if i == 2: waypoints.append({"lat": origin['lat'] + 1.0, "lng": origin['lng'] - 1.0})
            waypoints.append(destination)
            
            distance_km = base_dist * (1.1 ** i)
            duration_mins = distance_km / 1.5 # ~90kmph avg
            
        seg_distance = distance_km / 3
        seg_time = duration_mins / 3
        
        segments = [
            {"distance": seg_distance, "time_mins": int(seg_time * random.uniform(0.9, 1.1)), "type": "highway"},
            {"distance": seg_distance, "time_mins": int(seg_time * (2.0 if i==0 else random.uniform(0.9, 1.1))), "type": "traffic_zone" if i==0 else "highway"},
            {"distance": seg_distance, "time_mins": int(seg_time * random.uniform(0.9, 1.1)), "type": "highway"}
        ]
        
        routes_ret.append({
            "id": route_ids[i],
            "name": labels[i],
            "waypoints": waypoints,
            "total_distance_km": round(distance_km, 1),
            "estimated_time_mins": int(max(10, sum(s['time_mins'] for s in segments))),
            "segments": segments
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

# --- 3. Thermal Engine (Real-data upgraded) ---
def calculate_thermal_risk(route, cargo_max_temp):
    total_thermal_load = 0
    starting_cargo_temp = cargo_max_temp - 5  # Start cold
    current_cargo_temp = starting_cargo_temp
    cooling_capacity_per_min = 0.5  # Degrees C removed per minute by reefer unit
    waypoints = route.get('waypoints', [])

    segment_logs = []

    for idx, seg in enumerate(route['segments']):
        weather = get_segment_weather(route, idx, seg['type'], waypoints)
        ambient      = weather['external_temp_c']    # raw air temperature
        eff_road     = weather['effective_road_temp'] # air + asphalt penalty
        feels_like   = weather['feels_like_c']
        humidity     = weather['humidity_pct']
        wind_kmh     = weather['wind_kmh']
        solar        = weather['solar_factor']
        penalty      = weather['asphalt_penalty_c']
        penalty_rsn  = weather['penalty_reason']
        time         = seg['time_mins']

        # --- ENHANCED RADIANT PHYSICS MODEL ---
        # Humidity increases effective heat transfer into cargo
        humidity_penalty = (humidity - 50) * 0.03   # +0.03°C per % above 50%

        # Wind convective cooling lowers skin temperature
        wind_cooling = min(8, wind_kmh * 0.10)      # up to 8°C benefit

        if seg['type'] == 'traffic_zone':
            # Idling: full asphalt soak + zero wind benefit
            # Use effective_road_temp (includes asphalt penalty) as the base
            radiant_skin_temp = min(80, eff_road * 1.7 * solar) + humidity_penalty
            insulation_factor = 0.09
        else:
            # Moving: wind cooling applies; use effective road temp as base
            radiant_skin_temp = (eff_road + 5 * solar) - wind_cooling + humidity_penalty
            insulation_factor = 0.04

        for minute in range(int(time)):
            temp_diff   = radiant_skin_temp - current_cargo_temp
            heat_ingress = temp_diff * insulation_factor
            net_change   = heat_ingress - cooling_capacity_per_min
            current_cargo_temp += net_change
            if current_cargo_temp < -5:
                current_cargo_temp = -5

        risk_level = "LOW"
        if current_cargo_temp > cargo_max_temp:
            risk_level = "CRITICAL (SPOILAGE)"
        elif current_cargo_temp > cargo_max_temp - 2:
            risk_level = "HIGH WARNING"

        segment_logs.append({
            "segment_idx":        idx,
            "ambient_temp":       ambient,
            "effective_road_temp": eff_road,
            "asphalt_penalty_c":  penalty,
            "penalty_reason":     penalty_rsn,
            "feels_like_c":       feels_like,
            "humidity_pct":       humidity,
            "wind_kmh":           wind_kmh,
            "truck_skin_temp":    round(radiant_skin_temp, 1),
            "condition":          weather['condition'],
            "weather_source":     weather['source'],
            "time_spent":         time,
            "end_cargo_temp":     round(current_cargo_temp, 2),
            "risk_level":         risk_level
        })
        
    final_risk = "SAFE"
    for log in segment_logs:
        if "CRITICAL" in log['risk_level']:
             final_risk = "SPOILED"
        elif "HIGH" in log['risk_level'] and final_risk != "SPOILED":
             final_risk = "WARNING"
             
    # Calculate a numerical score
    spoil_threshold = cargo_max_temp
    overshoot = max(0, current_cargo_temp - spoil_threshold)
    score = min(100, int((overshoot / 5) * 100)) # 5 degrees over is 100% ruined
    if final_risk == "SAFE" and overshoot == 0:
        margin = spoil_threshold - current_cargo_temp
        if margin > 3:
            score = 5
        else:
            score = 15
            
    return {
        "final_cargo_temp_c": round(current_cargo_temp, 2),
        "thermal_risk_score": score,
        "status": final_risk,
        "segment_logs": segment_logs
    }
