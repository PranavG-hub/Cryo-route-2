from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import smtplib
import random
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from services import get_route_options, calculate_thermal_risk

import os
if os.path.exists('.env'):
    with open('.env', 'r') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k] = v

app = Flask(__name__, static_folder='static', static_url_path='/static', template_folder='templates')
CORS(app)

# In-memory OTP store (perfect for hackathon)
otp_store = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/auth/send-otp', methods=['POST'])
def send_otp():
    data = request.json
    email = data.get('email')
    
    if not email:
        return jsonify({"error": "Email is required"}), 400
        
    otp = str(random.randint(1000, 9999))
    
    sender_email = os.environ.get('GMAIL_ADDRESS', 'your_email@gmail.com')
    app_password = os.environ.get('GMAIL_APP_PASSWORD', 'your_password_here')
    
    try:
        # Construct Email
        msg = MIMEMultipart()
        msg['From'] = f"ColdLink Dispatch <{sender_email}>"
        msg['To'] = email
        msg['Subject'] = f"{otp} is your ColdLink Engine Security Code"
        
        body = f"""
        Dear Dispatcher,
        
        A sign-in attempt was detected for your ColdLink Engine.
        Your secure 2-Factor Authentication Code is:
        
        {otp}
        
        This code will expire in 5 minutes.
        If you did not request this, please contact IT immediately.
        
        - ColdLink Automated System
        """
        msg.attach(MIMEText(body, 'plain'))
        
        # Connect to Gmail SMTP
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, app_password)
        server.send_message(msg)
        server.quit()
        
        # Store OTP securely with 5 min expiry
        otp_store[email] = {
            "code": otp,
            "expiry": datetime.now() + timedelta(minutes=5)
        }
        
        return jsonify({"message": "OTP sent successfully!", "status": "success"})
        
    except Exception as e:
        print(f"SMTP Error: {str(e)}")
        # Fallback for dev mode if they didn't set up the password correctly
        otp_store[email] = {
            "code": otp,
            "expiry": datetime.now() + timedelta(minutes=5)
        }
        return jsonify({"message": f"Dev Mode: Check backend console for OTP ({otp})", "status": "dev_fallback"}), 200

@app.route('/api/auth/verify-otp', methods=['POST'])
def verify_otp():
    data = request.json
    email = data.get('email')
    entered_otp = data.get('otp')
    
    if email not in otp_store:
        return jsonify({"error": "No OTP requested for this email"}), 400
        
    stored_data = otp_store[email]
    
    if datetime.now() > stored_data["expiry"]:
        del otp_store[email]
        return jsonify({"error": "OTP has expired"}), 408
        
    if str(entered_otp) == str(stored_data["code"]):
        del otp_store[email] # clear after use
        return jsonify({"message": "Authentication successful", "status": "success"})
        
    return jsonify({"error": "Invalid OTP code"}), 401
@app.route('/api/routes/calculate', methods=['POST'])
def calculate_routes():
    data = request.json
    origin = data.get('origin', {'lat': 40.7128, 'lng': -74.0060}) # default NY
    destination = data.get('destination', {'lat': 38.9072, 'lng': -77.0369}) # default DC
    cargo_max_temp = data.get('cargo_max_temp', 8) # Vaccine default 8C
    
    routes = get_route_options(origin, destination)
    
    evaluated_routes = []
    
    for route in routes:
        thermal_data = calculate_thermal_risk(route, cargo_max_temp)
        route_eval = {
            **route,
            "thermal_analysis": thermal_data
        }
        evaluated_routes.append(route_eval)
        
    # Sort them by different metrics
    fastest_route = min(evaluated_routes, key=lambda x: x['estimated_time_mins'])
    safest_route = min(evaluated_routes, key=lambda x: x['thermal_analysis']['thermal_risk_score'])
    
    return jsonify({
        "all_routes": evaluated_routes,
        "fastest_route_id": fastest_route['id'],
        "safest_route_id": safest_route['id']
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
