// ColdLink Nexus — Dashboard & Routing Logic
// Map, Autocomplete, GPS → inline in index.html (initMap callback)
// This file: DirectionsService, backend handoff, results, telemetry.

const API_URL = '/api/routes/calculate';

// ── State ────────────────────────────────────────────────────────────────────
let truckMarkerGM       = null;
let directionsRenderer  = null;   // single Google Directions renderer
let heatCircles         = [];
let polylineOverlays    = [];
let activeRouteData     = null;

// ── DOM refs (safe — script is at end of body) ────────────────────────────────
const calculateBtn     = document.getElementById('calculateBtn');
const simulateBtnText  = document.getElementById('btnText');
const loader           = document.getElementById('loader');
const resultsContainer = document.getElementById('resultsContainer');
const cargoTypeSelect  = document.getElementById('cargoType');

// ── Execute Simulation ────────────────────────────────────────────────────────
calculateBtn.addEventListener('click', async () => {
    const origin = window.selectedOrigin;
    const dest   = window.selectedDest;

    if (!origin || !dest) {
        resultsContainer.innerHTML = `
            <div class="idle-text" style="color:var(--warn);padding:16px 0;">
                ⚠ Select an <b>Origin</b> and <b>Destination</b> from the autocomplete suggestions first.
            </div>`;
        return;
    }

    // ── UI: loading state ────────────────────────────────────────────────
    simulateBtnText.style.display = 'none';
    loader.style.display          = 'block';
    calculateBtn.disabled         = true;
    resultsContainer.innerHTML    = '';
    document.getElementById('telemetryBody').innerHTML =
        '<div class="idle-text" style="text-align:center;margin-top:40%;opacity:.5;">Running simulation…</div>';

    // ── Clear previous overlays ──────────────────────────────────────────
    if (directionsRenderer) { directionsRenderer.setMap(null); directionsRenderer = null; }
    heatCircles.forEach(c => { if (c && c.setMap) c.setMap(null); });
    heatCircles = [];
    polylineOverlays.forEach(p => { if (p && p.setMap) p.setMap(null); });
    polylineOverlays = [];
    if (truckMarkerGM) { truckMarkerGM.setMap(null); truckMarkerGM = null; }

    try {
        // ── Step 1: Get real road route from Google Directions API ───────
        const directionsService = new google.maps.DirectionsService();

        const dirResult = await new Promise((resolve, reject) => {
            directionsService.route({
                origin:      origin,
                destination: dest,
                travelMode:  google.maps.TravelMode.DRIVING,
                provideRouteAlternatives: true
            }, (result, status) => {
                if (status === 'OK') resolve(result);
                else reject(new Error(`Directions API: ${status}`));
            });
        });

        // ── Step 2: Draw the primary route on the map ────────────────────
        directionsRenderer = new google.maps.DirectionsRenderer({
            map:              window.googleMap,
            suppressMarkers:  false,
            polylineOptions: {
                strokeColor:   '#4CA87E',
                strokeWeight:  5,
                strokeOpacity: 0.85
            }
        });
        directionsRenderer.setDirections(dirResult);

        // ── Step 3: Extract distance & duration (primary route leg) ──────
        const primaryLeg = dirResult.routes[0].legs[0];
        const distanceKm = (primaryLeg.distance.value / 1000).toFixed(1);
        const durationMin = Math.round(primaryLeg.duration.value / 60);

        // Decode waypoints from the primary route overview polyline
        const overviewPath = dirResult.routes[0].overview_path;
        const waypoints = overviewPath.map(ll => ({ lat: ll.lat(), lng: ll.lng() }));

        // ── Step 4: Send to Flask thermodynamic engine ───────────────────
        const payload = {
            cargo_max_temp: parseFloat(cargoTypeSelect.value),
            origin:         origin,
            destination:    dest,
            // Pass GMaps data so backend can use it instead of recalculating
            gm_distance_km:   parseFloat(distanceKm),
            gm_duration_mins: durationMin,
            waypoints:        waypoints.slice(0, 30)  // sample for heat engine
        };

        const response = await fetch(API_URL, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(payload)
        });

        if (!response.ok) throw new Error(`Backend error: ${response.status}`);
        const data = await response.json();
        activeRouteData = data;

        // ── Step 5: Render results & draw thermal overlays ───────────────
        renderResults(data, dirResult);
        drawThermalOverlays(data, waypoints);

    } catch (err) {
        console.error('Simulation error:', err);
        const msg = err.message.includes('Directions API')
            ? `No valid road route found between these locations.<br><small>${err.message}</small>`
            : `Engine offline — ensure <code>python app.py</code> is running.<br><small>${err.message}</small>`;
        resultsContainer.innerHTML = `<div class="idle-text" style="color:#e57373;padding:16px 0;">⚠ ${msg}</div>`;
        document.getElementById('telemetryBody').innerHTML =
            '<div class="idle-text" style="text-align:center;margin-top:40%;opacity:.5;">Simulation aborted.</div>';
    } finally {
        simulateBtnText.style.display = 'block';
        loader.style.display          = 'none';
        calculateBtn.disabled         = false;
    }
});

// ── Thermal Overlay (heat circles on map) ─────────────────────────────────────
function drawThermalOverlays(data, waypoints) {
    if (!window.googleMap || !data.all_routes) return;
    const safestRoute = data.all_routes.find(r => r.id === data.safest_route_id);
    if (!safestRoute) return;

    safestRoute.thermal_analysis.segment_logs.forEach((log, i) => {
        const ptIdx = Math.min(
            Math.floor((i + 1) / safestRoute.thermal_analysis.segment_logs.length * waypoints.length),
            waypoints.length - 1
        );
        const pt = waypoints[ptIdx];
        if (!pt) return;

        const heatColor = log.ambient_temp > 38 ? '#C84C4C'
                        : log.ambient_temp > 30 ? '#C89A4C'
                        : '#4CA87E';

        const circle = new google.maps.Circle({
            center:        pt,
            radius:        log.ambient_temp * 500,
            strokeColor:   heatColor,
            strokeOpacity: 0.5,
            strokeWeight:  1,
            fillColor:     heatColor,
            fillOpacity:   0.10,
            map:           window.googleMap,
        });
        const infoWindow = new google.maps.InfoWindow({
            content: `<div style="font-family:Inter,sans-serif;font-size:12px;color:#152C22;min-width:180px;">
                <b>${log.condition}</b><br>
                Air: ${log.ambient_temp}°C &nbsp;|&nbsp; Road: ${log.effective_road_temp ?? log.ambient_temp}°C<br>
                Penalty: +${log.asphalt_penalty_c ?? 0}°C (${log.penalty_reason ?? '—'})<br>
                Cargo core: <b>${log.end_cargo_temp}°C</b>
            </div>`
        });
        circle.addListener('click', () => infoWindow.open({ map: window.googleMap, shouldFocus: false }));
        heatCircles.push(circle);
    });
}

// ── Results Cards ─────────────────────────────────────────────────────────────
function getRiskColorHex(score, status) {
    if (status === 'SPOILED') return '#ef4444';
    if (status === 'WARNING') return '#f59e0b';
    return '#10b981';
}

function renderResults(data, dirResult) {
    resultsContainer.innerHTML = '';

    // Summary banner using real Google Maps data
    const primaryLeg = dirResult && dirResult.routes[0] ? dirResult.routes[0].legs[0] : null;
    if (primaryLeg) {
        const banner = document.createElement('div');
        banner.style.cssText = 'padding:10px 0;border-bottom:1px solid var(--forest-border);margin-bottom:12px;font-size:11px;color:var(--text-muted);letter-spacing:.05em;';
        banner.innerHTML = `
            <span style="color:var(--safe);">● LIVE ROUTE</span>&nbsp;&nbsp;
            <b style="color:var(--champagne);">${primaryLeg.distance.text}</b> &nbsp;·&nbsp;
            <b style="color:var(--champagne);">${primaryLeg.duration.text}</b>
            &nbsp;<span style="color:var(--text-muted);">(Google Maps)</span>`;
        resultsContainer.appendChild(banner);
    }

    data.all_routes.forEach((route) => {
        const isFastest = route.id === data.fastest_route_id;
        const isSafest  = route.id === data.safest_route_id;
        const t         = route.thermal_analysis;
        const color     = getRiskColorHex(t.thermal_risk_score, t.status);

        let badges = '';
        if (isFastest) badges += `<span class="badge fastest" style="right:${isSafest?'55px':'10px'}">FS</span>`;
        if (isSafest)  badges += `<span class="badge safest">SF</span>`;

        const card = document.createElement('div');
        card.className = `route-card ${isSafest ? 'selected' : ''}`;
        card.innerHTML = `
            ${badges}
            <div class="route-header">
                <div class="route-name">${route.name}</div>
                <div class="route-id">ID: ${route.id}</div>
            </div>
            <div class="route-stats-grid">
                <div class="stat-box">
                    <span class="stat-label">ETA</span>
                    <span class="stat-value">${route.estimated_time_mins}m</span>
                </div>
                <div class="stat-box">
                    <span class="stat-label">DISTANCE</span>
                    <span class="stat-value">${route.total_distance_km}km</span>
                </div>
                <div class="stat-box">
                    <span class="stat-label">FINAL CARGO</span>
                    <span class="stat-value" style="color:${color}">${t.final_cargo_temp_c}°C</span>
                </div>
                <div class="stat-box">
                    <span class="stat-label">THERMAL RISK</span>
                    <span class="stat-value" style="color:${color}">${t.thermal_risk_score}%</span>
                    <div class="risk-bar">
                        <div class="risk-bar-fill" style="width:0%;background:${color}"></div>
                    </div>
                </div>
            </div>
            <button class="play-btn" data-route-id="${route.id}">
                <span class="material-icons-outlined" style="font-size:14px;margin-right:4px;">play_arrow</span>
                EXECUTE LIVE TRANSIT
            </button>`;

        card.addEventListener('click', (e) => {
            document.querySelectorAll('.route-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            if (e.target.closest('.play-btn')) playLiveTransit(route);
        });
        resultsContainer.appendChild(card);

        // Animate risk bar
        setTimeout(() => {
            const fill = card.querySelector('.risk-bar-fill');
            if (fill) fill.style.width = `${t.thermal_risk_score}%`;
        }, 120);
    });
}

// ── Live Truck Animation ───────────────────────────────────────────────────────
function playLiveTransit(route) {
    if (truckMarkerGM) { truckMarkerGM.setMap(null); truckMarkerGM = null; }
    const telBody = document.getElementById('telemetryBody');
    const wp = route.waypoints;
    if (!wp || wp.length < 2) {
        telBody.innerHTML = '<div class="idle-text" style="text-align:center;margin-top:40%;">No waypoint data.</div>';
        return;
    }

    truckMarkerGM = new google.maps.Marker({
        position: { lat: wp[0].lat, lng: wp[0].lng },
        map:      window.googleMap,
        icon: {
            path:         google.maps.SymbolPath.FORWARD_CLOSED_ARROW,
            scale:        5,
            fillColor:    '#C9A84C',
            fillOpacity:  1,
            strokeColor:  '#F7F5F0',
            strokeWeight: 1.5,
        },
        title: 'ColdLink Transit Vehicle'
    });

    let frame = 0;
    const totalFrames = 120;
    const interval = setInterval(() => {
        if (frame >= totalFrames) {
            clearInterval(interval);
            telBody.innerHTML += '<div class="tel-row" style="margin-top:16px;color:var(--safe);">[TRANSIT COMPLETE]</div>';
            return;
        }

        const fraction   = frame / totalFrames;
        const floatIndex = fraction * (wp.length - 1);
        const lower = Math.floor(floatIndex);
        const upper = Math.ceil(floatIndex);
        const t     = floatIndex - lower;

        let lat = wp[lower].lat;
        let lng = wp[lower].lng;
        if (lower !== upper) {
            lat += (wp[upper].lat - lat) * t;
            lng += (wp[upper].lng - lng) * t;
        }
        truckMarkerGM.setPosition({ lat, lng });

        const logs = route.thermal_analysis.segment_logs;
        const log  = logs[Math.min(logs.length - 1, Math.floor(fraction * logs.length))];
        const maxT = parseFloat(cargoTypeSelect.value);
        const safeClass = log.end_cargo_temp > maxT ? 'danger' : 'safe';
        const skinClass = log.truck_skin_temp > 50  ? 'danger' : '';

        telBody.innerHTML = `
            <div class="telemetry-node">
                <div class="telemetry-title">
                    T+${Math.floor(fraction * route.estimated_time_mins)}min
                    <span style="font-size:9px;color:var(--text-muted);">SECTOR ${log.segment_idx + 1}</span>
                </div>
                <div class="tel-row"><span>Air Ambient</span><span class="tel-val">${log.ambient_temp}°C</span></div>
                <div class="tel-row"><span>Eff. Road Temp</span><span class="tel-val" style="color:var(--warn);">${log.effective_road_temp ?? log.ambient_temp}°C</span></div>
                <div class="tel-row"><span>Asphalt +Δ</span><span class="tel-val">${log.asphalt_penalty_c ?? 0}°C</span></div>
                <div class="tel-row"><span>Radiant Skin</span><span class="tel-val ${skinClass}">${log.truck_skin_temp}°C</span></div>
                <div class="tel-row"><span>Core Cargo</span><span class="tel-val ${safeClass}">${log.end_cargo_temp}°C</span></div>
                <div class="tel-row"><span>Humidity</span><span class="tel-val">${log.humidity_pct ?? '—'}%</span></div>
                <div class="tel-row"><span>Wind</span><span class="tel-val">${log.wind_kmh ?? '—'} km/h</span></div>
                <div class="tel-row" style="margin-top:8px;font-size:10px;font-style:italic;">${log.condition}</div>
            </div>`;
        frame++;
    }, 80);
}
