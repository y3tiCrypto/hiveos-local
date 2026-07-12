import os
import re
import socket
import subprocess
import platform
import shutil
import logging
import threading
import random
from flask import Flask, jsonify, request, render_template, session

app = Flask(__name__)
# Secure randomly-generated key for session management
app.secret_key = os.urandom(24)

# Constants and Configuration Paths
HIVE_CONFIG_DIR = "/hive-config"
RIG_CONF_PATH = os.path.join(HIVE_CONFIG_DIR, "rig.conf")
NVIDIA_OC_CONF = os.path.join(HIVE_CONFIG_DIR, "nvidia-oc.conf")
AMD_OC_CONF = os.path.join(HIVE_CONFIG_DIR, "amd-oc.conf")

# Check environment
IS_LINUX = platform.system() == "Linux"
HAS_HIVEOS = IS_LINUX and os.path.exists(HIVE_CONFIG_DIR)

# Local configuration fallback paths for Demo Mode
MOCK_NVIDIA_OC_CONF = "./mock_nvidia-oc.conf"
MOCK_AMD_OC_CONF = "./mock_amd-oc.conf"
MOCK_RIG_CONF = "./mock_rig.conf"

# Access PIN Key Path
PIN_PATH = os.path.join(HIVE_CONFIG_DIR, "dashboard.key") if HAS_HIVEOS else "./dashboard.key"

# Thread safety lock for files access
config_lock = threading.Lock()

# 1. Setup Structured Production Logging
log_file = '/var/log/hiveos-local.log' if HAS_HIVEOS else './hiveos-local.log'
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger()

# Console logger stream handler
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(console)

def get_local_ip():
    """Detects primary LAN IP interface."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to public DNS address without sending packets to query routing table
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def get_rig_config_path():
    return RIG_CONF_PATH if HAS_HIVEOS else MOCK_RIG_CONF

def get_nvidia_oc_path():
    return NVIDIA_OC_CONF if HAS_HIVEOS else MOCK_NVIDIA_OC_CONF

def get_amd_oc_path():
    return AMD_OC_CONF if HAS_HIVEOS else MOCK_AMD_OC_CONF

# Load or generate access authentication PIN
def load_or_generate_pin():
    with config_lock:
        if os.path.exists(PIN_PATH):
            try:
                with open(PIN_PATH, 'r') as f:
                    pin = f.read().strip()
                    if len(pin) == 6 and pin.isdigit():
                        return pin
            except Exception as e:
                logging.error(f"Failed to read access PIN: {e}")
        
        # Generate new 6-digit random PIN
        pin = "".join([str(random.randint(0, 9)) for _ in range(6)])
        try:
            with open(PIN_PATH, 'w') as f:
                f.write(pin)
            if HAS_HIVEOS:
                os.chmod(PIN_PATH, 0o600) # Read/write by root only
            logging.info(f"Generated new dashboard access PIN: {pin}")
        except Exception as e:
            logging.error(f"Failed to write access PIN: {e}")
        return pin

# Initialize mock config files if not exists in Demo Mode
def init_mock_configs():
    if not HAS_HIVEOS:
        with config_lock:
            if not os.path.exists(MOCK_RIG_CONF):
                with open(MOCK_RIG_CONF, 'w') as f:
                    f.write(
                        'HIVE_VERSION="0.6-220@230501"\n'
                        'RIG_ID="133742"\n'
                        'RIG_PASSWD="demo_passwd"\n'
                        'FARM_HASH="d3m0ha5h123456789"\n'
                        'API_URL="https://api.hiveon.net"\n'
                        'MINER="lolminer"\n'
                    )
            if not os.path.exists(MOCK_NVIDIA_OC_CONF):
                with open(MOCK_NVIDIA_OC_CONF, 'w') as f:
                    f.write(
                        'CORE="100 0"\n'
                        'MEM="1000 2000"\n'
                        'PL="120 250"\n'
                        'FAN="60 0"\n'
                    )
            if not os.path.exists(MOCK_AMD_OC_CONF):
                with open(MOCK_AMD_OC_CONF, 'w') as f:
                    f.write(
                        'CORE="1100"\n'
                        'MEM="2000"\n'
                        'VDD="800"\n'
                        'VDDCI="750"\n'
                        'MVDD="1300"\n'
                        'FAN="65"\n'
                        'PL="100"\n'
                        'DPM="4"\n'
                        'REF="30"\n'
                    )

# Parse shell-like config files with locking
def parse_shell_config(filepath):
    config = {}
    with config_lock:
        if not os.path.exists(filepath):
            return config
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    match = re.match(r'^([A-Za-z0-9_]+)\s*=\s*(.*)$', line)
                    if match:
                        key = match.group(1)
                        val = match.group(2).strip()
                        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                            val = val[1:-1]
                        config[key] = val
        except Exception as e:
            logging.error(f"Error parsing config file {filepath}: {e}")
    return config

# Write shell-like config files with locking
def write_shell_config(filepath, config):
    with config_lock:
        try:
            with open(filepath, 'w') as f:
                for k, v in config.items():
                    f.write(f'{k}="{v}"\n')
            return True
        except Exception as e:
            logging.error(f"Error writing config file {filepath}: {e}")
            return False

# Strict regex parameter validation to block shell injection
def is_safe_parameter_value(value):
    val_str = str(value).strip()
    if not val_str:
        return True
    # Whitelist: Digits, whitespace, negative/positive sign
    return re.match(r'^[\-\+]?[0-9\s]+$', val_str) is not None

# Create backup files of current config files
def backup_configs():
    try:
        nv_path = get_nvidia_oc_path()
        if os.path.exists(nv_path):
            shutil.copy2(nv_path, nv_path + ".bak")
            
        amd_path = get_amd_oc_path()
        if os.path.exists(amd_path):
            shutil.copy2(amd_path, amd_path + ".bak")
        return True
    except Exception as e:
        logging.error(f"Failed to create backups of configurations: {e}")
        return False

# System stats query
def get_system_stats():
    stats = {
        "hostname": socket.gethostname(),
        "local_ip": get_local_ip(),
        "uptime": "Unknown",
        "cpu_load": [0.0, 0.0, 0.0],
        "ram_used_pct": 0.0,
        "ram_total_gb": 0.0,
        "is_demo": not HAS_HIVEOS,
        "rig_id": "Offline",
        "farm_hash": "Offline",
        "hive_version": "Local-1.0",
        "active_miner": "None"
    }

    rig_conf = parse_shell_config(get_rig_config_path())
    stats["rig_id"] = rig_conf.get("RIG_ID", "Not Found")
    stats["farm_hash"] = rig_conf.get("FARM_HASH", "Not Found")
    stats["hive_version"] = rig_conf.get("HIVE_VERSION", "Demo-v0.6")
    stats["active_miner"] = rig_conf.get("MINER", "lolminer")

    if IS_LINUX:
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
                hours = int(uptime_seconds // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                stats["uptime"] = f"{hours}h {minutes}m"
        except Exception:
            pass

        try:
            with open('/proc/loadavg', 'r') as f:
                stats["cpu_load"] = [float(x) for x in f.readline().split()[:3]]
        except Exception:
            pass

        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
                mem_total = int(re.search(r'MemTotal:\s+(\d+)', meminfo).group(1))
                mem_free = int(re.search(r'MemFree:\s+(\d+)', meminfo).group(1))
                mem_buffers = int(re.search(r'Buffers:\s+(\d+)', meminfo).group(1))
                mem_cached = int(re.search(r'Cached:\s+(\d+)', meminfo).group(1))
                mem_used = mem_total - (mem_free + mem_buffers + mem_cached)
                stats["ram_used_pct"] = round((mem_used / mem_total) * 100, 1)
                stats["ram_total_gb"] = round(mem_total / (1024 * 1024), 1)
        except Exception:
            pass
    else:
        stats["uptime"] = "1h 45m"
        stats["cpu_load"] = [0.45, 0.30, 0.15]
        stats["ram_used_pct"] = 42.5
        stats["ram_total_gb"] = 16.0

    return stats

# Shell command execution helper
def run_command(cmd):
    try:
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return res.stdout, res.stderr, res.returncode
    except Exception as e:
        return "", str(e), -1

# GPU metrics parser
def get_gpu_stats():
    gpus = []
    
    # 1. NVIDIA telemetry
    nvidia_detected = False
    if HAS_HIVEOS or IS_LINUX:
        stdout, stderr, code = run_command("nvidia-smi --query-gpu=index,name,temperature.gpu,fan.speed,power.draw,utilization.gpu,clocks.current.graphics,clocks.current.memory,power.limit --format=csv,noheader,nounits")
        if code == 0 and stdout:
            nvidia_detected = True
            lines = stdout.strip().split('\n')
            for line in lines:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 9:
                    idx = int(parts[0])
                    gpus.append({
                        "id": f"NV_{idx}",
                        "index": idx,
                        "brand": "NVIDIA",
                        "model": parts[1],
                        "temp": int(parts[2]),
                        "fan": int(parts[3]) if parts[3] != '[N/A]' else 0,
                        "power": float(parts[4]),
                        "power_limit": float(parts[8]),
                        "utilization": int(parts[5]),
                        "core_clock": int(parts[6]),
                        "mem_clock": int(parts[7]),
                        "hashrate": round(50.0 + (int(parts[6]) % 10) + (int(parts[7]) % 20) / 10.0, 2)
                    })

    # 2. AMD telemetry
    amd_detected = False
    if HAS_HIVEOS or IS_LINUX:
        if os.path.exists("/sys/class/drm"):
            cards = [d for d in os.listdir("/sys/class/drm") if re.match(r'^card\d+$', d)]
            amd_idx = 0
            for card in sorted(cards):
                hwmon_path = f"/sys/class/drm/{card}/device/hwmon"
                if os.path.exists(hwmon_path):
                    hwmons = os.listdir(hwmon_path)
                    if not hwmons:
                        continue
                    hpath = f"{hwmon_path}/{hwmons[0]}"
                    
                    vendor_path = f"/sys/class/drm/{card}/device/vendor"
                    if os.path.exists(vendor_path):
                        with open(vendor_path, 'r') as f:
                            vendor = f.read().strip()
                        if "0x1002" not in vendor:
                            continue
                            
                    try:
                        temp = 0
                        if os.path.exists(f"{hpath}/temp1_input"):
                            with open(f"{hpath}/temp1_input", 'r') as f:
                                temp = int(int(f.read().strip()) / 1000)
                        
                        fan = 0
                        if os.path.exists(f"{hpath}/fan1_input"):
                            with open(f"{hpath}/fan1_input", 'r') as f:
                                rpm = int(f.read().strip())
                                fan = min(100, int(rpm / 30))
                        
                        power = 0.0
                        if os.path.exists(f"{hpath}/power1_average"):
                            with open(f"{hpath}/power1_average", 'r') as f:
                                power = round(float(f.read().strip()) / 1000000.0, 1)
                                
                        model = "AMD Radeon GPU"
                        device_path = f"/sys/class/drm/{card}/device/device"
                        if os.path.exists(device_path):
                            with open(device_path, 'r') as f:
                                dev_id = f.read().strip()
                            model = f"AMD GPU ({dev_id})"
                        
                        gpus.append({
                            "id": f"AMD_{amd_idx}",
                            "index": amd_idx,
                            "brand": "AMD",
                            "model": model,
                            "temp": temp,
                            "fan": fan,
                            "power": power,
                            "power_limit": 150.0,
                            "utilization": 99,
                            "core_clock": 1200,
                            "mem_clock": 2000,
                            "hashrate": 30.5
                        })
                        amd_idx += 1
                        amd_detected = True
                    except Exception as e:
                        logging.error(f"Error reading AMD sysfs indices: {e}")

    # 3. Fallback mock setup
    if not nvidia_detected and not amd_detected:
        nv_oc = parse_shell_config(get_nvidia_oc_path())
        amd_oc = parse_shell_config(get_amd_oc_path())

        nv_core = nv_oc.get("CORE", "0 0").split()
        nv_mem = nv_oc.get("MEM", "0 0").split()
        nv_pl = nv_oc.get("PL", "0 0").split()
        nv_fan = nv_oc.get("FAN", "0 0").split()
        
        nv_core += ["0"] * (2 - len(nv_core))
        nv_mem += ["0"] * (2 - len(nv_mem))
        nv_pl += ["0"] * (2 - len(nv_pl))
        nv_fan += ["0"] * (2 - len(nv_fan))

        gpus.append({
            "id": "NV_0",
            "index": 0,
            "brand": "NVIDIA",
            "model": "GeForce RTX 3080",
            "temp": 62,
            "fan": int(nv_fan[0]) if int(nv_fan[0]) > 0 else 55,
            "power": float(nv_pl[0]) - 10 if int(nv_pl[0]) > 0 else 220.0,
            "power_limit": float(nv_pl[0]) if int(nv_pl[0]) > 0 else 250.0,
            "utilization": 100,
            "core_clock": 1450 + (int(nv_core[0]) if int(nv_core[0]) > 500 else 0),
            "mem_clock": 4750 + int(nv_mem[0]),
            "hashrate": round(95.0 + (int(nv_mem[0]) / 100.0) + (10 if int(nv_core[0]) > 500 else 0), 2)
        })

        gpus.append({
            "id": "NV_1",
            "index": 1,
            "brand": "NVIDIA",
            "model": "GeForce RTX 3070 Ti",
            "temp": 58,
            "fan": int(nv_fan[1]) if int(nv_fan[1]) > 0 else 48,
            "power": float(nv_pl[1]) - 15 if int(nv_pl[1]) > 0 else 185.0,
            "power_limit": float(nv_pl[1]) if int(nv_pl[1]) > 0 else 220.0,
            "utilization": 100,
            "core_clock": 1580 + (int(nv_core[1]) if int(nv_core[1]) > 500 else 0),
            "mem_clock": 4500 + int(nv_mem[1]),
            "hashrate": round(60.0 + (int(nv_mem[1]) / 120.0), 2)
        })

        amd_core = amd_oc.get("CORE", "0").split()
        amd_mem = amd_oc.get("MEM", "0").split()
        amd_fan = amd_oc.get("FAN", "0").split()
        
        amd_core += ["0"]
        amd_mem += ["0"]
        amd_fan += ["0"]

        gpus.append({
            "id": "AMD_0",
            "index": 0,
            "brand": "AMD",
            "model": "Radeon RX 6800 XT",
            "temp": 68,
            "fan": int(amd_fan[0]) if int(amd_fan[0]) > 0 else 60,
            "power": 165.0,
            "power_limit": float(amd_oc.get("PL", "180").split()[0]),
            "utilization": 99,
            "core_clock": int(amd_core[0]) if int(amd_core[0]) > 0 else 2100,
            "mem_clock": int(amd_mem[0]) if int(amd_mem[0]) > 0 else 1000,
            "hashrate": round(62.5 + (int(amd_mem[0]) - 1000) / 40.0 if int(amd_mem[0]) > 0 else 62.5, 2)
        })

    return gpus

# Read configs formatted
def get_overclocks_formatted():
    nv_data = parse_shell_config(get_nvidia_oc_path())
    amd_data = parse_shell_config(get_amd_oc_path())
    
    return {
        "nvidia": {
            "core": nv_data.get("CORE", "").split(),
            "mem": nv_data.get("MEM", "").split(),
            "pl": nv_data.get("PL", "").split(),
            "fan": nv_data.get("FAN", "").split()
        },
        "amd": {
            "core": amd_data.get("CORE", "").split(),
            "mem": amd_data.get("MEM", "").split(),
            "vdd": amd_data.get("VDD", "").split(),
            "vddci": amd_data.get("VDDCI", "").split(),
            "mvdd": amd_data.get("MVDD", "").split(),
            "fan": amd_data.get("FAN", "").split(),
            "pl": amd_data.get("PL", "").split(),
            "dpm": amd_data.get("DPM", "").split(),
            "ref": amd_data.get("REF", "").split()
        }
    }

# Require authentication for all endpoints
@app.before_request
def require_auth():
    # Exclude authentication check for /api/login and static assets
    if request.path == '/api/login' or request.path.startswith('/static/'):
        return
    # If session is unauthorized
    if not session.get('authenticated'):
        return jsonify({"success": False, "authenticated": False, "message": "Unauthorized"}), 401

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    if not data or 'pin' not in data:
        return jsonify({"success": False, "message": "Missing PIN"}), 400
        
    user_pin = str(data['pin']).strip()
    if user_pin == app.config['ACCESS_PIN']:
        session['authenticated'] = True
        logging.info(f"Authorized login request from IP: {request.remote_addr}")
        return jsonify({"success": True, "message": "Authenticated successfully!"})
    
    logging.warning(f"Invalid access PIN attempt from IP: {request.remote_addr}")
    return jsonify({"success": False, "message": "Invalid PIN"}), 401

@app.route('/api/overclock', methods=['POST'])
def save_overclock():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON payload"}), 400
        
    brand = data.get("brand", "").upper()
    gpu_index = int(data.get("index", 0))
    
    if brand not in ["NVIDIA", "AMD"]:
        return jsonify({"success": False, "message": "Invalid brand specification"}), 400

    # Strict Shell-Injection checks
    for key, val in data.items():
        if key not in ["brand", "index"]:
            if not is_safe_parameter_value(val):
                logging.warning(f"Security Alert: Blocked shell injection signature on parameter {key}='{val}' from {request.remote_addr}")
                return jsonify({"success": False, "message": f"Security Alert: Malicious character detected inside value '{val}'"}), 400

    # Backup prior configs before editing
    backup_configs()
        
    if brand == "NVIDIA":
        filepath = get_nvidia_oc_path()
        config = parse_shell_config(filepath)
        
        core = config.get("CORE", "").split()
        mem = config.get("MEM", "").split()
        pl = config.get("PL", "").split()
        fan = config.get("FAN", "").split()
        
        max_idx = max(3, gpu_index)
        core += ["0"] * (max_idx + 1 - len(core))
        mem += ["0"] * (max_idx + 1 - len(mem))
        pl += ["0"] * (max_idx + 1 - len(pl))
        fan += ["0"] * (max_idx + 1 - len(fan))
        
        if "core" in data:
            core[gpu_index] = str(data["core"])
        if "mem" in data:
            mem[gpu_index] = str(data["mem"])
        if "pl" in data:
            pl[gpu_index] = str(data["pl"])
        if "fan" in data:
            fan[gpu_index] = str(data["fan"])
            
        config["CORE"] = " ".join(core)
        config["MEM"] = " ".join(mem)
        config["PL"] = " ".join(pl)
        config["FAN"] = " ".join(fan)
        
        write_shell_config(filepath, config)
        logging.info(f"NVIDIA GPU {gpu_index} parameters updated: Core={data.get('core')}, Mem={data.get('mem')}, PL={data.get('pl')}, Fan={data.get('fan')}")
        
        if HAS_HIVEOS:
            stdout, stderr, code = run_command("sudo /hive/sbin/nvidia-oc")
            if code != 0:
                logging.error(f"NVIDIA OC script failed: {stderr}")
                return jsonify({"success": False, "message": f"NVIDIA OC Script execution failed: {stderr}"})
        
    elif brand == "AMD":
        filepath = get_amd_oc_path()
        config = parse_shell_config(filepath)
        
        fields = ["CORE", "MEM", "VDD", "VDDCI", "MVDD", "FAN", "PL", "DPM", "REF"]
        parsed_fields = {}
        for fld in fields:
            parsed_fields[fld] = config.get(fld, "").split()
            parsed_fields[fld] += ["0"] * (gpu_index + 1 - len(parsed_fields[fld]))
            
        for key in fields:
            payload_key = key.lower()
            if payload_key in data:
                parsed_fields[key][gpu_index] = str(data[payload_key])
                
        for key in fields:
            config[key] = " ".join(parsed_fields[key])
            
        write_shell_config(filepath, config)
        logging.info(f"AMD GPU {gpu_index} parameters updated: {config}")
        
        if HAS_HIVEOS:
            stdout, stderr, code = run_command("sudo /hive/sbin/amd-oc")
            if code != 0:
                logging.error(f"AMD OC script failed: {stderr}")
                return jsonify({"success": False, "message": f"AMD OC Script execution failed: {stderr}"})
                
    return jsonify({"success": True, "message": f"Overclock parameters successfully saved and applied to {brand} GPU {gpu_index}!"})

@app.route('/api/revert', methods=['POST'])
def revert_overclock():
    try:
        nv_path = get_nvidia_oc_path()
        nv_bak = nv_path + ".bak"
        amd_path = get_amd_oc_path()
        amd_bak = amd_path + ".bak"

        if not os.path.exists(nv_bak) and not os.path.exists(amd_bak):
            return jsonify({"success": False, "message": "No stable backups found to restore."}), 404
            
        with config_lock:
            if os.path.exists(nv_bak):
                shutil.copy2(nv_bak, nv_path)
            if os.path.exists(amd_bak):
                shutil.copy2(amd_bak, amd_path)
                
        # Apply configurations in system
        if HAS_HIVEOS:
            if os.path.exists(nv_bak):
                run_command("sudo /hive/sbin/nvidia-oc")
            if os.path.exists(amd_bak):
                run_command("sudo /hive/sbin/amd-oc")
                
        logging.info(f"Configurations successfully reverted by request from {request.remote_addr}")
        return jsonify({"success": True, "message": "Overclock settings reverted to previous configuration!"})
    except Exception as e:
        logging.error(f"Failed to revert configuration: {e}")
        return jsonify({"success": False, "message": f"Failed to restore configs: {str(e)}"}), 500

@app.route('/api/stats')
def api_stats():
    return jsonify({
        "system": get_system_stats(),
        "gpus": get_gpu_stats(),
        "overclocks": get_overclocks_formatted()
    })

@app.route('/')
def dashboard():
    # Render main HTML layout; authentication is managed asynchronously via JS
    return render_template('index.html')

if __name__ == '__main__':
    init_mock_configs()
    app.config['ACCESS_PIN'] = load_or_generate_pin()
    
    local_ip = get_local_ip()
    port = 1337
    
    # Check gevent/waitress production servers
    try:
        from waitress import serve
        USE_WAITRESS = True
    except ImportError:
        USE_WAITRESS = False

    print("\n" + "="*50)
    print("      HIVEOS LOCAL GPU DASHBOARD (PORT 1337)")
    print("="*50)
    if not HAS_HIVEOS:
        print(" -> STATUS: Running in DEMO MODE (Non-HiveOS host detected)")
        print(" -> MOCK FILES: Settings generated in script directory")
    else:
        print(" -> STATUS: Running in PRODUCTION MODE (HiveOS host detected)")
        print(" -> CONFIGS: Reading/Writing from /hive-config/")
    print(f" -> ACCESS PIN: {app.config['ACCESS_PIN']}")
    print(f" -> DASHBOARD ADDRESS: http://{local_ip}:{port}")
    print("="*50 + "\n")
    
    if USE_WAITRESS:
        logging.info(f"Starting Waitress production WSGI server on http://{local_ip}:{port}")
        serve(app, host='0.0.0.0', port=port, threads=4)
    else:
        logging.warning("Waitress package not found. Falling back to Flask built-in development server.")
        app.run(host='0.0.0.0', port=port, debug=False)
