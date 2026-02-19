/* utils.js - Generic Utilities (Audio, UUID, Logs, Device ID, Fullscreen) */

// --- UTILS ---
function generateUUID() {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

function getDeviceId() {
    var devId = localStorage.getItem('twg_device_id');
    if (!devId) {
        var randomPart = Math.random().toString(36).substring(2, 10).toUpperCase();
        devId = 'TC52-' + randomPart; 
        localStorage.setItem('twg_device_id', devId);
    }
    return devId;
}

function log(msg) {
    var c = document.getElementById('debugConsole');
    if(!c) return;
    var d = document.createElement('div');
    d.innerText = '[' + new Date().toLocaleTimeString().split(' ')[0] + '] ' + msg; 
    c.prepend(d); 
    console.log(msg);
}

function toggleDebug() {
    var c = document.getElementById('debugConsole');
    if(c) c.style.display = (c.style.display === 'none') ? 'block' : 'none';
}


// ============================================================
// FULLSCREEN MANAGEMENT
// ============================================================

function isPWAStandalone() {
    return (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
           (window.matchMedia && window.matchMedia('(display-mode: fullscreen)').matches) ||
           (window.navigator.standalone === true);
}

function isFullscreen() {
    return !!(document.fullscreenElement || 
              document.mozFullScreenElement || 
              document.webkitFullscreenElement || 
              document.msFullscreenElement);
}

/**
 * Checks if the currently focused element is a text input, password field,
 * textarea, or any other element that would trigger a virtual keyboard.
 * When such an element is focused, we must NOT force fullscreen because
 * doing so will dismiss or block the virtual keyboard on mobile devices.
 */
function isInputFocused() {
    var el = document.activeElement;
    if (!el) return false;
    var tag = el.tagName.toLowerCase();
    if (tag === 'textarea') return true;
    if (tag === 'select') return true;
    if (tag === 'input') {
        var type = (el.type || '').toLowerCase();
        // These input types trigger a virtual keyboard
        var keyboardTypes = ['text', 'password', 'email', 'number', 'search', 'tel', 'url', 'numeric'];
        return keyboardTypes.indexOf(type) !== -1;
    }
    // contenteditable elements also trigger keyboards
    if (el.isContentEditable) return true;
    return false;
}

function enterFullscreen() {
    var docEl = document.documentElement;
    var req = docEl.requestFullscreen || 
              docEl.mozRequestFullScreen || 
              docEl.webkitRequestFullScreen || 
              docEl.msRequestFullscreen;
    
    if (req) {
        return req.call(docEl).catch(function(e) {
            console.warn("Fullscreen: Request denied -", e.message);
        });
    }
    return Promise.resolve();
}

function exitFullscreen() {
    var exitFn = document.exitFullscreen || 
                 document.mozCancelFullScreen || 
                 document.webkitExitFullscreen || 
                 document.msExitFullscreen;
    if (exitFn) {
        exitFn.call(document).catch(function(e) {
            console.warn("Fullscreen: Exit failed -", e.message);
        });
    }
}

/**
 * Silently enters fullscreen on the next user interaction,
 * BUT only if no input field is currently focused (to avoid blocking the virtual keyboard).
 * Called on page load and whenever fullscreen is accidentally exited.
 */
function autoEnterFullscreen() {
    if (isPWAStandalone() || isFullscreen()) return;

    function tryEnter() {
        // CRITICAL: Do NOT enter fullscreen if an input is focused — it kills the virtual keyboard
        if (isInputFocused()) return;
        if (!isFullscreen() && !isPWAStandalone()) {
            enterFullscreen();
        }
    }

    // Browsers require a user gesture — attach to first touch/click
    document.addEventListener('touchstart', tryEnter, { once: true, passive: true });
    document.addEventListener('click', tryEnter, { once: true });
}

/**
 * Re-enter fullscreen if the user accidentally exits (swipe, etc.),
 * but NOT if an input field is focused (keyboard is open).
 */
function watchFullscreenExit() {
    ['fullscreenchange', 'webkitfullscreenchange', 'mozfullscreenchange', 'MSFullscreenChange'].forEach(function(evt) {
        document.addEventListener(evt, function() {
            if (!isFullscreen() && !isPWAStandalone()) {
                // Don't immediately re-enter if an input is focused (keyboard caused the exit)
                if (isInputFocused()) return;
                autoEnterFullscreen();
            }
        });
    });
}

/** Legacy compat */
function forceFullscreen() {
    // Respect input focus — don't force fullscreen when keyboard should be open
    if (isInputFocused()) return;
    if (!isFullscreen() && !isPWAStandalone()) {
        enterFullscreen();
    }
}

// --- Initialize: go fullscreen on first interaction, re-enter if exited ---
document.addEventListener('DOMContentLoaded', function() {
    autoEnterFullscreen();
    watchFullscreenExit();
});


// ============================================================
// AUDIO ENGINE
// ============================================================

var audioCtx = new (window.AudioContext || window.webkitAudioContext)();

function unlockAudio() { 
    if (audioCtx.state === 'suspended') audioCtx.resume().then(function() { 
        if (typeof log === 'function') log("Audio Resumed"); 
    }); 
}

['touchstart', 'click', 'keydown', 'mousedown'].forEach(function(evt) {
    document.body.addEventListener(evt, unlockAudio, {once:false, passive:true});
});

function playBeep(type) {
    try {
        if (audioCtx.state === 'suspended') audioCtx.resume();
        var osc = audioCtx.createOscillator();
        var gain = audioCtx.createGain();
        osc.connect(gain); gain.connect(audioCtx.destination);
        
        if (type === 'success') { 
            osc.frequency.value = 1500; osc.type = 'sine'; gain.gain.value = 0.3; 
            osc.start(); osc.stop(audioCtx.currentTime + 0.15); 
        } else { 
            osc.frequency.value = 150; osc.type = 'sawtooth'; gain.gain.value = 0.4; 
            osc.start(); osc.stop(audioCtx.currentTime + 0.4); 
        }
    } catch(e) { console.error("Audio Error:", e); }
}