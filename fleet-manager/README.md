# HiveOS Fleet Manager (Experimental)

> [!WARNING]
> **EXPERIMENTAL RELEASE**: The Fleet Manager utility is currently in an experimental phase. It is built strictly for private local segments (LAN) or secure, encrypted VPN networks (e.g., WireGuard). Do not expose port `8080` to the public internet without proper proxy authentication and firewall boundaries.

Fleet Manager is a centralized monitoring and control dashboard built to aggregate metrics and controls across your entire mining fleet running standard `hiveos-local` emergency local dashboard nodes.

## Features

- **Concurrent Fleet Metrics Aggregation**: Queries all registered rigs in parallel using a thread-pool executor.
- **Aggregated Fleet Counters**: Monitors fleet status (Online/Offline ratios), combined hashrates (both GPU + CPU), GPU thermal averages, and combined power draw.
- **Rig Hardware Metrics**: Tracks individual host configurations, active mining coins, current miner programs, card speeds, temperatures, fan duties, and RAM consumption.
- **Proxy Command Actions**: Directly trigger miner restarts, system reboots, and console logs streaming on any rig from a single central panel.
- **Persistent Local Storage**: Persists configured rigs in a local JSON storage (`data/rigs.json`) that can be mapped to a Docker volume.

## Quick Start (Docker Compose)

### 1. Requirements

Ensure Docker and Docker Compose are installed on your host system.

### 2. Startup

Navigate to the `fleet-manager` directory and run:

```bash
docker-compose up -d --build
```

The Fleet Manager will spin up and listen on port `8080`.

### 3. Usage

1. Open `http://<your-manager-ip>:8080` in your web browser.
2. Click **Add Rig**.
3. Input:
   - **Rig Label**: A custom nickname for the rig (e.g., `Rig-01`).
   - **IP Address / Host**: The LAN IP address of your mining rig.
   - **Port**: The port where the rig's local dashboard is running (default `1337`).
   - **Access PIN**: The 6-digit dashboard key PIN configured on the rig.
4. Click **Verify & Register**. The manager will verify connectivity and credentials immediately before adding it to the dashboard.
