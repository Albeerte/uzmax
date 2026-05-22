// ===== Robot Control — Client-side Logic =====

let holdTimeout;
let lastSentCmd = '';
const statusEl = document.getElementById('status');

// ─── Command Labels & Button ID Map ────────────────────────────
const CMD_LABELS = {
    robot_fwd: 'Forward', robot_back: 'Reverse',
    spin_ccw: 'Turning Left', spin_cw: 'Turning Right',
    fwd_left: 'Forward-Left', fwd_right: 'Forward-Right',
    back_left: 'Reverse-Left', back_right: 'Reverse-Right',
    stop: 'Stop'
};

const CMD_BTN_MAP = {
    robot_fwd: 'btn-fwd', robot_back: 'btn-rev',
    spin_ccw: 'btn-left', spin_cw: 'btn-right',
    fwd_left: 'btn-fl', fwd_right: 'btn-fr',
    back_left: 'btn-bl', back_right: 'btn-br',
    stop: 'btn-stop'
};

// ─── Send command to server ────────────────────────────────────
function issueCommand(cmd) {
    fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmd })
    }).then(r => r.json()).then(data => {
        const badge = document.getElementById('connection');
        const connText = document.getElementById('conn-text');
        if (data.serial_connected) {
            badge.className = 'connection-badge online';
            connText.textContent = 'Hardware Connected';
        } else {
            badge.className = 'connection-badge offline';
            connText.textContent = 'Simulation Mode';
        }
    }).catch(() => {});
}

// ─── Highlight active button ───────────────────────────────────
function setActive(cmd) {
    document.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
    if (CMD_BTN_MAP[cmd]) {
        document.getElementById(CMD_BTN_MAP[cmd])?.classList.add('active');
    }
}

// ─── Engage / Disengage drive ──────────────────────────────────
function engageDrive(cmd) {
    if (cmd === 'stop') {
        issueCommand('stop');
        lastSentCmd = '';
        setActive('stop');
        statusEl.innerHTML = '&#x25A0; Emergency Stop';
        statusEl.className = 'stopped';
        setTimeout(() => {
            statusEl.innerHTML = '&#x25CF; System Idle';
            statusEl.className = '';
            setActive('');
        }, 800);
        return;
    }

    // Don't re-send the same command
    if (cmd === lastSentCmd) return;
    lastSentCmd = cmd;

    issueCommand(cmd);
    setActive(cmd);

    statusEl.innerHTML = `&#x25B6; ${CMD_LABELS[cmd] || cmd}`;
    statusEl.className = 'active-cmd';

    clearTimeout(holdTimeout);
    holdTimeout = setTimeout(() => {
        issueCommand('stop');
        lastSentCmd = '';
        statusEl.innerHTML = '&#x23F1; Auto-Stopped (3s limit)';
        statusEl.className = 'stopped';
        setActive('');
        setTimeout(() => {
            statusEl.innerHTML = '&#x25CF; System Idle';
            statusEl.className = '';
        }, 1500);
    }, 3000);
}

function disengageDrive() {
    clearTimeout(holdTimeout);
    issueCommand('stop');
    lastSentCmd = '';
    setActive('');
    statusEl.innerHTML = '&#x25CF; System Idle';
    statusEl.className = '';
}

// ─── Button touch/click events ─────────────────────────────────
document.querySelectorAll('.btn').forEach(btn => {
    const command = btn.getAttribute('data-cmd');
    btn.addEventListener('mousedown', () => engageDrive(command));
    btn.addEventListener('mouseup', disengageDrive);
    btn.addEventListener('mouseleave', disengageDrive);
    btn.addEventListener('touchstart', (e) => { e.preventDefault(); engageDrive(command); });
    btn.addEventListener('touchend', (e) => { e.preventDefault(); disengageDrive(); });
});

// ─── Keyboard: combo detection for 8-directional ───────────────
const keysHeld = new Set();

function resolveCommand() {
    const w = keysHeld.has('w');
    const a = keysHeld.has('a');
    const s = keysHeld.has('s');
    const d = keysHeld.has('d');

    // Diagonal combos
    if (w && a) return 'fwd_left';
    if (w && d) return 'fwd_right';
    if (s && a) return 'back_left';
    if (s && d) return 'back_right';

    // Single directions
    if (w) return 'robot_fwd';
    if (s) return 'robot_back';
    if (a) return 'spin_ccw';
    if (d) return 'spin_cw';

    return null;
}

document.addEventListener('keydown', (e) => {
    const key = e.key.toLowerCase();
    if (key === ' ') { e.preventDefault(); engageDrive('stop'); return; }
    if ('wasd'.includes(key) && !keysHeld.has(key)) {
        keysHeld.add(key);
        const cmd = resolveCommand();
        if (cmd) engageDrive(cmd);
    }
});

document.addEventListener('keyup', (e) => {
    const key = e.key.toLowerCase();
    if ('wasd'.includes(key)) {
        keysHeld.delete(key);
        const cmd = resolveCommand();
        if (cmd) {
            // Switch to new direction (e.g., W+A released A -> switch to FWD)
            lastSentCmd = '';  // force re-send
            engageDrive(cmd);
        } else {
            disengageDrive();
        }
    }
});

// ─── Initial connection check ──────────────────────────────────
issueCommand('ping');
