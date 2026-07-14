import os
import re
import time
import json
import uuid
import logging
import secrets
import threading
import requests
from flask import Flask, jsonify, request, render_template, session
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# Constants and Storage Configuration
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RIGS_JSON_PATH = os.path.join(DATA_DIR, "rigs.json")

# Ensure persistence folder exists with safe permissions
os.makedirs(DATA_DIR, exist_ok=True)
try:
    os.chmod(DATA_DIR, 0o700)
except Exception:
    pass

# Initialize session security configuration
app.secret_key = secrets.token_hex(32)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Threading lock for storage operations
data_lock = threading.Lock()

# Logging config
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s'
)

def get_or_create_fleet_pin():
    """Generates an 8-character cryptographic random PIN if not present."""
    pin_file = os.path.join(DATA_DIR, "fleet_pin.txt")
    if os.path.exists(pin_file):
        try:
            with open(pin_file, "r") as f:
                return f.read().strip()
        except Exception:
            pass
            
    # Generate 8-character random PIN cryptographically
    pin = "".join([str(secrets.randbelow(10)) for _ in range(8)])
    try:
        with open(pin_file, "w") as f:
            f.write(pin)
        try:
            os.chmod(pin_file, 0o600)
        except Exception:
            pass
            
        logging.info("==================================================")
        logging.info(f"  FLEET MANAGER ACCESS PIN CREATED: {pin}")
        logging.info("  YOU CAN ALWAYS FIND IT IN YOUR DATA DIRECTORY.")
        logging.info("==================================================")
    except Exception as e:
        logging.error(f"Failed to save Fleet Access PIN: {e}")
    return pin

app.config['ACCESS_PIN'] = get_or_create_fleet_pin()

# Rate-limiting failed logins storage
failed_login_attempts = {}

@app.before_request
def require_auth():
    # Allow login page, static assets, and login endpoint without auth
    if request.path in ['/', '/api/login'] or request.path.startswith('/static/'):
        return
        
    if not session.get('authenticated'):
        return jsonify({"success": False, "authenticated": False, "message": "Unauthorized"}), 401
        
    # Enforce Anti-CSRF on modifying requests (POST, DELETE)
    if request.method in ['POST', 'DELETE']:
        token = request.headers.get('X-CSRF-Token')
        expected = session.get('csrf_token')
        if not token or not expected or token != expected:
            logging.warning(f"CSRF Alert: Invalid or missing token from IP {request.remote_addr}")
            return jsonify({"success": False, "message": "CSRF verification failed."}), 403

def load_rigs():
    """Reads rigs list from rigs.json with threading lock protection."""
    with data_lock:
        if not os.path.exists(RIGS_JSON_PATH):
            return []
        try:
            with open(RIGS_JSON_PATH, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Failed to read rigs storage: {e}")
            return []

def save_rigs(rigs):
    """Writes rigs list to rigs.json with threading lock protection and owner-only permissions."""
    with data_lock:
        try:
            file_exists = os.path.exists(RIGS_JSON_PATH)
            with open(RIGS_JSON_PATH, 'w') as f:
                json.dump(rigs, f, indent=4)
            if not file_exists:
                try:
                    os.chmod(RIGS_JSON_PATH, 0o600)
                except Exception:
                    pass
            return True
        except Exception as e:
            logging.error(f"Failed to write rigs storage: {e}")
            return False

def test_rig_connection(ip, port, pin):
    """Verifies credentials and connection health of standard local dashboard node."""
    url = f"http://{ip}:{port}"
    try:
        session = requests.Session()
        login_res = session.post(f"{url}/api/login", json={"pin": pin}, timeout=4)
        if login_res.status_code == 200:
            data = login_res.json()
            if data.get("success"):
                stats_res = session.get(f"{url}/api/stats", timeout=4)
                if stats_res.status_code == 200:
                    return True, stats_res.json()
                return False, "Failed to retrieve stats after successful authorization."
            return False, data.get("message", "Authorization rejected by host.")
        elif login_res.status_code == 429:
            return False, "Authorization blocked: Too many failed login attempts on host."
        return False, f"Host returned server status code {login_res.status_code}."
    except requests.exceptions.RequestException as e:
        logging.error(f"Connection test failed for {ip}:{port}: {e}")
        return False, "Connection timed out or host unreachable."

def fetch_single_rig_status(rig):
    """Worker task polling status of a single rig concurrently."""
    url = f"http://{rig['ip']}:{rig['port']}"
    try:
        session = requests.Session()
        login_res = session.post(f"{url}/api/login", json={"pin": rig["pin"]}, timeout=3)
        if login_res.status_code == 200 and login_res.json().get("success"):
            stats_res = session.get(f"{url}/api/stats", timeout=3)
            if stats_res.status_code == 200:
                return {
                    "id": rig["id"],
                    "name": rig["name"],
                    "ip": rig["ip"],
                    "port": rig["port"],
                    "online": True,
                    "stats": stats_res.json()
                }
        return {
            "id": rig["id"],
            "name": rig["name"],
            "ip": rig["ip"],
            "port": rig["port"],
            "online": False,
            "error": "Access validation failed."
        }
    except Exception:
        return {
            "id": rig["id"],
            "name": rig["name"],
            "ip": rig["ip"],
            "port": rig["port"],
            "online": False,
            "error": "Rig unreachable or offline."
        }

@app.route('/api/login', methods=['POST'])
def api_login():
    ip = request.remote_addr
    now = time.time()
    
    if ip in failed_login_attempts:
        record = failed_login_attempts[ip]
        if record["blocked_until"] > now:
            remaining = int(record["blocked_until"] - now)
            logging.warning(f"Blocked login attempt from locked-out IP {ip}. Remaining: {remaining}s")
            return jsonify({"success": False, "message": f"Too many failed attempts. Try again in {remaining} seconds."}), 429
            
    data = request.get_json()
    if not data or 'pin' not in data:
        return jsonify({"success": False, "message": "Missing PIN"}), 400
        
    user_pin = str(data['pin']).strip()
    if user_pin == app.config['ACCESS_PIN']:
        if ip in failed_login_attempts:
            del failed_login_attempts[ip]
            
        session['authenticated'] = True
        csrf_token = secrets.token_hex(16)
        session['csrf_token'] = csrf_token
        
        logging.info(f"Authorized Fleet Manager login request from IP: {ip}")
        return jsonify({"success": True, "message": "Authenticated successfully!", "csrf_token": csrf_token})
        
    if ip not in failed_login_attempts:
        failed_login_attempts[ip] = {"count": 1, "blocked_until": 0.0}
    else:
        failed_login_attempts[ip]["count"] += 1
        
    record = failed_login_attempts[ip]
    if record["count"] >= 5:
        record["blocked_until"] = now + 900
        logging.warning(f"IP {ip} locked out of Fleet Manager for 15 minutes after 5 failures.")
        return jsonify({"success": False, "message": "Too many failed attempts. Access blocked for 15 minutes."}), 429
        
    return jsonify({"success": False, "message": "Invalid Access PIN. Try again."}), 401

@app.route('/api/rigs', methods=['GET', 'POST'])
def manage_rigs():
    if request.method == 'GET':
        rigs = load_rigs()
        safe_list = [{k: v for k, v in r.items() if k != 'pin'} for r in rigs]
        return jsonify({
            "success": True,
            "csrf_token": session.get('csrf_token'),
            "rigs": safe_list
        })

    # POST - Add Rig
    data = request.get_json()
    if not data or 'name' not in data or 'ip' not in data or 'pin' not in data:
        return jsonify({"success": False, "message": "Missing required configuration fields."}), 400

    name = str(data['name']).strip()
    ip = str(data['ip']).strip()
    port = int(data.get('port', 1337))
    pin = str(data['pin']).strip()

    if not re.match(r'^[A-Za-z0-9_\-\s]+$', name):
        return jsonify({"success": False, "message": "Invalid rig name. Use alphanumeric characters only."}), 400
    if not re.match(r'^[a-zA-Z0-9\.\-\:]+$', ip):
        return jsonify({"success": False, "message": "Invalid Host/IP format."}), 400
    if not (1 <= port <= 65535):
        return jsonify({"success": False, "message": "Invalid Port index."}), 400
    if not (len(pin) == 6 and pin.isdigit()):
        return jsonify({"success": False, "message": "Access PIN must be a 6-digit number."}), 400

    connected, test_stats = test_rig_connection(ip, port, pin)
    if not connected:
        return jsonify({"success": False, "message": f"Rig connection test failed: {test_stats}"}), 400

    rigs = load_rigs()
    if any(r['ip'] == ip and r['port'] == port for r in rigs):
        return jsonify({"success": False, "message": "A rig with this IP address and Port is already configured."}), 409

    new_rig = {
        "id": str(uuid.uuid4()),
        "name": name,
        "ip": ip,
        "port": port,
        "pin": pin
    }
    rigs.append(new_rig)
    if save_rigs(rigs):
        logging.info(f"Added new rig to fleet: {name} ({ip}:{port})")
        return jsonify({"success": True, "message": f"Rig '{name}' successfully verified and added to fleet manager!"})
    return jsonify({"success": False, "message": "Failed to save rig config details."}), 500

@app.route('/api/rigs/<rig_id>', methods=['DELETE'])
def delete_rig(rig_id):
    rigs = load_rigs()
    target_idx = next((i for i, r in enumerate(rigs) if r['id'] == rig_id), -1)
    if target_idx == -1:
        return jsonify({"success": False, "message": "Rig not found."}), 404

    deleted_name = rigs[target_idx]['name']
    rigs.pop(target_idx)
    if save_rigs(rigs):
        logging.info(f"Removed rig from fleet: {deleted_name} (ID: {rig_id})")
        return jsonify({"success": True, "message": f"Rig '{deleted_name}' successfully removed from fleet."})
    return jsonify({"success": False, "message": "Failed to save updated rig configurations list."}), 500

@app.route('/api/fleet/stats', methods=['GET'])
def get_fleet_stats():
    rigs = load_rigs()
    if not rigs:
        return jsonify({
            "success": True,
            "summary": {
                "online_rigs": 0,
                "total_rigs": 0,
                "total_hashrate": 0.0,
                "avg_temp": 0.0,
                "total_power": 0.0
            },
            "rigs": []
        })

    with ThreadPoolExecutor(max_workers=min(16, len(rigs))) as executor:
        results = list(executor.map(fetch_single_rig_status, rigs))

    online_count = 0
    total_hashrate = 0.0
    total_power = 0.0
    temp_sum = 0
    gpu_count = 0

    for r in results:
        if r["online"]:
            online_count += 1
            stats = r["stats"]
            gpus = stats.get("gpus", [])
            for g in gpus:
                total_hashrate += g.get("hashrate", 0.0)
                total_power += g.get("power", 0.0)
                temp_sum += g.get("temp", 0)
                gpu_count += 1
            cpu_hash = stats.get("system", {}).get("cpu", {}).get("hashrate", 0.0)
            total_hashrate += cpu_hash / 1000000.0

    avg_temp = (temp_sum / gpu_count) if gpu_count > 0 else 0.0

    return jsonify({
        "success": True,
        "summary": {
            "online_rigs": online_count,
            "total_rigs": len(rigs),
            "total_hashrate": round(total_hashrate, 2),
            "avg_temp": round(avg_temp, 1),
            "total_power": round(total_power, 1)
        },
        "rigs": results
    })

@app.route('/api/fleet/control', methods=['POST'])
def proxy_control_action():
    data = request.get_json()
    if not data or 'rig_id' not in data or 'endpoint' not in data:
        return jsonify({"success": False, "message": "Missing required proxy parameters."}), 400

    rig_id = str(data['rig_id']).strip()
    endpoint = str(data['endpoint']).strip()
    payload = data.get('payload', {})

    if endpoint not in ["/api/miner/control", "/api/system/reboot", "/api/system/shutdown", "/api/overclock", "/api/revert", "/api/hugepages", "/api/autofan", "/api/watchdog"]:
        return jsonify({"success": False, "message": "Target endpoint operation is restricted."}), 403

    rigs = load_rigs()
    target_rig = next((r for r in rigs if r['id'] == rig_id), None)
    if not target_rig:
        return jsonify({"success": False, "message": "Target rig not configured in Fleet Manager."}), 404

    url = f"http://{target_rig['ip']}:{target_rig['port']}"
    try:
        session = requests.Session()
        login_res = session.post(f"{url}/api/login", json={"pin": target_rig["pin"]}, timeout=4)
        if login_res.status_code == 200:
            login_data = login_res.json()
            if login_data.get("success"):
                csrf_token = login_data.get("csrf_token")
                headers = {
                    "X-CSRF-Token": csrf_token,
                    "Content-Type": "application/json"
                }
                fwd_res = session.post(f"{url}{endpoint}", json=payload, headers=headers, timeout=4)
                if fwd_res.status_code == 200:
                    return jsonify(fwd_res.json())
                return jsonify({"success": False, "message": "Proxy call failed."}), fwd_res.status_code
            return jsonify({"success": False, "message": "Verification rejected on target rig."}), 401
        return jsonify({"success": False, "message": "Authorization request returned error code."}), 401
    except Exception as e:
        logging.error(f"Proxy request execution error: {e}")
        return jsonify({"success": False, "message": "Failed to contact target rig API. Verify connectivity."}), 500

@app.route('/api/fleet/log/<rig_id>', methods=['GET'])
def proxy_log_action(rig_id):
    rigs = load_rigs()
    target_rig = next((r for r in rigs if r['id'] == rig_id), None)
    if not target_rig:
        return jsonify({"success": False, "message": "Rig not found."}), 404

    url = f"http://{target_rig['ip']}:{target_rig['port']}"
    try:
        session = requests.Session()
        login_res = session.post(f"{url}/api/login", json={"pin": target_rig["pin"]}, timeout=4)
        if login_res.status_code == 200 and login_res.json().get("success"):
            log_res = session.get(f"{url}/api/miner/log", timeout=4)
            if log_res.status_code == 200:
                return jsonify(log_res.json())
            return jsonify({"success": False, "message": "Failed to query logs from target rig."}), log_res.status_code
        return jsonify({"success": False, "message": "Authorization rejected on target rig."}), 401
    except Exception as e:
        logging.error(f"Log retrieval proxy request failed: {e}")
        return jsonify({"success": False, "message": "Failed to reach target rig API logs endpoint."}), 500

@app.route('/')
def dashboard():
    return render_template('index.html')

if __name__ == '__main__':
    port = 8080
    logging.info(f"Starting Fleet Manager web interface on port {port}...")
    try:
        from waitress import serve
        serve(app, host='0.0.0.0', port=port, threads=8)
    except ImportError:
        app.run(host='0.0.0.0', port=port, debug=False)
