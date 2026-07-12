#!/bin/bash

# Ensure script is run as root
if [ "$EUID" -ne 0 ]; then
  echo "[-] ERROR: Please run this script as root (sudo ./install.sh)"
  exit 1
fi

echo "[+] Starting HiveOS Local Dashboard Installation..."

# Get current script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
echo "[+] Detected installation directory: $DIR"

# 1. Install Dependencies
echo "[+] Checking/Installing Python3 Flask dependency..."
if command -v apt-get &> /dev/null; then
  # Try to install via apt-get first to avoid pip package manager blocks
  apt-get update -y && apt-get install -y python3-flask
else
  # Fallback to python3 -m pip
  python3 -m pip install flask
fi

# Double check if flask is available
python3 -c "import flask" &> /dev/null
if [ $? -ne 0 ]; then
  echo "[-] WARNING: Flask could not be installed automatically via apt. Trying pip..."
  python3 -m pip install flask
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

# 4. Detect IP Address
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
echo -e "\033[0;32m[+] HIVEOS LOCAL DASHBOARD INSTALLED SUCCESSFULLY!\033[0m"
echo -e "=================================================================="
echo -e "The manager is running as a persistent background service."
echo -e "It will start automatically whenever this server boots."
echo -e ""
echo -e "Open the dashboard in any local web browser:"
echo -e "-> \033[1;36mhttp://${LOCAL_IP}:1337\033[0m"
echo -e "==================================================================\n"
