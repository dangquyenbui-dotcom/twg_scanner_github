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

    // Errors stay visible longer (4s) so the picker can read the message
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

function openModal(id) { document.getElementById(id).style.display = 'flex'; }
function closeModal(id) { document.getElementById(id).style.display = 'none'; }