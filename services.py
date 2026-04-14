import random
import math
import requests
import polyline

# --- 1. Route Service via OSRM ---
def get_osrm_route(origin, destination, intermediate=None):
    if intermediate:
        url = f"http://router.project-osrm.org/route/v1/driving/{origin['lng']},{origin['lat']};{intermediate['lng']},{intermediate['lat']};{destination['lng']},{destination['lat']}?alternatives=false&geometries=polyline&overview=full"
    else:
        url = f"http://router.project-osrm.org/route/v1/driving/{origin['lng']},{origin['lat']};{destination['lng']},{destination['lat']}?alternatives=false&geometries=polyline&overview=full"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data['code'] == 'Ok' and data['routes']:
                return data['routes'][0]
    except Exception as e:
        print(f"OSRM Error: {e}")
    return None

def get_route_options(origin, destination):
    routes_ret = []
    
    # 1. Direct Route
    r1 = get_osrm_route(origin, destination)
    
    # Calculate a midpoint with offsets for Alternatives
    dist_lat = destination['lat'] - origin['lat']
    dist_lng = destination['lng'] - origin['lng']
    mid_lat = origin['lat'] + (dist_lat / 2)
    mid_lng = origin['lng'] + (dist_lng / 2)
    
    # 2. Coastal/Bypass (Push orthogonally)
    r2 = get_osrm_route(origin, destination, {"lat": mid_lat - 1.0, "lng": mid_lng + 1.0})
    
    # 3. Inland (Push orthogonally opposite)
    r3 = get_osrm_route(origin, destination, {"lat": mid_lat + 1.0, "lng": mid_lng - 1.0})
    
    raw_routes = [r1, r2, r3]
    labels = ["NH Primary (Fastest)", "State Expressway (Bypass)", "Rural/Inland Route"]
    route_ids = ["R1_FAST", "R2_ALT", "R3_RURAL"]
    
    for i, r in enumerate(raw_routes):
        if not r: continue
        
        # Decode polyline (returns list of (lat, lng))
        pts = polyline.decode(r['geometry'])
        # Subsample points if it's too huge just to keep rendering fast, though leaflet handles it fine
        # We'll take every 5th point for very long routes
        if len(pts) > 1000:
            pts = pts[::5]
        waypoints = [{"lat": lat, "lng": lng} for lat, lng in pts]
        
        distance_km = r['distance'] / 1000
        duration_mins = r['duration'] / 60
        
        # Engine requires 3 segments for thermal analysis mapping
        seg_distance = distance_km / 3
        seg_time = duration_mins / 3
        
        # Add realistic traffic delays to Route 1
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
            "estimated_time_mins": int(sum(s['time_mins'] for s in segments)),
            "segments": segments
        })
        
    return routes_ret

# --- 2. Mock Weather Service (India Specific) ---
def get_segment_weather(route_id, segment_idx, segment_type):
    # Simulated India weather conditions
    if route_id == "R1_FAST":
        if segment_type == "traffic_zone":
            temp = 42 # Severe Indian Summer Heat Island
            condition = "Extreme Heat (Urban Traffic)"
        else:
            temp = 38
            condition = "Sunny / Dry (Plains)"
    elif route_id == "R2_ALT":
         temp = 33
         condition = "Coastal Breeze / Humid"
    elif route_id == "R3_RURAL":
         temp = 25
         condition = "Shaded / Hill Station"
    else:
         temp = 30
         condition = "Clear"
         
    return {
        "external_temp_c": temp,
        "condition": condition,
        "segment_type": segment_type
    }

# --- 3. Thermal Engine ---
def calculate_thermal_risk(route, cargo_max_temp):
    total_thermal_load = 0
    starting_cargo_temp = cargo_max_temp - 5  # Start reasonably cold
    current_cargo_temp = starting_cargo_temp
    
    cooling_capacity_per_min = 0.5 # Degrees C removed per minute 
    
    segment_logs = []
    
    for idx, seg in enumerate(route['segments']):
        weather = get_segment_weather(route['id'], idx, seg['type'])
        ambient = weather['external_temp_c']
        time = seg['time_mins']
        
        # --- NEW RADIANT PHYSICS MODEL ---
        # Radiant solar heat soaking into the truck's metal skin.
        # Wind convective cooling usually strips this away, but in traffic, it spikes.
        if weather['segment_type'] == "traffic_zone":
            # Idling on concrete in the sun = massive radiant soak
            radiant_skin_temp = min(75, ambient * 1.7) 
            insulation_factor = 0.08 # Thermal envelope breaks down faster under extreme delta
        else:
            # Moving on open highway = wind cooling keeps skin closer to ambient
            radiant_skin_temp = ambient + 5 
            insulation_factor = 0.04
            
        for minute in range(time):
            # Heat coming in from the SKINS, not just the air!
            temp_diff = radiant_skin_temp - current_cargo_temp
            heat_ingress = temp_diff * insulation_factor
            
            # Net change per minute
            net_change = heat_ingress - cooling_capacity_per_min
            
            # Refrigerator can only cool down to a limit (say, -5C)
            current_cargo_temp += net_change
            if current_cargo_temp < -5:
                current_cargo_temp = -5
                
        # Risk flags
        risk_level = "LOW"
        if current_cargo_temp > cargo_max_temp:
            risk_level = "CRITICAL (SPOILAGE)"
        elif current_cargo_temp > cargo_max_temp - 2:
            risk_level = "HIGH WARNING"
            
        segment_logs.append({
            "segment_idx": idx,
            "ambient_temp": ambient,
            "truck_skin_temp": round(radiant_skin_temp, 1),
            "condition": weather['condition'],
            "time_spent": time,
            "end_cargo_temp": round(current_cargo_temp, 2),
            "risk_level": risk_level
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
