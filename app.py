import os
import re
import socket
import subprocess
import platform
import shutil
import logging
import threading
import random
import time
import urllib.request
from flask import Flask, jsonify, request, render_template, session

app = Flask(__name__)
# Secure randomly-generated key for session management
app.secret_key = os.urandom(24)

# Constants and Configuration Paths
HIVE_CONFIG_DIR = "/hive-config"
RIG_CONF_PATH = os.path.join(HIVE_CONFIG_DIR, "rig.conf")
NVIDIA_OC_CONF = os.path.join(HIVE_CONFIG_DIR, "nvidia-oc.conf")
AMD_OC_CONF = os.path.join(HIVE_CONFIG_DIR, "amd-oc.conf")
WALLET_CONF_PATH = os.path.join(HIVE_CONFIG_DIR, "wallet.conf")
PIN_PATH = os.path.join(HIVE_CONFIG_DIR, "dashboard.key")
AUTOFAN_CONF = os.path.join(HIVE_CONFIG_DIR, "autofan.conf")
PRESETS_DIR = os.path.join(HIVE_CONFIG_DIR, "presets")

# Local Dashboard Release Version
VERSION = "1.0.4"

# Verify environments
IS_LINUX = platform.system() == "Linux"
HAS_HIVEOS = IS_LINUX and os.path.exists(HIVE_CONFIG_DIR)

# Thread safety lock for files access
config_lock = threading.Lock()

# IP failed logins tracker for rate-limiting
failed_login_attempts = {}

# Setup Structured Production Logging
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
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

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
            os.chmod(PIN_PATH, 0o600) # Read/write by root only
            logging.info(f"Generated new dashboard access PIN: {pin}")
        except Exception as e:
            logging.error(f"Failed to write access PIN: {e}")
        return pin

# Parse shell-like config files with locking
def parse_shell_config(filepath):
    config = {}
    
    # Enforce strict path prefix validation to mitigate CodeQL Path Traversal alerts
    filepath = os.path.abspath(filepath)
    allowed_base = os.path.abspath(HIVE_CONFIG_DIR)
    if not filepath.startswith(allowed_base + os.sep) and filepath != allowed_base:
        logging.error(f"Security Alert: Blocked unauthorized config file parse attempt: {filepath}")
        return config

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
    # Enforce strict path prefix validation to mitigate CodeQL Path Traversal alerts
    filepath = os.path.abspath(filepath)
    allowed_base = os.path.abspath(HIVE_CONFIG_DIR)
    if not filepath.startswith(allowed_base + os.sep) and filepath != allowed_base:
        logging.error(f"Security Alert: Blocked unauthorized config file write attempt: {filepath}")
        return False

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
    return re.match(r'^^[\-\+]?[0-9\s]+$$', val_str) is not None

# Overclock Parameters range check validation
def validate_overclock_ranges(brand, data):
    try:
        if brand == "NVIDIA":
            if "core" in data and data["core"] != "":
                val = int(data["core"])
                if val > 500:
                    if not (500 <= val <= 3000):
                        return False, "NVIDIA locked core clock must be between 500 and 3000 MHz."
                else:
                    if not (-1000 <= val <= 1000):
                        return False, "NVIDIA core clock offset must be between -1000 and 1000 MHz."
                        
            if "mem" in data and data["mem"] != "":
                val = int(data["mem"])
                if not (-2000 <= val <= 4000):
                    return False, "NVIDIA memory clock offset must be between -2000 and 4000 MHz."
                    
            if "pl" in data and data["pl"] != "":
                val = int(data["pl"])
                if not (0 <= val <= 600):
                    return False, "NVIDIA power limit must be between 0 and 600 Watts."
                    
            if "fan" in data and data["fan"] != "":
                val = int(data["fan"])
                if not (0 <= val <= 100):
                    return False, "NVIDIA fan speed must be between 0 and 100%."
                    
        elif brand == "AMD":
            if "core" in data and data["core"] != "":
                val = int(data["core"])
                if not (0 <= val <= 3000):
                    return False, "AMD core clock must be between 0 and 3000 MHz."
                    
            if "mem" in data and data["mem"] != "":
                val = int(data["mem"])
                if not (0 <= val <= 3000):
                    return False, "AMD memory clock must be between 0 and 3000 MHz."
                    
            if "vdd" in data and data["vdd"] != "":
                val = int(data["vdd"])
                if not (0 <= val <= 1500):
                    return False, "AMD core voltage (VDD) must be between 0 and 1500 mV."
                    
            if "vddci" in data and data["vddci"] != "":
                val = int(data["vddci"])
                if not (0 <= val <= 1500):
                    return False, "AMD VDDCI voltage must be between 0 and 1500 mV."
                    
            if "mvdd" in data and data["mvdd"] != "":
                val = int(data["mvdd"])
                if not (0 <= val <= 2000):
                    return False, "AMD memory voltage (MVDD) must be between 0 and 2000 mV."
                    
            if "fan" in data and data["fan"] != "":
                val = int(data["fan"])
                if not (0 <= val <= 100):
                    return False, "AMD fan speed must be between 0 and 100%."
                    
            if "pl" in data and data["pl"] != "":
                val = int(data["pl"])
                if not (0 <= val <= 500):
                    return False, "AMD power limit must be between 0 and 500 Watts."
                    
            if "dpm" in data and data["dpm"] != "":
                val = int(data["dpm"])
                if not (0 <= val <= 7):
                    return False, "AMD DPM state must be between 0 and 7."
                    
            if "ref" in data and data["ref"] != "":
                val = int(data["ref"])
                if not (0 <= val <= 100):
                    return False, "AMD memory refresh index (REF) must be between 0 and 100."
                    
        return True, ""
    except ValueError:
        return False, "Overclock parameters must be valid integers."

# Create backup files of current config files
def backup_configs():
    try:
        if os.path.exists(NVIDIA_OC_CONF):
            shutil.copy2(NVIDIA_OC_CONF, NVIDIA_OC_CONF + ".bak")
        if os.path.exists(AMD_OC_CONF):
            shutil.copy2(AMD_OC_CONF, AMD_OC_CONF + ".bak")
        return True
    except Exception as e:
        logging.error(f"Failed to create backups of configurations: {e}")
        return False

# CPU Mining Statistics Gatherers
def get_cpu_model():
    if IS_LINUX:
        try:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if line.strip().startswith('model name'):
                        return line.split(':')[1].strip()
        except Exception as e:
            logging.error(f"Failed to parse /proc/cpuinfo: {e}")
    return "Unknown CPU"

def get_cpu_temp():
    if IS_LINUX:
        paths = [
            "/sys/class/thermal/thermal_zone0/temp",
            "/sys/class/hwmon/hwmon0/temp1_input",
            "/sys/class/hwmon/hwmon1/temp1_input"
        ]
        for p in paths:
            if os.path.exists(p):
                try:
                    with open(p, 'r') as f:
                        temp = int(f.read().strip())
                        if temp > 1000:
                            temp = int(temp / 1000)
                        return temp
                except Exception:
                    pass
    return 0

def check_hugepages_status():
    if IS_LINUX:
        try:
            with open('/proc/meminfo', 'r') as f:
                content = f.read()
            match = re.search(r'HugePages_Total:\s+(\d+)', content)
            if match and int(match.group(1)) > 0:
                return True
        except Exception:
            pass
    return False

def get_xmrig_hashrate():
    log_path = "/var/log/miner/xmrig/lastrun_noappend.log"
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r') as f:
                lines = f.readlines()[-50:]
            for line in reversed(lines):
                match = re.search(r'speed \S+ \s*([0-9\.]+)\s+([0-9\.]+)', line)
                if match:
                    return float(match.group(1))
        except Exception:
            pass
    return 0.0

# System stats query
def get_system_stats():
    stats = {
        "hostname": socket.gethostname(),
        "local_ip": get_local_ip(),
        "uptime": "Unknown",
        "cpu_load": [0.0, 0.0, 0.0],
        "ram_used_pct": 0.0,
        "ram_total_gb": 0.0,
        "rig_id": "Offline",
        "farm_hash": "Offline",
        "hive_version": "Local-1.0",
        "active_miner": "None",
        "dashboard_version": VERSION,
        "cpu": {
            "model": get_cpu_model(),
            "temp": get_cpu_temp(),
            "hugepages": check_hugepages_status(),
            "hashrate": get_xmrig_hashrate()
        }
    }

    rig_conf = parse_shell_config(RIG_CONF_PATH)
    stats["rig_id"] = rig_conf.get("RIG_ID", "Not Found")
    stats["farm_hash"] = rig_conf.get("FARM_HASH", "Not Found")
    stats["hive_version"] = rig_conf.get("HIVE_VERSION", "Not Found")
    stats["active_miner"] = rig_conf.get("MINER", "None")

    wallet_conf = parse_shell_config(WALLET_CONF_PATH)
    stats["coin"] = wallet_conf.get("COIN", "None")

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
    
    if HAS_HIVEOS or IS_LINUX:
        stdout, stderr, code = run_command("nvidia-smi --query-gpu=index,name,temperature.gpu,fan.speed,power.draw,utilization.gpu,clocks.current.graphics,clocks.current.memory,power.limit --format=csv,noheader,nounits")
        if code == 0 and stdout:
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
                        "hashrate": 0.0
                    })

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
                            "power_limit": 0.0,
                            "utilization": 0,
                            "core_clock": 0,
                            "mem_clock": 0,
                            "hashrate": 0.0
                        })
                        amd_idx += 1
                    except Exception as e:
                        logging.error(f"Error reading AMD sysfs indices: {e}")

    return gpus

# Read configs formatted
def get_overclocks_formatted():
    nv_data = parse_shell_config(NVIDIA_OC_CONF)
    amd_data = parse_shell_config(AMD_OC_CONF)
    
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

# Require authentication and CSRF token validations for all endpoints
@app.before_request
def require_auth():
    if request.path in ['/', '/api/login'] or request.path.startswith('/static/'):
        return
    if not session.get('authenticated'):
        return jsonify({"success": False, "authenticated": False, "message": "Unauthorized"}), 401
        
    # Enforce Anti-CSRF on all POST write actions
    if request.method == 'POST':
        token = request.headers.get('X-CSRF-Token')
        expected = session.get('csrf_token')
        if not token or not expected or token != expected:
            logging.warning(f"CSRF Alert: Invalid or missing token from IP {request.remote_addr}")
            return jsonify({"success": False, "message": "CSRF verification failed."}), 403

@app.route('/api/login', methods=['POST'])
def api_login():
    ip = request.remote_addr
    now = time.time()
    
    # Check if currently locked out
    if ip in failed_login_attempts:
        record = failed_login_attempts[ip]
        if record["blocked_until"] > now:
            remaining = int(record["blocked_until"] - now)
            logging.warning(f"Blocked login attempt from locked-out IP {ip}. Remaining lockout: {remaining}s")
            return jsonify({"success": False, "message": f"Too many failed attempts. Try again in {remaining} seconds."}), 429
            
    data = request.get_json()
    if not data or 'pin' not in data:
        return jsonify({"success": False, "message": "Missing PIN"}), 400
        
    user_pin = str(data['pin']).strip()
    if user_pin == app.config['ACCESS_PIN']:
        # Reset failure record
        if ip in failed_login_attempts:
            del failed_login_attempts[ip]
            
        session['authenticated'] = True
        # Generate CSRF token
        csrf_token = os.urandom(16).hex()
        session['csrf_token'] = csrf_token
        
        logging.info(f"Authorized login request from IP: {ip}")
        return jsonify({"success": True, "message": "Authenticated successfully!", "csrf_token": csrf_token})
    
    # Log failure and increment counters
    if ip not in failed_login_attempts:
        failed_login_attempts[ip] = {"count": 1, "blocked_until": 0.0}
    else:
        failed_login_attempts[ip]["count"] += 1
        
    record = failed_login_attempts[ip]
    if record["count"] >= 5:
        record["blocked_until"] = now + 900.0  # 15 minutes lockout
        logging.warning(f"IP {ip} locked out for 15 minutes due to 5 failed attempts")
        return jsonify({"success": False, "message": "Too many failed attempts. Locked out for 15 minutes."}), 429
        
    logging.warning(f"Invalid access PIN attempt {record['count']}/5 from IP: {ip}")
    return jsonify({"success": False, "message": f"Invalid PIN. {5 - record['count']} attempts remaining."}), 401

@app.route('/api/overclock', methods=['POST'])
def save_overclock():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON payload"}), 400
        
    brand = data.get("brand", "").upper()
    try:
        gpu_index = int(data.get("index", 0))
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "GPU index must be an integer."}), 400
        
    if not (0 <= gpu_index < 64):
        return jsonify({"success": False, "message": "GPU index out of acceptable bounds (0-63)."}), 400
    
    if brand not in ["NVIDIA", "AMD"]:
        return jsonify({"success": False, "message": "Invalid brand specification"}), 400

    # 1. Strict Shell-Injection checks
    for key, val in data.items():
        if key not in ["brand", "index"]:
            if not is_safe_parameter_value(val):
                logging.warning(f"Security Alert: Blocked shell injection signature on parameter {key}='{val}' from {request.remote_addr}")
                return jsonify({"success": False, "message": f"Security Alert: Malicious character detected inside value '{val}'"}), 400

    # 2. Clamping bounds check validation
    is_valid, err_msg = validate_overclock_ranges(brand, data)
    if not is_valid:
        logging.warning(f"Overclock range validation failed: {err_msg} from IP {request.remote_addr}")
        return jsonify({"success": False, "message": err_msg}), 400

    # Backup prior configs before editing
    backup_configs()
        
    if brand == "NVIDIA":
        filepath = NVIDIA_OC_CONF
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
        
        stdout, stderr, code = run_command("sudo /hive/sbin/nvidia-oc")
        if code != 0:
            logging.error(f"NVIDIA OC script failed: {stderr}")
            return jsonify({"success": False, "message": "NVIDIA overclock script failed to apply settings."})
        
    elif brand == "AMD":
        filepath = AMD_OC_CONF
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
        
        stdout, stderr, code = run_command("sudo /hive/sbin/amd-oc")
        if code != 0:
            logging.error(f"AMD OC script failed: {stderr}")
            return jsonify({"success": False, "message": "AMD overclock script failed to apply settings."})
                
    return jsonify({"success": True, "message": f"Overclock parameters successfully saved and applied to {brand} GPU {gpu_index}!"})

@app.route('/api/revert', methods=['POST'])
def revert_overclock():
    try:
        nv_bak = NVIDIA_OC_CONF + ".bak"
        amd_bak = AMD_OC_CONF + ".bak"

        if not os.path.exists(nv_bak) and not os.path.exists(amd_bak):
            return jsonify({"success": False, "message": "No stable backups found to restore."}), 404
            
        with config_lock:
            if os.path.exists(nv_bak):
                shutil.copy2(nv_bak, NVIDIA_OC_CONF)
            if os.path.exists(amd_bak):
                shutil.copy2(amd_bak, AMD_OC_CONF)
                
        if os.path.exists(nv_bak):
            run_command("sudo /hive/sbin/nvidia-oc")
        if os.path.exists(amd_bak):
            run_command("sudo /hive/sbin/amd-oc")
                     
        logging.info(f"Configurations successfully reverted by request from {request.remote_addr}")
        return jsonify({"success": True, "message": "Overclock settings reverted to previous configuration!"})
    except Exception as e:
        logging.error(f"Failed to revert configuration: {e}")
        return jsonify({"success": False, "message": "An internal error occurred while trying to restore configurations."}), 500

@app.route('/api/hugepages', methods=['POST'])
def toggle_hugepages():
    data = request.get_json()
    enable = data.get("enable", True) if data else True
        
    action = "enable" if enable else "disable"
    cmd = f"sudo /hive/bin/hugepages {action}"
    stdout, stderr, code = run_command(cmd)
    
    if code == 0:
        msg = f"Huge Pages successfully {action}d!"
        logging.info(msg)
        return jsonify({"success": True, "message": msg})
    else:
        logging.error(f"Failed to configure Huge Pages: {stderr}")
        return jsonify({"success": False, "message": "Failed to configure System Huge Pages."}), 500

@app.route('/api/miner/control', methods=['POST'])
def miner_control():
    data = request.get_json()
    if not data or 'action' not in data:
        return jsonify({"success": False, "message": "Missing action parameter"}), 400
        
    action = str(data['action']).strip().lower()
    if action not in ["start", "stop", "restart"]:
        return jsonify({"success": False, "message": "Invalid action parameter. Must be start, stop, or restart."}), 400
        
    logging.info(f"Miner control request: '{action}' received from IP: {request.remote_addr}")
    
    if action == "start":
        stdout, stderr, code = run_command("sudo /hive/bin/miner start")
    elif action == "stop":
        stdout, stderr, code = run_command("sudo /hive/bin/miner stop")
    elif action == "restart":
        stdout, stderr, code = run_command("sudo /hive/bin/miner stop && sudo /hive/bin/miner start")
        
    if code == 0:
        msg = f"Miner successfully {action}ed!"
        logging.info(msg)
        return jsonify({"success": True, "message": msg})
    else:
        logging.error(f"Miner control command failed: {stderr}")
        return jsonify({"success": False, "message": "Miner command failed to execute."}), 500

# 1. System Power Routes (Reboot / Shutdown)
@app.route('/api/system/reboot', methods=['POST'])
def system_reboot():
    logging.info(f"System reboot requested by IP: {request.remote_addr}")
    cmd = 'nohup bash -c "sleep 1.5 && sudo /hive/sbin/sreboot" > /dev/null 2>&1 &'
    subprocess.Popen(cmd, shell=True)
    return jsonify({"success": True, "message": "Reboot command initiated. Rig will restart shortly."})

@app.route('/api/system/shutdown', methods=['POST'])
def system_shutdown():
    logging.info(f"System shutdown requested by IP: {request.remote_addr}")
    cmd = 'nohup bash -c "sleep 1.5 && sudo /hive/sbin/sreboot shutdown" > /dev/null 2>&1 &'
    subprocess.Popen(cmd, shell=True)
    return jsonify({"success": True, "message": "Shutdown command initiated. Rig will power down shortly."})

# 2. Miner Console Log Streamer
@app.route('/api/miner/log', methods=['GET'])
def get_miner_log():
    rig_conf = parse_shell_config(RIG_CONF_PATH)
    miner = rig_conf.get("MINER", "").strip().lower()
    if not miner or miner == "none":
        return jsonify({"success": False, "message": "No active miner is configured on this rig."}), 404
        
    log_candidates = [
        f"/var/log/miner/{miner}/{miner}.log",
        f"/var/log/miner/{miner}/lastrun_noappend.log",
        f"/var/log/miner/{miner}/lastrun.log",
    ]
    
    log_content = ""
    found_path = None
    allowed_base = os.path.abspath("/var/log/miner")
    for p in log_candidates:
        p_abs = os.path.abspath(p)
        # Verify candidate log resides strictly inside allowed log folder path to satisfy CodeQL
        if p_abs.startswith(allowed_base + os.sep):
            if os.path.exists(p_abs):
                found_path = p_abs
                break
            
    if found_path:
        try:
            with open(found_path, 'r', errors='ignore') as f:
                lines = f.readlines()[-150:]
                log_content = "".join(lines)
        except Exception as e:
            logging.error(f"Error reading miner log {found_path}: {e}")
            return jsonify({"success": False, "message": "Failed to read miner log file."}), 500
    else:
        return jsonify({"success": False, "message": f"Log file for miner '{miner}' not found. Verify miner is running."}), 404
        
    return jsonify({"success": True, "miner": miner, "log": log_content})

# 3. Watchdog Config Management
@app.route('/api/watchdog', methods=['GET', 'POST'])
def handle_watchdog():
    if request.method == 'GET':
        rig_conf = parse_shell_config(RIG_CONF_PATH)
        return jsonify({
            "success": True,
            "wd_enabled": rig_conf.get("WD_ENABLED", "0"),
            "wd_min_hashrate": rig_conf.get("WD_MIN_HASHRATE", "0")
        })
        
    # POST
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Invalid payload"}), 400
        
    enabled = str(data.get("wd_enabled", "0")).strip()
    min_hashrate = str(data.get("wd_min_hashrate", "0")).strip()
    
    if enabled not in ["0", "1"]:
        return jsonify({"success": False, "message": "wd_enabled must be 0 or 1."}), 400
    if not re.match(r'^[0-9\.]+$', min_hashrate):
        return jsonify({"success": False, "message": "Min hashrate must be a valid number."}), 400
        
    rig_conf = parse_shell_config(RIG_CONF_PATH)
    rig_conf["WD_ENABLED"] = enabled
    rig_conf["WD_MIN_HASHRATE"] = min_hashrate
    
    if write_shell_config(RIG_CONF_PATH, rig_conf):
        logging.info(f"Watchdog settings updated by IP: {request.remote_addr} (Enabled={enabled}, Min={min_hashrate})")
        run_command("sudo /hive/bin/wd restart")
        return jsonify({"success": True, "message": "Watchdog settings saved and daemon restarted!"})
    else:
        return jsonify({"success": False, "message": "Failed to write watchdog settings to rig.conf."}), 500

# 4. Autofan Settings Config
@app.route('/api/autofan', methods=['GET', 'POST'])
def handle_autofan():
    if request.method == 'GET':
        config = parse_shell_config(AUTOFAN_CONF)
        return jsonify({
            "success": True,
            "enabled": config.get("ENABLED", "0"),
            "target_temp": config.get("TARGET_TEMP", "60"),
            "target_mem_temp": config.get("TARGET_MEM_TEMP", "80"),
            "min_fan": config.get("MIN_FAN", "30"),
            "max_fan": config.get("MAX_FAN", "100"),
            "critical_temp": config.get("CRITICAL_TEMP", "85")
        })
        
    # POST
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Invalid payload"}), 400
        
    enabled = str(data.get("enabled", "0")).strip()
    target_temp = str(data.get("target_temp", "60")).strip()
    target_mem_temp = str(data.get("target_mem_temp", "80")).strip()
    min_fan = str(data.get("min_fan", "30")).strip()
    max_fan = str(data.get("max_fan", "100")).strip()
    critical_temp = str(data.get("critical_temp", "85")).strip()
    
    for val in [enabled, target_temp, target_mem_temp, min_fan, max_fan, critical_temp]:
        if not val.isdigit():
            return jsonify({"success": False, "message": "All autofan values must be integers."}), 400
            
    if enabled not in ["0", "1"]:
        return jsonify({"success": False, "message": "enabled must be 0 or 1."}), 400
    if not (30 <= int(target_temp) <= 90):
        return jsonify({"success": False, "message": "Target core temperature must be between 30 and 90 C."}), 400
    if not (40 <= int(target_mem_temp) <= 110):
        return jsonify({"success": False, "message": "Target memory temperature must be between 40 and 110 C."}), 400
    if not (0 <= int(min_fan) <= 100) or not (0 <= int(max_fan) <= 100):
        return jsonify({"success": False, "message": "Fan speed limits must be between 0 and 100%."}), 400
    if int(min_fan) > int(max_fan):
        return jsonify({"success": False, "message": "Minimum fan speed cannot be greater than maximum fan speed."}), 400
    if not (50 <= int(critical_temp) <= 95):
        return jsonify({"success": False, "message": "Critical temperature must be between 50 and 95 C."}), 400
        
    config = {
        "ENABLED": enabled,
        "TARGET_TEMP": target_temp,
        "TARGET_MEM_TEMP": target_mem_temp,
        "MIN_FAN": min_fan,
        "MAX_FAN": max_fan,
        "CRITICAL_TEMP": critical_temp,
        "CRITICAL_TEMP_ACTION": "reboot"
    }
    
    if write_shell_config(AUTOFAN_CONF, config):
        logging.info(f"Autofan configuration updated by IP: {request.remote_addr}")
        run_command("sudo /hive/bin/autofan restart")
        return jsonify({"success": True, "message": "Autofan settings saved and service restarted!"})
    else:
        return jsonify({"success": False, "message": "Failed to save autofan.conf"}), 500

# 5. Local Preset Profile Swappers
@app.route('/api/presets', methods=['GET'])
def list_presets():
    presets = []
    if os.path.exists(PRESETS_DIR):
        try:
            presets = [d for d in os.listdir(PRESETS_DIR) if os.path.isdir(os.path.join(PRESETS_DIR, d))]
        except Exception as e:
            logging.error(f"Failed to list presets directory: {e}")
    return jsonify({"success": True, "presets": sorted(presets)})

@app.route('/api/presets/save', methods=['POST'])
def save_preset():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({"success": False, "message": "Missing preset name"}), 400
        
    name = str(data['name']).strip()
    if not re.match(r'^[A-Za-z0-9_\-\s]+$', name):
        return jsonify({"success": False, "message": "Invalid preset name. Use alphanumeric characters and spaces only."}), 400
        
    # Enforce strict path prefix containment validation to block CodeQL Path Traversal warnings
    presets_dir_abs = os.path.abspath(PRESETS_DIR)
    preset_path = os.path.abspath(os.path.join(presets_dir_abs, name))
    if not preset_path.startswith(presets_dir_abs + os.sep) and preset_path != presets_dir_abs:
        logging.warning(f"Security Alert: Blocked path containment escape in save preset '{name}' from IP {request.remote_addr}")
        return jsonify({"success": False, "message": "Invalid preset name path configuration."}), 400
    
    try:
        with config_lock:
            if not os.path.exists(preset_path):
                os.makedirs(preset_path, exist_ok=True)
                
            if os.path.exists(WALLET_CONF_PATH):
                shutil.copy2(WALLET_CONF_PATH, os.path.join(preset_path, "wallet.conf"))
            if os.path.exists(os.path.join(HIVE_CONFIG_DIR, "miner.conf")):
                shutil.copy2(os.path.join(HIVE_CONFIG_DIR, "miner.conf"), os.path.join(preset_path, "miner.conf"))
                
            rig_conf = parse_shell_config(RIG_CONF_PATH)
            write_shell_config(os.path.join(preset_path, "rig_preset.conf"), {
                "MINER": rig_conf.get("MINER", "none")
            })
            
        logging.info(f"Preset '{name}' saved successfully by IP: {request.remote_addr}")
        return jsonify({"success": True, "message": f"Preset '{name}' successfully saved!"})
    except Exception as e:
        logging.error(f"Failed to save preset '{name}': {e}")
        return jsonify({"success": False, "message": "Failed to save preset files."}), 500

@app.route('/api/presets/apply', methods=['POST'])
def apply_preset():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({"success": False, "message": "Missing preset name"}), 400
        
    name = str(data['name']).strip()
    if not re.match(r'^[A-Za-z0-9_\-\s]+$', name):
        return jsonify({"success": False, "message": "Invalid preset name."}), 400
        
    # Enforce strict path prefix containment validation to block CodeQL Path Traversal warnings
    presets_dir_abs = os.path.abspath(PRESETS_DIR)
    preset_path = os.path.abspath(os.path.join(presets_dir_abs, name))
    if not preset_path.startswith(presets_dir_abs + os.sep) and preset_path != presets_dir_abs:
        logging.warning(f"Security Alert: Blocked path containment escape in apply preset '{name}' from IP {request.remote_addr}")
        return jsonify({"success": False, "message": "Invalid preset name path configuration."}), 400
        
    if not os.path.exists(preset_path):
        return jsonify({"success": False, "message": f"Preset '{name}' does not exist."}), 404
        
    try:
        with config_lock:
            preset_wallet = os.path.join(preset_path, "wallet.conf")
            preset_miner = os.path.join(preset_path, "miner.conf")
            preset_rig = os.path.join(preset_path, "rig_preset.conf")
            
            if os.path.exists(preset_wallet):
                shutil.copy2(preset_wallet, WALLET_CONF_PATH)
            if os.path.exists(preset_miner):
                shutil.copy2(preset_miner, os.path.join(HIVE_CONFIG_DIR, "miner.conf"))
                
            if os.path.exists(preset_rig):
                p_rig = parse_shell_config(preset_rig)
                if "MINER" in p_rig:
                    rig_conf = parse_shell_config(RIG_CONF_PATH)
                    rig_conf["MINER"] = p_rig["MINER"]
                    write_shell_config(RIG_CONF_PATH, rig_conf)
                    
        logging.info(f"Preset '{name}' applied successfully by IP: {request.remote_addr}. Restarting miner...")
        run_command("sudo /hive/bin/miner stop && sudo /hive/bin/miner start")
        return jsonify({"success": True, "message": f"Preset '{name}' applied successfully! Miner restarting..."})
    except Exception as e:
        logging.error(f"Failed to apply preset '{name}': {e}")
        return jsonify({"success": False, "message": "Failed to restore preset configuration files."}), 500

@app.route('/api/presets/delete', methods=['POST'])
def delete_preset():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({"success": False, "message": "Missing preset name"}), 400
        
    name = str(data['name']).strip()
    if not re.match(r'^[A-Za-z0-9_\-\s]+$', name):
        return jsonify({"success": False, "message": "Invalid preset name."}), 400
        
    # Enforce strict path prefix containment validation to block CodeQL Path Traversal warnings
    presets_dir_abs = os.path.abspath(PRESETS_DIR)
    preset_path = os.path.abspath(os.path.join(presets_dir_abs, name))
    if not preset_path.startswith(presets_dir_abs + os.sep) and preset_path != presets_dir_abs:
        logging.warning(f"Security Alert: Blocked path containment escape in delete preset '{name}' from IP {request.remote_addr}")
        return jsonify({"success": False, "message": "Invalid preset name path configuration."}), 400
        
    if not os.path.exists(preset_path):
        return jsonify({"success": False, "message": "Preset not found."}), 404
        
    try:
        with config_lock:
            shutil.rmtree(preset_path)
            
        logging.info(f"Preset '{name}' deleted successfully by IP: {request.remote_addr}")
        return jsonify({"success": True, "message": f"Preset '{name}' successfully deleted."})
    except Exception as e:
        logging.error(f"Failed to delete preset '{name}': {e}")
        return jsonify({"success": False, "message": "Failed to remove preset files."}), 500

def ping_host(host, count=1, timeout=2):
    """Utility helper pinging a destination IP/Host under Linux environment."""
    cmd = f"ping -c {count} -W {timeout} {host}"
    try:
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return res.returncode == 0
    except Exception:
        return False

def get_local_gateway():
    """Detects default routing gateway IP using route commands."""
    try:
        res = subprocess.run("ip route show | grep default", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0 and res.stdout:
            parts = res.stdout.split()
            if len(parts) >= 3:
                return parts[2]
    except Exception:
        pass
    return "127.0.0.1"

@app.route('/api/diagnostics', methods=['GET'])
def get_diagnostics():
    gateway = get_local_gateway()
    
    # Run diagnostics pings
    gateway_ok = ping_host(gateway)
    internet_ok = ping_host("8.8.8.8")
    hive_api_ok = ping_host("api.hiveon.com")
    
    # DNS check
    dns_ok = False
    try:
        socket.gethostbyname("google.com")
        dns_ok = True
    except Exception:
        pass
        
    # GPU kernel driver logs check
    gpu_logs = "No driver logs detected."
    try:
        res = subprocess.run("dmesg | grep -iE 'nouveau|nvidia|amdgpu|pci|thermal|power' | tail -n 25", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0 and res.stdout:
            gpu_logs = res.stdout
    except Exception as e:
        logging.error(f"Failed to retrieve dmesg driver logs: {e}")
        gpu_logs = "Failed to retrieve driver logs from system kernel."
        
    return jsonify({
        "success": True,
        "gateway_ip": gateway,
        "gateway_ping": "Online" if gateway_ok else "Offline",
        "internet_wan": "Online" if internet_ok else "Offline",
        "dns_resolution": "Working" if dns_ok else "Failed",
        "hiveos_api": "Reachable" if hive_api_ok else "Unreachable",
        "gpu_logs": gpu_logs
    })

@app.route('/api/flightsheet', methods=['GET', 'POST'])
def handle_flightsheet():
    if request.method == 'GET':
        wallet_conf = parse_shell_config(WALLET_CONF_PATH)
        rig_conf = parse_shell_config(RIG_CONF_PATH)
        return jsonify({
            "success": True,
            "coin": wallet_conf.get("COIN", ""),
            "wallet": wallet_conf.get("WAL", ""),
            "pool": wallet_conf.get("POOL_URL", ""),
            "miner": rig_conf.get("MINER", "none")
        })
        
    # POST - Save Flight Sheet
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON payload"}), 400
        
    coin = str(data.get("coin", "")).strip()
    wallet = str(data.get("wallet", "")).strip()
    pool = str(data.get("pool", "")).strip()
    miner = str(data.get("miner", "none")).strip().lower()
    
    # Parameter inputs validation
    if not re.match(r'^[A-Za-z0-9_\-\s]+$', coin):
        return jsonify({"success": False, "message": "Invalid Coin parameter. Use alphanumeric characters only."}), 400
    if not re.match(r'^[A-Za-z0-9_\-\s\.\/\@]+$', wallet):
        return jsonify({"success": False, "message": "Invalid Wallet format."}), 400
    if not re.match(r'^[a-zA-Z0-9\.\-\:\/]+$', pool):
        return jsonify({"success": False, "message": "Invalid Pool URL format."}), 400
        
    whitelisted_miners = [
        "lolminer", "xmrig", "gminer", "rigel", "bzminer", 
        "teamredminer", "hiveon", "srbminer", "wildrig-multi",
        "bminer", "ccminer", "t-rex", "none"
    ]
    if miner not in whitelisted_miners:
        return jsonify({"success": False, "message": "Unsupported miner program choice."}), 400

    # Backup files first
    try:
        if os.path.exists(WALLET_CONF_PATH):
            shutil.copy2(WALLET_CONF_PATH, WALLET_CONF_PATH + ".bak")
        if os.path.exists(RIG_CONF_PATH):
            shutil.copy2(RIG_CONF_PATH, RIG_CONF_PATH + ".bak")
    except Exception as e:
        logging.error(f"Backup configurations failed: {e}")
        
    # Update configurations
    wallet_conf = parse_shell_config(WALLET_CONF_PATH)
    wallet_conf["COIN"] = coin
    wallet_conf["WAL"] = wallet
    wallet_conf["POOL_URL"] = pool
    # Write back
    if not write_shell_config(WALLET_CONF_PATH, wallet_conf):
        return jsonify({"success": False, "message": "Failed to write wallet.conf"}), 500
        
    rig_conf = parse_shell_config(RIG_CONF_PATH)
    rig_conf["MINER"] = miner
    if not write_shell_config(RIG_CONF_PATH, rig_conf):
        return jsonify({"success": False, "message": "Failed to write rig.conf"}), 500
        
    logging.info(f"Emergency Local Flight Sheet updated by IP: {request.remote_addr} (Coin={coin}, Miner={miner})")
    
    # Restart miner to apply settings on the fly
    run_command("sudo /hive/bin/miner stop && sudo /hive/bin/miner start")
    return jsonify({"success": True, "message": "Flight sheet saved successfully! Miner daemon restarting..."})

@app.route('/api/overclock/reset', methods=['POST'])
def reset_overclock():
    # Create backups first
    backup_configs()
    
    nv_stock = {
        "CORE": "",
        "MEM": "",
        "PL": "",
        "FAN": ""
    }
    amd_stock = {
        "CORE": "",
        "MEM": "",
        "VDD": "",
        "VDDCI": "",
        "MVDD": "",
        "FAN": "",
        "PL": "",
        "DPM": "",
        "REF": ""
    }
    
    if write_shell_config(NVIDIA_OC_CONF, nv_stock) and write_shell_config(AMD_OC_CONF, amd_stock):
        logging.info(f"Emergency overclock reset to stock by request from {request.remote_addr}")
        # Apply clean stock settings immediately on hardware
        run_command("sudo /hive/sbin/nvidia-oc")
        run_command("sudo /hive/sbin/amd-oc")
        return jsonify({"success": True, "message": "Emergency reset completed! All overclock profiles reset to safe factory stock limits."})
    else:
        return jsonify({"success": False, "message": "Failed to overwrite overclock configuration files."}), 500

@app.route('/api/services/control', methods=['POST'])
def service_control():
    data = request.get_json()
    if not data or 'service' not in data or 'action' not in data:
        return jsonify({"success": False, "message": "Missing service or action parameter."}), 400
        
    service = str(data['service']).strip().lower()
    action = str(data['action']).strip().lower()
    
    if service not in ["wd", "autofan", "hiveos-local"]:
        return jsonify({"success": False, "message": "Invalid service target."}), 400
    if action not in ["start", "stop", "restart"]:
        return jsonify({"success": False, "message": "Invalid action choice."}), 400
        
    logging.info(f"Service control: '{action}' on '{service}' by IP: {request.remote_addr}")
    
    code = 0
    stderr = ""
    
    if service == "wd":
        if action in ["start", "restart"]:
            stdout, stderr, code = run_command("sudo /hive/bin/wd restart")
        else:
            stdout, stderr, code = run_command("sudo /hive/bin/wd stop")
    elif service == "autofan":
        if action in ["start", "restart"]:
            stdout, stderr, code = run_command("sudo /hive/bin/autofan restart")
        else:
            stdout, stderr, code = run_command("sudo /hive/bin/autofan stop")
    elif service == "hiveos-local":
        if action == "restart":
            cmd = 'nohup bash -c "sleep 1.5 && sudo systemctl restart hiveos-local.service" > /dev/null 2>&1 &'
            subprocess.Popen(cmd, shell=True)
            return jsonify({"success": True, "message": "Logger service restart scheduled."})
        elif action == "stop":
            cmd = 'nohup bash -c "sleep 1.5 && sudo systemctl stop hiveos-local.service" > /dev/null 2>&1 &'
            subprocess.Popen(cmd, shell=True)
            return jsonify({"success": True, "message": "Logger service shutdown scheduled."})
        elif action == "start":
            stdout, stderr, code = run_command("sudo systemctl start hiveos-local.service")
            
    if code == 0:
        return jsonify({"success": True, "message": f"Service '{service}' successfully {action}ed!"})
    else:
        logging.error(f"Service control execution failed on {service}: {stderr}")
        return jsonify({"success": False, "message": "Service command execution failed. Check system logs."}), 500

@app.route('/api/update/check', methods=['GET'])
def check_update():
    try:
        url = "https://raw.githubusercontent.com/y3tiCrypto/hiveos-local/main/version.txt"
        req = urllib.request.Request(url, headers={'User-Agent': 'HiveOS-Local-Dashboard'})
        with urllib.request.urlopen(req, timeout=5) as response:
            remote_ver = response.read().decode('utf-8').strip()
        
        update_available = remote_ver != VERSION
        
        return jsonify({
            "success": True,
            "local_version": VERSION,
            "remote_version": remote_ver,
            "update_available": update_available
        })
    except Exception as e:
        logging.warning(f"Failed to check remote version: {e}")
        return jsonify({
            "success": False,
            "local_version": VERSION,
            "remote_version": "Unknown",
            "update_available": False,
            "error": "Failed to verify version against GitHub."
        })

@app.route('/api/update/pull', methods=['POST'])
def pull_update():
    data = request.get_json()
    if not data or 'pin' not in data:
        return jsonify({"success": False, "message": "Missing PIN verification parameter"}), 400
        
    user_pin = str(data['pin']).strip()
    if user_pin != app.config['ACCESS_PIN']:
        logging.warning(f"Failed update PIN verification attempt from IP: {request.remote_addr}")
        return jsonify({"success": False, "message": "Invalid PIN verification code. Update aborted."}), 401

    logging.info(f"Dashboard update authorized with PIN by IP: {request.remote_addr}")
    cwd = os.getcwd()
    
    # Add safe directory flag
    run_command(f"git config --global --add safe.directory {cwd}")
    
    stdout_f, stderr_f, code_f = run_command("git fetch --all")
    stdout_r, stderr_r, code_r = run_command("git reset --hard origin/main")
    
    if code_r == 0:
        msg = "Update successfully pulled from GitHub! Restarting dashboard service..."
        logging.info(msg)
        cmd = 'nohup bash -c "sleep 1.5 && sudo systemctl restart hiveos-local.service" > /dev/null 2>&1 &'
        subprocess.Popen(cmd, shell=True)
        return jsonify({"success": True, "message": msg})
    else:
        err_msg = f"Failed to pull git update: {stderr_r or stderr_f}"
        logging.error(err_msg)
        return jsonify({"success": False, "message": "Failed to pull dashboard update from GitHub repository."}), 500

@app.route('/api/stats')
def api_stats():
    return jsonify({
        "system": get_system_stats(),
        "gpus": get_gpu_stats(),
        "overclocks": get_overclocks_formatted()
    })

@app.route('/')
def dashboard():
    return render_template('index.html')

if __name__ == '__main__':
    # 2. Strict Platform Locks
    if not IS_LINUX:
        print("\n" + "="*60)
        print("[-] CRITICAL ERROR: THIS DASHBOARD MUST RUN ON LINUX HOSTS.")
        print("    HiveOS requires direct integration with sysfs and native CLI tools.")
        print("="*60 + "\n")
        os._exit(1)
        
    if not os.path.exists(HIVE_CONFIG_DIR):
        print("\n" + "="*60)
        print("[-] CRITICAL ERROR: HIVEOS CONFIG DIRECTORY NOT DETECTED (/hive-config/).")
        print("    This software runs exclusively on live standard HiveOS rig nodes.")
        print("="*60 + "\n")
        os._exit(1)

    # Initialize presets directory
    os.makedirs(PRESETS_DIR, exist_ok=True)

    app.config['ACCESS_PIN'] = load_or_generate_pin()
    
    local_ip = get_local_ip()
    port = 1337
    
    try:
        from waitress import serve
        USE_WAITRESS = True
    except ImportError:
        USE_WAITRESS = False

    print("\n" + "="*60)
    print("      HIVEOS LOCAL GPU DASHBOARD (PORT 1337)")
    print("="*60)
    print(" -> STATUS: Running in PRODUCTION MODE (HiveOS host verified)")
    print(" -> CONFIGS: Reading/Writing from /hive-config/")
    print(f" -> ACCESS PIN: {app.config['ACCESS_PIN']}")
    print(f" -> DASHBOARD ADDRESS: http://{local_ip}:{port}")
    print("="*60 + "\n")
    
    if USE_WAITRESS:
        logging.info(f"Starting Waitress production WSGI server on http://{local_ip}:{port}")
        serve(app, host='0.0.0.0', port=port, threads=4)
    else:
        logging.warning("Waitress package not found. Falling back to Flask built-in development server.")
        app.run(host='0.0.0.0', port=port, debug=False)
