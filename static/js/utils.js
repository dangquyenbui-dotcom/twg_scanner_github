/* utils.js - Generic Utilities (Audio, UUID, Logs) */

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
    const doc = window.document; const docEl = doc.documentElement;
    const req = docEl.requestFullscreen || docEl.mozRequestFullScreen || docEl.webkitRequestFullScreen || docEl.msRequestFullscreen;
    if(!doc.fullscreenElement && !doc.mozFullScreenElement && !doc.webkitFullscreenElement && !doc.msFullscreenElement && req) {
        req.call(docEl).catch(e=>{});
    }
}

// --- AUDIO ENGINE ---
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

function unlockAudio() { 
    if (audioCtx.state === 'suspended') audioCtx.resume().then(() => log("Audio Resumed")); 
}

// Auto-bind audio unlock
['touchstart', 'click', 'keydown', 'mousedown'].forEach(evt => {
    document.body.addEventListener(evt, unlockAudio, {once:false, passive:true});
});

function playBeep(type) {
    try {
        if (audioCtx.state === 'suspended') audioCtx.resume();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
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