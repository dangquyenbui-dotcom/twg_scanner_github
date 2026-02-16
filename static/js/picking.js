/* picking.js - Core Logic for Hybrid Scanning */

// --- GLOBAL STATE ---
// SERVER_DATA is defined in the HTML file before this script loads
const SO_NUMBER = SERVER_DATA.soNumber || ""; 
let sessionPicks = [], binCache = {};
let selectedItemCode = null, selectedLineNo = null; 
let currentBinMaxQty = 999999, currentOrderMaxQty = 999999, currentBin = ""; 
let isAutoMode = true, isSubmitting = false;

// --- AUDIO ENGINE ---
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

function unlockAudio() { 
    if (audioCtx.state === 'suspended') { 
        audioCtx.resume().then(() => log("Audio Resumed")); 
    }
}

// Aggressively unlock audio on any interaction
['touchstart', 'click', 'keydown', 'mousedown'].forEach(evt => {
    document.body.addEventListener(evt, unlockAudio, {once:false, passive:true});
});

function playBeep(type) {
    try {
        if (audioCtx.state === 'suspended') audioCtx.resume();
        
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.connect(gain); 
        gain.connect(audioCtx.destination);
        
        if (type === 'success') { 
            osc.frequency.value = 1500; 
            osc.type = 'sine';
            gain.gain.value = 0.3; 
            osc.start(); 
            osc.stop(audioCtx.currentTime + 0.15); 
        } else { 
            osc.frequency.value = 150; 
            osc.type = 'sawtooth';
            gain.gain.value = 0.4; 
            osc.start(); 
            osc.stop(audioCtx.currentTime + 0.4); 
        }
    } catch(e) { console.error("Audio Error:", e); }
}

// --- INIT ---
window.onload = function() {
    log("App Loaded");
    if(SO_NUMBER) { loadFromLocal(); updateSessionDisplay(); updateMode(); }
    updateStatusUI(navigator.onLine);
    const soInput = document.getElementById('soInput');
    if(soInput) setTimeout(() => soInput.focus(), 200);
    attachScannerListeners();
};

window.addEventListener('online', () => updateStatusUI(true));
window.addEventListener('offline', () => updateStatusUI(false));

function updateStatusUI(online) {
    const bar = document.getElementById('statusBar');
    const txt = document.getElementById('statusText');
    if (online) { bar.classList.replace('status-offline', 'status-online'); txt.innerText = '📶 SYSTEM ONLINE'; } 
    else { bar.classList.replace('status-online', 'status-offline'); txt.innerText = '🚫 OFFLINE'; }
}

// --- UNIVERSAL FULLSCREEN ---
function forceFullscreen() {
    const doc = window.document; const docEl = doc.documentElement;
    const requestFullScreen = docEl.requestFullscreen || docEl.mozRequestFullScreen || docEl.webkitRequestFullScreen || docEl.msRequestFullscreen;
    if(!doc.fullscreenElement && !doc.mozFullScreenElement && !doc.webkitFullscreenElement && !doc.msFullscreenElement) {
        if(requestFullScreen) requestFullScreen.call(docEl).catch(e=>{});
    }
}
document.addEventListener('click', forceFullscreen, {once:true});
document.addEventListener('touchstart', forceFullscreen, {once:true});

// --- DEBUG ---
function log(msg) {
    const c = document.getElementById('debugConsole');
    if(!c) return;
    const d = document.createElement('div');
    const time = new Date().toLocaleTimeString().split(' ')[0];
    d.innerText = `[${time}] ${msg}`; c.prepend(d); console.log(msg);
}
function toggleDebug() {
    const c = document.getElementById('debugConsole');
    c.style.display = (c.style.display === 'none') ? 'block' : 'none';
}

// --- SCANNER INPUTS ---
function attachScannerListeners() {
    const inputs = document.querySelectorAll('input.scan-input');
    inputs.forEach(el => {
        let debounceTimer;

        el.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.keyCode === 13) { 
                e.preventDefault(); 
                clearTimeout(debounceTimer); 
                handleAction(el); 
            }
        });

        el.addEventListener('input', () => {
            clearTimeout(debounceTimer);
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
    unlockAudio();

    if (el.id === 'soInput') document.getElementById('soForm').submit();
    else if (el.id === 'binInput') validateBin();
    else if (el.id === 'itemInput') handleItemScan();
    else if (el.id === 'qtyInput') addToSession(); 
}

function toggleKeyboard(inputId) {
    unlockAudio(); 
    const el = document.getElementById(inputId);
    if (!el) return;
    if (el.inputMode === 'none') { el.inputMode = 'text'; log(`${inputId} Keyboard: ON`); el.blur(); setTimeout(() => el.focus(), 50); } 
    else { el.inputMode = 'none'; log(`${inputId} Keyboard: OFF`); el.blur(); }
}

function safeFocus(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.inputMode = 'none'; 
    el.focus();
    setTimeout(() => { el.inputMode = 'text'; }, 300); 
}

// --- STORAGE & LOGIC ---
function saveToLocal() {
    if(!SO_NUMBER) return;
    if (!localStorage.getItem(`twg_batch_id_${SO_NUMBER}`)) localStorage.setItem(`twg_batch_id_${SO_NUMBER}`, crypto.randomUUID());
    localStorage.setItem(`twg_picks_${SO_NUMBER}`, JSON.stringify(sessionPicks));
    const p = document.getElementById('pendingCount');
    if(p) {
        p.style.display = sessionPicks.length ? 'inline-block' : 'none'; 
        p.innerText = `${sessionPicks.length}`;
    }
}
function loadFromLocal() { const s = localStorage.getItem(`twg_picks_${SO_NUMBER}`); if(s) try { sessionPicks = JSON.parse(s); } catch(e){} }
function clearLocal() { localStorage.removeItem(`twg_picks_${SO_NUMBER}`); localStorage.removeItem(`twg_batch_id_${SO_NUMBER}`); sessionPicks = []; updateSessionDisplay(); saveToLocal(); }

function updateMode() {
    unlockAudio();
    const modeEl = document.querySelector('input[name="pickMode"]:checked');
    if(!modeEl) return;
    
    isAutoMode = modeEl.value === 'auto';
    const qtyInput = document.getElementById('qtyInput');
    
    if (isAutoMode) {
        qtyInput.readOnly = true; 
        qtyInput.value = 1; 
        document.getElementById('btnMinus').classList.add('d-none'); document.getElementById('btnPlus').classList.add('d-none'); document.getElementById('addBtnContainer').classList.add('d-none');
        if(currentBin) setTimeout(() => safeFocus('itemInput'), 100);
    } else {
        qtyInput.readOnly = false; 
        document.getElementById('btnMinus').classList.remove('d-none'); document.getElementById('btnPlus').classList.remove('d-none'); document.getElementById('addBtnContainer').classList.remove('d-none');
    }
}

function selectRow(row, itemCode, remainingQty, lineNo) {
    unlockAudio();
    document.querySelectorAll('.item-row').forEach(r => r.classList.remove('active-row'));
    row.classList.add('active-row');
    selectedItemCode = itemCode; selectedLineNo = lineNo; currentOrderMaxQty = remainingQty;
    
    document.getElementById('binInput').value = ''; document.getElementById('itemInput').value = '';
    
    updateSessionDisplay();
    
    currentBinMaxQty = 999999; 
    setTimeout(() => { safeFocus('binInput'); }, 100);
    prefetchBins(itemCode);
}

function validateBin() {
    const binVal = document.getElementById('binInput').value.trim();
    if(!binVal || !selectedItemCode) return;
    log(`Validating Bin: ${binVal}`);
    
    if (binCache[selectedItemCode]) {
        const f = binCache[selectedItemCode].find(b => b.bin === binVal);
        if (f) { 
            currentBinMaxQty = f.qty; currentBin = binVal; 
            showToast(`Bin Verified. Max: ${f.qty}`, 'success'); 
            safeFocus('itemInput'); 
            return; 
        }
    }
    
    if (!navigator.onLine) { showToast("Offline: Cannot verify.", 'warning'); return; }
    
    fetch('/validate_bin', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ bin: binVal, item: selectedItemCode })
    }).then(r=>r.json()).then(d => {
        if(d.status === 'success') { 
            currentBinMaxQty = d.onhand; currentBin = binVal; 
            showToast(`Bin Verified. Max: ${d.onhand}`, 'success'); 
            safeFocus('itemInput'); 
        }
        else { showToast(d.msg, 'error'); document.getElementById('binInput').value=''; safeFocus('binInput'); }
    }).catch(()=> showToast("Network Error", 'error'));
}

function addToSession() {
    if(!selectedItemCode) { showToast("Select item first!", 'warning'); return; }
    if(document.getElementById('binInput').value.trim() !== currentBin) { showToast("Validate bin first", 'warning'); return; }
    
    let qty = isAutoMode ? 1 : (parseFloat(document.getElementById('qtyInput').value)||0);
    if(qty <= 0) return;

    let success = false;
    try {
        const currentLineTotal = sessionPicks.filter(p => p.lineNo === selectedLineNo).reduce((s,p) => s + p.qty, 0);
        const currentBinTotal = sessionPicks.filter(p => p.item === selectedItemCode && p.bin === currentBin).reduce((s,p) => s + p.qty, 0);

        if(currentBinTotal + qty > currentBinMaxQty) { showToast(`BIN LIMIT EXCEEDED (Max: ${currentBinMaxQty})`, 'error'); return; }
        if(currentLineTotal + qty > currentOrderMaxQty) { showToast(`ORDER LIMIT EXCEEDED (Need: ${currentOrderMaxQty})`, 'error'); return; }

        playBeep('success');

        const existingIndex = sessionPicks.findIndex(p => p.lineNo === selectedLineNo && p.bin === currentBin && p.item === selectedItemCode);
        
        if (existingIndex > -1) {
            sessionPicks[existingIndex].qty += qty;
            log(`Aggregated +${qty} to existing entry.`);
        } else {
            sessionPicks.push({ id:Date.now(), lineNo:selectedLineNo, item:selectedItemCode, bin:currentBin, qty:qty });
            log(`Added new entry: ${qty}`);
        }

        success = true;

        updateSessionDisplay(); 
        
        const q = document.getElementById('qtyInput');
        q.classList.remove('flash-active'); void q.offsetWidth; q.classList.add('flash-active');

        setTimeout(saveToLocal, 0);
        
        showToast(`Added ${qty} x ${selectedItemCode}`, 'success', false);
        
    } finally {
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
    
    const match = scan.toLowerCase().includes(selectedItemCode.trim().toLowerCase()) || selectedItemCode.toLowerCase().includes(scan.toLowerCase());
    
    if(!match) {
        showToast("Wrong Item!", 'error'); 
        document.getElementById('itemInput').value=''; 
        if(isAutoMode) setTimeout(() => safeFocus('itemInput'), 50);
        return;
    }
    
    if (isAutoMode) {
        addToSession();
    } else {
        document.getElementById('qtyInput').focus();
    }
}

function submitFinal() {
    if(isSubmitting || sessionPicks.length===0) return;
    if(!navigator.onLine) { alert("OFFLINE. Move to Wi-Fi."); return; }
    if(!confirm(`Submit ${sessionPicks.length} pick lines?`)) return;
    
    isSubmitting = true;
    const btn = document.getElementById('btnSubmit'); 
    const originalText = btn.innerHTML; 
    btn.innerHTML = "⏳ Sending..."; 
    btn.disabled = true;
    
    const batchId = localStorage.getItem(`twg_batch_id_${SO_NUMBER}`);

    fetch('/process_batch_scan', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ so:SO_NUMBER, picks:sessionPicks, batch_id:batchId })
    }).then(r=>r.json()).then(d => {
        if(d.status==='success') { 
            showToast("Success!", 'success'); 
            clearLocal(); 
            setTimeout(()=>location.reload(), 1500); 
        } else { 
            alert("ERROR: "+d.msg); 
            isSubmitting=false; btn.innerHTML=originalText; btn.disabled=false; 
        }
    }).catch(()=>{ 
        alert("Network Failed"); 
        isSubmitting=false; btn.innerHTML=originalText; btn.disabled=false; 
    });
}

// --- HELPERS ---
function updateSessionDisplay() {
    const totalQty = sessionPicks.reduce((acc, p) => acc + p.qty, 0);
    const btnView = document.getElementById('scanCount');
    if(btnView) btnView.innerText = `(${totalQty})`;
    
    document.querySelectorAll('.picked-cell').forEach(c => c.innerText = "0");
    
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
        const i=document.getElementById('qtyInput'); 
        i.value=Math.max(0, (parseFloat(i.value)||0)+n); 
    } 
}

function showToast(m, t='info', playSound=true){ 
    const c=document.getElementById('toastContainer'); 
    const d=document.createElement('div'); 
    d.style.cssText = `background:${t=='error'?'#e53e3e':'#38a169'}; color:white; padding:10px 20px; border-radius:4px; margin-bottom:10px; box-shadow:0 4px 6px rgba(0,0,0,0.1); font-weight:bold; font-size:14px;`;
    d.innerText=m; c.appendChild(d);
    
    if(playSound) playBeep(t==='error'?'error':'success');
    
    setTimeout(()=>{ d.style.opacity='0'; setTimeout(()=>d.remove(),300); }, 2000);
}

function openBinModal(){
    if(document.activeElement) document.activeElement.blur();
    if(!selectedItemCode) return;
    document.getElementById('binModal').style.display='flex';
    prefetchBins(selectedItemCode).then(()=>{ if(binCache[selectedItemCode]) populateBinList(binCache[selectedItemCode]); });
}

async function prefetchBins(item) {
    if(binCache[item]) return;
    const l=document.getElementById('binList'); l.innerHTML='<div class="text-center" style="padding:20px;">Loading...</div>';
    try { 
        const r=await fetch('/get_item_bins', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({item})}); 
        const d=await r.json(); 
        if(d.status==='success') { binCache[item]=d.bins; populateBinList(d.bins); } 
        else l.innerText=d.msg; 
    } catch(e) { l.innerText='Connection Failed'; }
}

function populateBinList(bins) {
    const l = document.getElementById('binList'); 
    l.innerHTML = ''; 

    if (!bins.length) { 
        l.innerHTML = '<div class="text-center" style="padding:20px;">No Stock</div>'; 
        return; 
    }

    // UPDATED: Create Table Header
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
            <tbody>
    `;

    // UPDATED: Create Rows with data
    bins.forEach(b => { 
        // Highlight logic: If Avail > 0, make it bold/green, else grey
        const availStyle = b.avail > 0 ? 'font-weight:bold; color:#2d3748;' : 'color:#a0aec0;';
        
        html += `
            <tr style="border-bottom:1px solid #e2e8f0;">
                <td style="padding:10px 8px; font-weight:bold; color:#2b6cb0; font-size:14px;">${b.bin}</td>
                <td style="text-align:center; padding:10px 8px;">${b.qty}</td>
                <td style="text-align:center; padding:10px 8px; color:#e53e3e;">${b.alloc}</td>
                <td style="text-align:center; padding:10px 8px; ${availStyle}">${b.avail}</td>
            </tr>
        `;
    });

    html += `</tbody></table>`;
    html += `<div style="text-align:right; font-size:10px; color:#a0aec0; padding:5px;">Tap outside to close</div>`;

    l.innerHTML = html;
}

function openReviewModal(){
    const l = document.getElementById('reviewList'); 
    const htmlParts = sessionPicks.map((p, i) => 
        `<tr>
            <td>${p.item}</td>
            <td>${p.bin}</td>
            <td style="font-weight:bold;">${p.qty}</td>
            <td><button class="btn-small-action" style="background:#e53e3e; padding: 2px 8px;" onclick="removePick(${i})">X</button></td>
        </tr>`
    );
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

function closeModal(id){ document.getElementById(id).style.display='none'; }