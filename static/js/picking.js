/* * TWG Scanner - Picking Logic
 * Version: 1.5 (Live Write Edition)
 * File: static/js/picking.js
 */

// ==========================================================================
// 1. GLOBAL STATE & CONFIGURATION
// ==========================================================================

// Ensure SERVER_DATA is available (passed from Flask template)
const SO_NUMBER = (typeof SERVER_DATA !== 'undefined' && SERVER_DATA.soNumber) ? SERVER_DATA.soNumber : ""; 

// Core State Variables
let sessionPicks = [];          // Array to store scanned items
let binCache = {};              // Cache for bin lookups to reduce network calls
let selectedItemCode = null;    // Currently selected item from the main grid
let selectedLineNo = null;      // Currently selected line number
let currentBinMaxQty = 999999;  // Max limit for the current bin (Inventory)
let currentOrderMaxQty = 999999;// Max limit for the current order line
let currentBin = "";            // Currently validated bin
let isAutoMode = true;          // Toggle between Auto (Speed) and Manual (Qty)
let isSubmitting = false;       // Lock to prevent double submission

// ==========================================================================
// 2. UTILITY FUNCTIONS
// ==========================================================================

/**
 * Generates a UUID v4.
 * Fallback for environments where crypto.randomUUID() is not available (HTTP).
 */
function generateUUID() {
    // 1. Try native crypto (Secure Contexts only - HTTPS)
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }
    // 2. Fallback (HTTP / Older Browsers)
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

function log(msg) {
    const c = document.getElementById('debugConsole');
    if(!c) return;
    const d = document.createElement('div');
    d.innerText = `[${new Date().toLocaleTimeString().split(' ')[0]}] ${msg}`; 
    c.prepend(d); 
    console.log(msg);
}

function toggleDebug() {
    const c = document.getElementById('debugConsole');
    if(c) c.style.display = (c.style.display === 'none') ? 'block' : 'none';
}

function forceFullscreen() {
    const doc = window.document; 
    const docEl = doc.documentElement;
    const requestFullScreen = docEl.requestFullscreen || docEl.mozRequestFullScreen || docEl.webkitRequestFullScreen || docEl.msRequestFullscreen;
    
    if(!doc.fullscreenElement && !doc.mozFullScreenElement && !doc.webkitFullscreenElement && !doc.msFullscreenElement) {
        if(requestFullScreen) requestFullScreen.call(docEl).catch(e=>{});
    }
}

// ==========================================================================
// 3. AUDIO ENGINE
// ==========================================================================

const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

/**
 * Attempts to wake up the Audio Context.
 * Mobile browsers suspend audio until a user interaction occurs.
 */
function unlockAudio() { 
    if (audioCtx.state === 'suspended') { 
        audioCtx.resume().then(() => log("Audio Resumed")); 
    }
}

// Bind unlock to common interaction events
['touchstart', 'click', 'keydown', 'mousedown'].forEach(evt => {
    document.body.addEventListener(evt, unlockAudio, {once:false, passive:true});
});

function playBeep(type) {
    try {
        // Ensure context is running
        if (audioCtx.state === 'suspended') audioCtx.resume();
        
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.connect(gain); 
        gain.connect(audioCtx.destination);
        
        if (type === 'success') { 
            // High Pitch Success Beep (Sine Wave)
            osc.frequency.value = 1500; 
            osc.type = 'sine';
            gain.gain.value = 0.3; 
            osc.start(); 
            osc.stop(audioCtx.currentTime + 0.15); 
        } else { 
            // Low Pitch Error Buzz (Sawtooth Wave)
            osc.frequency.value = 150; 
            osc.type = 'sawtooth';
            gain.gain.value = 0.4; 
            osc.start(); 
            osc.stop(audioCtx.currentTime + 0.4); 
        }
    } catch(e) { 
        console.error("Audio Error:", e); 
    }
}

// ==========================================================================
// 4. INITIALIZATION
// ==========================================================================

window.onload = function() {
    log("App Loaded - v1.5");
    
    // Restore session if valid
    if(SO_NUMBER) { 
        loadFromLocal(); 
        updateSessionDisplay(); 
        updateMode(); 
    }
    
    // Check initial network status
    updateStatusUI(navigator.onLine);
    
    // Focus the correct input
    const soInput = document.getElementById('soInput');
    if(soInput) setTimeout(() => soInput.focus(), 200);
    
    // Attach Listeners
    attachScannerListeners();
    document.addEventListener('click', forceFullscreen, {once:true});
    document.addEventListener('touchstart', forceFullscreen, {once:true});
};

window.addEventListener('online', () => updateStatusUI(true));
window.addEventListener('offline', () => updateStatusUI(false));

function updateStatusUI(online) {
    const bar = document.getElementById('statusBar');
    const txt = document.getElementById('statusText');
    if (online) { 
        bar.classList.replace('status-offline', 'status-online'); 
        txt.innerText = '📶 SYSTEM ONLINE'; 
    } else { 
        bar.classList.replace('status-online', 'status-offline'); 
        txt.innerText = '🚫 OFFLINE'; 
    }
}

// ==========================================================================
// 5. SCANNER INPUT HANDLING
// ==========================================================================

function attachScannerListeners() {
    const inputs = document.querySelectorAll('input.scan-input');
    inputs.forEach(el => {
        let debounceTimer;

        // Listener 1: "Enter" Key (Standard Scanners)
        el.addEventListener('keydown', (e) => { 
            if (e.key === 'Enter' || e.keyCode === 13) { 
                e.preventDefault(); 
                clearTimeout(debounceTimer); // Cancel any pending auto-submit
                handleAction(el); 
            } 
        });

        // Listener 2: "Input" Event (Keyboard Emulation Scanners)
        el.addEventListener('input', () => { 
            clearTimeout(debounceTimer); 
            // Wait 150ms for the scanner to finish typing
            debounceTimer = setTimeout(() => { 
                if (el.value.length > 2) { 
                    log(`Auto-Submitting: ${el.id}`); 
                    handleAction(el); 
                } 
            }, 150); 
        });
    });
}

function handleAction(el) {
    if (el.value.trim() === "") return;
    
    unlockAudio(); // Ensure audio is ready
    
    // Route action based on input ID
    if (el.id === 'soInput') document.getElementById('soForm').submit();
    else if (el.id === 'binInput') validateBin();
    else if (el.id === 'itemInput') handleItemScan();
    else if (el.id === 'qtyInput') addToSession(); 
}

/**
 * Toggles the software keyboard for manual entry.
 */
function toggleKeyboard(inputId) {
    unlockAudio(); 
    const el = document.getElementById(inputId); 
    if (!el) return;
    
    if (el.inputMode === 'none') { 
        el.inputMode = 'text'; 
        log(`${inputId} Keyboard: ON`); 
        el.blur(); 
        setTimeout(() => el.focus(), 50); 
    } else { 
        el.inputMode = 'none'; 
        log(`${inputId} Keyboard: OFF`); 
        el.blur(); 
    }
}

/**
 * Focuses an element without triggering the soft keyboard (for scanning).
 */
function safeFocus(id) {
    const el = document.getElementById(id); 
    if (!el) return;
    
    el.inputMode = 'none'; 
    el.focus(); 
    // Re-enable text mode after focus is set
    setTimeout(() => { el.inputMode = 'text'; }, 300); 
}

// ==========================================================================
// 6. STORAGE & SESSION MANAGEMENT
// ==========================================================================

function saveToLocal() {
    if(!SO_NUMBER) return;
    
    // Generate a Batch ID if one doesn't exist
    if (!localStorage.getItem(`twg_batch_id_${SO_NUMBER}`)) {
        localStorage.setItem(`twg_batch_id_${SO_NUMBER}`, generateUUID());
    }
    
    localStorage.setItem(`twg_picks_${SO_NUMBER}`, JSON.stringify(sessionPicks));
    
    // Update Pending Count Badge
    const p = document.getElementById('pendingCount');
    if(p) {
        p.style.display = sessionPicks.length ? 'inline-block' : 'none'; 
        p.innerText = `${sessionPicks.length}`;
    }
}

function loadFromLocal() { 
    const s = localStorage.getItem(`twg_picks_${SO_NUMBER}`); 
    if(s) {
        try { sessionPicks = JSON.parse(s); } catch(e){ console.error("Load Failed", e); } 
    }
}

function clearLocal() { 
    localStorage.removeItem(`twg_picks_${SO_NUMBER}`); 
    localStorage.removeItem(`twg_batch_id_${SO_NUMBER}`); 
    sessionPicks = []; 
    updateSessionDisplay(); 
    saveToLocal(); // Saves empty state
}

// ==========================================================================
// 7. PICKING LOGIC (CORE)
// ==========================================================================

function updateMode() {
    unlockAudio();
    const modeEl = document.querySelector('input[name="pickMode"]:checked');
    if(!modeEl) return;
    
    isAutoMode = modeEl.value === 'auto';
    const qtyInput = document.getElementById('qtyInput');
    
    if (isAutoMode) {
        // AUTO MODE: Read-only Qty, Hidden Buttons
        qtyInput.readOnly = true; 
        qtyInput.value = 1; 
        document.getElementById('btnMinus').classList.add('d-none'); 
        document.getElementById('btnPlus').classList.add('d-none'); 
        document.getElementById('addBtnContainer').classList.add('d-none');
        
        // Auto-focus Item input if Bin is ready
        if(currentBin) setTimeout(() => safeFocus('itemInput'), 100);
    } else {
        // MANUAL MODE: Editable Qty, Visible Buttons
        qtyInput.readOnly = false; 
        document.getElementById('btnMinus').classList.remove('d-none'); 
        document.getElementById('btnPlus').classList.remove('d-none'); 
        document.getElementById('addBtnContainer').classList.remove('d-none');
    }
}

/**
 * Handles user tapping a row in the main Item Grid.
 */
function selectRow(row, itemCode, remainingQty, lineNo) {
    unlockAudio();
    
    // Highlight UI
    document.querySelectorAll('.item-row').forEach(r => r.classList.remove('active-row'));
    row.classList.add('active-row');
    
    // Update State
    selectedItemCode = itemCode; 
    selectedLineNo = lineNo; 
    currentOrderMaxQty = remainingQty;
    
    // Reset Inputs
    document.getElementById('binInput').value = ''; 
    document.getElementById('itemInput').value = '';
    
    updateSessionDisplay();
    
    // Reset Bin Limits temporarily
    currentBinMaxQty = 999999; 
    
    // Focus Bin Input
    setTimeout(() => { safeFocus('binInput'); }, 100);
    
    // Background fetch of bins
    prefetchBins(itemCode);
}

/**
 * Validates the scanned Bin against the Database/Cache.
 */
function validateBin() {
    const binVal = document.getElementById('binInput').value.trim();
    if(!binVal || !selectedItemCode) return;
    
    log(`Validating Bin: ${binVal}`);
    
    // 1. Check Cache first (Avoids network latency)
    if (binCache[selectedItemCode]) {
        const f = binCache[selectedItemCode].find(b => b.bin === binVal);
        if (f) { 
            currentBinMaxQty = f.qty; 
            currentBin = binVal; 
            showToast(`Bin Verified. Max: ${f.qty}`, 'success'); 
            safeFocus('itemInput'); 
            return; 
        }
    }
    
    // 2. Check Network Status
    if (!navigator.onLine) { 
        showToast("Offline: Cannot verify.", 'warning'); 
        return; 
    }
    
    // 3. Server Check
    fetch('/validate_bin', {
        method: 'POST', 
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ bin: binVal, item: selectedItemCode })
    })
    .then(r => r.json())
    .then(d => {
        if(d.status === 'success') { 
            currentBinMaxQty = d.onhand; 
            currentBin = binVal; 
            showToast(`Bin Verified. Max: ${d.onhand}`, 'success'); 
            safeFocus('itemInput'); 
        } else { 
            showToast(d.msg, 'error'); 
            document.getElementById('binInput').value=''; 
            safeFocus('binInput'); 
        }
    })
    .catch(() => showToast("Network Error", 'error'));
}

/**
 * Adds the item to the sessionPicks array.
 */
function addToSession() {
    // Basic Checks
    if(!selectedItemCode) { showToast("Select item first!", 'warning'); return; }
    if(document.getElementById('binInput').value.trim() !== currentBin) { showToast("Validate bin first", 'warning'); return; }
    
    let qty = isAutoMode ? 1 : (parseFloat(document.getElementById('qtyInput').value)||0);
    if(qty <= 0) return;

    let success = false;
    try {
        // Calculate Totals
        const currentLineTotal = sessionPicks.filter(p => p.lineNo === selectedLineNo).reduce((s,p) => s + p.qty, 0);
        const currentBinTotal = sessionPicks.filter(p => p.item === selectedItemCode && p.bin === currentBin).reduce((s,p) => s + p.qty, 0);

        // Limit Checks
        if(currentBinTotal + qty > currentBinMaxQty) { 
            showToast(`BIN LIMIT EXCEEDED (Max: ${currentBinMaxQty})`, 'error'); 
            return; 
        }
        if(currentLineTotal + qty > currentOrderMaxQty) { 
            showToast(`ORDER LIMIT EXCEEDED (Need: ${currentOrderMaxQty})`, 'error'); 
            return; 
        }

        // SUCCESS!
        playBeep('success');

        // Aggregation Logic: Find if we already have this specific pick
        const existingIndex = sessionPicks.findIndex(p => p.lineNo === selectedLineNo && p.bin === currentBin && p.item === selectedItemCode);
        
        if (existingIndex > -1) {
            sessionPicks[existingIndex].qty += qty;
        } else {
            sessionPicks.push({ 
                id: Date.now(), 
                lineNo: selectedLineNo, 
                item: selectedItemCode, 
                bin: currentBin, 
                qty: qty 
            });
        }

        success = true;
        updateSessionDisplay(); 
        
        // Flash UI
        const q = document.getElementById('qtyInput');
        q.classList.remove('flash-active'); 
        void q.offsetWidth; 
        q.classList.add('flash-active');

        // Background Save
        setTimeout(saveToLocal, 0);
        
        showToast(`Added ${qty} x ${selectedItemCode}`, 'success', false); // False = don't double beep
        
    } finally {
        // Reset Inputs based on Mode
        if(isAutoMode) {
            document.getElementById('itemInput').value = '';
            setTimeout(() => safeFocus('itemInput'), 50);
        } else {
            if(success) document.getElementById('qtyInput').value = 1;
        }
    }
}

function handleItemScan() {
    const scan = document.getElementById('itemInput').value.trim();
    if(!selectedItemCode || !scan) return;
    
    // Flexible String Matching (Contains)
    const match = scan.toLowerCase().includes(selectedItemCode.trim().toLowerCase()) || selectedItemCode.toLowerCase().includes(scan.toLowerCase());
    
    if(!match) {
        showToast("Wrong Item!", 'error'); 
        document.getElementById('itemInput').value=''; 
        if(isAutoMode) setTimeout(() => safeFocus('itemInput'), 50);
        return;
    }
    
    // Proceed to Add
    if (isAutoMode) {
        addToSession();
    } else {
        document.getElementById('qtyInput').focus();
    }
}

// ==========================================================================
// 8. SERVER SUBMISSION
// ==========================================================================

function submitFinal() {
    if(isSubmitting || sessionPicks.length===0) return;
    
    if(!navigator.onLine) { alert("OFFLINE. Move to Wi-Fi."); return; }
    if(!confirm(`Submit ${sessionPicks.length} pick lines?`)) return;
    
    isSubmitting = true;
    
    // UI Feedback
    const btn = document.getElementById('btnSubmit'); 
    const originalText = btn.innerHTML; 
    btn.innerHTML = "⏳ Sending..."; 
    btn.disabled = true;
    
    // Get existing Batch ID or null (server handles generation if null, but we prefer sending it)
    let batchId = localStorage.getItem(`twg_batch_id_${SO_NUMBER}`);
    if (!batchId) batchId = generateUUID();

    fetch('/process_batch_scan', {
        method: 'POST', 
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ 
            so: SO_NUMBER, 
            picks: sessionPicks, 
            batch_id: batchId 
        })
    })
    .then(r => {
        if (!r.ok) throw new Error(`HTTP Error ${r.status}`);
        return r.json();
    })
    .then(d => {
        if(d.status === 'success') { 
            showToast("Success!", 'success'); 
            alert(d.msg); // Show the server log/message
            clearLocal(); // Wipe local storage on success
            setTimeout(() => location.reload(), 1500); 
        } else { 
            alert("SERVER ERROR: "+d.msg); 
            isSubmitting = false; 
            btn.innerHTML = originalText; 
            btn.disabled = false; 
        }
    })
    .catch(e => { 
        alert("Network Failed: " + e.message); 
        console.error(e);
        isSubmitting = false; 
        btn.innerHTML = originalText; 
        btn.disabled = false; 
    });
}

// ==========================================================================
// 9. HELPER FUNCTIONS & MODALS
// ==========================================================================

function updateSessionDisplay() {
    const totalQty = sessionPicks.reduce((acc, p) => acc + p.qty, 0);
    const btnView = document.getElementById('scanCount');
    if(btnView) btnView.innerText = `(${totalQty})`;
    
    // Clear all grid counters
    document.querySelectorAll('.picked-cell').forEach(c => c.innerText = "0");
    
    // Fill grid counters from session data
    sessionPicks.forEach(p => { 
        const c = document.querySelector(`.picked-cell[data-line="${p.lineNo}"]`); 
        if(c) {
            const currentVal = parseFloat(c.innerText||0);
            c.innerText = currentVal + p.qty; 
        }
    });
}

function adjustQty(n) { 
    if(!isAutoMode) { 
        const i = document.getElementById('qtyInput'); 
        i.value = Math.max(0, (parseFloat(i.value)||0)+n); 
    } 
}

function showToast(m, t='info', playSound=true){ 
    const c = document.getElementById('toastContainer'); 
    const d = document.createElement('div'); 
    
    const bg = t === 'error' ? '#e53e3e' : '#38a169';
    d.style.cssText = `background:${bg}; color:white; padding:10px 20px; border-radius:4px; margin-bottom:10px; box-shadow:0 4px 6px rgba(0,0,0,0.1); font-weight:bold; font-size:14px;`;
    d.innerText = m; 
    
    c.appendChild(d);
    
    if(playSound) playBeep(t==='error'?'error':'success');
    
    setTimeout(() => { 
        d.style.opacity = '0'; 
        setTimeout(() => d.remove(), 300); 
    }, 2000);
}

// --- BIN MODAL ---

function openBinModal(){
    if(document.activeElement) document.activeElement.blur();
    if(!selectedItemCode) return;
    
    document.getElementById('binModal').style.display = 'flex';
    prefetchBins(selectedItemCode).then(() => { 
        if(binCache[selectedItemCode]) populateBinList(binCache[selectedItemCode]); 
    });
}

async function prefetchBins(item) {
    if(binCache[item]) return;
    const l = document.getElementById('binList'); 
    l.innerHTML = '<div class="text-center" style="padding:20px;">Loading...</div>';
    
    try { 
        const r = await fetch('/get_item_bins', {
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({item})
        }); 
        const d = await r.json(); 
        
        if(d.status === 'success') { 
            binCache[item] = d.bins; 
            populateBinList(d.bins); 
        } else {
            l.innerText = d.msg; 
        }
    } catch(e) { 
        l.innerText = 'Connection Failed'; 
    }
}

function populateBinList(bins) {
    const l = document.getElementById('binList'); 
    l.innerHTML = ''; 

    if (!bins.length) { 
        l.innerHTML = '<div class="text-center" style="padding:20px;">No Stock</div>'; 
        return; 
    }

    // Rich Table with Alloc/Avail/Onhand
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

    bins.forEach(b => { 
        const availStyle = b.avail > 0 ? 'font-weight:bold; color:#2d3748;' : 'color:#a0aec0;';
        html += `
            <tr style="border-bottom:1px solid #e2e8f0;">
                <td style="padding:10px 8px; font-weight:bold; color:#2b6cb0; font-size:14px;">${b.bin}</td>
                <td style="text-align:center; padding:10px 8px;">${b.qty}</td>
                <td style="text-align:center; padding:10px 8px; color:#e53e3e;">${b.alloc}</td>
                <td style="text-align:center; padding:10px 8px; ${availStyle}">${b.avail}</td>
            </tr>`;
    });

    html += `</tbody></table>`;
    html += `<div style="text-align:right; font-size:10px; color:#a0aec0; padding:5px;">Tap outside to close</div>`;

    l.innerHTML = html;
}

// --- REVIEW MODAL ---

function openReviewModal(){
    const l = document.getElementById('reviewList'); 
    
    // Render list rows
    const htmlParts = sessionPicks.map((p, i) => `
        <tr>
            <td>${p.item}</td>
            <td>${p.bin}</td>
            <td style="font-weight:bold;">${p.qty}</td>
            <td><button class="btn-small-action" style="background:#e53e3e; padding: 2px 8px;" onclick="removePick(${i})">X</button></td>
        </tr>
    `);
    
    l.innerHTML = htmlParts.join('');
    
    document.getElementById('emptyReview').style.display = sessionPicks.length ? 'none' : 'block'; 
    document.getElementById('reviewModal').style.display = 'flex';
}

function removePick(i){ 
    if(confirm("Remove this entry?")){ 
        sessionPicks.splice(i,1); 
        openReviewModal(); 
        updateSessionDisplay(); 
        setTimeout(saveToLocal, 0); 
    } 
}

function clearSession() {
    if(confirm("Clear ALL scanned items?")) {
        sessionPicks = [];
        openReviewModal(); 
        updateSessionDisplay(); 
        setTimeout(saveToLocal, 0);
    }
}

function closeModal(id){ 
    document.getElementById(id).style.display='none'; 
}