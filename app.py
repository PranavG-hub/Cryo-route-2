from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
import smtplib
import random
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# Google Auth imports
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from services import get_route_options, calculate_thermal_risk

import os
if os.path.exists('.env'):
    with open('.env', 'r') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k] = v

app = Flask(__name__, static_folder='static', static_url_path='/static', template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'super-secure-hackathon-key-1234')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///coldlink.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=True)

with app.app_context():
    db.create_all()

CORS(app)

# In-memory OTP store
otp_store = {}

@app.route('/')
def index():
    # Pass the Google Client ID carefully to the frontend templater
    client_id = os.environ.get('GOOGLE_CLIENT_ID', 'MISSING_CLIENT_ID_IN_ENV')
    return render_template('index.html', google_client_id=client_id)

@app.route('/api/auth/verify-google', methods=['POST'])
def verify_google():
    data = request.json
    token = data.get('credential')
    
    if not token:
        return jsonify({"error": "No credential provided"}), 400
        
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    
    try:
        # Verify the mathematically secure JWT against Google's public keys
        idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
        email = idinfo.get('email')
        
        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({"error": "ACCESS DENIED. Account not found. Please switch to the NEW DISPATCHER tab."}), 403
            
        session['user_id'] = user.id
        return jsonify({"message": "Successfully authenticated via Google", "email": email, "status": "success"})
        
    except ValueError as e:
        # Invalid token
        print("Google OAuth verification failed:", str(e))
        return jsonify({"error": "Invalid Google token. Security alert."}), 401

@app.route('/api/auth/signup-google', methods=['POST'])
def signup_google():
    data = request.json
    token = data.get('credential')
    
    if not token:
        return jsonify({"error": "No credential provided"}), 400
        
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    
    try:
        idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
        email = idinfo.get('email')
        name = idinfo.get('name', 'Dispatcher')
        
        user = User.query.filter_by(email=email).first()
        if user:
            return jsonify({"error": "ACCOUNT EXISTS. Please switch to the SYSTEM LOGIN tab."}), 400
            
        new_user = User(email=email, name=name)
        db.session.add(new_user)
        db.session.commit()
        
        session['user_id'] = new_user.id
        return jsonify({"message": "Successfully registered via Google", "email": email, "status": "success"})
        
    except ValueError as e:
        print("Google OAuth verification failed:", str(e))
        return jsonify({"error": "Invalid Google token. Security alert."}), 401

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
        msg = MIMEMultipart()
        msg['From'] = f"ColdLink Dispatch <{sender_email}>"
        msg['To'] = email
        msg['Subject'] = f"{otp} is your ColdLink Engine Security Code"
        
        body = f"Dear Dispatcher,\n\nYour secure 2-Factor Authentication Code is:\n\n{otp}\n\nThis code will expire in 5 minutes.\n\n- ColdLink Automated System"
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, app_password)
        server.send_message(msg)
        server.quit()
        
        otp_store[email] = {
            "code": otp,
            "expiry": datetime.now() + timedelta(minutes=5)
        }
        
        return jsonify({"message": "OTP sent successfully!", "status": "success"})
    except Exception as e:
        print(f"SMTP Error: {str(e)}")
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
        del otp_store[email]
        return jsonify({"message": "Authentication successful", "status": "success"})
        
    return jsonify({"error": "Invalid OTP code"}), 401

@app.route('/api/routes/calculate', methods=['POST'])
def calculate_routes():
    data = request.json
    origin = data.get('origin', {'lat': 40.7128, 'lng': -74.0060})
    destination = data.get('destination', {'lat': 38.9072, 'lng': -77.0369})
    cargo_max_temp = data.get('cargo_max_temp', 8)
    
    routes = get_route_options(origin, destination)
    
    evaluated_routes = []
    
    for route in routes:
        thermal_data = calculate_thermal_risk(route, cargo_max_temp)
        route_eval = {
            **route,
            "thermal_analysis": thermal_data
        }
        evaluated_routes.append(route_eval)
        
    fastest_route = min(evaluated_routes, key=lambda x: x['estimated_time_mins'])
    safest_route = min(evaluated_routes, key=lambda x: x['thermal_analysis']['thermal_risk_score'])
    
    return jsonify({
        "all_routes": evaluated_routes,
        "fastest_route_id": fastest_route['id'],
        "safest_route_id": safest_route['id']
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
