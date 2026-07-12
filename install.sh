#!/bin/bash

# Ensure script is run as root
if [ "$EUID" -ne 0 ]; then
  echo "[-] ERROR: Please run this script as root (sudo ./install.sh)"
  exit 1
fi

echo "[+] Starting HiveOS Local Dashboard Hardened Installation..."

# Get current script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
echo "[+] Detected installation directory: $DIR"

# 1. Install Dependencies (Flask + Waitress)
echo "[+] Checking/Installing Python3 dependencies (Flask, Waitress)..."
if command -v apt-get &> /dev/null; then
  apt-get update -y && apt-get install -y python3-flask python3-pip
  # Try to install waitress via apt or pip requirements
  apt-get install -y python3-waitress || python3 -m pip install -r "$DIR/requirements.txt"
else
  python3 -m pip install -r "$DIR/requirements.txt"
fi

# Double check dependencies
python3 -c "import flask, waitress" &> /dev/null
if [ $? -ne 0 ]; then
  echo "[+] Attempting force-install of flask/waitress via pip..."
  python3 -m pip install -r "$DIR/requirements.txt"
fi

# 2. Create Systemd Service File
SERVICE_FILE="/etc/systemd/system/hiveos-local.service"
echo "[+] Creating systemd service unit: $SERVICE_FILE"

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=HiveOS Local GPU Manager Dashboard
After=network.target

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=/usr/bin/python3 app.py
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF

# 3. Reload systemd daemon and enable service
echo "[+] Registering and starting background service..."
systemctl daemon-reload
systemctl enable hiveos-local.service
systemctl restart hiveos-local.service

# Wait a brief moment for the service to start and write the PIN key
echo "[+] Initializing security keys..."
sleep 1.5

# 4. Read Access PIN
PIN_KEY_PATH="/hive-config/dashboard.key"
if [ ! -f "$PIN_KEY_PATH" ]; then
  # Fallback to local directory if not running on standard HiveOS directory structure
  PIN_KEY_PATH="$DIR/dashboard.key"
fi

if [ -f "$PIN_KEY_PATH" ]; then
  ACCESS_PIN=$(cat "$PIN_KEY_PATH")
else
  ACCESS_PIN="[ERROR: Key file not found]"
fi

# 5. Detect LAN IP Address
LOCAL_IP=$(python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(('8.8.8.8', 1))
    print(s.getsockname()[0])
except Exception:
    print('127.0.0.1')
finally:
    s.close()
")

echo -e "\n=================================================================="
echo -e "\033[0;32m[+] HIVEOS LOCAL DASHBOARD HARDENED & INSTALLED SUCCESSFULLY!\033[0m"
echo -e "=================================================================="
echo -e "The manager is running as a multithreaded production WSGI service."
echo -e "It will start automatically whenever this rig boots."
echo -e ""
echo -e "Open the dashboard in any local web browser:"
echo -e "-> \033[1;36mhttp://${LOCAL_IP}:1337\033[0m"
echo -e ""
echo -e "\033[1;33m[!] IMPORTANT SECURITY ACCESS PIN:\033[0m"
echo -e "Authorization Key: \033[1;32m${ACCESS_PIN}\033[0m"
echo -e "Please keep this PIN safe. It is required to log into the dashboard."
echo -e "==================================================================\n"
