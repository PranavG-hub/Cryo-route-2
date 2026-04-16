// --- DIAGNOSTIC ALERT TO PROVE CACHE STATE ---
alert("DIAGNOSTIC: IF YOU SEE THIS, YOU HAVE THE LATEST CODE! Clicking OK will load the app.");

const API_URL = '/api/routes/calculate';
const API_SEND_OTP = '/api/auth/send-otp';
const API_VERIFY_OTP = '/api/auth/verify-otp';

let currentEmail = ""; 
let truckMarker = null;

// --- DOM ELEMENTS ---
const loginOverlay = document.getElementById('loginOverlay');
const appContainer = document.getElementById('appContainer');
const authContainer = document.getElementById('authContainer');
const otpContainer = document.getElementById('otpContainer');
const genericAuthForm = document.getElementById('genericAuthForm');
const emailInput = document.getElementById('emailInput');
const authBtnText = document.getElementById('authBtnText');
const authErrorMsg = document.getElementById('authErrorMsg');

const verifyOtpBtn = document.getElementById('verifyOtpBtn');
const otpBtnText = document.getElementById('otpBtnText');
const otpLoader = document.getElementById('loginLoader');
const otpErrorMsg = document.getElementById('otpErrorMsg');

const tabSignIn = document.getElementById('tabSignIn');
const tabSignUp = document.getElementById('tabSignUp');
const authSubtitle = document.getElementById('authSubtitle');
const passField = document.getElementById('passField');

// --- AUTHENTICATION FLOW ---
tabSignIn.addEventListener('click', () => {
    tabSignIn.classList.add('active'); tabSignUp.classList.remove('active');
    authSubtitle.innerText = 'SECURE TERMINAL ACCESS';
    authBtnText.innerText = 'INITIALIZE LOGIN';
    passField.style.display = 'block';
});

tabSignUp.addEventListener('click', () => {
    tabSignUp.classList.add('active'); tabSignIn.classList.remove('active');
    authSubtitle.innerText = 'NEW OPERATIVE REGISTRATION';
    authBtnText.innerText = 'DISPATCH VERIFICATION OTP';
    passField.style.display = 'none';
});

// GIS Callback
async function handleGoogleLogin(response) {
    const credential = response.credential;
    authErrorMsg.style.display = 'none';
    
    try {
        const verifyRes = await fetch('/api/auth/verify-google', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ credential })
        });
        const data = await verifyRes.json();
        
        if (verifyRes.ok) {
            console.log("Logged in as:", data.email);
            loginOverlay.classList.add('hidden');
            appContainer.classList.remove('app-hidden');
            setTimeout(() => map.invalidateSize(), 300);
        } else {
            authErrorMsg.innerText = data.error || "GOOGLE UPLINK REJECTED.";
            authErrorMsg.style.display = 'block';
        }
    } catch (err) {
        authErrorMsg.innerText = "VERIFICATION SERVER DISCONNECTED.";
        authErrorMsg.style.display = 'block';
    }
}

// Strictly Initialize Google Identity safely to block Auto-logins!
window.onload = function () {
    const googleBtnContainer = document.getElementById('googleBtnContainer');
    if (googleBtnContainer) {
        const clientId = googleBtnContainer.getAttribute('data-client_id');
        google.accounts.id.initialize({
            client_id: clientId,
            callback: handleGoogleLogin,
            auto_select: false // Strict blockade
        });
        google.accounts.id.renderButton(
            document.getElementById("googleBtnContainer"),
            { theme: "filled_black", size: "large", width: "300" }
        );
        // We explicitly DO NOT call google.accounts.id.prompt() here so it NEVER auto logs in!
    }
}

// Trigger OTP generation via Backend
async function requestOtpFlow(e) {
    if (e) e.preventDefault();
    
    currentEmail = emailInput.value.trim();
    if(!currentEmail) {
        authErrorMsg.innerText = "EMAIL REQUIRED FOR SYSTEM UPLINK.";
        authErrorMsg.style.display = 'block';
        return;
    }

    authBtnText.innerText = 'TRANSMITTING REQUEST...';
    authErrorMsg.style.display = 'none';
    
    try {
        const response = await fetch(API_SEND_OTP, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: currentEmail })
        });
        const data = await response.json();
        
        if (response.ok) {
            authContainer.style.display = 'none';
            otpContainer.style.display = 'block';
            console.log(data.message); // In case of dev fallback
        } else {
            authErrorMsg.innerText = data.error || "CONNECTION FAILED.";
            authErrorMsg.style.display = 'block';
            authBtnText.innerText = 'RETRY INITIALIZE';
        }
    } catch (err) {
        authErrorMsg.innerText = "ENGINE IS OFFLINE.";
        authErrorMsg.style.display = 'block';
        authBtnText.innerText = 'RETRY INITIALIZE';
    }
}

genericAuthForm.addEventListener('submit', requestOtpFlow);

// OTP Inputs behavior
const otpBoxes = document.querySelectorAll('.otp-box');
otpBoxes.forEach((box, index) => {
    box.addEventListener('input', () => {
        if (box.value.length === 1 && index < otpBoxes.length - 1) {
            otpBoxes[index + 1].focus();
        }
    });
});

verifyOtpBtn.addEventListener('click', async () => {
    let enteredCode = "";
    otpBoxes.forEach(b => enteredCode += b.value);
    
    if(enteredCode.length !== 4) {
        otpErrorMsg.innerText = "INVALID CHECKSUM LENGTH.";
        otpErrorMsg.style.display = 'block';
        return;
    }

    otpBtnText.style.display = 'none';
    otpLoader.style.display = 'block';
    otpErrorMsg.style.display = 'none';
    
    try {
        const response = await fetch(API_VERIFY_OTP, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: currentEmail, otp: enteredCode })
        });
        const data = await response.json();
        
        if (response.ok) {
            loginOverlay.classList.add('hidden');
            appContainer.classList.remove('app-hidden');
            setTimeout(() => map.invalidateSize(), 300);
        } else {
            otpErrorMsg.innerText = data.error || "DECRYPTION FAILED.";
            otpErrorMsg.style.display = 'block';
        }
    } catch (err) {
        otpErrorMsg.innerText = "SERVER DISCONNECTED.";
        otpErrorMsg.style.display = 'block';
    } finally {
        otpBtnText.style.display = 'block';
        otpLoader.style.display = 'none';
    }
});


// --- LOCATIONS DATA (INDIA MAX ROUTES) ---
const indianCities = [
    { name: 'Delhi', lat: 28.7041, lng: 77.1025 },
    { name: 'Mumbai', lat: 19.0760, lng: 72.8777 },
    { name: 'Bangalore', lat: 12.9716, lng: 77.5946 },
    { name: 'Hyderabad', lat: 17.3850, lng: 78.4867 },
    { name: 'Ahmedabad', lat: 23.0225, lng: 72.5714 },
    { name: 'Chennai', lat: 13.0827, lng: 80.2707 },
    { name: 'Kolkata', lat: 22.5726, lng: 88.3639 },
    { name: 'Surat', lat: 21.1702, lng: 72.8311 },
    { name: 'Pune', lat: 18.5204, lng: 73.8567 },
    { name: 'Jaipur', lat: 26.9124, lng: 75.7873 },
    { name: 'Lucknow', lat: 26.8467, lng: 80.9462 },
    { name: 'Kanpur', lat: 26.4499, lng: 80.3319 },
    { name: 'Nagpur', lat: 21.1458, lng: 79.0882 },
    { name: 'Indore', lat: 22.7196, lng: 75.8577 },
    { name: 'Bhopal', lat: 23.2599, lng: 77.4126 },
    { name: 'Patna', lat: 25.5941, lng: 85.1376 },
    { name: 'Vadodara', lat: 22.3072, lng: 73.1812 },
    { name: 'Ludhiana', lat: 30.9010, lng: 75.8573 },
    { name: 'Agra', lat: 27.1767, lng: 78.0081 },
    { name: 'Varanasi', lat: 25.3176, lng: 82.9739 },
    { name: 'Amritsar', lat: 31.6340, lng: 74.8723 },
    { name: 'Guwahati', lat: 26.1158, lng: 91.7086 },
    { name: 'Bhubaneswar', lat: 20.2961, lng: 85.8245 }
];
indianCities.sort((a,b) => a.name.localeCompare(b.name));

const originSelect = document.getElementById('originSelect');
const destSelect = document.getElementById('destSelect');

indianCities.forEach((city, index) => {
    originSelect.add(new Option(city.name, index));
    destSelect.add(new Option(city.name, index));
});
originSelect.value = indianCities.findIndex(c => c.name === 'Delhi');
destSelect.value = indianCities.findIndex(c => c.name === 'Mumbai');


// --- MAP INITIALIZATION ---
const map = L.map('map', {zoomControl: false}).setView([22.5937, 78.9629], 5);
L.control.zoom({ position: 'topright' }).addTo(map);

L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; OpenStreetMap', subdomains: 'abcd', maxZoom: 20
}).addTo(map);

let currentLayers = [];

// --- TEMPORARY AUTH BYPASS REMOVED ---
// --- GPS LOCATION LOGIC ---
let userCustomOrigin = null;
const gpsBtn = document.getElementById('gpsBtn');

gpsBtn.addEventListener('click', () => {
    if ("geolocation" in navigator) {
        gpsBtn.innerHTML = '<span class="material-icons-outlined hud-value glow-blue">radar</span>';
        navigator.geolocation.getCurrentPosition(
            (position) => {
                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                userCustomOrigin = { lat, lng };
                
                const opt = new Option("📍 GPS COORDINATES", "gps");
                originSelect.insertBefore(opt, originSelect.firstChild);
                originSelect.value = "gps";
                
                gpsBtn.innerHTML = '<span class="material-icons-outlined glow-blue">my_location</span>';
                map.flyTo([lat, lng], 10);
            },
            () => { alert("GPS UPLINK FAILED."); gpsBtn.innerHTML = '<span class="material-icons-outlined">my_location</span>'; }
        );
    }
});


// --- ENGINE INTEGRATION ---
const calculateBtn = document.getElementById('calculateBtn');
const simulateBtnText = document.getElementById('btnText');
const loader = document.getElementById('loader');
const resultsContainer = document.getElementById('resultsContainer');
const cargoTypeSelect = document.getElementById('cargoType');

calculateBtn.addEventListener('click', async () => {
    let originObj, destObj;
    if (originSelect.value === "gps" && userCustomOrigin) { originObj = userCustomOrigin; } 
    else { originObj = indianCities[originSelect.value]; }
    destObj = indianCities[destSelect.value];
    
    if (!originObj || !destObj) return;

    simulateBtnText.style.display = 'none';
    loader.style.display = 'block';
    calculateBtn.disabled = true;
    
    currentLayers.forEach(layer => map.removeLayer(layer));
    currentLayers = [];
    resultsContainer.innerHTML = '';
    document.getElementById('telemetryBody').innerHTML = '<div class="idle-text" style="text-align: center; margin-top: 50%;">AWAITING TRANSIT START</div>';
    
    try {
        const payload = {
            cargo_max_temp: parseFloat(cargoTypeSelect.value),
            origin: { lat: originObj.lat, lng: originObj.lng },
            destination: { lat: destObj.lat, lng: destObj.lng }
        };
        const response = await fetch(API_URL, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
        });
        const data = await response.json();
        renderResults(data);
        drawRoutes(data);
    } catch (error) {
        resultsContainer.innerHTML = `<div class="idle-text" style="color: var(--acc-danger);">ENGINE OFFLINE.</div>`;
    } finally {
        simulateBtnText.style.display = 'block';
        loader.style.display = 'none';
        calculateBtn.disabled = false;
    }
});

function getRiskColorHex(score, status) {
    if (status === "SPOILED") return '#ef4444'; 
    if (status === "WARNING") return '#f59e0b'; 
    return '#10b981'; 
}

function renderResults(data) {
    data.all_routes.forEach((route, index) => {
        const isFastest = route.id === data.fastest_route_id;
        const isSafest = route.id === data.safest_route_id;
        const t_data = route.thermal_analysis;
        const colorCode = getRiskColorHex(t_data.thermal_risk_score, t_data.status);
        
        let badges = '';
        if (isFastest) badges += `<span class="badge fastest" style="right: ${isSafest ? '55px' : '10px'}">FS</span>`;
        if (isSafest) badges += `<span class="badge safest">SF</span>`;
        
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
                    <span class="stat-label">ETA (TRAFFIC)</span>
                    <span class="stat-value">${route.estimated_time_mins}m</span>
                </div>
                <div class="stat-box">
                    <span class="stat-label">DISTANCE</span>
                    <span class="stat-value">${route.total_distance_km}km</span>
                </div>
                <div class="stat-box">
                    <span class="stat-label">FINAL CORE TEMP</span>
                    <span class="stat-value" style="color: ${colorCode};">${t_data.final_cargo_temp_c}°C</span>
                </div>
                <div class="stat-box">
                    <span class="stat-label">RISK FACTOR</span>
                    <span class="stat-value" style="color: ${colorCode};">${t_data.thermal_risk_score}%</span>
                    <div class="risk-bar">
                        <div class="risk-bar-fill" style="width: 0%; background-color: ${colorCode};"></div>
                    </div>
                </div>
            </div>
            <button class="play-btn" data-route-id="${route.id}">
                <span class="material-icons-outlined" style="font-size: 14px; margin-right: 4px;">play_arrow</span> EXECUTE LIVE TRANSIT
            </button>
        `;
        
        card.addEventListener('click', (e) => {
            highlightRoute(route.id);
            document.querySelectorAll('.route-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            if(e.target.closest('.play-btn')) playLiveTransit(route);
        });
        resultsContainer.appendChild(card);
        
        // Trigger animation for risk bar
        setTimeout(() => {
            const fill = card.querySelector('.risk-bar-fill');
            if(fill) fill.style.width = `${t_data.thermal_risk_score}%`;
        }, 100);
    });
}

function drawRoutes(data) {
    const latlngsCollection = [];
    data.all_routes.forEach(route => {
        const isSafest = route.id === data.safest_route_id;
        const latlngs = route.waypoints.map(p => [p.lat, p.lng]);
        latlngsCollection.push(...latlngs);
        
        const polyline = L.polyline(latlngs, {
            color: isSafest ? '#10b981' : '#64748b', weight: isSafest ? 4 : 2,
            opacity: isSafest ? 1 : 0.3, route_id: route.id, dashArray: isSafest ? null : '4,8'
        }).addTo(map);
        
        route.thermal_analysis.segment_logs.forEach((log) => {
            const ptIdx = Math.min(log.segment_idx + 1, latlngs.length - 2); 
            const pt = latlngs[ptIdx];
            if (pt) {
                let heatColor = '#38bdf8'; 
                if (log.ambient_temp > 30) heatColor = '#f59e0b'; 
                if (log.ambient_temp > 38) heatColor = '#ef4444'; 
                
                const circle = L.circle(pt, {
                    color: heatColor, fillColor: heatColor, fillOpacity: isSafest ? 0.2 : 0,
                    radius: log.ambient_temp * 500, route_id: route.id
                }).addTo(map);
                circle.bindPopup(`ZONE T: ${log.ambient_temp}°C | SKN T: ${log.truck_skin_temp}°C`);
                currentLayers.push(circle);
            }
        });
        currentLayers.push(polyline);
    });
    
    if (latlngsCollection.length > 0) map.fitBounds(L.latLngBounds(latlngsCollection), { padding: [50, 50] });
}

function highlightRoute(routeId) {
    if(truckMarker) { map.removeLayer(truckMarker); truckMarker = null; }
    map.eachLayer((layer) => {
        if (layer.options && layer.options.route_id) {
            if (layer.options.route_id === routeId) {
                if (layer instanceof L.Polyline && !(layer instanceof L.Circle)) {
                    layer.setStyle({color: '#10b981', weight: 4, opacity: 1, dashArray: null}); layer.bringToFront();
                } else if (layer instanceof L.Circle) layer.setStyle({fillOpacity: 0.2});
            } else {
                if (layer instanceof L.Polyline && !(layer instanceof L.Circle)) {
                    layer.setStyle({color: '#64748b', weight: 2, opacity: 0.3, dashArray: '4,8'});
                } else if (layer instanceof L.Circle) layer.setStyle({fillOpacity: 0});
            }
        }
    });
}

function playLiveTransit(route) {
    if(truckMarker) map.removeLayer(truckMarker);
    const telBody = document.getElementById('telemetryBody');
    
    const truckIcon = L.divIcon({
        className: 'custom-truck-icon',
        html: `<div style="background: #000; border: 2px solid var(--acc-primary); box-shadow: 0 0 10px var(--acc-primary); width: 14px; height: 14px; transform: rotate(45deg);"></div>`,
        iconSize: [18, 18], iconAnchor: [9, 9]
    });
    
    const wp = route.waypoints;
    if(wp.length < 2) return;
    
    truckMarker = L.marker([wp[0].lat, wp[0].lng], {icon: truckIcon}).addTo(map);
    
    let frame = 0; const totalFrames = 100;
    const interval = setInterval(() => {
        if(frame >= totalFrames) {
            clearInterval(interval);
            telBody.innerHTML += '<div class="tel-row" style="margin-top: 20px; color: var(--acc-safe);">[TRANSIT COMPLETE]</div>';
            return;
        }
        
        const fraction = frame / totalFrames;
        const floatIndex = fraction * (wp.length - 1);
        const lowerIndex = Math.floor(floatIndex);
        const upperIndex = Math.ceil(floatIndex);
        const localFrac = floatIndex - lowerIndex;
        
        let lat = wp[lowerIndex].lat; let lng = wp[lowerIndex].lng;
        if (lowerIndex !== upperIndex) {
            lat = lat + (wp[upperIndex].lat - lat) * localFrac;
            lng = lng + (wp[upperIndex].lng - lng) * localFrac;
        }
        truckMarker.setLatLng([lat, lng]);
        
        const logs = route.thermal_analysis.segment_logs;
        const currentLog = logs[Math.min(logs.length - 1, Math.floor(fraction * logs.length))];
        
        let safeClass = currentLog.end_cargo_temp > parseFloat(document.getElementById('cargoType').value) ? 'danger' : '';
        let skinClass = currentLog.truck_skin_temp > 50 ? 'danger' : '';
        
        telBody.innerHTML = `
            <div class="telemetry-node">
                <div class="telemetry-title">T: +${Math.floor(fraction * route.estimated_time_mins)}m <span style="font-size: 9px; color: var(--acc-primary);">SECTOR ${currentLog.segment_idx}</span></div>
                <div class="tel-row"><span>AIR AMBIENT</span> <span>${currentLog.ambient_temp}°C</span></div>
                <div class="tel-row"><span>RADIANT SKIN</span> <span class="tel-val ${skinClass}">${currentLog.truck_skin_temp}°C</span></div>
                <div class="tel-row"><span>CORE CARGO</span> <span class="tel-val ${safeClass}">${currentLog.end_cargo_temp}°C</span></div>
                <div class="tel-row" style="margin-top: 10px; font-size: 10px;">> ${currentLog.condition}</div>
            </div>
        `;
        frame++;
    }, 100);
}
