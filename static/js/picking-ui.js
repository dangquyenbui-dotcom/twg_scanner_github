/* picking-ui.js - User Interface & Visuals */

function updateStatusUI(online) {
    const bar = document.getElementById('statusBar');
    const txt = document.getElementById('statusText');
    if (online) { 
        bar.classList.replace('status-offline', 'status-online'); txt.innerText = '📶 SYSTEM ONLINE'; 
    } else { 
        bar.classList.replace('status-online', 'status-offline'); txt.innerText = '🚫 OFFLINE'; 
    }
}

function updateSessionDisplay(sessionPicks) {
    const totalQty = sessionPicks.reduce((acc, p) => acc + p.qty, 0);
    const btnView = document.getElementById('scanCount');
    if(btnView) btnView.innerText = `(${totalQty})`;
    
    // Clear & Update Grid
    document.querySelectorAll('.picked-cell').forEach(c => c.innerText = "0");
    sessionPicks.forEach(p => { 
        const c = document.querySelector(`.picked-cell[data-line="${p.lineNo}"]`); 
        if(c) c.innerText = parseFloat(c.innerText||0) + p.qty; 
    });
    
    // Update Pending Count Badge
    const p = document.getElementById('pendingCount');
    if(p) {
        p.style.display = sessionPicks.length ? 'inline-block' : 'none'; 
        p.innerText = `${sessionPicks.length}`;
    }
}

function showToast(m, t='info', playSound=true) { 
    const c = document.getElementById('toastContainer'); 
    const d = document.createElement('div'); 
    const bg = t === 'error' ? '#e53e3e' : '#38a169';
    
    d.style.cssText = `background:${bg}; color:white; padding:10px 20px; border-radius:4px; margin-bottom:10px; box-shadow:0 4px 6px rgba(0,0,0,0.1); font-weight:bold; font-size:14px;`;
    d.innerText = m; 
    c.appendChild(d);
    
    if(playSound) playBeep(t==='error'?'error':'success');

    const duration = (t === 'error') ? 4000 : 2000;
    setTimeout(() => { d.style.opacity = '0'; setTimeout(() => d.remove(), 300); }, duration);
}

// --- BIN VALIDATION HELPER (Client-side safety filter) ---
/**
 * Validates a bin value on the client side:
 * - Must be exactly 15 characters long
 * - The 5th character (index 4) must be numeric (0-9)
 */
function isValidBin(binStr) {
    if (!binStr || binStr.length !== 15) return false;
    var ch = binStr.charAt(4);
    return ch >= '0' && ch <= '9';
}

// --- MODAL RENDERERS ---

function renderBinList(bins) {
    const l = document.getElementById('binList'); 
    l.innerHTML = ''; 

    // Client-side safety filter: only show bins with 15 chars and numeric 5th character
    const filteredBins = bins.filter(b => isValidBin(b.bin));

    if (!filteredBins.length) { 
        l.innerHTML = '<div class="text-center" style="padding:20px;">No Stock</div>'; 
        return; 
    }

    let html = `
        <table style="width:100%; border-collapse: collapse; font-size:12px;">
            <thead style="background:#edf2f7; color:#4a5568;">
                <tr>
                    <th style="text-align:left; padding:8px; border-bottom:2px solid #cbd5e0;">BIN</th>
                    <th style="text-align:center; padding:8px; border-bottom:2px solid #cbd5e0;">On Hand</th>
                    <th style="text-align:center; padding:8px; border-bottom:2px solid #cbd5e0;">Alloc</th>
                    <th style="text-align:center; padding:8px; border-bottom:2px solid #cbd5e0;">Avail</th>
                </tr>
            </thead>
            <tbody>`;

    filteredBins.forEach(b => { 
        const availStyle = b.avail > 0 ? 'font-weight:bold; color:#2d3748;' : 'color:#a0aec0;';
        html += `
            <tr style="border-bottom:1px solid #e2e8f0;">
                <td style="padding:10px 8px; font-weight:bold; color:#2b6cb0; font-size:14px;">${b.bin}</td>
                <td style="text-align:center; padding:10px 8px; font-size:14px;">${b.qty}</td>
                <td style="text-align:center; padding:10px 8px; font-size:14px; color:#e53e3e;">${b.alloc}</td>
                <td style="text-align:center; padding:10px 8px; font-size:14px; ${availStyle}">${b.avail}</td>
            </tr>`;
    });

    html += `</tbody></table><div style="text-align:right; font-size:10px; color:#a0aec0; padding:5px;">Tap outside to close</div>`;
    l.innerHTML = html;
}

function renderReviewList(sessionPicks) {
    const l = document.getElementById('reviewList'); 

    const htmlParts = sessionPicks.map((p, i) => {
        // --- ZERO PICK: distinct red styling with exception badge ---
        if (p.mode === 'Zero' && p.qty === 0) {
            var exLabel = p.exception || '—';
            return `
            <tr style="background:#fff5f5;">
                <td style="color:#e53e3e; font-weight:bold;">${p.item}</td>
                <td style="color:#a0aec0; font-style:italic;">—</td>
                <td style="font-weight:bold; color:#e53e3e;">0</td>
                <td style="text-align:center;">
                    <span style="display:inline-block; background:#fed7d7; color:#c53030; font-size:10px; font-weight:700; padding:2px 6px; border-radius:3px; letter-spacing:0.3px;">${exLabel}</span>
                </td>
                <td><button class="btn-small-action" style="background:#e53e3e; padding: 2px 8px;" onclick="removePick(${i})">X</button></td>
            </tr>`;
        }

        // --- NORMAL PICK: existing logic unchanged ---
        // Determine mode badge styling
        var modeLabel = p.mode || '—';
        var modeBg, modeColor;
        if (modeLabel === 'Auto') {
            modeBg = '#ebf8ff'; modeColor = '#2b6cb0'; // blue tones
        } else if (modeLabel === 'Manual') {
            modeBg = '#fefcbf'; modeColor = '#975a16'; // yellow/amber tones
        } else {
            modeBg = '#edf2f7'; modeColor = '#718096'; // grey fallback for old data
        }

        return `
        <tr>
            <td>${p.item}</td>
            <td>${p.bin}</td>
            <td style="font-weight:bold;">${p.qty}</td>
            <td style="text-align:center;">
                <span style="display:inline-block; background:${modeBg}; color:${modeColor}; font-size:10px; font-weight:700; padding:2px 6px; border-radius:3px; letter-spacing:0.3px;">${modeLabel}</span>
            </td>
            <td><button class="btn-small-action" style="background:#e53e3e; padding: 2px 8px;" onclick="removePick(${i})">X</button></td>
        </tr>`;
    });
    
    l.innerHTML = htmlParts.join('');
    document.getElementById('emptyReview').style.display = sessionPicks.length ? 'none' : 'block'; 
}

// --- PRE-SUBMIT EXCEPTIONS RENDERER ---
function renderExceptionList(shortLines) {
    const l = document.getElementById('exceptionList');
    
    // SHORTENED VALUES to prevent SQL truncation errors
    const EXCEPTION_CODES = [
        {val: "", label: "-- Select Reason --"},
        {val: "SHORT", label: "Short Pick (Not enough in bin)"},
        {val: "DMG", label: "Damaged (Found, unpickable)"},
        {val: "NOFND", label: "No Find (Bin empty/Missing)"},
        {val: "BADLC", label: "Wrong Location (Inv mismatch)"}
    ];

    let html = '';
    shortLines.forEach(line => {
        html += `
        <div style="margin-bottom: 12px; padding: 12px; background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 6px;">
            <div style="font-weight:bold; font-size:14px; color:#2d3748; margin-bottom:4px;">
                Ln ${line.lineNo}: <span style="color:#2b6cb0;">${line.item}</span>
            </div>
            <div style="font-size:12px; font-weight:bold; color:#e53e3e; margin-bottom:8px;">
                Needed: ${line.need} &nbsp;|&nbsp; Picked: ${line.picked}
            </div>
            <select class="scan-input exception-select" data-line="${line.lineNo}" style="width:100%; height:38px; font-size:14px; border-color:#cbd5e0;">
                ${EXCEPTION_CODES.map(c => `<option value="${c.val}">${c.label}</option>`).join('')}
            </select>
        </div>`;
    });
    
    l.innerHTML = html;
}

function openModal(id) { document.getElementById(id).style.display = 'flex'; }
function closeModal(id) { 
    document.getElementById(id).style.display = 'none'; 
    // After closing the bin modal, return focus to Scan Bin input
    if (id === 'binModal') {
        setTimeout(function() { safeFocus('binInput'); }, 100);
    }
}

// --- CLOSE MODAL ON OUTSIDE TAP ---
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.modal-overlay').forEach(function(overlay) {
        overlay.addEventListener('click', function(e) {
            // Only close if the tap was on the dark overlay itself, not on modal content
            if (e.target === overlay) {
                overlay.style.display = 'none';
                // After closing the bin modal, return focus to Scan Bin input
                if (overlay.id === 'binModal') {
                    setTimeout(function() { safeFocus('binInput'); }, 100);
                }
            }
        });
    });
});

// ============================================================
// CUSTOM DIALOGS — replaces browser alert() and confirm()
// Shows "TWG WMS App" instead of the IP address
// ============================================================

var _twgDialogResolve = null;

function _createDialogOverlay() {
    var existing = document.getElementById('twgDialogOverlay');
    if (existing) return existing;

    var overlay = document.createElement('div');
    overlay.id = 'twgDialogOverlay';
    overlay.style.cssText = 'position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6); display:none; justify-content:center; align-items:center; z-index:9999;';

    overlay.innerHTML = 
        '<div id="twgDialogBox" style="background:white; width:88%; max-width:320px; border-radius:10px; box-shadow:0 10px 30px rgba(0,0,0,0.3); overflow:hidden;">' +
            '<div style="background:#1a202c; padding:10px 14px; display:flex; align-items:center; gap:8px;">' +
                '<span style="font-size:16px;">📦</span>' +
                '<span style="color:#a0aec0; font-size:12px; font-weight:700; letter-spacing:0.5px;">TWG WMS App</span>' +
            '</div>' +
            '<div id="twgDialogMsg" style="padding:18px 16px; font-size:14px; color:#2d3748; line-height:1.5; white-space:pre-wrap; word-wrap:break-word;"></div>' +
            '<div id="twgDialogButtons" style="padding:10px 16px 14px; display:flex; gap:10px; justify-content:flex-end;"></div>' +
        '</div>';

    document.body.appendChild(overlay);
    return overlay;
}

/**
 * Custom alert — shows a branded dialog with OK button.
 * Returns a Promise that resolves when OK is tapped.
 * Usage: await twgAlert("Something happened");
 *    or: twgAlert("Something happened").then(function() { ... });
 */
function twgAlert(message) {
    return new Promise(function(resolve) {
        var overlay = _createDialogOverlay();
        document.getElementById('twgDialogMsg').textContent = message;

        var btnArea = document.getElementById('twgDialogButtons');
        btnArea.innerHTML = '<button id="twgDialogOk" style="flex:1; height:40px; border:none; border-radius:6px; background:#1a202c; color:white; font-weight:700; font-size:14px; cursor:pointer;">OK</button>';

        overlay.style.display = 'flex';

        document.getElementById('twgDialogOk').onclick = function() {
            overlay.style.display = 'none';
            resolve();
        };
    });
}

/**
 * Custom confirm — shows a branded dialog with Cancel / OK buttons.
 * Returns a Promise that resolves true (OK) or false (Cancel).
 * Usage: var ok = await twgConfirm("Are you sure?");
 *    or: twgConfirm("Are you sure?").then(function(ok) { if(ok) ... });
 */
function twgConfirm(message) {
    return new Promise(function(resolve) {
        var overlay = _createDialogOverlay();
        document.getElementById('twgDialogMsg').textContent = message;

        var btnArea = document.getElementById('twgDialogButtons');
        btnArea.innerHTML = 
            '<button id="twgDialogCancel" style="flex:1; height:40px; border:2px solid #cbd5e0; border-radius:6px; background:white; color:#4a5568; font-weight:700; font-size:14px; cursor:pointer;">Cancel</button>' +
            '<button id="twgDialogOk" style="flex:1; height:40px; border:none; border-radius:6px; background:#1a202c; color:white; font-weight:700; font-size:14px; cursor:pointer;">OK</button>';

        overlay.style.display = 'flex';

        document.getElementById('twgDialogCancel').onclick = function() {
            overlay.style.display = 'none';
            resolve(false);
        };
        document.getElementById('twgDialogOk').onclick = function() {
            overlay.style.display = 'none';
            resolve(true);
        };
    });
}