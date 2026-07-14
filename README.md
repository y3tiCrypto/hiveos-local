# HiveOS Local GPU Manager (HiveOS-Local)

A lightweight, local, browser-based emergency diagnostics and GPU overclocking manager designed to run side-by-side on rigs powered by **HiveOS** (https://hiveon.com).

When Hiveon's remote API or central cloud servers experience outages, communication between your mining rig and the main HiveOS dashboard breaks, rendering remote management impossible. **HiveOS-Local** bypasses the cloud entirely, hosting a production-grade, secure, and user-friendly control interface directly from the mining rig's local IP address on port **`1337`**.

---

## Production-Grade Capabilities

This application is hardened for live environments with the following layers:

1. 🔒 **PIN-Protected Authentication**: To prevent unauthorized users on your local network (LAN) from accessing the dashboard and tampering with clock limits or GPU voltages, the API and web UI are secured with a 6-digit access PIN. This PIN is auto-generated during installation and saved securely in `/hive-config/dashboard.key` (only readable by root).
2. 🛡️ **Strict Input Sanitization**: All overclock parameters sent to the server are validated against a strict alphanumeric/character whitelist. Any attempt to inject bash meta-characters (like `;`, `&`, `|`, `$`, or backticks) will trigger a security exception, blocking command injection attacks.
3. 🧵 **Thread-Safe File Syncing**: File writes are synchronized using Python's `threading.Lock()` to prevent file corruption during concurrent operations.
4. ⚙️ **Production WSGI Backend**: Runs on a multithreaded **Waitress WSGI** production server (handling up to 4 concurrent worker threads) instead of the single-threaded Flask development server.
5. 🔄 **Fail-safe Rollback**: A backup copy of the overclock configurations (`nvidia-oc.conf.bak` and `amd-oc.conf.bak`) is created before any parameter updates are saved. Rigs can be instantly rolled back to their last-known stable configuration using the "Revert Settings" button.
6. 📝 **Structured Server Logging**: Critical operations, updates, and authorization failures are written with timestamped severity tags directly to `/var/log/hiveos-local.log` (or local file in Demo Mode).
7. 🌐 **Fleet Manager Integration**: A centralized, Dockerized manager is included under the `fleet-manager/` subdirectory to aggregate statistics, monitor temperatures, check speeds, and proxy commands across all your local mining rig nodes.

---

## Quick Start Installation

Execute these commands inside your HiveOS shell (via SSH, Shellinabox, or local terminal) to install the service:

```bash
# 1. Clone the repository to your local rig
git clone https://github.com/y3tiCrypto/hiveos-local.git

# 2. Navigate to the directory
cd hiveos-local

# 3. Give execution permissions to the installer
chmod +x install.sh

# 4. Run the installer as root
sudo ./install.sh

# 5. Upgrading / Updating
# If you need to pull the latest updates from GitHub and reinstall:
sudo ./install.sh --upgrade

# 6. Uninstallation
# If you want to stop, disable, and clean up the dashboard service:
sudo ./install.sh --uninstall
```

During installation, the script will read dependencies from [requirements.txt](file:///g:/LocalHiveOS/requirements.txt) to check and install the Flask and Waitress packages, register a systemd daemon (`hiveos-local.service`), and start the server on port `1337`.

If you prefer to install packages manually or verify dependencies outside of the shell script, you can run:
```bash
pip3 install -r requirements.txt
```

Once complete, the installer will display the rig's active IP address and the **Access Authorization PIN**. Open any web browser on your local network and navigate to:
```
http://<rig-local-ip>:1337
```
Log in using the displayed 6-digit PIN.

---

## Beginner's Overclocking Guide

Overclocking optimizes the graphics card's hashrate (speed) and reduces power draw (heat). Use the following guidelines to configure settings inside the dashboard:

### NVIDIA GPU Overclocking

1. **Core Clock (Offset vs. Absolute/Locked)**:
   - **Offset Mode**: Enters a relative shift (e.g. `-200` or `+100`). This shifts the entire clock curve.
   - **Locked Core Clock (Recommended)**: Entering any value **above 500** (e.g. `1450` or `1500`) locks the GPU core to that exact frequency. This significantly reduces temperature and power consumption while maintaining maximum hashrate.
2. **Memory Clock Offset**:
   - In Linux (HiveOS), memory clocks are **effectively doubled** compared to Windows. If you use a `+1000` memory offset in Windows, you must enter `2000` in HiveOS.
3. **Power Limit (Watts)**:
   - Limits the maximum power the GPU is allowed to consume. When using a Locked Core Clock, you can set the Power Limit to `0` (or leave it blank), as the locked core speed automatically handles power management.

### AMD GPU Overclocking

1. **Core Clock (MHz) & Core Voltage (mV)**:
   - Unlike Nvidia, AMD requires the absolute target core clock and the exact voltage (e.g. `1150` core clock at `800` mV). Setting the voltage lower reduces power and heat (known as *undervolting*). Modify in tiny steps (5-10 mV at a time).
2. **Memory Clock (MHz)**:
   - Set the absolute memory speed (e.g. `2000` or `2100` MHz).
3. **DPM State**:
   - Dynamic Power Management index (typically values `1` through `7`). Setting a locked state (usually `4` or `5`) forces GPU stability.
4. **MVDD / VDDCI**:
   - Advanced memory bus voltages. If you are unsure, set them to `0` to keep the card's factory default values.

---

## File System Integration

HiveOS-Local interfaces directly with the native HiveOS configurations stored inside the `/hive-config/` directory:

- **/hive-config/rig.conf**: Parsed to display the rig's local designation (Rig ID, Active Miner, and HiveOS version).
- **/hive-config/wallet.conf**: Parsed to extract the active mined coin/cryptocurrency symbol.
- **/hive-config/nvidia-oc.conf**: Spliced when saving NVIDIA overclocks. Contains space-separated parameters mapping to GPU indices (e.g. `CORE="100 120 0"`). After writing, it executes `sudo /hive/sbin/nvidia-oc` to apply parameters immediately.
- **/hive-config/amd-oc.conf**: Spliced when saving AMD overclocks. After writing, it executes `sudo /hive/sbin/amd-oc` to apply changes.
- **/hive-config/dashboard.key**: Stores the 6-digit PIN used for dashboard authorization.

---

## CPU Mining & Tuning Control

For rigs running CPU miners (e.g. **XMRig**), the dashboard provides real-time CPU diagnostics and control:
- **Processor Identification**: Automatically parses and displays the processor name from `/proc/cpuinfo`.
- **Core Temperatures**: Reads core temps from system-level hardware sensors inside `/sys/class/thermal`.
- **Huge Pages Optimization**: Displays VM Huge Pages status. Selecting **"Toggle Huge Pages"** invokes `sudo /hive/bin/hugepages enable|disable` immediately. Enabling Huge Pages is highly recommended for algorithms like RandomX (Monero) to prevent hashrate drop.
- **CPU Hashrate Logging**: Extracts live performance rates directly from the miner log output file at `/var/log/miner/xmrig/lastrun_noappend.log`.

---

## Miner & Rig Operations Management

The dashboard offers advanced local command options inside the dashboard:
- **Miner Actions**: Start, stop, or restart the mining daemon directly.
- **Rig Power Actions**: Gracefully reboot or shutdown the system hardware remotely using whitelisted calls to `/hive/sbin/sreboot`.
- **Live console log streaming**: Click "View Miner Log" to launch a scrollable terminal streaming your active miner log outputs updated in real-time.
- **Hashrate Watchdog & Autofan Tuning**: Configure low hashrate reboot conditions and GPU core/memory temperature fan ranges directly on the rig.
- **Profile Presets (Flight Sheets)**: Save your current configurations as named presets and hot-swap between coins and wallets locally.
- **Emergency Flight Sheet Configurer**: Directly edit and apply Coin, Wallet Address, Pool server connections, and selected Miner variables without SSH.
- **Local Network & Hardware Diagnostics**: Check default gateway, DNS, WAN, and HiveOS cloud ping times, and parse tail outputs of kernel GPU driver error messages.
- **Emergency Overclock Reset to Stock**: Instantly blank all GPU overclocks to safe factory stock limits with one click to recover from instability or freezes.
- **Background Services Management**: Toggle active states of background services including the local watchdog daemon (`wd`), the autofan daemon (`autofan`), and the `hiveos-local` web server.

---

## Centralized Monitoring (Fleet Manager)

The codebase includes **Fleet Manager**, a centralized monitoring server designed to run inside a Docker container.
It allows you to:
- Monitor multiple mining rigs from a single unified Bootstrap 5 dashboard.
- View real-time speeds, temps, and active miner stats.
- Proxy rig operations (like restarting miners or rebooting rigs) safely.

To run the Fleet Manager:
1. Ensure Docker is installed on your local monitoring machine.
2. Navigate to `fleet-manager/` folder.
3. Launch the container: `docker-compose up -d --build`.
4. Open `http://localhost:8080` to access the Fleet Manager panel.

For more details, see the [Fleet Manager README](./fleet-manager/README.md).

---

## Security Best Practices

Because this dashboard executes shell scripts and controls hardware voltages:

1. **Firewall Boundaries**: Do not expose port `1337` directly to the open internet. Access the dashboard exclusively via local Wi-Fi / LAN, or use a secure VPN (like WireGuard or OpenVPN) if connecting remotely.
2. **Plaintext Cookie Warning**: The dashboard serves over plain HTTP on LAN port `1337`. Session cookies and CSRF tokens travel in plaintext. Ensure your local segment is secure (e.g. dedicated mining VLAN) to prevent local session capturing.
3. **Access Security & Lockout**: The 6-digit key PIN restricts admin features. Inputting 5 failed attempts will temporarily lock out the IP address for 15 minutes. To regenerate the PIN at any time, delete `/hive-config/dashboard.key` and restart the service.

---

## License
Distributed under the MIT License. Copyright (c) 2026 **Y3TI Coding Team**. See `LICENSE` for more information.

---

*Note: This software is completely scratch-built by AI, as a way to help HiveOS users at least manage their GPUs.*
