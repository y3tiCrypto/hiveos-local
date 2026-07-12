# Security Policy & Guidelines

This document outlines the security policies, vulnerability reporting channels, and deployment guidelines for the **HiveOS Local GPU Manager** (HiveOS-Local), maintained by the **Y3TI Coding Team**.

---

## 1. Supported Versions

Only the latest release version on the `main` branch is actively supported and receive security updates.

| Version | Supported |
| :--- | :--- |
| **Latest (main)** |  Yes |
| All Legacy |  No |

---

## 2. Reporting a Vulnerability

The Y3TI Coding Team takes security seriously. If you find a vulnerability (e.g. bypass authentication, arbitrary execution, file access limits), please report it directly using the instructions below.

### 2.1. Vulnerability Reporting Channels
- **Reporting Contact**: Please open a confidential GitHub Security Advisory, or email the team at `security@y3ticoding.team` (if active).
- **Required Details**:
  - A description of the issue and the potential impact.
  - Step-by-step reproduction instructions (PoC script, query payload, or settings input).
  - The configuration details (e.g., HiveOS version, Nvidia/AMD GPU count).

Please do not open public issues on GitHub for potential security bugs until they have been reviewed and mitigated by the team.

---

## 3. Secure Deployment Guidelines

Because this software interfaces directly with hardware clocks and runs as `root` to execute Linux system-level configurations, please follow these guidelines to keep your rigs secure:

### 3.1. Network Isolation & Plaintext Cookies (LAN only)
- **Warning**: Do not expose port `1337` to the open internet. 
- **Plaintext Cookie Notice**: Because the dashboard is served over plain HTTP, the session cookie and CSRF tokens travel in cleartext across the local network segment. If you bridge VLANs or host untrusted devices on the same subnet, attackers could capture session traffic.
- **Guideline**: Secure the local network segment using dedicated mining VLANs. Ensure your local router has firewall rules blocking port `1337` from external ingress interfaces. If you need to access the dashboard remotely:
  - Connect to the local network using a secure VPN (such as WireGuard, OpenVPN, or Tailscale).
  - Access the server using the VPN-assigned IP address.

### 3.2. Access PIN Management
- **PIN Location**: The generated access PIN is stored in plaintext inside `/hive-config/dashboard.key` on HiveOS rigs.
- **File System Permissions**: On a real HiveOS rig, the installation script automatically restricts read/write permissions on the key file using `chmod 600`. Only the root user can view the PIN on the host machine.
- **PIN Rotation**: If your PIN is compromised or you want to rotate it, run these commands inside the host terminal:
  ```bash
  # Delete the current key file
  sudo rm /hive-config/dashboard.key
  
  # Restart the service to generate a new PIN
  sudo systemctl restart hiveos-local.service
  
  # Read the newly generated PIN
  sudo cat /hive-config/dashboard.key
  ```

### 3.3. Restricting Sudo Privileges
- **Running context**: The background service `hiveos-local` runs as the `root` user by default. This is required because querying metrics (e.g., reading card stats from `sysfs` or running `nvidia-smi` to read power draw), toggling CPU hugepages, controlling miner states, and executing GPU settings (`nvidia-oc` and `amd-oc`) requires root-level hardware interface access.
- **Guideline**: Do not edit the systemd unit `ExecStart` parameters to run as a standard user unless you have specifically configured `sudoers` passwordless permissions for:
  - `/usr/bin/nvidia-smi`
  - `/hive/sbin/nvidia-oc`
  - `/hive/sbin/amd-oc`
  - `/hive/bin/hugepages`
  - `/hive/bin/miner`
  - `/hive-config/` configuration files (write access)

---

## 4. Security Philosophy

We build software that respects owner privacy. This emergency utility does not report metrics to remote hosts and operates fully offline on your LAN boundaries, except for read-only version check requests sent to `raw.githubusercontent.com` over HTTPS when polling for dashboard code updates.

*Policy compiled by the **Y3TI Coding Team**.*
