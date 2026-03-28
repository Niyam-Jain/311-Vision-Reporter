/* ========================================
   NYC 311 Vision Reporter — Live API Frontend
   WebSocket + AudioWorklet + Audio Playback
   ======================================== */

const $ = (sel) => document.querySelector(sel);

/* ---------- State ---------- */
const state = {
    imageBlob: null,
    imageDataUrl: null,
    latitude: null,
    longitude: null,
    gpsLocked: false,
    cameraStream: null,
    micActive: false,
    // Audio
    micContext: null,
    micWorklet: null,
    micSource: null,
    playContext: null,
    playQueue: [],
    playPlaying: false,
};

/* ---------- DOM refs ---------- */
const els = {
    screenCapture: $("#screen-capture"),
    screenChat:    $("#screen-chat"),
    cameraPreview: $("#camera-preview"),
    photoPreview:  $("#photo-preview"),
    cameraPlaceholder: $("#camera-placeholder"),
    cameraContainer: $(".camera-preview-container"),
    btnCamera:  $("#btn-camera"),
    btnUpload:  $("#btn-upload"),
    fileInput:  $("#file-input"),
    btnSubmit:  $("#btn-submit"),
    gpsDot:     $(".gps-dot"),
    gpsText:    $("#gps-text"),
    chatMessages: $("#chat-messages"),
    chatForm:     $("#chat-form"),
    chatInput:    $("#chat-input"),
    chatLoading:  $("#chat-loading"),
    btnBack:    $("#btn-back"),
    btnNew:     $("#btn-new"),
    btnMic:     $("#btn-mic"),
    micLabel:   $("#mic-label"),
    loadingOverlay: $("#loading-overlay"),
    loadingText:    $("#loading-text"),
};

/* ============================================================
   WebSocket
   ============================================================ */
let ws = null;
let wsReady = false;
const WS_RECONNECT_DELAY = 3000;

function connectWS() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${location.host}/ws`);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
        wsReady = true;
        console.log("[WS] connected");
    };

    ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
            // Raw PCM audio from the agent — queue for playback
            playAudioChunk(event.data);
        } else {
            try {
                const msg = JSON.parse(event.data);
                handleServerMessage(msg);
            } catch (e) {
                console.warn("[WS] non-JSON text:", event.data);
            }
        }
    };

    ws.onerror = (e) => console.warn("[WS] error", e);

    ws.onclose = () => {
        wsReady = false;
        console.log(`[WS] closed — reconnecting in ${WS_RECONNECT_DELAY}ms`);
        setTimeout(connectWS, WS_RECONNECT_DELAY);
    };
}

function wsSend(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(data);
    }
}

function handleServerMessage(msg) {
    switch (msg.type) {
        case "transcript":
            // Transcription of spoken audio — show in chat
            if (msg.role === "agent") {
                addMessage("agent", msg.content);
            } else if (msg.role === "user" && msg.content.trim()) {
                addMessage("user", msg.content);
            }
            break;

        case "text":
            addMessage("agent", msg.content);
            break;

        case "draft":
            renderDraftCard(msg.complaint);
            break;

        default:
            console.log("[WS] unknown message type:", msg.type);
    }
}

/* ============================================================
   GPS
   ============================================================ */
function initGPS() {
    if (!navigator.geolocation) {
        setGPSStatus("error", "Geolocation not supported");
        return;
    }
    navigator.geolocation.watchPosition(
        (pos) => {
            state.latitude  = pos.coords.latitude;
            state.longitude = pos.coords.longitude;
            state.gpsLocked = true;
            setGPSStatus("locked", `${pos.coords.latitude.toFixed(5)}, ${pos.coords.longitude.toFixed(5)}`);
            checkReady();
        },
        (err) => {
            console.warn("GPS error:", err.message);
            setGPSStatus("error", "Location unavailable — enable GPS");
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 }
    );
}

function setGPSStatus(status, text) {
    els.gpsDot.className = "gps-dot";
    if (status === "locked") els.gpsDot.classList.add("locked");
    else if (status === "error") els.gpsDot.classList.add("error");
    else els.gpsDot.classList.add("pulse");
    els.gpsText.textContent = text;
}

/* ============================================================
   Camera / Upload
   ============================================================ */
async function openCamera() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 960 } },
            audio: false,
        });
        state.cameraStream = stream;
        els.cameraPreview.srcObject = stream;
        els.cameraPreview.classList.add("active");
        els.cameraPlaceholder.classList.add("hidden");
        els.photoPreview.classList.add("hidden");
        els.btnCamera.onclick = captureFromCamera;
    } catch (err) {
        console.warn("Camera not available:", err.message);
        els.fileInput.click();
    }
}

function captureFromCamera() {
    const video = els.cameraPreview;
    const canvas = document.createElement("canvas");
    canvas.width  = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
        setPhoto(blob, canvas.toDataURL("image/jpeg", 0.85));
    }, "image/jpeg", 0.85);
    stopCamera();
}

function stopCamera() {
    if (state.cameraStream) {
        state.cameraStream.getTracks().forEach((t) => t.stop());
        state.cameraStream = null;
    }
    els.cameraPreview.classList.remove("active");
}

function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setPhoto(file, reader.result);
    reader.readAsDataURL(file);
}

function setPhoto(blob, dataUrl) {
    state.imageBlob    = blob;
    state.imageDataUrl = dataUrl;
    els.photoPreview.src = dataUrl;
    els.photoPreview.classList.remove("hidden");
    els.cameraPlaceholder.classList.add("hidden");
    els.cameraContainer.classList.add("has-photo");
    checkReady();
}

function checkReady() {
    const ready = state.imageBlob && state.gpsLocked;
    els.btnSubmit.disabled = !ready;
    if (ready) els.btnSubmit.classList.remove("hidden");
}

/* ============================================================
   Submit photo over WebSocket
   ============================================================ */
async function submitPhoto() {
    if (!state.imageBlob || !state.gpsLocked) return;

    showLoading("Sending to AI…");

    try {
        // Convert blob to base64
        const arrayBuffer = await state.imageBlob.arrayBuffer();
        const b64 = btoa(
            new Uint8Array(arrayBuffer).reduce((s, b) => s + String.fromCharCode(b), "")
        );

        wsSend(JSON.stringify({
            type: "image",
            image_base64: b64,
            latitude:  state.latitude,
            longitude: state.longitude,
        }));

        switchToChat();
        addImageMessage();
        showTyping();
    } catch (err) {
        console.error("Submit error:", err);
        addToast("Failed to send photo. Please try again.");
    } finally {
        hideLoading();
    }
}

/* ============================================================
   Audio — Microphone capture via AudioWorklet
   ============================================================ */
async function startMic() {
    try {
        // Use 16 kHz context — Chrome/Edge support custom sample rates
        state.micContext = new AudioContext({ sampleRate: 16000 });
        // Chrome may suspend AudioContext even on user gesture — force resume
        if (state.micContext.state === "suspended") {
            await state.micContext.resume();
        }
        console.log("[mic] AudioContext state:", state.micContext.state, "sampleRate:", state.micContext.sampleRate);
        await state.micContext.audioWorklet.addModule("audio-processor.js");

        const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        state.micSource = state.micContext.createMediaStreamSource(stream);

        state.micWorklet = new AudioWorkletNode(state.micContext, "pcm-capture");
        let chunkCount = 0;
        state.micWorklet.port.onmessage = (e) => {
            wsSend(e.data.buffer);
            chunkCount++;
            if (chunkCount <= 3 || chunkCount % 50 === 0) {
                console.log(`[mic] sent chunk #${chunkCount}, ${e.data.byteLength} bytes, ws state: ${ws?.readyState}`);
            }
        };

        state.micSource.connect(state.micWorklet);
        state.micWorklet.connect(state.micContext.destination);

        state.micActive = true;
        els.btnMic.classList.add("listening");
        els.micLabel.textContent = "Tap to stop";
    } catch (err) {
        console.error("Mic error:", err);
        addToast("Microphone unavailable. Use the text box below.");
    }
}

function stopMic() {
    if (state.micSource)  state.micSource.disconnect();
    if (state.micWorklet) state.micWorklet.disconnect();
    if (state.micContext) state.micContext.close();
    state.micSource  = null;
    state.micWorklet = null;
    state.micContext = null;
    state.micActive  = false;
    els.btnMic.classList.remove("listening");
    els.micLabel.textContent = "Tap to speak";
}

function toggleMic() {
    if (state.micActive) {
        stopMic();
    } else {
        startMic();
    }
}

/* ============================================================
   Audio — Playback of agent's PCM audio (24 kHz from Gemini)
   ============================================================ */
const PLAY_SAMPLE_RATE = 24000;

function ensurePlayContext() {
    if (!state.playContext || state.playContext.state === "closed") {
        state.playContext = new AudioContext({ sampleRate: PLAY_SAMPLE_RATE });
    }
    if (state.playContext.state === "suspended") {
        state.playContext.resume();
    }
}

function playAudioChunk(arrayBuffer) {
    ensurePlayContext();
    hideTyping();

    // Convert Int16 PCM → Float32
    const int16 = new Int16Array(arrayBuffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768.0;
    }

    const audioBuffer = state.playContext.createBuffer(1, float32.length, PLAY_SAMPLE_RATE);
    audioBuffer.copyToChannel(float32, 0);

    state.playQueue.push(audioBuffer);
    if (!state.playPlaying) drainPlayQueue();
}

let playEndTime = 0;

function drainPlayQueue() {
    if (state.playQueue.length === 0) {
        state.playPlaying = false;
        return;
    }
    state.playPlaying = true;
    ensurePlayContext();

    const buf = state.playQueue.shift();
    const src = state.playContext.createBufferSource();
    src.buffer = buf;
    src.connect(state.playContext.destination);

    const startAt = Math.max(state.playContext.currentTime, playEndTime);
    src.start(startAt);
    playEndTime = startAt + buf.duration;
    src.onended = drainPlayQueue;
}

/* ============================================================
   Chat text sending
   ============================================================ */
function sendChatMessage(text) {
    if (!text.trim()) return;
    addMessage("user", text);
    els.chatInput.value = "";
    showTyping();
    wsSend(JSON.stringify({ type: "text", content: text }));
}

/* ============================================================
   Draft card rendering + fake submission flow
   ============================================================ */
let mapsApiKey = "";
fetch("/api/config").then(r => r.json()).then(cfg => { mapsApiKey = cfg.maps_api_key || ""; }).catch(() => {});

function buildMapUrl(lat, lng) {
    if (!mapsApiKey || lat == null || lng == null) return null;
    return `https://maps.googleapis.com/maps/api/staticmap?center=${lat},${lng}&zoom=17&size=400x200&markers=color:red|${lat},${lng}&key=${mapsApiKey}`;
}

function generateComplaintNumber() {
    const n = Math.floor(10000 + Math.random() * 89999);
    return `311-2026-${n}`;
}

async function runSubmissionFlow(btn, statusEl, complaint, complaintNum) {
    const steps = [
        { text: "Connecting to Open311 API...",          delay: 500  },
        { text: "Uploading photo evidence...",           delay: 800  },
        { text: `Submitting complaint #${complaintNum}...`, delay: 700 },
        { text: "Confirmed ✓",                           delay: 500  },
    ];

    for (const step of steps) {
        statusEl.textContent = step.text;
        await new Promise(r => setTimeout(r, step.delay));
    }

    // Replace the whole draft card with the success card
    const card = btn.closest(".draft-card");
    card.innerHTML = `
        <div class="success-card">
            <div class="success-icon">✅</div>
            <h3>Complaint Submitted Successfully</h3>
            <p class="complaint-num">${complaintNum}</p>
            <p class="address-line">${complaint.address_string || ""}</p>
            <p class="email-note">You'll receive updates at your registered email</p>
            <p class="demo-note">Demo mode — Open311 API integration ready for production</p>
        </div>`;
    scrollToBottom();
}

function renderDraftCard(complaint) {
    hideTyping();
    const lat = state.latitude;
    const lng = state.longitude;
    const mapUrl = buildMapUrl(lat, lng);
    const complaintNum = generateComplaintNumber();

    const div = document.createElement("div");
    div.className = "message agent";
    div.innerHTML = `
        <div class="draft-card">
            <h3>📋 Complaint Review</h3>
            ${mapUrl ? `<img class="map-thumbnail" src="${mapUrl}" alt="Location map">` : ""}
            <dl>
                <dt>Issue</dt>       <dd>${complaint.service_name || "—"}</dd>
                <dt>Severity</dt>    <dd>${complaint.severity_label || "—"} (${complaint.severity || "—"}/5)</dd>
                <dt>Address</dt>     <dd>${complaint.address_string || "—"}</dd>
                <dt>Borough</dt>     <dd>${complaint.borough || "—"}</dd>
                <dt>ZIP</dt>         <dd>${complaint.zipcode || "—"}</dd>
                <dt>Description</dt> <dd>${complaint.description || "—"}</dd>
            </dl>
            <div class="draft-actions">
                <button class="btn-approve">Approve &amp; Submit</button>
                <span class="submit-status"></span>
            </div>
        </div>`;

    const btn = div.querySelector(".btn-approve");
    const statusEl = div.querySelector(".submit-status");

    btn.addEventListener("click", () => {
        btn.disabled = true;
        btn.innerHTML = `<span class="btn-spinner"></span> Submitting to NYC 311...`;
        runSubmissionFlow(btn, statusEl, complaint, complaintNum);
    });

    els.chatMessages.appendChild(div);
    scrollToBottom();
}

/* ============================================================
   UI Helpers
   ============================================================ */
function addMessage(role, text) {
    hideTyping();
    const div = document.createElement("div");
    div.className = `message ${role}`;
    div.innerHTML = formatMessage(text);
    els.chatMessages.appendChild(div);
    scrollToBottom();
}

function addImageMessage() {
    if (!state.imageDataUrl) return;
    const div = document.createElement("div");
    div.className = "message user";
    div.innerHTML = `<img class="message-image" src="${state.imageDataUrl}" alt="Reported issue photo">
<span style="font-size:12px;opacity:0.8;">📍 ${state.latitude.toFixed(5)}, ${state.longitude.toFixed(5)}</span>`;
    els.chatMessages.appendChild(div);
    scrollToBottom();
}

function formatMessage(text) {
    return text
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.*?)\*/g, "<em>$1</em>")
        .replace(/`(.*?)`/g, "<code>$1</code>")
        .replace(/\n/g, "<br>");
}

function scrollToBottom() {
    requestAnimationFrame(() => {
        els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
    });
}

function showTyping() { els.chatLoading.classList.remove("hidden"); scrollToBottom(); }
function hideTyping() { els.chatLoading.classList.add("hidden"); }

function showLoading(text) {
    els.loadingText.textContent = text || "Processing…";
    els.loadingOverlay.classList.remove("hidden");
}
function hideLoading() { els.loadingOverlay.classList.add("hidden"); }

function switchToChat() {
    els.screenCapture.classList.remove("active");
    els.screenChat.classList.add("active");
    els.chatInput.focus();
}

function switchToCapture() {
    els.screenChat.classList.remove("active");
    els.screenCapture.classList.add("active");
}

function resetApp() {
    state.imageBlob    = null;
    state.imageDataUrl = null;
    if (state.micActive) stopMic();

    els.photoPreview.classList.add("hidden");
    els.cameraPlaceholder.classList.remove("hidden");
    els.cameraContainer.classList.remove("has-photo");
    els.btnSubmit.classList.add("hidden");
    els.btnSubmit.disabled = true;
    els.chatMessages.innerHTML = "";
    els.btnCamera.onclick = openCamera;

    switchToCapture();
}

function addToast(text) {
    const toast = document.createElement("div");
    toast.style.cssText = `
        position:fixed;bottom:32px;left:50%;transform:translateX(-50%);
        background:rgba(248,113,113,0.95);color:white;padding:12px 24px;
        border-radius:12px;font-size:14px;font-weight:500;z-index:200;
        animation:messageIn 0.3s ease-out;max-width:90vw;text-align:center;`;
    toast.textContent = text;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

/* ============================================================
   Event Listeners
   ============================================================ */
els.btnCamera.addEventListener("click", openCamera);
els.fileInput.addEventListener("change", handleFileUpload);
els.btnSubmit.addEventListener("click", submitPhoto);
els.btnMic.addEventListener("click", toggleMic);

els.chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    sendChatMessage(els.chatInput.value);
});

els.btnBack.addEventListener("click", () => {
    if (confirm("Go back? Your current conversation will be preserved.")) {
        switchToCapture();
    }
});

els.btnNew.addEventListener("click", () => {
    if (confirm("Start a new report? This will clear the current conversation.")) {
        resetApp();
    }
});

/* ============================================================
   Init
   ============================================================ */
connectWS();
initGPS();
console.log("NYC 311 Vision Reporter (Live API) loaded");
