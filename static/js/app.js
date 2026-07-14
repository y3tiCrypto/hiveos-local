// Global state to store overclock configurations
let activeOverclocks = {};
let csrfToken = '';

document.addEventListener('DOMContentLoaded', function() {
    // 1. Theme Toggle Logic
    const htmlElement = document.documentElement;
    const themeToggleBtn = document.getElementById('themeToggleBtn');
    const themeToggleIcon = document.getElementById('themeToggleIcon');

    // Retrieve saved theme or default to dark
    const savedTheme = localStorage.getItem('theme') || 'dark';
    setTheme(savedTheme);

    themeToggleBtn.addEventListener('click', () => {
        const currentTheme = htmlElement.getAttribute('data-bs-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        setTheme(newTheme);
    });

    function setTheme(theme) {
        htmlElement.setAttribute('data-bs-theme', theme);
        localStorage.setItem('theme', theme);
        
        if (theme === 'dark') {
            themeToggleIcon.className = 'bi bi-moon-stars-fill';
            themeToggleBtn.classList.remove('btn-light');
            themeToggleBtn.classList.add('btn-dark');
        } else {
            themeToggleIcon.className = 'bi bi-sun-fill';
            themeToggleBtn.classList.remove('btn-dark');
            themeToggleBtn.classList.add('btn-light');
        }
    }

    // 2. Authentication Login Handler
    const loginForm = document.getElementById('loginForm');
    const loginOverlay = document.getElementById('loginOverlay');
    const loginError = document.getElementById('loginError');
    const revertBtn = document.getElementById('revertSettingsBtn');

    loginForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        const pin = document.getElementById('loginPin').value.trim();
        
        const submitBtn = loginForm.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Verifying...`;
        
        try {
            const response = await fetch('/api/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ pin: pin })
            });
            const data = await response.json();
            
            if (response.ok && data.success) {
                csrfToken = data.csrf_token;
                loginOverlay.classList.add('d-none');
                loginError.classList.add('d-none');
                revertBtn.classList.remove('d-none');
                showToast("Authorized successfully!", true);
                fetchStats();
            } else {
                loginError.classList.remove('d-none');
                document.getElementById('loginPin').value = '';
            }
        } catch (error) {
            console.error("Authentication failed:", error);
            showToast("Network error during authorization check.", false);
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = "Authorize Session";
        }
    });

    // 3. Rollback Backup Configurations Handler
    revertBtn.addEventListener('click', async function() {
        if (!confirm("Are you sure you want to revert all GPU settings to the last saved stable backup? This will restore files and apply them to the system.")) {
            return;
        }
        
        revertBtn.disabled = true;
        const icon = revertBtn.querySelector('i');
        icon.className = 'bi bi-arrow-counterclockwise spin-animation';
        
        try {
            const response = await fetch('/api/revert', {
                method: 'POST',
                headers: {
                    'X-CSRF-Token': csrfToken
                }
            });
            const data = await response.json();
            
            if (response.ok && data.success) {
                showToast(data.message, true);
                fetchStats();
            } else {
                showToast(data.message || "Failed to restore backups.", false);
            }
        } catch (error) {
            console.error("Rollback failed:", error);
            showToast("Network error trying to restore backup.", false);
        } finally {
            revertBtn.disabled = false;
            icon.className = 'bi bi-arrow-counterclockwise';
        }
    });

    // Toggle Huge Pages Handler
    const toggleHpBtn = document.getElementById('toggleHugepagesBtn');
    toggleHpBtn.addEventListener('click', async function() {
        const currentStatus = document.getElementById('hugePagesStatus').textContent.trim();
        const enable = currentStatus !== "Enabled";
        
        toggleHpBtn.disabled = true;
        const icon = toggleHpBtn.querySelector('i');
        icon.className = 'bi bi-gear-fill spin-animation';
        
        try {
            const response = await fetch('/api/hugepages', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrfToken
                },
                body: JSON.stringify({ enable: enable })
            });
            const data = await response.json();
            if (response.ok && data.success) {
                showToast(data.message, true);
                fetchStats();
            } else {
                showToast(data.message || "Failed to configure Huge Pages.", false);
            }
        } catch (error) {
            console.error("Huge Pages toggle failed:", error);
            showToast("Network error trying to toggle Huge Pages.", false);
        } finally {
            toggleHpBtn.disabled = false;
            icon.className = 'bi bi-gear-fill';
        }
    });

    // Miner Control Helper
    async function sendMinerControl(action, buttonId) {
        const btn = document.getElementById(buttonId);
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Sending...`;
        
        try {
            const response = await fetch('/api/miner/control', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrfToken
                },
                body: JSON.stringify({ action: action })
            });
            const data = await response.json();
            if (response.ok && data.success) {
                showToast(data.message, true);
                fetchStats();
            } else {
                showToast(data.message || `Failed to ${action} miner.`, false);
            }
        } catch (error) {
            console.error(`Miner control error (${action}):`, error);
            showToast(`Network error attempting to ${action} miner.`, false);
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }

    document.getElementById('minerStartBtn').addEventListener('click', () => sendMinerControl('start', 'minerStartBtn'));
    document.getElementById('minerStopBtn').addEventListener('click', () => {
        if (confirm("Are you sure you want to STOP mining operations on this rig?")) {
            sendMinerControl('stop', 'minerStopBtn');
        }
    });
    document.getElementById('minerRestartBtn').addEventListener('click', () => sendMinerControl('restart', 'minerRestartBtn'));

    // 4. Poll for GPU Stats and Rig Config
    fetchStats(); // Initial load
    checkUpdate(); // Initial check for dashboard updates on GitHub
    const statsInterval = setInterval(fetchStats, 5000); // Poll every 5s
    const updateInterval = setInterval(checkUpdate, 600000); // Check updates every 10m

    // Manual Refresh button
    const refreshBtn = document.getElementById('refreshStatsBtn');
    refreshBtn.addEventListener('click', () => {
        refreshBtn.disabled = true;
        const icon = refreshBtn.querySelector('i');
        icon.className = 'bi bi-arrow-clockwise spin-animation';
        
        fetchStats().finally(() => {
            setTimeout(() => {
                refreshBtn.disabled = false;
                icon.className = 'bi bi-arrow-clockwise';
            }, 800);
        });
    });

    // 5. Form Submit Handlers for Overclocking
    document.getElementById('nvOcForm').addEventListener('submit', function(e) {
        e.preventDefault();
        submitOverclock(this, 'nvOcModal');
    });

    document.getElementById('amdOcForm').addEventListener('submit', function(e) {
        e.preventDefault();
        submitOverclock(this, 'amdOcModal');
    });

    // Apply update trigger
    const applyUpdateBtn = document.getElementById('applyUpdateBtn');
    applyUpdateBtn.addEventListener('click', async function() {
        const pinInput = document.getElementById('updateVerificationPin');
        const pin = pinInput.value.trim();
        if (pin.length !== 6 || !/^\d+$/.test(pin)) {
            showToast("Please enter a valid 6-digit confirmation PIN.", false);
            return;
        }
        
        if (!confirm("Are you sure you want to pull the latest updates from GitHub and restart the local dashboard? Rigs configurations will reset to main branch head.")) {
            return;
        }
        
        const overlay = document.getElementById('updateOverlay');
        overlay.classList.remove('d-none');
        overlay.classList.add('d-flex');
        
        try {
            const response = await fetch('/api/update/pull', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrfToken
                },
                body: JSON.stringify({ pin: pin })
            });
            const data = await response.json();
            if (response.ok && data.success) {
                showToast(data.message, true);
                setTimeout(() => {
                    window.location.reload();
                }, 6000);
            } else {
                overlay.classList.remove('d-flex');
                overlay.classList.add('d-none');
                showToast(data.message || "Failed to pull update.", false);
            }
        } catch (error) {
            console.error("Update pull failed:", error);
            overlay.classList.remove('d-flex');
            overlay.classList.add('d-none');
            showToast("Network error trying to pull update.", false);
        }
    });

    // Manual check for updates trigger
    const manualCheckBtn = document.getElementById('manualCheckUpdateBtn');
    manualCheckBtn.addEventListener('click', async () => {
        manualCheckBtn.disabled = true;
        const icon = manualCheckBtn.querySelector('i');
        icon.className = 'bi bi-arrow-repeat spin-animation';
        
        await checkUpdate(true);
        
        setTimeout(() => {
            manualCheckBtn.disabled = false;
            icon.className = 'bi bi-arrow-repeat';
        }, 1000);
    });

    // Reboot / Shutdown bindings
    document.getElementById('rigRebootBtn').addEventListener('click', async () => {
        if (confirm("Are you sure you want to REBOOT this rig? Mining operations will be suspended during reboot.")) {
            sendSystemPowerAction('/api/system/reboot', 'rigRebootBtn');
        }
    });
    
    document.getElementById('rigShutdownBtn').addEventListener('click', async () => {
        if (confirm("Are you sure you want to SHUTDOWN this rig? Power will be cut from the hardware.")) {
            sendSystemPowerAction('/api/system/shutdown', 'rigShutdownBtn');
        }
    });
    
    // Emergency Overclock Reset trigger
    document.getElementById('emergencyResetClocksBtn').addEventListener('click', async () => {
        if (!confirm("WARNING: This will instantly clear all GPU overclock values (clocks, fans, voltages, power limits) to factory stock configurations. Stabilize rig now?")) {
            return;
        }
        
        const btn = document.getElementById('emergencyResetClocksBtn');
        const origHTML = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Resetting...`;
        
        try {
            const res = await fetch('/api/overclock/reset', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrfToken
                }
            });
            const data = await res.json();
            if (res.ok && data.success) {
                showToast(data.message, true);
                fetchStats();
            } else {
                showToast(data.message || "Failed to reset clocks.", false);
            }
        } catch (e) {
            console.error(e);
            showToast("Network error trying to reset clocks.", false);
        } finally {
            btn.disabled = false;
            btn.innerHTML = origHTML;
        }
    });

    // Background Services control triggers
    document.querySelectorAll('.service-ctrl-btn').forEach(btn => {
        btn.addEventListener('click', async function() {
            const service = this.dataset.service;
            const action = this.dataset.action;
            
            if (!confirm(`Are you sure you want to ${action} the '${service}' service daemon?`)) {
                return;
            }
            
            this.disabled = true;
            const origHTML = this.innerHTML;
            this.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>`;
            
            try {
                const res = await fetch('/api/services/control', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': csrfToken
                    },
                    body: JSON.stringify({ service, action })
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    showToast(data.message, true);
                    if (service === 'hiveos-local') {
                        setTimeout(() => { window.location.reload(); }, 3500);
                    }
                } else {
                    showToast(data.message || "Failed to control service.", false);
                }
            } catch (e) {
                console.error(e);
                showToast("Network error communicating with service manager.", false);
            } finally {
                this.disabled = false;
                this.innerHTML = origHTML;
            }
        });
    });
    
    // Emergency Flight Sheet Configurer form submit
    document.getElementById('emergencyFlightSheetForm').addEventListener('submit', async function(e) {
        e.preventDefault();
        const submitBtn = this.querySelector('button[type="submit"]');
        const origHTML = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Saving...`;

        const coin = document.getElementById('fsCoin').value.trim();
        const wallet = document.getElementById('fsWallet').value.trim();
        const pool = document.getElementById('fsPool').value.trim();
        const miner = document.getElementById('fsMiner').value;

        try {
            const response = await fetch('/api/flightsheet', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrfToken
                },
                body: JSON.stringify({ coin, wallet, pool, miner })
            });
            const data = await response.json();
            if (response.ok && data.success) {
                showToast(data.message, true);
                fetchStats();
            } else {
                showToast(data.message || "Failed to apply flight sheet.", false);
            }
        } catch (error) {
            console.error(error);
            showToast("Network error trying to apply configuration.", false);
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = origHTML;
        }
    });

    // Diagnostics modal bindings
    const diagModalEl = document.getElementById('diagModal');
    const diagModal = new bootstrap.Modal(diagModalEl);
    
    document.getElementById('openDiagBtn').addEventListener('click', () => {
        diagModal.show();
    });
    
    document.getElementById('runDiagBtn').addEventListener('click', runDiagnostics);
    diagModalEl.addEventListener('shown.bs.modal', runDiagnostics);
    
    async function sendSystemPowerAction(endpoint, btnId) {
        const btn = document.getElementById(btnId);
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Sending...`;
        
        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'X-CSRF-Token': csrfToken }
            });
            const data = await response.json();
            if (response.ok && data.success) {
                showToast(data.message, true);
            } else {
                showToast(data.message || "Power command failed.", false);
            }
        } catch (error) {
            console.error("Power action failed:", error);
            showToast("Network error executing power command.", false);
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }

    // Miner logs viewer
    const logModal = document.getElementById('minerLogModal');
    let logPollInterval = null;
    
    document.getElementById('viewMinerLogBtn').addEventListener('click', () => {
        const modal = new bootstrap.Modal(logModal);
        modal.show();
    });
    
    logModal.addEventListener('shown.bs.modal', () => {
        fetchMinerLog();
        logPollInterval = setInterval(fetchMinerLog, 2000);
    });
    
    logModal.addEventListener('hidden.bs.modal', () => {
        if (logPollInterval) {
            clearInterval(logPollInterval);
            logPollInterval = null;
        }
    });
    
    async function fetchMinerLog() {
        try {
            const response = await fetch('/api/miner/log');
            if (response.status === 401) return;
            const data = await response.json();
            
            const consoleEl = document.getElementById('minerLogConsole');
            if (response.ok && data.success) {
                document.getElementById('activeMinerLogName').textContent = data.miner.toUpperCase();
                consoleEl.textContent = data.log || "Log file is currently empty.";
                consoleEl.scrollTop = consoleEl.scrollHeight;
            } else {
                consoleEl.textContent = "Error: " + (data.message || "Failed to read logs.");
            }
        } catch (error) {
            document.getElementById('minerLogConsole').textContent = "Failed to reach backend API for logs.";
        }
    }

    // Watchdog form submit
    document.getElementById('watchdogForm').addEventListener('submit', async function(e) {
        e.preventDefault();
        const btn = this.querySelector('button[type="submit"]');
        btn.disabled = true;
        
        const payload = {
            wd_enabled: document.getElementById('wdEnabled').value,
            wd_min_hashrate: document.getElementById('wdMinHashrate').value
        };
        
        try {
            const response = await fetch('/api/watchdog', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrfToken
                },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            if (response.ok && data.success) {
                showToast(data.message, true);
            } else {
                showToast(data.message || "Failed to save watchdog.", false);
            }
        } catch (error) {
            showToast("Network error saving watchdog.", false);
        } finally {
            btn.disabled = false;
        }
    });
    
    // Autofan form submit
    document.getElementById('autofanForm').addEventListener('submit', async function(e) {
        e.preventDefault();
        const btn = this.querySelector('button[type="submit"]');
        btn.disabled = true;
        
        const payload = {
            enabled: document.getElementById('afEnabled').value,
            target_temp: document.getElementById('afTargetCore').value,
            target_mem_temp: document.getElementById('afTargetMem').value,
            min_fan: document.getElementById('afMinFan').value,
            max_fan: document.getElementById('afMaxFan').value,
            critical_temp: document.getElementById('afCriticalTemp').value
        };
        
        try {
            const response = await fetch('/api/autofan', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrfToken
                },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            if (response.ok && data.success) {
                showToast(data.message, true);
            } else {
                showToast(data.message || "Failed to save autofan settings.", false);
            }
        } catch (error) {
            showToast("Network error saving autofan settings.", false);
        } finally {
            btn.disabled = false;
        }
    });

    // Save Preset form submit
    document.getElementById('savePresetForm').addEventListener('submit', async function(e) {
        e.preventDefault();
        const input = document.getElementById('newPresetName');
        const name = input.value.trim();
        const btn = this.querySelector('button[type="submit"]');
        btn.disabled = true;
        
        try {
            const response = await fetch('/api/presets/save', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrfToken
                },
                body: JSON.stringify({ name: name })
            });
            const data = await response.json();
            if (response.ok && data.success) {
                showToast(data.message, true);
                input.value = '';
                loadPresetsList();
            } else {
                showToast(data.message || "Failed to save preset.", false);
            }
        } catch (error) {
            showToast("Network error saving preset profile.", false);
        } finally {
            btn.disabled = false;
        }
    });
});

// Toast notification helper
function showToast(message, isSuccess = true) {
    const toastEl = document.getElementById('statusToast');
    const toastMessage = document.getElementById('toastMessage');
    const toastIcon = document.getElementById('toastIcon');
    
    toastMessage.textContent = message;
    
    if (isSuccess) {
        toastEl.className = 'toast align-items-center text-bg-success border-0 show';
        toastIcon.className = 'bi bi-check-circle-fill fs-5';
    } else {
        toastEl.className = 'toast align-items-center text-bg-danger border-0 show';
        toastIcon.className = 'bi bi-exclamation-octagon-fill fs-5';
    }
    
    setTimeout(() => {
        toastEl.classList.remove('show');
    }, 4500);
}

// Fetch stats from backend API
async function fetchStats() {
    try {
        const response = await fetch('/api/stats');
        
        // Handle 401 Unauthorized status
        if (response.status === 401) {
            document.getElementById('loginOverlay').classList.remove('d-none');
            document.getElementById('revertSettingsBtn').classList.add('d-none');
            document.getElementById('emergencyResetClocksBtn').classList.add('d-none');
            return;
        }
        
        if (!response.ok) throw new Error("Network response was not ok");
        
        const data = await response.json();
        
        // Hide login if active
        if (!document.getElementById('loginOverlay').classList.contains('d-none')) {
            document.getElementById('loginOverlay').classList.add('d-none');
            document.getElementById('revertSettingsBtn').classList.remove('d-none');
            document.getElementById('emergencyResetClocksBtn').classList.remove('d-none');
            loadTuningSettings();
        }
        
        // Save OC data globally to prefill forms
        activeOverclocks = data.overclocks;
        
        // Update header & badges
        document.getElementById('localIpAddress').textContent = data.system.local_ip + ':1337';
        document.getElementById('dashboardVersion').textContent = data.system.dashboard_version;
        document.getElementById('currentVerText').textContent = data.system.dashboard_version;
        
        // Update System Diagnostics Panel
        document.getElementById('statRigId').textContent = data.system.rig_id;
        document.getElementById('statUptime').textContent = data.system.uptime;
        document.getElementById('statCpu').textContent = data.system.cpu_load[0].toFixed(2);
        document.getElementById('statRam').textContent = data.system.ram_used_pct + '% / ' + data.system.ram_total_gb + ' GB';
        document.getElementById('statMiner').textContent = data.system.active_miner;
        document.getElementById('statVersion').textContent = data.system.hive_version;

        // Calculate and Update GPU Overall Summaries
        let totalHashrate = 0;
        let totalPower = 0;
        let sumTemp = 0;
        let sumFan = 0;
        let gpuCount = data.gpus.length;

        data.gpus.forEach(gpu => {
            totalHashrate += gpu.hashrate;
            totalPower += gpu.power;
            sumTemp += gpu.temp;
            sumFan += gpu.fan;
        });

        let avgTemp = gpuCount > 0 ? (sumTemp / gpuCount).toFixed(1) : 0;
        let avgFan = gpuCount > 0 ? (sumFan / gpuCount).toFixed(1) : 0;

        document.getElementById('statGpuCount').textContent = gpuCount + ' Cards';
        document.getElementById('statTotalHashrate').textContent = totalHashrate.toFixed(2) + ' MH/s';
        document.getElementById('statAvgTemp').textContent = avgTemp + ' °C';
        document.getElementById('statAvgFan').textContent = avgFan + ' %';
        document.getElementById('statTotalPower').textContent = totalPower.toFixed(1) + ' W';
        document.getElementById('statCoin').textContent = data.system.coin || 'Unknown';
        
        // Update CPU Mining Panel
        document.getElementById('cpuModelName').textContent = data.system.cpu.model;
        document.getElementById('cpuTemp').textContent = data.system.cpu.temp + ' °C';
        
        const hpStatus = document.getElementById('hugePagesStatus');
        if (data.system.cpu.hugepages) {
            hpStatus.textContent = "Enabled";
            hpStatus.className = "stat-value text-success";
        } else {
            hpStatus.textContent = "Disabled";
            hpStatus.className = "stat-value text-danger";
        }
        
        const hashrate = data.system.cpu.hashrate;
        const formattedHash = hashrate > 1000 ? (hashrate / 1000).toFixed(2) + ' KH/s' : hashrate.toFixed(0) + ' H/s';
        document.getElementById('cpuHashrateBadge').textContent = formattedHash;

        // Render GPU cards
        renderGpus(data.gpus);
        
    } catch (error) {
        console.error("Error fetching stats:", error);
        document.getElementById('gpuContainer').innerHTML = `
            <div class="col-12">
                <div class="alert alert-danger text-center glass-card py-4" role="alert">
                    <i class="bi bi-wifi-off fs-1 d-block mb-2"></i>
                    <h4 class="alert-heading fw-bold">Lost Connection to Rig Server</h4>
                    <p class="mb-0 small">The Local Dashboard cannot reach the backend web API. Ensure the Python server is running on port 1337.</p>
                </div>
            </div>
        `;
    }
}

// Render GPU layout dynamically
function renderGpus(gpus) {
    const container = document.getElementById('gpuContainer');
    container.innerHTML = '';
    
    if (gpus.length === 0) {
        container.innerHTML = `
            <div class="col-12 text-center py-4">
                <p class="text-muted">No mining GPUs detected on this rig.</p>
            </div>
        `;
        return;
    }
    
    gpus.forEach(gpu => {
        const tempClass = gpu.temp > 75 ? 'danger' : (gpu.temp > 65 ? 'warning' : 'success');
        const fanClass = gpu.fan > 80 ? 'danger' : 'primary';
        
        const cardCol = document.createElement('div');
        cardCol.className = 'col-md-6 col-lg-4';
        
        cardCol.innerHTML = `
            <div class="card glass-card h-100">
                <div class="card-body d-flex flex-column justify-content-between">
                    <div>
                        <!-- Card Header -->
                        <div class="gpu-header d-flex justify-content-between align-items-center mb-3">
                            <span class="small fw-semibold text-muted">GPU ${gpu.index}</span>
                            <span class="badge bg-accent-glow text-primary fw-bold font-monospace">${gpu.hashrate} MH/s</span>
                        </div>
                        
                        <!-- GPU Specs -->
                        <h3 class="h5 fw-bold mb-1">${gpu.model}</h3>
                        <p class="small text-muted mb-3">
                            <span class="brand-${gpu.brand.toLowerCase()}">${gpu.brand}</span> • PCI Bus ${gpu.id}
                        </p>
                        
                        <!-- Temperature Progress Bar -->
                        <div class="metric-row">
                            <div class="metric-label">
                                <span>Temperature</span>
                                <span class="metric-value">${gpu.temp}°C</span>
                            </div>
                            <div class="progress bg-black bg-opacity-20" style="height: 8px;">
                                <div class="progress-bar progress-bar-glow-${tempClass === 'danger' ? 'red' : (tempClass === 'success' ? 'green' : 'primary')}" 
                                     role="progressbar" style="width: ${gpu.temp}%" aria-valuenow="${gpu.temp}" aria-valuemin="0" aria-valuemax="100"></div>
                            </div>
                        </div>

                        <!-- Fan Speed Progress Bar -->
                        <div class="metric-row">
                            <div class="metric-label">
                                <span>Fan Speed</span>
                                <span class="metric-value">${gpu.fan}%</span>
                            </div>
                            <div class="progress bg-black bg-opacity-20" style="height: 8px;">
                                <div class="progress-bar progress-bar-glow-${fanClass === 'danger' ? 'red' : 'primary'}" 
                                     role="progressbar" style="width: ${gpu.fan}%" aria-valuenow="${gpu.fan}" aria-valuemin="0" aria-valuemax="100"></div>
                            </div>
                        </div>

                        <!-- Clocks and Power Metrics -->
                        <div class="row g-2 mt-2 pt-2 border-top border-secondary-subtle text-center">
                            <div class="col-4">
                                <div class="small text-muted">Core Clock</div>
                                <div class="fw-semibold small">${gpu.core_clock} MHz</div>
                            </div>
                            <div class="col-4">
                                <div class="small text-muted">Mem Clock</div>
                                <div class="fw-semibold small">${gpu.mem_clock} MHz</div>
                            </div>
                            <div class="col-4">
                                <div class="small text-muted">Power</div>
                                <div class="fw-semibold small text-danger-emphasis">${gpu.power}W <span class="text-muted small">/ ${gpu.power_limit}W</span></div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Action Buttons -->
                    <div class="mt-4">
                        <button class="btn btn-sm btn-outline-primary w-100 py-2 fw-semibold d-flex align-items-center justify-content-center gap-1" 
                                onclick="openOcModal('${gpu.brand}', ${gpu.index})">
                            <i class="bi bi-sliders"></i> Edit Overclocks
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        container.appendChild(cardCol);
    });
}

// Prefill and open the correct modal for the selected GPU
window.openOcModal = function(brand, index) {
    const placeholders = document.querySelectorAll('.gpu-index-placeholder');
    placeholders.forEach(el => el.textContent = index);
    
    const inputs = document.querySelectorAll('.gpu-index-input');
    inputs.forEach(el => el.value = index);

    if (brand === "NVIDIA") {
        const nvCore = activeOverclocks.nvidia?.core?.[index] || "";
        const nvMem = activeOverclocks.nvidia?.mem?.[index] || "";
        const nvPl = activeOverclocks.nvidia?.pl?.[index] || "";
        const nvFan = activeOverclocks.nvidia?.fan?.[index] || "";
        
        document.getElementById('nvCore').value = nvCore === "0" ? "" : nvCore;
        document.getElementById('nvMem').value = nvMem === "0" ? "" : nvMem;
        document.getElementById('nvPl').value = nvPl === "0" ? "" : nvPl;
        document.getElementById('nvFan').value = nvFan === "0" ? "" : nvFan;

        const modal = new bootstrap.Modal(document.getElementById('nvOcModal'));
        modal.show();
    } else if (brand === "AMD") {
        const oc = activeOverclocks.amd || {};
        document.getElementById('amdCore').value = (oc.core?.[index] === "0" ? "" : oc.core?.[index]) || "";
        document.getElementById('amdMem').value = (oc.mem?.[index] === "0" ? "" : oc.mem?.[index]) || "";
        document.getElementById('amdVdd').value = (oc.vdd?.[index] === "0" ? "" : oc.vdd?.[index]) || "";
        document.getElementById('amdVddci').value = (oc.vddci?.[index] === "0" ? "" : oc.vddci?.[index]) || "";
        document.getElementById('amdMvdd').value = (oc.mvdd?.[index] === "0" ? "" : oc.mvdd?.[index]) || "";
        document.getElementById('amdDpm').value = (oc.dpm?.[index] === "0" ? "" : oc.dpm?.[index]) || "";
        document.getElementById('amdRef').value = (oc.ref?.[index] === "0" ? "" : oc.ref?.[index]) || "";
        document.getElementById('amdPl').value = (oc.pl?.[index] === "0" ? "" : oc.pl?.[index]) || "";
        document.getElementById('amdFan').value = (oc.fan?.[index] === "0" ? "" : oc.fan?.[index]) || "";

        const modal = new bootstrap.Modal(document.getElementById('amdOcModal'));
        modal.show();
    }
};

// Submit overclock data via AJAX
async function submitOverclock(formElement, modalId) {
    const formData = new FormData(formElement);
    const payload = {};
    
    formData.forEach((value, key) => {
        if (key === 'index') {
            payload[key] = parseInt(value);
        } else if (key === 'brand') {
            payload[key] = value;
        } else {
            payload[key] = value.trim() === '' ? '0' : value.trim();
        }
    });

    const submitBtn = formElement.querySelector('button[type="submit"]');
    const originalText = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Saving...`;

    try {
        const response = await fetch('/api/overclock', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': csrfToken
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();
        
        if (response.ok && data.success) {
            showToast(data.message, true);
            const modalInstance = bootstrap.Modal.getInstance(document.getElementById(modalId));
            modalInstance.hide();
            fetchStats();
        } else {
            showToast(data.message || "Failed to apply overclock parameters.", false);
        }
    } catch (error) {
        console.error("Error applying overclock:", error);
        showToast("Network error. Failed to reach the rig API.", false);
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
    }
}

// Check for updates on GitHub
async function checkUpdate(isManual = false) {
    try {
        const response = await fetch('/api/update/check');
        if (response.status === 401) {
            if (isManual) showToast("Unauthorized. Please authorize your session first.", false);
            return;
        }
        
        if (response.ok) {
            const data = await response.json();
            if (data.success && data.update_available) {
                document.getElementById('remoteVersionText').textContent = 'v' + data.remote_version;
                document.getElementById('updateBanner').classList.remove('d-none');
                if (isManual) {
                    showToast(`New update found! v${data.remote_version} is available.`, true);
                }
            } else {
                document.getElementById('updateBanner').classList.add('d-none');
                if (isManual) {
                    showToast(`Your dashboard is already up to date (v${data.local_version}).`, true);
                }
            }
        } else {
            if (isManual) showToast("Failed to communicate with update checker API.", false);
        }
    } catch (error) {
        console.error("Failed to check for updates:", error);
        if (isManual) showToast("Network error checking for updates.", false);
    }
}

// Load tuning settings on authorization
async function loadTuningSettings() {
    try {
        const wdRes = await fetch('/api/watchdog');
        if (wdRes.ok) {
            const wdData = await wdRes.json();
            if (wdData.success) {
                document.getElementById('wdEnabled').value = wdData.wd_enabled;
                document.getElementById('wdMinHashrate').value = wdData.wd_min_hashrate;
            }
        }
        
        const afRes = await fetch('/api/autofan');
        if (afRes.ok) {
            const afData = await afRes.json();
            if (afData.success) {
                document.getElementById('afEnabled').value = afData.enabled;
                document.getElementById('afTargetCore').value = afData.target_temp;
                document.getElementById('afTargetMem').value = afData.target_mem_temp;
                document.getElementById('afMinFan').value = afData.min_fan;
                document.getElementById('afMaxFan').value = afData.max_fan;
                document.getElementById('afCriticalTemp').value = afData.critical_temp;
            }
        }
        
        
        loadFlightSheetSettings();
        loadPresetsList();
    } catch (error) {
        console.error("Failed to load tuning configs:", error);
    }
}

// Load list of saved configuration presets
async function loadPresetsList() {
    const container = document.getElementById('presetsContainer');
    try {
        const response = await fetch('/api/presets');
        const data = await response.json();
        if (response.ok && data.success) {
            if (data.presets.length === 0) {
                container.innerHTML = `<div class="text-center text-muted small py-4">No profiles saved yet. Save active flight sheet as a preset.</div>`;
                return;
            }
            
            let html = '<div class="list-group list-group-flush border border-secondary-subtle rounded bg-dark-card">';
            data.presets.forEach(name => {
                html += `
                    <div class="list-group-item bg-transparent d-flex justify-content-between align-items-center py-2 px-3">
                        <span class="fw-semibold text-white small">${name}</span>
                        <div class="d-flex gap-2">
                            <button class="btn btn-xs btn-success fw-semibold py-1 px-2 apply-preset-btn" data-preset="${name}">
                                <i class="bi bi-play-circle-fill"></i> Swap
                            </button>
                            <button class="btn btn-xs btn-outline-danger py-1 px-2 delete-preset-btn" data-preset="${name}">
                                <i class="bi bi-trash"></i>
                            </button>
                        </div>
                    </div>`;
            });
            html += '</div>';
            container.innerHTML = html;
            
            document.querySelectorAll('.apply-preset-btn').forEach(btn => {
                btn.addEventListener('click', function() {
                    const name = this.getAttribute('data-preset');
                    if (confirm(`Are you sure you want to load profile preset "${name}"? Active miner config files will be overwritten and miner restarted.`)) {
                        applyPreset(name);
                    }
                });
            });
            
            document.querySelectorAll('.delete-preset-btn').forEach(btn => {
                btn.addEventListener('click', function() {
                    const name = this.getAttribute('data-preset');
                    if (confirm(`Are you sure you want to delete profile preset "${name}"?`)) {
                        deletePreset(name);
                    }
                });
            });
        } else {
            container.innerHTML = `<div class="text-danger small py-3 text-center">Failed to load presets.</div>`;
        }
    } catch (error) {
        container.innerHTML = `<div class="text-danger small py-3 text-center">Connection error.</div>`;
    }
}

async function applyPreset(name) {
    try {
        const response = await fetch('/api/presets/apply', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': csrfToken
            },
            body: JSON.stringify({ name: name })
        });
        const data = await response.json();
        if (response.ok && data.success) {
            showToast(data.message, true);
            fetchStats();
        } else {
            showToast(data.message || "Failed to apply profile preset.", false);
        }
    } catch (error) {
        showToast("Network error applying preset.", false);
    }
}

async function deletePreset(name) {
    try {
        const response = await fetch('/api/presets/delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': csrfToken
            },
            body: JSON.stringify({ name: name })
        });
        const data = await response.json();
        if (response.ok && data.success) {
            showToast(data.message, true);
            loadPresetsList();
        } else {
            showToast(data.message || "Failed to delete preset.", false);
        }
    } catch (error) {
        showToast("Network error deleting preset.", false);
    }
}

async function loadFlightSheetSettings() {
    try {
        const res = await fetch('/api/flightsheet');
        if (res.ok) {
            const data = await res.json();
            if (data && data.success) {
                document.getElementById('fsCoin').value = data.coin;
                document.getElementById('fsWallet').value = data.wallet;
                document.getElementById('fsPool').value = data.pool;
                document.getElementById('fsMiner').value = data.miner;
            }
        }
    } catch (e) {
        console.error("Failed to load flight sheet settings:", e);
    }
}

async function runDiagnostics() {
    const runBtn = document.getElementById('runDiagBtn');
    const origHTML = runBtn.innerHTML;
    runBtn.disabled = true;
    runBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Running...`;

    document.getElementById('diagGatewayStatus').className = 'badge bg-secondary';
    document.getElementById('diagGatewayStatus').textContent = 'Testing...';
    document.getElementById('diagInternetStatus').className = 'badge bg-secondary';
    document.getElementById('diagInternetStatus').textContent = 'Testing...';
    document.getElementById('diagDnsStatus').className = 'badge bg-secondary';
    document.getElementById('diagDnsStatus').textContent = 'Testing...';
    document.getElementById('diagHiveApiStatus').className = 'badge bg-secondary';
    document.getElementById('diagHiveApiStatus').textContent = 'Testing...';
    document.getElementById('diagGpuLogs').textContent = 'Running system tests...';

    try {
        const res = await fetch('/api/diagnostics');
        if (res.ok) {
            const data = await res.json();
            if (data.success) {
                document.getElementById('diagGatewayIp').textContent = data.gateway_ip;
                
                const setBadge = (id, status) => {
                    const el = document.getElementById(id);
                    el.textContent = status;
                    el.className = `badge ${status === 'Online' || status === 'Working' || status === 'Reachable' ? 'bg-success' : 'bg-danger'}`;
                };
                
                setBadge('diagGatewayStatus', data.gateway_ping);
                setBadge('diagInternetStatus', data.internet_wan);
                setBadge('diagDnsStatus', data.dns_resolution);
                setBadge('diagHiveApiStatus', data.hiveos_api);
                document.getElementById('diagGpuLogs').textContent = data.gpu_logs;
            }
        } else {
            document.getElementById('diagGpuLogs').textContent = 'Diagnostics API request failed.';
        }
    } catch (e) {
        console.error(e);
        document.getElementById('diagGpuLogs').textContent = 'Connection timeout checking diagnostics.';
    } finally {
        runBtn.disabled = false;
        runBtn.innerHTML = origHTML;
    }
}
