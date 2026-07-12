import os
import re
import socket
import subprocess
import platform
from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

# Constants and Configuration Paths
HIVE_CONFIG_DIR = "/hive-config"
RIG_CONF_PATH = os.path.join(HIVE_CONFIG_DIR, "rig.conf")
NVIDIA_OC_CONF = os.path.join(HIVE_CONFIG_DIR, "nvidia-oc.conf")
AMD_OC_CONF = os.path.join(HIVE_CONFIG_DIR, "amd-oc.conf")

# Check if running in a real HiveOS Linux environment
IS_LINUX = platform.system() == "Linux"
HAS_HIVEOS = IS_LINUX and os.path.exists(HIVE_CONFIG_DIR)

# Mock files for Demo Mode when not running on HiveOS
MOCK_NVIDIA_OC_CONF = "./mock_nvidia-oc.conf"
MOCK_AMD_OC_CONF = "./mock_amd-oc.conf"
MOCK_RIG_CONF = "./mock_rig.conf"

def get_local_ip():
    """Detects the machine's primary local IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not send actual packets over the network, just queries OS routing
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def get_rig_config_path():
    if HAS_HIVEOS:
        return RIG_CONF_PATH
    return MOCK_RIG_CONF

def get_nvidia_oc_path():
    if HAS_HIVEOS:
        return NVIDIA_OC_CONF
    return MOCK_NVIDIA_OC_CONF

def get_amd_oc_path():
    if HAS_HIVEOS:
        return AMD_OC_CONF
    return MOCK_AMD_OC_CONF

# Initialize mock config files if not exists in Demo Mode
def init_mock_configs():
    if not HAS_HIVEOS:
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

# Parse shell-like config files (e.g. rig.conf, nvidia-oc.conf)
def parse_shell_config(filepath):
    config = {}
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
                    # Strip surrounding quotes if present
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    config[key] = val
    except Exception as e:
        print(f"Error parsing config file {filepath}: {e}")
    return config

# Write shell-like config files
def write_shell_config(filepath, config):
    try:
        with open(filepath, 'w') as f:
            for k, v in config.items():
                f.write(f'{k}="{v}"\n')
        return True
    except Exception as e:
        print(f"Error writing config file {filepath}: {e}")
        return False

# System Metrics gathering
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

    # Rig Config Info
    rig_conf = parse_shell_config(get_rig_config_path())
    stats["rig_id"] = rig_conf.get("RIG_ID", "Not Found")
    stats["farm_hash"] = rig_conf.get("FARM_HASH", "Not Found")
    stats["hive_version"] = rig_conf.get("HIVE_VERSION", "Demo-v0.6")
    stats["active_miner"] = rig_conf.get("MINER", "lolminer")

    # Uptime & CPU Load
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
                # Available memory formula
                mem_used = mem_total - (mem_free + mem_buffers + mem_cached)
                stats["ram_used_pct"] = round((mem_used / mem_total) * 100, 1)
                stats["ram_total_gb"] = round(mem_total / (1024 * 1024), 1)
        except Exception:
            pass
    else:
        # Fallback for Windows/macOS development
        stats["uptime"] = "1h 45m"
        stats["cpu_load"] = [0.45, 0.30, 0.15]
        stats["ram_used_pct"] = 42.5
        stats["ram_total_gb"] = 16.0

    return stats

# Helper to run system command
def run_command(cmd):
    try:
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return res.stdout, res.stderr, res.returncode
    except Exception as e:
        return "", str(e), -1

# Gather GPU Stats (Real or Mocked)
def get_gpu_stats():
    gpus = []
    
    # 1. NVIDIA Discovery
    nvidia_detected = False
    if HAS_HIVEOS or IS_LINUX:
        # Check if nvidia-smi exists
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
                        "hashrate": round(50.0 + (int(parts[6]) % 10) + (int(parts[7]) % 20) / 10.0, 2) # Simulated hashrate based on clocks
                    })

    # 2. AMD Discovery
    amd_detected = False
    if HAS_HIVEOS or IS_LINUX:
        # We check if rocm-smi exists or we look up /sys/class/drm/card*
        # Alternatively, parse the standard amd-info tool output if present
        stdout, stderr, code = run_command("amd-info")
        if code == 0 and stdout:
            amd_detected = True
            # Simple text parsing of amd-info (very simplified block extraction)
            # Typically looks like: GPU0, RX 580, Temp 65C, Fan 55% etc.
            # If amd-info parsing is complex, we will read directly from sysfs below as fallback.
            pass

        # Sysfs Fallback for AMD
        if not amd_detected and os.path.exists("/sys/class/drm"):
            cards = [d for d in os.listdir("/sys/class/drm") if re.match(r'^card\d+$', d)]
            # Filter cards with hardware monitoring (real GPUs, not virtual display cards)
            amd_idx = 0
            for card in sorted(cards):
                hwmon_path = f"/sys/class/drm/{card}/device/hwmon"
                if os.path.exists(hwmon_path):
                    hwmons = os.listdir(hwmon_path)
                    if not hwmons:
                        continue
                    hpath = f"{hwmon_path}/{hwmons[0]}"
                    
                    # Check vendor
                    vendor_path = f"/sys/class/drm/{card}/device/vendor"
                    if os.path.exists(vendor_path):
                        with open(vendor_path, 'r') as f:
                            vendor = f.read().strip()
                        if "0x1002" not in vendor: # AMD Vendor ID is 0x1002
                            continue
                            
                    # Gather AMD GPU stats from Sysfs
                    try:
                        temp = 0
                        if os.path.exists(f"{hpath}/temp1_input"):
                            with open(f"{hpath}/temp1_input", 'r') as f:
                                temp = int(int(f.read().strip()) / 1000)
                        
                        fan = 0
                        if os.path.exists(f"{hpath}/fan1_input"):
                            with open(f"{hpath}/fan1_input", 'r') as f:
                                # Sometimes fan speed is reported as RPM or raw speed, let's try to get percentage
                                # If there's no percent file, we default to a mock percentage based on RPM
                                rpm = int(f.read().strip())
                                fan = min(100, int(rpm / 30)) # Estimate percentage
                        
                        power = 0.0
                        if os.path.exists(f"{hpath}/power1_average"):
                            with open(f"{hpath}/power1_average", 'r') as f:
                                power = round(float(f.read().strip()) / 1000000.0, 1)
                                
                        # Model name
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
                            "power_limit": 150.0, # Default estimate
                            "utilization": 99, # Default active
                            "core_clock": 1200,
                            "mem_clock": 2000,
                            "hashrate": 30.5
                        })
                        amd_idx += 1
                        amd_detected = True
                    except Exception as e:
                        print(f"Error reading AMD card sysfs: {e}")

    # 3. Fallback to Demo Mode (Mock GPUs)
    if not nvidia_detected and not amd_detected:
        # Load from active overclocks to show they apply
        nv_oc = parse_shell_config(get_nvidia_oc_path())
        amd_oc = parse_shell_config(get_amd_oc_path())

        # Mock NVIDIA GPU 0
        nv_core = nv_oc.get("CORE", "0 0").split()
        nv_mem = nv_oc.get("MEM", "0 0").split()
        nv_pl = nv_oc.get("PL", "0 0").split()
        nv_fan = nv_oc.get("FAN", "0 0").split()
        
        # Pad arrays if shorter
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

        # Mock NVIDIA GPU 1
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

        # Mock AMD GPU 0
        amd_core = amd_oc.get("CORE", "0").split()
        amd_mem = amd_oc.get("MEM", "0").split()
        amd_vdd = amd_oc.get("VDD", "0").split()
        amd_fan = amd_oc.get("FAN", "0").split()
        
        amd_core += ["0"]
        amd_mem += ["0"]
        amd_vdd += ["0"]
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

# Read overclock parameters formatted for the frontend
def get_overclocks_formatted():
    # Read NVIDIA Config
    nv_path = get_nvidia_oc_path()
    nv_data = parse_shell_config(nv_path)
    
    # Read AMD Config
    amd_path = get_amd_oc_path()
    amd_data = parse_shell_config(amd_path)
    
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

# Apply Overclocks route
@app.route('/api/overclock', methods=['POST'])
def save_overclock():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON payload"}), 400
        
    brand = data.get("brand", "").upper()
    gpu_index = int(data.get("index", 0))
    
    if brand not in ["NVIDIA", "AMD"]:
        return jsonify({"success": False, "message": "Invalid brand specification"}), 400
        
    if brand == "NVIDIA":
        filepath = get_nvidia_oc_path()
        config = parse_shell_config(filepath)
        
        # Read parameters
        core = config.get("CORE", "").split()
        mem = config.get("MEM", "").split()
        pl = config.get("PL", "").split()
        fan = config.get("FAN", "").split()
        
        # Pad arrays
        max_idx = max(3, gpu_index)
        core += ["0"] * (max_idx + 1 - len(core))
        mem += ["0"] * (max_idx + 1 - len(mem))
        pl += ["0"] * (max_idx + 1 - len(pl))
        fan += ["0"] * (max_idx + 1 - len(fan))
        
        # Update values
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
        
        # If on HiveOS, execute the system script
        if HAS_HIVEOS:
            stdout, stderr, code = run_command("sudo /hive/sbin/nvidia-oc")
            if code != 0:
                return jsonify({"success": False, "message": f"NVIDIA OC Script execution failed: {stderr}"})
        
    elif brand == "AMD":
        filepath = get_amd_oc_path()
        config = parse_shell_config(filepath)
        
        # Read parameters
        fields = ["CORE", "MEM", "VDD", "VDDCI", "MVDD", "FAN", "PL", "DPM", "REF"]
        parsed_fields = {}
        for fld in fields:
            parsed_fields[fld] = config.get(fld, "").split()
            parsed_fields[fld] += ["0"] * (gpu_index + 1 - len(parsed_fields[fld]))
            
        # Update values
        for key in fields:
            payload_key = key.lower()
            if payload_key in data:
                parsed_fields[key][gpu_index] = str(data[payload_key])
                
        for key in fields:
            config[key] = " ".join(parsed_fields[key])
            
        write_shell_config(filepath, config)
        
        # If on HiveOS, execute system script
        if HAS_HIVEOS:
            stdout, stderr, code = run_command("sudo /hive/sbin/amd-oc")
            if code != 0:
                return jsonify({"success": False, "message": f"AMD OC Script execution failed: {stderr}"})
                
    return jsonify({"success": True, "message": f"Overclock parameters successfully saved and applied to {brand} GPU {gpu_index}!"})

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
    # Initialize mock files if in demo mode
    init_mock_configs()
    
    local_ip = get_local_ip()
    port = 1337
    
    print("\n" + "="*50)
    print("      HIVEOS LOCAL GPU DASHBOARD (PORT 1337)")
    print("="*50)
    if not HAS_HIVEOS:
        print(" -> STATUS: Running in DEMO MODE (Non-HiveOS host detected)")
        print(" -> MOCK FILES: Rig and Overclock settings generated locally")
    else:
        print(" -> STATUS: Running in PRODUCTION MODE (HiveOS host detected)")
        print(" -> CONFIGS: Reading from /hive-config/")
    print(f" -> DASHBOARD ADDRESS: http://{local_ip}:{port}")
    print("="*50 + "\n")
    
    app.run(host='0.0.0.0', port=port, debug=False)
