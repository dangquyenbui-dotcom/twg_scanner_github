/* picking.js - Core Logic & Controller
 * Depends on: utils.js, picking-ui.js
 */

// --- STATE ---
const SO_NUMBER = (typeof SERVER_DATA !== 'undefined' && SERVER_DATA.soNumber) ? SERVER_DATA.soNumber : ""; 
let sessionPicks = [];
let binCache = {};
let selectedItemCode = null, selectedLineNo = null, selectedUpc = null; 
let currentBinMaxQty = 999999, currentOrderMaxQty = 999999, currentBin = ""; 
let isAutoMode = true, isSubmitting = false;

// --- INIT ---
window.onload = function() {
    log("App Core Loaded");
    if(SO_NUMBER) { 
        loadFromLocal(); 
        updateSessionDisplay(sessionPicks); 
        updateMode(); 
    }
    updateStatusUI(navigator.onLine);
    
    const soInput = document.getElementById('soInput');
    if(soInput) setTimeout(() => soInput.focus(), 200);
    
    attachScannerListeners();
    document.addEventListener('click', forceFullscreen, {once:true});
};

window.addEventListener('online', () => updateStatusUI(true));
window.addEventListener('offline', () => updateStatusUI(false));

// --- SCANNER LOGIC ---
function attachScannerListeners() {
    document.querySelectorAll('input.scan-input').forEach(el => {
        let debounceTimer;
        el.addEventListener('keydown', (e) => { 
            if (e.key === 'Enter' || e.keyCode === 13) { 
                e.preventDefault(); clearTimeout(debounceTimer); handleAction(el); 
            } 
        });
        el.addEventListener('input', () => { 
            clearTimeout(debounceTimer); 
            debounceTimer = setTimeout(() => { 
                if (el.value.length > 2) { log(`Auto: ${el.id}`); handleAction(el); } 
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

// --- CORE LOGIC ---

// Updated to accept UPC
function selectRow(row, itemCode, remainingQty, lineNo, upc) {
    unlockAudio();
    document.querySelectorAll('.item-row').forEach(r => r.classList.remove('active-row'));
    row.classList.add('active-row');
    
    // FIX: Aggressive Cleaning for Item and UPC
    selectedItemCode = itemCode ? itemCode.toString().trim() : ""; 
    selectedLineNo = lineNo; 
    
    // FIX: Ensure 'None' string (from template leakage) or nulls are treated as empty
    if (!upc || upc === 'None' || upc === 'null') {
        selectedUpc = "";
    } else {
        selectedUpc = upc.toString().trim();
    }
    
    currentOrderMaxQty = remainingQty;
    
    document.getElementById('binInput').value = ''; 
    document.getElementById('itemInput').value = '';
    
    updateSessionDisplay(sessionPicks);
    currentBinMaxQty = 999999; 
    setTimeout(() => safeFocus('binInput'), 100);
    prefetchBins(selectedItemCode); 
    
    if (selectedUpc) log(`Row Selected: ${selectedItemCode} (UPC: ${selectedUpc})`);
}

function validateBin() {
    const binVal = document.getElementById('binInput').value.trim();
    if(!binVal || !selectedItemCode) return;
    
    // Cache check
    if (binCache[selectedItemCode]) {
        const f = binCache[selectedItemCode].find(b => b.bin === binVal);
        if (f) { verifySuccess(f.qty, binVal); return; }
    }
    
    if (!navigator.onLine) { showToast("Offline: Cannot verify.", 'warning'); return; }
    
    fetch('/validate_bin', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ bin: binVal, item: selectedItemCode })
    }).then(r=>r.json()).then(d => {
        if(d.status === 'success') { verifySuccess(d.onhand, binVal); } 
        else { showToast(d.msg, 'error'); document.getElementById('binInput').value=''; safeFocus('binInput'); }
    }).catch(()=> showToast("Network Error", 'error'));
}

function verifySuccess(qty, bin) {
    currentBinMaxQty = qty; currentBin = bin;
    showToast(`Verified. Max: ${qty}`, 'success'); 
    safeFocus('itemInput');
}

function addToSession() {
    if(!selectedItemCode) { showToast("Select item!", 'warning'); return; }
    if(document.getElementById('binInput').value.trim() !== currentBin) { showToast("Scan Bin first", 'warning'); return; }
    
    let qty = isAutoMode ? 1 : (parseFloat(document.getElementById('qtyInput').value)||0);
    if(qty <= 0) return;

    // Logic Limits
    const currentLineTotal = sessionPicks.filter(p => p.lineNo === selectedLineNo).reduce((s,p) => s + p.qty, 0);
    const currentBinTotal = sessionPicks.filter(p => p.item === selectedItemCode && p.bin === currentBin).reduce((s,p) => s + p.qty, 0);
    
    if(currentBinTotal + qty > currentBinMaxQty) { showToast(`Bin Limit: ${currentBinMaxQty}`, 'error'); return; }
    if(currentLineTotal + qty > currentOrderMaxQty) { showToast(`Order Limit: ${currentOrderMaxQty}`, 'error'); return; }

    // Success
    playBeep('success');
    const existingIndex = sessionPicks.findIndex(p => p.lineNo === selectedLineNo && p.bin === currentBin && p.item === selectedItemCode);
    
    if (existingIndex > -1) sessionPicks[existingIndex].qty += qty;
    else sessionPicks.push({ id:Date.now(), lineNo:selectedLineNo, item:selectedItemCode, bin:currentBin, qty:qty });

    updateSessionDisplay(sessionPicks);
    
    // Visual Flash
    const q = document.getElementById('qtyInput');
    q.classList.remove('flash-active'); void q.offsetWidth; q.classList.add('flash-active');
    
    setTimeout(saveToLocal, 0);
    showToast(`Added ${qty} x ${selectedItemCode}`, 'success', false);
    
    resetInputAfterAdd(qty > 0);
}

function resetInputAfterAdd(success) {
    if(isAutoMode) {
        document.getElementById('itemInput').value = '';
        setTimeout(() => safeFocus('itemInput'), 50);
    } else if(success) {
        document.getElementById('qtyInput').value = 1;
    }
}

function handleItemScan() {
    const scan = document.getElementById('itemInput').value.trim();
    if(!selectedItemCode || !scan) return;
    
    const scanNorm = scan.toLowerCase();
    const itemNorm = (selectedItemCode || "").trim().toLowerCase();
    const upcNorm = selectedUpc ? selectedUpc.toLowerCase() : "";

    // VALIDATION: Strict Match on Item Code OR Exact Match on UPC
    const match = 
        scanNorm === itemNorm || 
        (upcNorm && scanNorm === upcNorm);
    
    if(!match) {
        showToast("Wrong Item/UPC!", 'error'); 
        document.getElementById('itemInput').value=''; 
        if(isAutoMode) setTimeout(() => safeFocus('itemInput'), 50);
        return;
    }
    
    if (isAutoMode) addToSession();
    else document.getElementById('qtyInput').focus();
}

function submitFinal() {
    if(isSubmitting || sessionPicks.length===0) return;
    
    if(!navigator.onLine) { alert("OFFLINE. Connect to Wi-Fi."); return; }
    
    // USER CONFIRMATION (Required)
    if(!confirm(`CONFIRM SUBMISSION:\n\nAre you sure you want to commit ${sessionPicks.length} pick lines to the database?`)) return;
    
    isSubmitting = true;
    const btn = document.getElementById('btnSubmit'); 
    const originalText = btn.innerHTML; 
    btn.innerHTML = "⏳ Sending..."; btn.disabled = true;
    
    let batchId = localStorage.getItem(`twg_batch_id_${SO_NUMBER}`);
    if (!batchId) batchId = generateUUID();

    fetch('/process_batch_scan', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ so:SO_NUMBER, picks:sessionPicks, batch_id:batchId })
    })
    .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then(d => {
        if(d.status === 'success') { 
            playBeep('success'); // AUDIO CONFIRMATION
            alert(d.msg); // VISUAL CONFIRMATION
            clearLocal(); 
            setTimeout(() => location.reload(), 1500); 
        } else { 
            alert("SERVER ERROR: "+d.msg); 
            resetSubmitBtn(btn, originalText);
        }
    })
    .catch(e => { 
        alert("Network Failed: " + e.message); 
        resetSubmitBtn(btn, originalText);
    });
}

function resetSubmitBtn(btn, txt) { isSubmitting=false; btn.innerHTML=txt; btn.disabled=false; }

// --- STORAGE & MODES ---

function saveToLocal() {
    if(!SO_NUMBER) return;
    if (!localStorage.getItem(`twg_batch_id_${SO_NUMBER}`)) localStorage.setItem(`twg_batch_id_${SO_NUMBER}`, generateUUID());
    localStorage.setItem(`twg_picks_${SO_NUMBER}`, JSON.stringify(sessionPicks));
}

function loadFromLocal() { 
    const s = localStorage.getItem(`twg_picks_${SO_NUMBER}`); 
    if(s) try { sessionPicks = JSON.parse(s); } catch(e){} 
}

function clearLocal() { 
    localStorage.removeItem(`twg_picks_${SO_NUMBER}`); 
    localStorage.removeItem(`twg_batch_id_${SO_NUMBER}`); 
    sessionPicks = []; 
    updateSessionDisplay(sessionPicks); 
    saveToLocal(); 
}

function updateMode() {
    unlockAudio();
    const modeEl = document.querySelector('input[name="pickMode"]:checked');
    if(!modeEl) return;
    
    isAutoMode = modeEl.value === 'auto';
    const qtyInput = document.getElementById('qtyInput');
    
    if (isAutoMode) {
        qtyInput.readOnly = true; qtyInput.value = 1; 
        document.getElementById('btnMinus').classList.add('d-none'); 
        document.getElementById('btnPlus').classList.add('d-none'); 
        document.getElementById('addBtnContainer').classList.add('d-none');
        if(currentBin) setTimeout(() => safeFocus('itemInput'), 100);
    } else {
        qtyInput.readOnly = false; 
        document.getElementById('btnMinus').classList.remove('d-none'); 
        document.getElementById('btnPlus').classList.remove('d-none'); 
        document.getElementById('addBtnContainer').classList.remove('d-none');
    }
}

// --- MODAL CONTROLLERS ---

function openBinModal(){
    if(document.activeElement) document.activeElement.blur();
    if(!selectedItemCode) return;
    openModal('binModal');
    prefetchBins(selectedItemCode).then(() => { if(binCache[selectedItemCode]) renderBinList(binCache[selectedItemCode]); });
}

async function prefetchBins(item) {
    if(binCache[item]) return;
    const l = document.getElementById('binList'); l.innerHTML = '<div class="text-center" style="padding:20px;">Loading...</div>';
    try { 
        const r = await fetch('/get_item_bins', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({item}) }); 
        const d = await r.json(); 
        if(d.status === 'success') { binCache[item] = d.bins; renderBinList(d.bins); } else { l.innerText = d.msg; }
    } catch(e) { l.innerText = 'Connection Failed'; }
}

function openReviewModal(){
    renderReviewList(sessionPicks);
    openModal('reviewModal');
}

function removePick(i){ 
    if(confirm("Remove this entry?")){ 
        sessionPicks.splice(i,1); 
        openReviewModal(); updateSessionDisplay(sessionPicks); setTimeout(saveToLocal, 0); 
    } 
}

function clearSession() {
    if(confirm("Clear ALL scanned items?")) { 
        sessionPicks = []; openReviewModal(); updateSessionDisplay(sessionPicks); setTimeout(saveToLocal, 0); 
    }
}

function toggleKeyboard(id) { 
    unlockAudio(); const el = document.getElementById(id); 
    if(el.inputMode==='none') { el.inputMode='text'; el.blur(); setTimeout(()=>el.focus(),50); } 
    else { el.inputMode='none'; el.blur(); } 
}
function safeFocus(id) { const el = document.getElementById(id); el.inputMode='none'; el.focus(); setTimeout(()=>el.inputMode='text',300); }
function adjustQty(n) { if(!isAutoMode) { const i=document.getElementById('qtyInput'); i.value=Math.max(0, (parseFloat(i.value)||0)+n); } }