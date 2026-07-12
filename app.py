import os
import re
import socket
import subprocess
import platform
import shutil
import logging
import threading
import random
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

# Local Dashboard Release Version
VERSION = "1.0.0"

# Verify environments
IS_LINUX = platform.system() == "Linux"
HAS_HIVEOS = IS_LINUX and os.path.exists(HIVE_CONFIG_DIR)

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
    return re.match(r'^[\-\+]?[0-9\s]+$', val_str) is not None

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
    
    # 1. NVIDIA telemetry
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
                        "hashrate": 0.0 # live hashrate must be read from miners; setting default
                    })

    # 2. AMD telemetry
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

# Require authentication for all endpoints
@app.before_request
def require_auth():
    if request.path == '/api/login' or request.path.startswith('/static/'):
        return
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
    logging.info(f"Dashboard update requested by IP: {request.remote_addr}")
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
