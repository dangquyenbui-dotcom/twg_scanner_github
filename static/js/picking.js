/* picking.js - Core Logic & Controller */

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
    attachKeyboardAvoidance();
    document.addEventListener('click', forceFullscreen, {once:true});
};

window.addEventListener('online', () => updateStatusUI(true));
window.addEventListener('offline', () => updateStatusUI(false));

// --- UI EXPERIENCE IMPROVEMENT ---
function attachKeyboardAvoidance() {
    const inputs = document.querySelectorAll('.tc52-controls input');
    const layout = document.getElementById('mainLayout');

    inputs.forEach(input => {
        const triggerShift = () => {
            if (layout) {
                layout.classList.add('keyboard-visible');
                setTimeout(() => {
                    input.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 100);
            }
        };

        input.addEventListener('mousedown', triggerShift);
        input.addEventListener('touchstart', triggerShift);

        input.addEventListener('blur', () => {
            if (layout) layout.classList.remove('keyboard-visible');
        });
    });
}

// --- REFINED SCANNER VS MANUAL LOGIC ---
function attachScannerListeners() {
    document.querySelectorAll('input.scan-input').forEach(el => {
        let lastKeyTime = Date.now();
        
        el.addEventListener('keydown', (e) => { 
            const now = Date.now();
            const diff = now - lastKeyTime;
            lastKeyTime = now;

            if (e.key === 'Enter' || e.keyCode === 13) { 
                e.preventDefault(); 
                handleAction(el); 
                return;
            }

            // Hardware scanners are extremely fast (< 10ms between keys)
            // If the time since last key is high, we treat it as manual typing
            // and clear any pending auto-lookup timers.
            if (diff > 50) {
                clearTimeout(el.scanTimeout);
            }
        });

        el.addEventListener('input', () => { 
            const val = el.value.trim();

            // Special Case: SO Input auto-submits at 7 digits
            if (el.id === 'soInput' && val.length === 7) {
                handleAction(el);
                return;
            }

            // For Bin and Item inputs:
            // Only trigger auto-lookup if characters arrive in a rapid "burst" (Scanner)
            // We use a very short timeout to catch the end of the scanner data dump
            clearTimeout(el.scanTimeout);
            if (val.length > 5) {
                el.scanTimeout = setTimeout(() => {
                    const timeSinceLastKey = Date.now() - lastKeyTime;
                    // If the last character was received recently and rapidly, process it.
                    if (timeSinceLastKey < 100) {
                        log(`Auto-Scan triggered for: ${el.id}`);
                        handleAction(el);
                    }
                }, 40); 
            }
        });
    });
}

function handleAction(el) {
    const val = el.value.trim();
    if (val === "") return;
    unlockAudio();

    if (el.id === 'soInput') {
        if (val.length === 7) {
            el.value = val;
            document.getElementById('soForm').submit();
        } else {
            log("Submit blocked: SO must be 7 digits.");
        }
    }
    else if (el.id === 'binInput') validateBin();
    else if (el.id === 'itemInput') handleItemScan();
    else if (el.id === 'qtyInput') addToSession(); 
}

// --- CORE LOGIC ---
function selectRow(row, itemCode, remainingQty, lineNo, upc) {
    unlockAudio();
    document.querySelectorAll('.item-row').forEach(r => r.classList.remove('active-row'));
    row.classList.add('active-row');
    
    selectedItemCode = itemCode ? itemCode.toString().trim() : ""; 
    selectedLineNo = lineNo; 
    selectedUpc = (!upc || upc === 'None' || upc === 'null') ? "" : upc.toString().trim();
    currentOrderMaxQty = remainingQty;
    
    document.querySelectorAll('.disabled-control').forEach(el => el.classList.remove('disabled-control'));
    document.getElementById('scanForm').querySelectorAll('input, button').forEach(el => el.disabled = false);
    
    document.getElementById('binInput').placeholder = "Scan Bin...";
    document.getElementById('itemInput').placeholder = "Scan Item...";
    document.getElementById('binInput').value = ''; 
    document.getElementById('itemInput').value = '';
    
    updateSessionDisplay(sessionPicks);
    currentBinMaxQty = 999999; 
    setTimeout(() => safeFocus('binInput'), 100);
    prefetchBins(selectedItemCode); 
}

function validateBin() {
    const binVal = document.getElementById('binInput').value.trim();
    if(!binVal || !selectedItemCode) return;
    
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

    const currentLineTotal = sessionPicks.filter(p => p.lineNo === selectedLineNo).reduce((s,p) => s + p.qty, 0);
    const currentBinTotal = sessionPicks.filter(p => p.item === selectedItemCode && p.bin === currentBin).reduce((s,p) => s + p.qty, 0);
    
    if(currentBinTotal + qty > currentBinMaxQty) { showToast(`Bin Limit: ${currentBinMaxQty}`, 'error'); return; }
    if(currentLineTotal + qty > currentOrderMaxQty) { showToast(`Order Limit: ${currentOrderMaxQty}`, 'error'); return; }

    playBeep('success');
    const existingIndex = sessionPicks.findIndex(p => p.lineNo === selectedLineNo && p.bin === currentBin && p.item === selectedItemCode);
    
    if (existingIndex > -1) sessionPicks[existingIndex].qty += qty;
    else sessionPicks.push({ id:Date.now(), lineNo:selectedLineNo, item:selectedItemCode, bin:currentBin, qty:qty });

    updateSessionDisplay(sessionPicks);
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

    const match = scanNorm === itemNorm || (upcNorm && scanNorm === upcNorm);
    
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
    if(!confirm(`CONFIRM SUBMISSION:\n\nAre you sure you want to commit ${sessionPicks.length} pick lines?`)) return;
    
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
    .then(r => r.json())
    .then(d => {
        if(d.status === 'success') { 
            playBeep('success'); 
            alert(d.msg); 
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
        if(currentBin && !document.getElementById('itemInput').disabled) setTimeout(() => safeFocus('itemInput'), 100);
    } else {
        qtyInput.readOnly = false; 
        document.getElementById('btnMinus').classList.remove('d-none'); 
        document.getElementById('btnPlus').classList.remove('d-none'); 
        document.getElementById('addBtnContainer').classList.remove('d-none');
    }
}

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
    if(el.disabled) return;
    if(el.inputMode==='none') { 
        el.inputMode = (id === 'soInput') ? 'numeric' : 'text'; 
        el.blur(); 
        setTimeout(()=>el.focus(),50); 
    } 
    else { el.inputMode='none'; el.blur(); } 
}

function safeFocus(id) { 
    const el = document.getElementById(id); 
    if(el.disabled) return;
    el.inputMode='none'; 
    el.focus(); 
    setTimeout(()=>el.inputMode='text',300); 
}

function adjustQty(n) { 
    if(!isAutoMode) { 
        const i=document.getElementById('qtyInput'); 
        i.value=Math.max(0, (parseFloat(i.value)||0)+n); 
    } 
}