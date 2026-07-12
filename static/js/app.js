// Global state to store overclock configurations
let activeOverclocks = {};

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
                method: 'POST'
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

    // 4. Poll for GPU Stats and Rig Config
    fetchStats(); // Initial load
    const statsInterval = setInterval(fetchStats, 5000); // Poll every 5s

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
            return;
        }
        
        if (!response.ok) throw new Error("Network response was not ok");
        
        const data = await response.json();
        
        // Hide login if active
        document.getElementById('loginOverlay').classList.add('d-none');
        document.getElementById('revertSettingsBtn').classList.remove('d-none');
        
        // Save OC data globally to prefill forms
        activeOverclocks = data.overclocks;
        
        // Update header & badges
        document.getElementById('localIpAddress').textContent = data.system.local_ip + ':1337';
        
        const demoBadge = document.getElementById('demoModeBadge');
        if (data.system.is_demo) {
            demoBadge.classList.remove('d-none');
        } else {
            demoBadge.classList.add('d-none');
        }
        
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
                'Content-Type': 'application/json'
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
