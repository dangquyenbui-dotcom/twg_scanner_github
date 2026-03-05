/* picking.js - Core Logic & Controller */

// --- STATE ---
const SO_NUMBER = (typeof SERVER_DATA !== 'undefined' && SERVER_DATA.soNumber) ? SERVER_DATA.soNumber : ""; 
let sessionPicks = [];
let binCache = {};
let selectedItemCode = null, selectedLineNo = null, selectedUpc = null; 
let currentBinMaxQty = 999999, currentOrderMaxQty = 999999, currentBin = ""; 
let isAutoMode = true, isSubmitting = false;

// Will hold the merged picks ready for commit while the exception modal is open
let pendingCommitPicks = [];

// --- INIT ---
window.onload = function() {
    log("App Core Loaded");
    if(SO_NUMBER) { 
        loadFromLocal(); 
        updateSessionDisplay(sessionPicks); 
        refreshZeroPickRows();
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

/**
 * Determines if the user is actively typing via a virtual (on-screen) keyboard.
 * Hardware barcode scanners inject text with inputMode='none' or very rapidly,
 * while virtual keyboard users will have inputMode set to 'text', 'numeric', etc.
 */
function isVirtualKeyboardActive(el) {
    return el.inputMode && el.inputMode !== 'none';
}

/**
 * Strips Codabar start/stop characters and DataWedge symbology wrappers
 * from a scanned string. Returns an array of candidate values to try
 * matching against item codes and UPCs.
 *
 * CASE 1 (original): Leading+trailing alpha wrapping a purely numeric core.
 *   Matches DataWedge symbology identifiers on UPC barcodes.
 *   'A729419150129A' → '729419150129'
 *
 * CASE 2 (new): Single Codabar start/stop character (A, B, C, or D) on
 *   each end wrapping an alphanumeric item code. These four letters are the
 *   standard Codabar start/stop symbols that scanners may prepend/append.
 *   'AA9101MBA' → 'A9101MB'
 *
 * Examples:
 *   'A729419150129A' → '729419150129'  (Case 1: alpha wraps, numeric core → strip)
 *   'AA9101MBA'      → 'A9101MB'       (Case 2: Codabar A…A wrapping → strip one each end)
 *   'A9101MB'        → 'A9101MB'       (no change — no wrapping detected)
 *   'ABC12345'       → 'ABC12345'      (no change — alpha only on left end)
 *   'WIDGET-X'       → 'WIDGET-X'      (no change — not numeric core, no Codabar pattern)
 *   '729419150129'   → '729419150129'  (no change — no wrapping chars)
 *   'AB'             → 'AB'            (no change — too short for meaningful strip)
 *   'X100'           → 'X100'          (no change — alpha only on left end)
 *
 * This is ONLY used for item/UPC scan comparison in handleItemScan().
 * It does NOT affect bin scanning, SO input, or any server-side data.
 */
function stripWrappingAlpha(str) {
    if (!str) return str;

    var candidates = [];

    // CASE 1: Full alpha wrapping around a purely numeric core
    // e.g. 'A729419150129A' → '729419150129'
    var match = str.match(/^[A-Za-z]+(\d+)[A-Za-z]+$/);
    if (match) {
        candidates.push(match[1]);
    }

    // CASE 2: Single Codabar start/stop character (A, B, C, D) on each end
    // wrapping an alphanumeric item code that contains at least one digit.
    // e.g. 'AA9101MBA' → 'A9101MB'
    if (str.length >= 3) {
        var first = str.charAt(0).toUpperCase();
        var last = str.charAt(str.length - 1).toUpperCase();
        var codabarStopChars = 'ABCD';
        if (codabarStopChars.indexOf(first) !== -1 && codabarStopChars.indexOf(last) !== -1) {
            var core = str.substring(1, str.length - 1);
            // Safety: only strip if the core contains at least one digit
            // (prevents false positives on short plain-text like 'AB', 'CAD', 'DAD')
            if (core.length > 0 && /\d/.test(core)) {
                candidates.push(core);
            }
        }
    }

    // Return the first candidate found, or the original string if no pattern matched
    return candidates.length > 0 ? candidates[0] : str;
}

/**
 * Returns all plausible decoded values for a raw scan string.
 * Used by handleItemScan() to try matching against item code and UPC
 * without losing the original raw value.
 *
 * Always includes the raw value as the first element, followed by
 * any stripped variants (deduped).
 */
function getScanCandidates(rawStr) {
    if (!rawStr) return [rawStr];

    var candidates = [rawStr]; // Always try raw first

    // CASE 1: Full alpha wrapping around a purely numeric core
    var match = rawStr.match(/^[A-Za-z]+(\d+)[A-Za-z]+$/);
    if (match && match[1] !== rawStr) {
        candidates.push(match[1]);
    }

    // CASE 2: Single Codabar start/stop character (A, B, C, D) on each end
    if (rawStr.length >= 3) {
        var first = rawStr.charAt(0).toUpperCase();
        var last = rawStr.charAt(rawStr.length - 1).toUpperCase();
        var codabarStopChars = 'ABCD';
        if (codabarStopChars.indexOf(first) !== -1 && codabarStopChars.indexOf(last) !== -1) {
            var core = rawStr.substring(1, rawStr.length - 1);
            if (core.length > 0 && /\d/.test(core)) {
                // Only add if not already in candidates
                if (candidates.indexOf(core) === -1) {
                    candidates.push(core);
                }
            }
        }
    }

    return candidates;
}

function attachScannerListeners() {
    document.querySelectorAll('input.scan-input').forEach(el => {
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
            
            const rawVal = el.value;
            const cleanVal = rawVal.trim();

            if (el.id === 'soInput') {
                if (cleanVal.length === 7) {
                    log("7-digit Sales Order detected. Processing...");
                    handleAction(el);
                }
                return; 
            }

            // --- FIX: Only auto-trigger if virtual keyboard is NOT active ---
            if (isVirtualKeyboardActive(el)) {
                log(`Virtual keyboard active on ${el.id} — waiting for Enter key.`);
                return;
            }

            debounceTimer = setTimeout(() => { 
                if (cleanVal.length > 5) { 
                    log(`Auto Scan Detected: ${el.id}`); 
                    handleAction(el); 
                } 
            }, 300); 
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
            log("Submit blocked: SO must be 7 digits (scanned or typed).");
        }
    }
    else if (el.id === 'binInput') validateBin();
    else if (el.id === 'itemInput') handleItemScan();
    else if (el.id === 'qtyInput') addToSession(); 
}

// --- CORE LOGIC ---

function selectRow(row, itemCode, remainingQty, lineNo, upc) {
    unlockAudio();

    // Block interaction if this line has a Zero Pick — must remove it from Review first
    if (isZeroPickedLine(lineNo)) {
        showToast("Line " + lineNo + " is Zero Picked — remove from View to re-enable", 'error');
        return;
    }

    document.querySelectorAll('.item-row').forEach(r => r.classList.remove('active-row'));
    row.classList.add('active-row');
    
    selectedItemCode = itemCode ? itemCode.toString().trim() : ""; 
    selectedLineNo = lineNo; 
    
    if (!upc || upc === 'None' || upc === 'null') {
        selectedUpc = "";
    } else {
        selectedUpc = upc.toString().trim();
    }
    
    currentOrderMaxQty = remainingQty;
    
    // --- ENABLE CONTROLS ON SELECTION ---
    document.querySelectorAll('.disabled-control').forEach(el => el.classList.remove('disabled-control'));
    document.getElementById('scanForm').querySelectorAll('input, button').forEach(el => el.disabled = false);
    
    // Reset placeholders
    document.getElementById('binInput').placeholder = "Scan Bin...";
    document.getElementById('itemInput').placeholder = "Scan Item...";
    
    document.getElementById('binInput').value = ''; 
    document.getElementById('itemInput').value = '';
    
    // Hide UPC badge on new row selection
    hideUpcBadge();
    
    updateSessionDisplay(sessionPicks);
    currentBinMaxQty = 999999; 
    setTimeout(() => safeFocus('binInput'), 100);
    prefetchBins(selectedItemCode);

    // Update the keyboard context bar with selected item info
    if (typeof window.updateContextBar === 'function') {
        window.updateContextBar();
    }
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

    // Update context bar with bin info
    if (typeof window.updateContextBar === 'function') {
        window.updateContextBar();
    }
}

function addToSession() {
    if(!selectedItemCode) { showToast("Select item!", 'warning'); return; }
    if(document.getElementById('binInput').value.trim() !== currentBin) { showToast("Scan Bin first", 'warning'); return; }
    
    let qty = isAutoMode ? 1 : (parseFloat(document.getElementById('qtyInput').value)||0);
    if(qty <= 0) return;

    // --- Client-side guards use MERGED totals (lineNo+bin+item, ignoring mode) ---
    const currentLineTotal = sessionPicks.filter(p => p.lineNo === selectedLineNo).reduce((s,p) => s + p.qty, 0);
    const currentBinTotal = sessionPicks.filter(p => p.item === selectedItemCode && p.bin === currentBin).reduce((s,p) => s + p.qty, 0);
    
    if(currentBinTotal + qty > currentBinMaxQty) { showToast(`Bin Limit: ${currentBinMaxQty}`, 'error'); return; }
    if(currentLineTotal + qty > currentOrderMaxQty) { showToast(`Order Limit: ${currentOrderMaxQty}`, 'error'); return; }

    playBeep('success');

    // Determine current pick mode label
    var pickModeLabel = isAutoMode ? 'Auto' : 'Manual';

    // Deduplication includes mode — so Auto and Manual show as SEPARATE rows in View Scanned
    const existingIndex = sessionPicks.findIndex(p => p.lineNo === selectedLineNo && p.bin === currentBin && p.item === selectedItemCode && p.mode === pickModeLabel);
    
    if (existingIndex > -1) {
        sessionPicks[existingIndex].qty += qty;
    } else {
        sessionPicks.push({ id:Date.now(), lineNo:selectedLineNo, item:selectedItemCode, bin:currentBin, qty:qty, mode:pickModeLabel });
    }

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
        // NOTE: Do NOT hide UPC badge here — let it stay visible so the picker
        // can see the translation confirmation. It will hide on the next scan
        // cycle (new input into itemInput, row change, or mismatch).
        setTimeout(() => safeFocus('itemInput'), 50);
    } else if(success) {
        document.getElementById('qtyInput').value = 1;
    }
}

/**
 * handleItemScan — Matches scanned barcode against the selected item code and UPC.
 *
 * MATCHING STRATEGY (v1.9.0):
 * The raw scan value is expanded into multiple "candidates" via getScanCandidates().
 * Each candidate is compared (case-insensitive) against:
 *   1. The selected item code (direct match)
 *   2. The selected UPC value (UPC match)
 *
 * This handles three real-world scenarios:
 *   A) Direct scan of item code — raw value matches item code directly.
 *   B) UPC barcode with DataWedge symbology wrapper — e.g. 'A729419150129A'
 *      stripped to '729419150129' matches the UPC.
 *   C) Codabar-encoded item code — e.g. 'AA9101MBA' stripped to 'A9101MB'
 *      matches the item code after removing Codabar start/stop characters.
 *
 * The first matching candidate wins. If no candidate matches, it's an error.
 */
function handleItemScan() {
    const rawScan = document.getElementById('itemInput').value.trim();
    if(!selectedItemCode || !rawScan) return;
    
    const itemNorm = (selectedItemCode || "").trim().toLowerCase();
    const upcNorm = selectedUpc ? selectedUpc.toLowerCase() : "";

    // Get all plausible decoded values for this scan (raw + stripped variants)
    var candidates = getScanCandidates(rawScan);
    
    var isDirectMatch = false;
    var isUpcMatch = false;
    var matchedCandidate = '';

    // Try each candidate against item code and UPC
    for (var ci = 0; ci < candidates.length; ci++) {
        var candidateNorm = candidates[ci].toLowerCase();
        
        if (candidateNorm === itemNorm) {
            isDirectMatch = true;
            matchedCandidate = candidates[ci];
            break; // Direct item match takes highest priority
        }
        if (upcNorm && candidateNorm === upcNorm) {
            isUpcMatch = true;
            matchedCandidate = candidates[ci];
            // Don't break — keep looking for a direct match which takes priority
        }
    }

    var match = isDirectMatch || isUpcMatch;
    
    if(!match) {
        showToast("Wrong Item/UPC!", 'error'); 
        document.getElementById('itemInput').value=''; 
        hideUpcBadge();
        if(isAutoMode) setTimeout(() => safeFocus('itemInput'), 50);
        return;
    }
    
    // Show UPC translation badge if matched via UPC (not direct item code)
    if (isUpcMatch && !isDirectMatch) {
        showUpcBadge(matchedCandidate, selectedItemCode);
    } else {
        hideUpcBadge();
    }
    
    if (isAutoMode) addToSession();
    else document.getElementById('qtyInput').focus();
}

// --- UPC TRANSLATION BADGE ---

function showUpcBadge(upcValue, itemCode) {
    var badge = document.getElementById('upcBadge');
    if (!badge) return;
    
    var upcText = document.getElementById('upcBadgeText');
    if (upcText) {
        upcText.innerHTML = '<span class="upc-badge-label">UPC</span> ' + 
            escapeHtml(upcValue) + 
            ' <span class="upc-badge-arrow">\u2192</span> ' + 
            '<strong>' + escapeHtml(itemCode) + '</strong>' +
            ' <span class="upc-badge-check">\u2713</span>';
    }
    
    // Force reflow so transition plays even if already visible
    badge.classList.remove('upc-badge-visible');
    badge.classList.add('upc-badge-hidden');
    void badge.offsetWidth;
    badge.classList.remove('upc-badge-hidden');
    badge.classList.add('upc-badge-visible');
}

function hideUpcBadge() {
    var badge = document.getElementById('upcBadge');
    if (!badge) return;
    badge.classList.remove('upc-badge-visible');
    badge.classList.add('upc-badge-hidden');
}

function escapeHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

// --- END UPC BADGE ---

/**
 * Merges sessionPicks by lineNo + bin + item (summing qty, dropping mode).
 * This produces the EXACT same payload shape as the original code before mode was added.
 * The server receives one record per lineNo+bin+item — identical commit behavior.
 *
 * Zero-pick entries (qty=0, mode='Zero') are passed through individually
 * since they carry their own exception code and should not be merged.
 */
function mergePicksForCommit(picks) {
    var merged = {};
    var zeroPicks = [];

    picks.forEach(function(p) {
        // Zero picks pass through directly — they carry their own exception code
        if (p.mode === 'Zero' && p.qty === 0) {
            zeroPicks.push({ id: p.id, lineNo: p.lineNo, item: p.item, bin: p.bin || '', qty: 0, exception: p.exception || '' });
            return;
        }

        var key = p.lineNo + '|' + p.bin + '|' + p.item;
        if (merged[key]) {
            merged[key].qty += p.qty;
        } else {
            // Clone without mode — server never sees mode field
            merged[key] = { id: p.id, lineNo: p.lineNo, item: p.item, bin: p.bin, qty: p.qty };
        }
    });

    var result = [];
    for (var k in merged) {
        if (merged.hasOwnProperty(k)) result.push(merged[k]);
    }

    // Append zero picks at the end
    return result.concat(zeroPicks);
}

// --- EXCEPTION WORKFLOW ---

async function checkExceptionsAndSubmit() {
    if(isSubmitting || sessionPicks.length === 0) return;
    if(!navigator.onLine) { twgAlert("OFFLINE. Connect to Wi-Fi."); return; }

    pendingCommitPicks = mergePicksForCommit(sessionPicks);
    var shortLines = [];
    var lineTotals = {};

    // Collect exception codes already embedded in zero-pick entries
    var preloadedExceptions = {};
    pendingCommitPicks.forEach(function(p) {
        if (p.qty === 0 && p.exception) {
            preloadedExceptions[String(p.lineNo)] = p.exception;
        }
    });

    // Group the commit batch by lineNo to get total picked amount
    pendingCommitPicks.forEach(p => {
        lineTotals[p.lineNo] = (lineTotals[p.lineNo] || 0) + p.qty;
    });

    // Check DOM for original ordered quantity (Need) vs Picked amount
    for (var lineNo in lineTotals) {
        // Skip lines that already have a zero-pick exception — they are fully accounted for
        if (preloadedExceptions[String(lineNo)]) continue;

        var row = document.getElementById('row-' + lineNo);
        if (row) {
            var needQty = parseInt(row.cells[2].innerText, 10);
            var pickedQty = lineTotals[lineNo];
            
            // It's a short pick if they picked > 0 but less than needed
            if (pickedQty > 0 && pickedQty < needQty) {
                shortLines.push({
                    lineNo: lineNo,
                    item: pendingCommitPicks.find(p => p.lineNo == parseInt(lineNo)).item,
                    need: needQty,
                    picked: pickedQty
                });
            }
        }
    }

    // If there are partial picks (excluding zero-picks), open the forced exception modal
    if (shortLines.length > 0) {
        renderExceptionList(shortLines);
        openModal('exceptionModal');
    } else {
        // No partial picks, go straight to regular confirmation
        var ok = await twgConfirm("CONFIRM SUBMISSION:\n\nAre you sure you want to commit " + pendingCommitPicks.length + " pick lines?");
        if (!ok) return;
        executeSubmit(pendingCommitPicks, preloadedExceptions);
    }
}

function confirmExceptionsAndSubmit() {
    var exceptions = {};
    var selects = document.querySelectorAll('.exception-select');
    
    // Ensure all partial-picked lines have a selected reason
    for (var i = 0; i < selects.length; i++) {
        if (!selects[i].value) {
            twgAlert("Please select a reason for all short-picked lines before submitting.");
            return;
        }
        exceptions[selects[i].dataset.line] = selects[i].value;
    }

    // Merge in any pre-loaded zero-pick exceptions (these were set during zero-pick workflow)
    pendingCommitPicks.forEach(function(p) {
        if (p.qty === 0 && p.exception) {
            exceptions[String(p.lineNo)] = p.exception;
        }
    });
    
    closeModal('exceptionModal');
    executeSubmit(pendingCommitPicks, exceptions);
}

function executeSubmit(commitPicks, exceptions) {
    isSubmitting = true;
    const btn = document.getElementById('btnSubmit'); 
    const originalText = btn.innerHTML; 
    btn.innerHTML = "⏳ Sending..."; btn.disabled = true;
    
    let batchId = localStorage.getItem(`twg_batch_id_${SO_NUMBER}`);
    if (!batchId) batchId = generateUUID();

    fetch('/process_batch_scan', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ so:SO_NUMBER, picks:commitPicks, exceptions: exceptions, batch_id:batchId })
    })
    .then(r => r.json())
    .then(d => {
        if(d.status === 'success') { 
            playBeep('success'); 
            twgAlert(d.msg).then(function() {
                clearLocal(); 
                setTimeout(() => location.reload(), 500); 
            });
        } else { 
            twgAlert("SERVER ERROR: "+d.msg); 
            resetSubmitBtn(btn, originalText);
        }
    })
    .catch(e => { 
        twgAlert("Network Failed: " + e.message); 
        resetSubmitBtn(btn, originalText);
    });
}

function resetSubmitBtn(btn, txt) { isSubmitting=false; btn.innerHTML=txt; btn.disabled=false; }

// --- END EXCEPTION WORKFLOW ---

// ============================================================
// ZERO PICK WORKFLOW — Report a line as unfindable (qty=0)
// This is entirely additive and does NOT modify any existing
// scanning, validation, or submission logic.
// ============================================================

/**
 * Opens the Zero Pick modal for the currently selected row.
 * The picker must select a reason code before confirming.
 * No bin scan or item scan is required — the picker is reporting
 * that they could not find ANY stock for this line.
 */
function openZeroPickModal() {
    if (!selectedItemCode || !selectedLineNo) {
        showToast("Select a line first", 'error');
        return;
    }

    // Prevent duplicate zero picks for the same line
    var existing = sessionPicks.find(function(p) { return p.lineNo === selectedLineNo && p.mode === 'Zero'; });
    if (existing) {
        showToast("Line " + selectedLineNo + " already has a Zero Pick", 'error');
        return;
    }

    // Prevent zero pick if the line already has normal picks
    var hasNormalPicks = sessionPicks.some(function(p) { return p.lineNo === selectedLineNo && p.qty > 0; });
    if (hasNormalPicks) {
        showToast("Line " + selectedLineNo + " already has picks — use Submit to report short", 'error');
        return;
    }

    // Build the modal content
    var needQty = currentOrderMaxQty; // remaining qty for this line
    var body = document.getElementById('zeroPickBody');
    body.innerHTML = 
        '<div style="padding:12px;">' +
            '<div style="margin-bottom:12px; padding:12px; background:#fff5f5; border:2px solid #feb2b2; border-radius:6px;">' +
                '<div style="font-weight:bold; font-size:15px; color:#2d3748; margin-bottom:4px;">' +
                    'Line ' + selectedLineNo + ': <span style="color:#2b6cb0;">' + escapeHtml(selectedItemCode) + '</span>' +
                '</div>' +
                '<div style="font-size:13px; font-weight:bold; color:#e53e3e; margin-bottom:8px;">' +
                    'Needed: ' + needQty + ' &nbsp;|&nbsp; Picking: <span style="font-size:16px;">0</span>' +
                '</div>' +
                '<div style="font-size:12px; color:#718096; margin-bottom:10px;">Select a reason why this line cannot be picked:</div>' +
                '<select id="zeroPickReason" class="scan-input" style="width:100%; height:38px; font-size:14px; border-color:#cbd5e0;">' +
                    '<option value="">-- Select Reason --</option>' +
                    '<option value="NOFND">No Find (Bin empty / Missing)</option>' +
                    '<option value="DMG">Damaged (Found, all unpickable)</option>' +
                '</select>' +
            '</div>' +
        '</div>';

    openModal('zeroPickModal');
}

/**
 * Confirms the zero pick — validates a reason was selected,
 * then pushes a qty=0 entry into sessionPicks with mode='Zero'
 * and the exception code embedded directly in the pick.
 */
async function confirmZeroPick() {
    var reasonSelect = document.getElementById('zeroPickReason');
    if (!reasonSelect || !reasonSelect.value) {
        twgAlert("Please select a reason before confirming.");
        return;
    }

    var reason = reasonSelect.value;

    // Push a zero-qty pick with the exception code baked in
    sessionPicks.push({
        id: Date.now(),
        lineNo: selectedLineNo,
        item: selectedItemCode,
        bin: '',          // No bin — picker couldn't find stock
        qty: 0,
        mode: 'Zero',
        exception: reason  // Stored directly on the pick — used at submit time
    });

    closeModal('zeroPickModal');
    updateSessionDisplay(sessionPicks);
    lockZeroPickRow(selectedLineNo);
    setTimeout(saveToLocal, 0);
    playBeep('success');
    showToast('Zero Pick: Ln ' + selectedLineNo + ' (' + reason + ')', 'success', false);
}

// ============================================================
// END ZERO PICK WORKFLOW
// ============================================================

// --- ZERO PICK ROW STATE HELPERS ---

/**
 * Checks if a line number currently has a Zero Pick entry in sessionPicks.
 */
function isZeroPickedLine(lineNo) {
    return sessionPicks.some(function(p) { return p.lineNo === lineNo && p.mode === 'Zero' && p.qty === 0; });
}

/**
 * Applies greyed-out styling to a row in the order grid.
 * Called after a Zero Pick is confirmed.
 */
function lockZeroPickRow(lineNo) {
    var row = document.getElementById('row-' + lineNo);
    if (!row) return;
    row.style.opacity = '0.4';
    row.style.pointerEvents = 'none';
    row.classList.remove('active-row');
    row.classList.add('zero-picked-row');
}

/**
 * Restores a row to its normal interactive state.
 * Called when a Zero Pick entry is removed from the review list.
 */
function unlockZeroPickRow(lineNo) {
    var row = document.getElementById('row-' + lineNo);
    if (!row) return;
    row.style.opacity = '1';
    row.style.pointerEvents = '';
    row.classList.remove('zero-picked-row');
}

/**
 * Scans all sessionPicks and applies/removes row locks as needed.
 * Called on page load (after restoring from localStorage) and after
 * any pick removal to keep the grid state consistent.
 */
function refreshZeroPickRows() {
    // First unlock all rows
    document.querySelectorAll('.zero-picked-row').forEach(function(row) {
        row.style.opacity = '1';
        row.style.pointerEvents = '';
        row.classList.remove('zero-picked-row');
    });
    // Then lock any that have zero picks
    sessionPicks.forEach(function(p) {
        if (p.mode === 'Zero' && p.qty === 0) {
            lockZeroPickRow(p.lineNo);
        }
    });
}

// --- END ZERO PICK ROW STATE HELPERS ---

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

async function removePick(i){ 
    var ok = await twgConfirm("Remove this entry?");
    if(ok){ 
        sessionPicks.splice(i,1); 
        openReviewModal(); updateSessionDisplay(sessionPicks); refreshZeroPickRows(); setTimeout(saveToLocal, 0); 
    } 
}

async function clearSession() {
    var ok = await twgConfirm("Clear ALL scanned items?");
    if(ok) { 
        sessionPicks = []; openReviewModal(); updateSessionDisplay(sessionPicks); refreshZeroPickRows(); setTimeout(saveToLocal, 0); 
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