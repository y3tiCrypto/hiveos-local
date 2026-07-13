// HiveOS Fleet Manager SPA Frontend Script
document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const fleetGridContainer = document.getElementById('fleetGridContainer');
    const refreshFleetBtn = document.getElementById('refreshFleetBtn');
    const addRigForm = document.getElementById('addRigForm');
    const addRigModalEl = document.getElementById('addRigModal');
    const addRigError = document.getElementById('addRigError');
    
    // Log Modal Elements
    const minerLogModalEl = document.getElementById('minerLogModal');
    const minerLogConsole = document.getElementById('minerLogConsole');
    const activeRigLogName = document.getElementById('activeRigLogName');
    
    // Summary Cards Elements
    const fleetStatusText = document.getElementById('fleetStatusText');
    const fleetHashrateText = document.getElementById('fleetHashrateText');
    const fleetTempText = document.getElementById('fleetTempText');
    const fleetPowerText = document.getElementById('fleetPowerText');

    // Bootstrap Instances
    const addRigModal = new bootstrap.Modal(addRigModalEl);
    const minerLogModal = new bootstrap.Modal(minerLogModalEl);
    const statusToastEl = document.getElementById('statusToast');
    const statusToast = new bootstrap.Toast(statusToastEl);

    // Global variables
    let logPollInterval = null;
    let currentLogRigId = null;

    // Toast Utility Helper
    function showToast(message, isSuccess = true) {
        const toastEl = document.getElementById('statusToast');
        const iconEl = document.getElementById('toastIcon');
        const msgEl = document.getElementById('toastMessage');

        toastEl.className = `toast align-items-center border-0 text-white ${isSuccess ? 'bg-success' : 'bg-danger'}`;
        iconEl.className = isSuccess ? 'bi bi-check-circle-fill fs-5' : 'bi bi-x-circle-fill fs-5';
        msgEl.textContent = message;
        statusToast.show();
    }

    // Fetch Fleet data and update dashboard
    async function fetchFleet() {
        refreshFleetBtn.disabled = true;
        const icon = refreshFleetBtn.querySelector('i');
        icon.className = 'bi bi-arrow-clockwise spin-animation';

        try {
            const res = await fetch('/api/fleet/stats');
            if (res.ok) {
                const data = await res.json();
                if (data.success) {
                    updateSummaryCards(data.summary);
                    renderRigs(data.rigs);
                }
            } else {
                showToast("Failed to fetch fleet stats.", false);
            }
        } catch (err) {
            console.error(err);
            showToast("Network error polling fleet.", false);
        } finally {
            refreshFleetBtn.disabled = false;
            icon.className = 'bi bi-arrow-clockwise';
        }
    }

    function updateSummaryCards(summary) {
        fleetStatusText.textContent = `${summary.online_rigs} / ${summary.total_rigs}`;
        fleetHashrateText.textContent = `${summary.total_hashrate.toFixed(2)} MH/s`;
        fleetTempText.textContent = `${summary.avg_temp.toFixed(1)}°C`;
        fleetPowerText.textContent = `${summary.total_power} W`;
    }

    function renderRigs(rigs) {
        fleetGridContainer.innerHTML = '';

        if (rigs.length === 0) {
            fleetGridContainer.innerHTML = `
                <div class="col-12 text-center py-5">
                    <i class="bi bi-display text-muted fs-1 mb-3 d-block"></i>
                    <h3 class="h5 fw-bold text-muted">No Rigs Configured</h3>
                    <p class="text-secondary small mb-4">You haven't added any HiveOS local dashboard nodes to your fleet manager yet.</p>
                    <button class="btn btn-primary btn-sm fw-semibold" data-bs-toggle="modal" data-bs-target="#addRigModal">
                        <i class="bi bi-plus-circle-fill"></i> Register Your First Rig
                    </button>
                </div>
            `;
            return;
        }

        rigs.forEach(rig => {
            const cardCol = document.createElement('div');
            cardCol.className = 'col-lg-6';

            if (rig.online) {
                const stats = rig.stats;
                const activeMiner = stats.system.active_miner;
                const coin = stats.system.coin || 'Unknown';
                const gpus = stats.gpus || [];
                const cpu = stats.system.cpu || {};
                
                // Construct GPU listings summary
                let gpuElementsHTML = '';
                if (gpus.length > 0) {
                    gpuElementsHTML = `
                        <div class="table-responsive mt-3">
                            <table class="table table-sm table-dark table-borderless align-middle mb-0" style="font-size: 0.85rem;">
                                <thead>
                                    <tr class="text-muted border-bottom border-secondary-subtle">
                                        <th>GPU</th>
                                        <th>Brand</th>
                                        <th>Temp/Fan</th>
                                        <th>Power</th>
                                        <th class="text-end">Hashrate</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${gpus.map(g => `
                                        <tr>
                                            <td class="fw-semibold text-white">#${g.index}</td>
                                            <td><span class="brand-${g.brand.toLowerCase()}">${g.brand}</span></td>
                                            <td>${g.temp}°C / ${g.fan}%</td>
                                            <td>${g.power}W</td>
                                            <td class="text-end font-monospace text-primary fw-semibold">${g.hashrate} MH/s</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    `;
                } else {
                    gpuElementsHTML = `<p class="small text-muted mt-2 mb-0"><i class="bi bi-info-circle"></i> No active GPUs detected on this rig.</p>`;
                }

                // Compile CPU miner block
                let cpuHTML = '';
                if (cpu.hashrate > 0) {
                    cpuHTML = `
                        <div class="mt-2 p-2 rounded bg-dark-card d-flex justify-content-between align-items-center border border-secondary-subtle" style="font-size: 0.8rem;">
                            <span class="text-muted"><i class="bi bi-cpu text-info"></i> CPU Mining (${cpu.model})</span>
                            <span class="font-monospace text-info-emphasis fw-bold">${(cpu.hashrate / 1000.0).toFixed(1)} KH/s</span>
                        </div>
                    `;
                }

                cardCol.innerHTML = `
                    <div class="card glass-card h-100">
                        <div class="card-body d-flex flex-column justify-content-between">
                            <div>
                                <!-- Header info -->
                                <div class="d-flex justify-content-between align-items-center mb-3 pb-2 border-bottom border-secondary-subtle">
                                    <div class="d-flex align-items-center gap-2">
                                        <span class="pulse-online" title="Online"></span>
                                        <h3 class="h5 fw-bold mb-0 text-white">${rig.name}</h3>
                                    </div>
                                    <div class="d-flex gap-1">
                                        <span class="badge badge-coin">Coin: ${coin}</span>
                                        <span class="badge badge-miner">${activeMiner}</span>
                                    </div>
                                </div>

                                <!-- Rig Specs details -->
                                <div class="row g-2 mb-2" style="font-size: 0.85rem;">
                                    <div class="col-6">
                                        <span class="text-muted d-block">IP / Port</span>
                                        <span class="fw-semibold">${rig.ip}:${rig.port}</span>
                                    </div>
                                    <div class="col-6">
                                        <span class="text-muted d-block">Uptime</span>
                                        <span class="fw-semibold">${stats.system.uptime}</span>
                                    </div>
                                    <div class="col-6">
                                        <span class="text-muted d-block">Rig ID</span>
                                        <span class="fw-semibold font-monospace">${stats.system.rig_id}</span>
                                    </div>
                                    <div class="col-6">
                                        <span class="text-muted d-block">RAM Usage</span>
                                        <span class="fw-semibold">${stats.system.ram_used_pct}% of ${stats.system.ram_total_gb} GB</span>
                                    </div>
                                </div>

                                ${cpuHTML}
                                ${gpuElementsHTML}
                            </div>

                            <!-- Controls buttons -->
                            <div class="mt-4 pt-3 border-top border-secondary-subtle d-flex flex-wrap gap-2">
                                <button class="btn btn-sm btn-outline-warning fw-semibold px-3 rig-control-btn" data-rig-id="${rig.id}" data-action="/api/miner/control" data-payload='{"action":"restart"}' data-confirm-msg="Restart miner daemon on ${rig.name}?">
                                    <i class="bi bi-arrow-counterclockwise"></i> Restart Miner
                                </button>
                                <button class="btn btn-sm btn-outline-danger fw-semibold px-3 rig-control-btn" data-rig-id="${rig.id}" data-action="/api/system/reboot" data-payload='{}' data-confirm-msg="Are you sure you want to REBOOT ${rig.name}?">
                                    <i class="bi bi-power"></i> Reboot
                                </button>
                                <button class="btn btn-sm btn-outline-primary fw-semibold px-3 view-log-btn" data-rig-id="${rig.id}" data-rig-name="${rig.name}">
                                    <i class="bi bi-terminal"></i> Logs
                                </button>
                                <a href="http://${rig.ip}:${rig.port}" target="_blank" class="btn btn-sm btn-outline-secondary fw-semibold ms-auto px-3">
                                    <i class="bi bi-box-arrow-up-right"></i> Open Link
                                </a>
                                <button class="btn btn-sm btn-outline-secondary text-danger border-danger-subtle delete-rig-btn px-2" data-rig-id="${rig.id}" data-rig-name="${rig.name}" title="Remove Rig">
                                    <i class="bi bi-trash"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            } else {
                // Offline rendering state
                cardCol.innerHTML = `
                    <div class="card glass-card h-100 border-danger border-opacity-25 bg-danger bg-opacity-10">
                        <div class="card-body d-flex flex-column justify-content-between text-center py-4">
                            <div>
                                <div class="d-flex align-items-center justify-content-center gap-2 mb-3">
                                    <span class="pulse-offline" title="Offline"></span>
                                    <h3 class="h5 fw-bold mb-0 text-white">${rig.name}</h3>
                                </div>
                                <p class="text-danger small mb-1 fw-semibold"><i class="bi bi-exclamation-triangle-fill"></i> Host Offline or Connection Failed</p>
                                <p class="text-muted small font-monospace mb-4 bg-dark bg-opacity-50 p-2 rounded">${rig.ip}:${rig.port} - ${rig.error || 'Connection timed out.'}</p>
                            </div>

                            <div class="d-flex gap-2 justify-content-center">
                                <button class="btn btn-sm btn-outline-light px-4 retry-rig-btn" data-rig-id="${rig.id}">
                                    <i class="bi bi-arrow-repeat"></i> Retry Connection
                                </button>
                                <a href="http://${rig.ip}:${rig.port}" target="_blank" class="btn btn-sm btn-outline-secondary px-3 text-white border-secondary">
                                    <i class="bi bi-box-arrow-up-right"></i> Local Link
                                </a>
                                <button class="btn btn-sm btn-outline-danger px-3 delete-rig-btn" data-rig-id="${rig.id}" data-rig-name="${rig.name}">
                                    <i class="bi bi-trash"></i> Remove
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            }

            fleetGridContainer.appendChild(cardCol);
        });

        // Bind Controls listeners
        bindCardActions();
    }

    function bindCardActions() {
        // Control actions buttons (Restart Miner, Reboot, Shutdown)
        document.querySelectorAll('.rig-control-btn').forEach(btn => {
            btn.addEventListener('click', async function() {
                const rigId = this.dataset.rigId;
                const endpoint = this.dataset.action;
                const payload = JSON.parse(this.dataset.payload);
                const confirmMsg = this.dataset.confirmMsg;

                if (!confirm(confirmMsg)) return;

                this.disabled = true;
                const origHTML = this.innerHTML;
                this.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Sending...`;

                try {
                    const res = await fetch('/api/fleet/control', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            rig_id: rigId,
                            endpoint: endpoint,
                            payload: payload
                        })
                    });
                    const data = await res.json();
                    if (res.ok && data.success) {
                        showToast(data.message || "Command successfully executed!", true);
                    } else {
                        showToast(data.message || "Failed to execute command on target rig.", false);
                    }
                } catch (err) {
                    console.error(err);
                    showToast("Failed to communicate with Fleet Manager proxy.", false);
                } finally {
                    this.disabled = false;
                    this.innerHTML = origHTML;
                }
            });
        });

        // Delete rig buttons
        document.querySelectorAll('.delete-rig-btn').forEach(btn => {
            btn.addEventListener('click', async function() {
                const rigId = this.dataset.rigId;
                const name = this.dataset.rigName;

                if (!confirm(`Are you sure you want to remove rig '${name}' from Fleet Manager monitoring?`)) return;

                try {
                    const res = await fetch(`/api/rigs/${rigId}`, { method: 'DELETE' });
                    const data = await res.json();
                    if (res.ok && data.success) {
                        showToast(data.message, true);
                        fetchFleet();
                    } else {
                        showToast(data.message || "Failed to remove rig.", false);
                    }
                } catch (err) {
                    console.error(err);
                    showToast("Failed to contact API.", false);
                }
            });
        });

        // Retry connection buttons
        document.querySelectorAll('.retry-rig-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                fetchFleet();
            });
        });

        // Terminal Log triggers
        document.querySelectorAll('.view-log-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const rigId = this.dataset.rigId;
                const name = this.dataset.rigName;
                
                activeRigLogName.textContent = name;
                minerLogConsole.textContent = "Connecting to rig and fetching active miner logs...\n";
                currentLogRigId = rigId;

                minerLogModal.show();
            });
        });
    }

    // Modal Logs Polling handlers
    async function fetchRigLog() {
        if (!currentLogRigId) return;
        try {
            const res = await fetch(`/api/fleet/log/${currentLogRigId}`);
            if (res.ok) {
                const data = await res.json();
                if (data.success && data.log) {
                    minerLogConsole.textContent = data.log;
                    minerLogConsole.scrollTop = minerLogConsole.scrollHeight;
                } else {
                    minerLogConsole.textContent = `[Error] ${data.message || 'Log file is currently empty.'}`;
                }
            } else {
                minerLogConsole.textContent = `[Error] Rig returned HTTP status code ${res.status}.`;
            }
        } catch (err) {
            console.error(err);
            minerLogConsole.textContent = `[Connection Error] Failed to fetch log updates.`;
        }
    }

    minerLogModalEl.addEventListener('shown.bs.modal', () => {
        fetchRigLog();
        logPollInterval = setInterval(fetchRigLog, 2000);
    });

    minerLogModalEl.addEventListener('hidden.bs.modal', () => {
        if (logPollInterval) {
            clearInterval(logPollInterval);
            logPollInterval = null;
        }
        currentLogRigId = null;
    });

    // Add Rig Form submit trigger
    addRigForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        addRigError.classList.add('d-none');

        const submitBtn = document.getElementById('addRigSubmitBtn');
        const origHTML = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Verifying...`;

        const name = document.getElementById('rigName').value.trim();
        const ip = document.getElementById('rigIp').value.trim();
        const port = parseInt(document.getElementById('rigPort').value.trim());
        const pin = document.getElementById('rigPin').value.trim();

        try {
            const res = await fetch('/api/rigs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    name: name,
                    ip: ip,
                    port: port,
                    pin: pin
                })
            });
            const data = await res.json();
            if (res.ok && data.success) {
                showToast(data.message, true);
                addRigForm.reset();
                addRigModal.hide();
                fetchFleet();
            } else {
                addRigError.textContent = data.message || "Failed to register rig.";
                addRigError.classList.remove('d-none');
            }
        } catch (err) {
            console.error(err);
            addRigError.textContent = "Network timeout trying to verify credentials. Make sure port is open.";
            addRigError.classList.remove('d-none');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = origHTML;
        }
    });

    // Refresh button click
    refreshFleetBtn.addEventListener('click', fetchFleet);

    // Initial page load fetch
    fetchFleet();
});
