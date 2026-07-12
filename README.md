# HiveOS Local GPU Manager (HiveOS-Local)

A lightweight, local, browser-based emergency diagnostics and GPU overclocking manager designed to run side-by-side on rigs powered by **HiveOS** (https://hiveon.com). 

When Hiveon's remote API or central cloud servers experience outages, communication between your mining rig and the main HiveOS dashboard breaks, rendering remote management impossible. **HiveOS-Local** bypasses the cloud entirely, hosting a premium, user-friendly control interface directly from the mining rig's local IP address on port **`1337`**.

---

## Key Features

- 🔋 **Zero Cloud Dependencies**: Connects directly to the rig's local web server via its LAN IP address.
- 🎨 **Premium Modern Design**: Glassmorphic, responsive Bootstrap 5 interface featuring dark mode (default) and light mode toggle.
- ⚡ **Real-Time Telemetry**: Real-time stats (updates every 5 seconds) for core/memory clock, power limits, fan speeds, temperatures, and hashrate estimation.
- 📈 **Basic GPU Overclocking**: Interactively modify core clocks (offsets or locked absolute clocks), memory clocks, fan targets, and voltages.
- ⚙️ **Direct OS Splicing**: Seamlessly reads and updates native HiveOS configuration files (`nvidia-oc.conf`, `amd-oc.conf`, `rig.conf`) and runs system scripts to apply settings immediately.
- 💡 **Novice-Friendly Documentation**: Built-in tooltips and a clear, detailed guide explaining advanced overclocking terminology in basic terms.
- 💻 **Automatic Developer Fallback**: Automatically switches to a functional **Demo Mode** with simulated hardware if run on a non-HiveOS system (e.g. Windows/macOS), enabling easy testing and local modification.

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
```

During installation, the script will install the Flask dependency, register a systemd daemon (`hiveos-local.service`), and start the server on port `1337`.

Once complete, the installer will display the rig's active IP address. Open any web browser on your local network and navigate to:
```
http://<rig-local-ip>:1337
```

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
- **/hive-config/nvidia-oc.conf**: Spliced when saving NVIDIA overclocks. Contains space-separated parameters mapping to GPU indices (e.g. `CORE="100 120 0"`). After writing, it executes `sudo /hive/sbin/nvidia-oc` to apply parameters immediately.
- **/hive-config/amd-oc.conf**: Spliced when saving AMD overclocks. After writing, it executes `sudo /hive/sbin/amd-oc` to apply changes.

### Running Locally (Demo Mode)

For development or preview, you can run the application on Windows, macOS, or standard Linux distributions. It will automatically detect the absence of HiveOS directories, generate dummy configuration files in the root folder, and spawn a simulated rig with mocked Nvidia and AMD graphics cards.

Run the Flask server using:
```bash
python app.py
```
Open `http://localhost:1337` in your browser. Any overclocking adjustments you submit will modify the mock configurations on your disk and simulate performance differences in the UI.

---

## Security Best Practices

Because this dashboard executes shell scripts and controls hardware voltages:

1. **Firewall Boundaries**: Do not expose port `1337` directly to the open internet. Access the dashboard exclusively via local Wi-Fi / LAN, or use a secure VPN (like WireGuard or OpenVPN) if connecting remotely.
2. **Network Scans**: HiveOS-Local automatically scans and displays its local network IP during boot so that you don't have to scan ports manually or login to your router dashboard to identify it.

---

## License
Distributed under the MIT License. See `LICENSE` for more information.
