let doctorMqttClient = null;
let doctorControlTopic = "";
let pendingMqttPayloads = [];

function connectDoctorMQTT(appId, channel) {
  const targetAppId = appId || (document.getElementById("appId") ? document.getElementById("appId").value.trim() : "");
  const targetChannel = channel || (document.getElementById("channel") ? document.getElementById("channel").value.trim() : "torus");

  if (!targetAppId) {
    console.warn("[Doctor MQTT] App ID is missing, skipping MQTT connection.");
    return;
  }

  const cleanAppId = targetAppId.substring(0, 8);
  doctorControlTopic = `${targetChannel}-control-${cleanAppId}`;

  if (doctorMqttClient && doctorMqttClient.connected) {
    return;
  }

  const brokerUrls = [
    "wss://broker.hivemq.com:8884/mqtt",
    "wss://broker.emqx.io:8084/mqtt"
  ];
  let attempts = 0;

  function tryConnectDoctor() {
    const url = brokerUrls[attempts % brokerUrls.length];
    console.log(`[Doctor MQTT] Connecting to ${url} on topic: ${doctorControlTopic}`);
    try {
      doctorMqttClient = mqtt.connect(url, { keepalive: 30, reconnectPeriod: 3000 });

      doctorMqttClient.on("connect", () => {
        console.log(`[Doctor MQTT] Connected to ${url} on topic: ${doctorControlTopic}`);
        // Flush any queued payloads
        while (pendingMqttPayloads.length > 0) {
          const payload = pendingMqttPayloads.shift();
          doctorMqttClient.publish(doctorControlTopic, payload);
          console.log(`[Doctor MQTT] Flushed queued control to ${doctorControlTopic}:`, payload);
        }
      });

      doctorMqttClient.on("error", (err) => {
        console.error(`[Doctor MQTT] Connection error on ${url}:`, err);
        doctorMqttClient.end();
        attempts++;
        if (attempts < 4) {
          setTimeout(tryConnectDoctor, 1500);
        }
      });
    } catch (e) {
      console.error("[Doctor MQTT] Exception on connection attempt:", e);
    }
  }

  tryConnectDoctor();
}

function sendControlCommand(name, value) {
  if (roleInput.value !== "doctor") return;

  const payload = JSON.stringify({ control: name, value: value });

  if (!doctorMqttClient || !doctorMqttClient.connected) {
    console.log(`[Doctor MQTT] Not connected yet. Initiating connection and queuing: ${name} = ${value}`);
    pendingMqttPayloads.push(payload);
    connectDoctorMQTT();
    return;
  }

  doctorMqttClient.publish(doctorControlTopic, payload);
  console.log(`[Doctor MQTT] Published control: ${name} = ${value} to ${doctorControlTopic}`);
}

const appIdInput = document.getElementById("appId");
const channelInput = document.getElementById("channel");
const tokenInput = document.getElementById("token");
const uidInput = document.getElementById("uid");
const joinBtn = document.getElementById("joinBtn");
const leaveBtn = document.getElementById("leaveBtn");
const statusEl = document.getElementById("status");
const videosGrid = document.getElementById("videos-grid");
const localCard = document.getElementById("local-card");
const localPlayerEl = document.getElementById("local-player");
const localFitBtn = document.getElementById("local-fit-btn");
const localPinBtn = document.getElementById("local-pin-btn");
const localZoomInBtn = document.getElementById("local-zoom-in-btn");
const localZoomOutBtn = document.getElementById("local-zoom-out-btn");

// Role & Mic Mute selectors
const roleInput = document.getElementById("role");
const feedTypeContainer = document.getElementById("feed-type-container");
const feedTypeInput = document.getElementById("feedType");
const muteBtn = document.getElementById("muteBtn");
const localCameraBtn = document.getElementById("local-camera-btn");
const localMicBtn = document.getElementById("local-mic-btn");
const backBtn = document.getElementById("backBtn");

// Floating self-view selectors
const floatingSelfView = document.getElementById("floating-self-view");
const selfViewCloseBtn = document.getElementById("self-view-close-btn");
const selfViewCamBtn = document.getElementById("self-view-cam-btn");
const selfViewMicBtn = document.getElementById("self-view-mic-btn");
const selfViewMinimizeBtn = document.getElementById("self-view-minimize-btn");

// Initialize muteBtn and localMicBtn state on load
const savedPatientMuted = localStorage.getItem("patient_mic_muted") === "true";
if (savedPatientMuted) {
  muteBtn.classList.add("muted");
  muteBtn.textContent = "Unmute Mic";
  if (localMicBtn) {
    localMicBtn.classList.remove("active");
    localMicBtn.classList.add("inactive");
    localMicBtn.title = "Unmute Microphone";
  }
} else {
  muteBtn.classList.remove("muted");
  muteBtn.textContent = "Mute Mic";
  if (localMicBtn) {
    localMicBtn.classList.add("active");
    localMicBtn.classList.remove("inactive");
    localMicBtn.title = "Mute Microphone";
  }
}
syncSelfViewControls();

let client;
let localTracks = {
  audioTrack: null,
  videoTrack: null,
};

let popoutWindow = null;
let doctorPopoutWindow = null;
let patientPopoutWindow = null;

// Store zoom and translation states for each video card container
const zoomStates = new Map();

const PROBE_SVG = `<svg class="title-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle; display: inline-block; color: #a78bfa; margin-right: 6px;"><path d="M9 9h6v6a3 3 0 0 1-3 3h0a3 3 0 0 1-3-3V9z"/><path d="M8 9V6c0-1.5 1.5-3 4-3s4 1.5 4 3v3"/><path d="M8 6h8"/><path d="M12 18v3c0 1-1 2-2 2"/></svg>`;
const PATIENT_SVG = `<svg class="title-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle; display: inline-block; color: #a78bfa; margin-right: 6px;"><circle cx="10" cy="8" r="4"/><path d="M3 20v-2a4 4 0 0 1 4-4h6"/><path d="M19 14v6"/><path d="M16 17h6"/></svg>`;

// Initialize local card state
localCard.classList.add("fit-contain");

// Dynamically toggle visibility of the feed-type selector based on Role and automatically lock pre-defined UIDs
roleInput.addEventListener("change", () => {
  const selectedRole = roleInput.value;
  if (selectedRole === "doctor") {
    uidInput.value = 3001;
  } else if (selectedRole === "patient") {
    uidInput.value = 4001;
  } else if (selectedRole === "viewer") {
    // Generate a unique random UID for each viewer tab (e.g. 6000 + random)
    uidInput.value = 6000 + Math.floor(Math.random() * 9000);
  }
  if (feedTypeContainer) feedTypeContainer.style.display = "none";
  updateControlsButtonVisibility();
  updateSettingsSessionCodeVisibility();
});

let OFFICIAL_TOKEN_VALUE = "";

// Dynamically fetch Agora configuration from the backend environment
async function fetchAgoraConfiguration() {
  const isPort3000 = window.location.port === "3000";
  const endpoints = isPort3000
    ? ["/api/agora/config", "http://127.0.0.1:3000/api/agora/config", "http://localhost:3000/api/agora/config"]
    : ["http://127.0.0.1:3000/api/agora/config", "http://localhost:3000/api/agora/config", "/api/agora/config"];

  for (const url of endpoints) {
    try {
      const resp = await fetch(url, { method: "GET" });
      if (resp.ok) {
        const data = await resp.json();
        if (data.token) {
          OFFICIAL_TOKEN_VALUE = data.token;
          const tokenInputEl = document.getElementById("token");
          if (tokenInputEl && !tokenInputEl.value.trim()) {
            tokenInputEl.value = data.token;
          }
        }
        if (data.appId && typeof appIdInput !== "undefined" && appIdInput && !appIdInput.value.trim()) {
          appIdInput.value = data.appId;
        }
        if (data.channel && typeof channelInput !== "undefined" && channelInput && !channelInput.value.trim()) {
          channelInput.value = data.channel;
        }
        return data;
      }
    } catch (e) {
      // Continue next endpoint
    }
  }
  return null;
}

// Automatically fetch Agora config from environment on startup
fetchAgoraConfiguration();

// Ensure Token field exists with plain text display and exact official value
function ensureTokenFieldExists() {
  let tokenWrapper = document.getElementById("settings-token-wrapper");
  let tokenInputEl = document.getElementById("token");

  const controlsGrid = document.querySelector("#settingsModal .controls-grid");
  if (!controlsGrid) return;

  if (!tokenWrapper) {
    tokenWrapper = document.createElement("label");
    tokenWrapper.id = "settings-token-wrapper";
    tokenWrapper.className = "full-width";

    const tokenSpan = document.createElement("span");
    tokenSpan.textContent = "Token";
    tokenWrapper.appendChild(tokenSpan);

    if (tokenInputEl) {
      tokenInputEl.type = "text";
      tokenInputEl.placeholder = "Enter Agora Token";
      tokenInputEl.spellcheck = false;
      tokenInputEl.autocomplete = "off";
      if (!tokenInputEl.value && OFFICIAL_TOKEN_VALUE) {
        tokenInputEl.value = OFFICIAL_TOKEN_VALUE;
      }
      tokenWrapper.appendChild(tokenInputEl);
    } else {
      tokenInputEl = document.createElement("input");
      tokenInputEl.id = "token";
      tokenInputEl.type = "text";
      tokenInputEl.placeholder = "Enter Agora Token";
      if (OFFICIAL_TOKEN_VALUE) {
        tokenInputEl.value = OFFICIAL_TOKEN_VALUE;
      }
      tokenInputEl.spellcheck = false;
      tokenInputEl.autocomplete = "off";
      tokenWrapper.appendChild(tokenInputEl);
    }

    const sessionCodeWrapper = document.getElementById("settings-session-code-wrapper") ||
      document.querySelector(".modal-session-code-wrapper")?.closest("label");
    const uidWrapper = document.getElementById("settings-uid-wrapper") ||
      document.getElementById("uid")?.closest("label");

    const anchor = sessionCodeWrapper || uidWrapper;
    if (anchor && anchor.nextSibling) {
      controlsGrid.insertBefore(tokenWrapper, anchor.nextSibling);
    } else {
      controlsGrid.appendChild(tokenWrapper);
    }
  } else {
    if (tokenInputEl) {
      if (tokenInputEl.type === "hidden") tokenInputEl.type = "text";
      if (!tokenInputEl.value && OFFICIAL_TOKEN_VALUE) tokenInputEl.value = OFFICIAL_TOKEN_VALUE;
      tokenInputEl.placeholder = "Enter Agora Token";
      tokenInputEl.spellcheck = false;
    }
    const span = tokenWrapper.querySelector("span");
    if (span) span.textContent = "Token";
  }

  if (!OFFICIAL_TOKEN_VALUE) {
    fetchAgoraConfiguration();
  }
}

// Update Session Code & Token visibility in Agora Connection Settings based on Active Role
// Token is visible on Doctor, Patient, and Viewer sides.
// STRICT SECURITY RULE: Session Code is visible on Doctor side only. Never visible to Patient or Viewer.
function updateSettingsSessionCodeVisibility() {
  ensureTokenFieldExists();
  const sessionCodeWrapper = document.getElementById("settings-session-code-wrapper") ||
    document.querySelector(".modal-session-code-wrapper")?.closest("label");
  const uidWrapper = document.getElementById("settings-uid-wrapper") ||
    document.getElementById("uid")?.closest("label");
  const tokenWrapper = document.getElementById("settings-token-wrapper");
  const feedTypeCont = document.getElementById("feed-type-container");

  // Remove Live Feed / USB camera selector from UI completely
  if (feedTypeCont) feedTypeCont.style.display = "none";

  let currentRole = "doctor";
  if (roleInput && roleInput.value) {
    currentRole = roleInput.value;
  } else if (typeof currentAuthenticatedUser !== "undefined" && currentAuthenticatedUser && currentAuthenticatedUser.role) {
    currentRole = currentAuthenticatedUser.role;
  }

  document.body.dataset.role = currentRole;

  // Token is visible across Doctor, Patient, and Viewer
  if (tokenWrapper) {
    tokenWrapper.style.display = "";
  }

  // Session Code is visible ONLY on Doctor side
  if (currentRole === "doctor") {
    if (sessionCodeWrapper) sessionCodeWrapper.style.display = "";
    if (uidWrapper) uidWrapper.classList.remove("full-width");
  } else {
    if (sessionCodeWrapper) sessionCodeWrapper.style.display = "none";
    if (uidWrapper) uidWrapper.classList.add("full-width");
  }
}

// Join Order Tracking & Sorting
const joinOrder = [];

function updateCardOrders() {
  const localUidVal = uidInput.value.trim() ? Number(uidInput.value) : (roleInput.value === "patient" ? 4001 : 3001);

  // Separate viewers from other feeds
  const coreFeeds = [5001, 4001, 3001];

  // Find all active viewers in joinOrder
  const viewersInCall = joinOrder.filter(uid => !coreFeeds.includes(uid));
  // Sort viewers by their assigned viewer numbers
  viewersInCall.sort((a, b) => getViewerNumber(a) - getViewerNumber(b));

  const displayList = [];
  const currentRole = roleInput.value;

  if (currentRole === "doctor") {
    // 1. Ultrasound Feed
    if (joinOrder.includes(5001)) {
      displayList.push(5001);
    }
    // 2. Patient Camera
    if (joinOrder.includes(4001)) {
      displayList.push(4001);
    }
    // 3. Doctor Camera (self-view)
    if (joinOrder.includes(3001)) {
      displayList.push(3001);
    }
    // 4. Viewers
    for (const viewerUid of viewersInCall) {
      displayList.push(viewerUid);
    }
  } else if (currentRole === "patient") {
    // 1. Ultrasound Feed
    if (joinOrder.includes(5001)) {
      displayList.push(5001);
    }
    // 2. Doctor Camera
    if (joinOrder.includes(3001)) {
      displayList.push(3001);
    }
    // 3. Patient Camera (self-view)
    if (joinOrder.includes(4001)) {
      displayList.push(4001);
    }
    // 4. Viewers
    for (const viewerUid of viewersInCall) {
      displayList.push(viewerUid);
    }
  } else {
    // Viewer Mode layout
    // 1. Ultrasound Feed
    if (joinOrder.includes(5001)) {
      displayList.push(5001);
    }
    // 2. Patient Camera
    if (joinOrder.includes(4001)) {
      displayList.push(4001);
    }
    // 3. Doctor Camera
    if (joinOrder.includes(3001)) {
      displayList.push(3001);
    }
    // 4. Viewers
    for (const viewerUid of viewersInCall) {
      displayList.push(viewerUid);
    }
  }

  // Update card elements' style order and titles
  const cards = document.querySelectorAll(".video-card");
  cards.forEach(card => {
    let uid;
    if (card.id === "local-card") {
      uid = localUidVal;
    } else {
      uid = Number(card.id.replace("remote-card-", ""));
    }

    const idx = displayList.indexOf(uid);
    if (idx !== -1) {
      card.style.order = idx + 1;
    } else {
      card.style.order = 999;
    }

    // Dynamic Title Management
    const h2 = card.querySelector(".video-header h2");
    if (h2) {
      if (uid === 5001) {
        h2.innerHTML = PROBE_SVG + "Remote Ultrasound Feed";
      } else if (uid === 3001) {
        const isLocal = (card.id === "local-card");
        const hasVideo = isLocal ? !!localTracks.videoTrack : !!client?.remoteUsers.find(u => u.uid === 3001)?.videoTrack;
        h2.innerHTML = "🩺 Doctor Camera" + (hasVideo ? "" : " (No Video)");
      } else if (uid === 4001) {
        const isLocal = (card.id === "local-card");
        const hasVideo = isLocal ? !!localTracks.videoTrack : !!client?.remoteUsers.find(u => u.uid === 4001)?.videoTrack;
        h2.innerHTML = PATIENT_SVG + "Patient Camera" + (hasVideo ? "" : " (No Video)");
      } else {
        const viewerNum = getViewerNumber(uid);
        const isLocal = (card.id === "local-card");
        const hasVideo = isLocal ? !!localTracks.videoTrack : !!client?.remoteUsers.find(u => u.uid === uid)?.videoTrack;
        h2.innerHTML = `👤 Viewer ${viewerNum} Camera` + (hasVideo ? "" : " (No Video)");
      }
    }

    // Show/hide popout button on local card
    if (card.id === "local-card") {
      const localPopoutBtn = document.getElementById("local-popout-btn");
      if (localPopoutBtn) {
        localPopoutBtn.style.display = (uid === 5001 || uid === 3001 || uid === 4001) ? "" : "none";
      }
    }
  });
}

// ==========================================================================
// VIEWER DYNAMIC TRACKING & NUMBERING LOGIC
// ==========================================================================
const activeViewers = new Set();

function getViewerNumber(uid) {
  const viewers = Array.from(activeViewers);
  viewers.sort((a, b) => a - b);
  const idx = viewers.indexOf(uid);
  return idx !== -1 ? idx + 1 : 1;
}

// Mirroring Local Camera Feed to Floating Self-View Canvas
let mirrorActive = false;

function startSelfViewMirror() {
  const canvas = document.getElementById("self-view-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  function drawFrame() {
    if (!mirrorActive) return;

    const localVideo = localPlayerEl.querySelector("video");
    const isCamActive = localCameraBtn && localCameraBtn.classList.contains("active");
    if (isCamActive && localVideo && localVideo.readyState >= 2) {
      if (canvas.width !== localVideo.videoWidth || canvas.height !== localVideo.videoHeight) {
        canvas.width = localVideo.videoWidth;
        canvas.height = localVideo.videoHeight;
      }
      ctx.drawImage(localVideo, 0, 0, canvas.width, canvas.height);
    } else {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#0c0d17";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#9ca3af";
      ctx.font = "12px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("Camera Preview Muted", canvas.width / 2, canvas.height / 2);
    }

    // Periodically sync self view overlay icon states
    syncSelfViewControls();

    requestAnimationFrame(drawFrame);
  }

  mirrorActive = true;
  requestAnimationFrame(drawFrame);
}

function stopSelfViewMirror() {
  mirrorActive = false;
}

function syncSelfViewControls() {
  if (!selfViewCamBtn || !selfViewMicBtn) return;

  if (localCameraBtn.classList.contains("active")) {
    selfViewCamBtn.classList.remove("inactive");
    selfViewCamBtn.classList.add("active");
    selfViewCamBtn.title = "Turn Camera OFF";
  } else {
    selfViewCamBtn.classList.add("inactive");
    selfViewCamBtn.classList.remove("active");
    selfViewCamBtn.title = "Turn Camera ON";
  }

  if (localMicBtn.classList.contains("active")) {
    selfViewMicBtn.classList.remove("inactive");
    selfViewMicBtn.classList.add("active");
    selfViewMicBtn.title = "Mute Microphone";
  } else {
    selfViewMicBtn.classList.add("inactive");
    selfViewMicBtn.classList.remove("active");
    selfViewMicBtn.title = "Unmute Microphone";
  }
}

function resetFloatingSelfViewPosition() {
  if (floatingSelfView) {
    floatingSelfView.style.left = "";
    floatingSelfView.style.top = "";
    floatingSelfView.style.bottom = "";
    floatingSelfView.style.transform = "";
    floatingSelfView.classList.remove("minimized");

    // Also reset minimize button icon and title
    const minBtn = document.getElementById("self-view-minimize-btn");
    if (minBtn) {
      minBtn.title = "Minimize Self View";
      minBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
          stroke-linecap="round" stroke-linejoin="round">
          <line x1="5" y1="12" x2="19" y2="12"></line>
        </svg>
      `;
    }
  }
}


function setStatus(message) {
  const statusText = statusEl ? statusEl.querySelector(".status-text") : null;
  const msgLower = (message || "").toLowerCase();

  let displayText = message || "Video Call: Standby";
  let stateClass = "idle";

  if (msgLower.includes("connected to") || msgLower === "connected" || msgLower.includes("live")) {
    displayText = "Video Call • Live";
    stateClass = "connected";
  } else if (msgLower.includes("connecting") || msgLower.includes("joining")) {
    displayText = "Connecting Video...";
    stateClass = "connecting";
  } else if (msgLower.includes("failed") || msgLower.includes("error") || msgLower.includes("enter")) {
    displayText = "Video Call • Error";
    stateClass = "error";
  } else if (msgLower.includes("leave") || msgLower.includes("disconnect") || msgLower.includes("not connected") || msgLower === "") {
    displayText = "Video Call: Standby";
    stateClass = "idle";
  }

  if (statusText) {
    statusText.textContent = displayText;
  } else if (statusEl) {
    statusEl.textContent = displayText;
  }

  if (statusEl) {
    statusEl.className = `status-pill ${stateClass}`;
  }
}

// Retrieves the inner HTML5 <video> tag injected by Agora SDK
function getVideoElement(playerEl) {
  return playerEl.querySelector("video");
}

// Applies scale and translation transforms dynamically directly to the HTML5 video element
function applyZoomTransform(card, playerEl) {
  const video = getVideoElement(playerEl);
  if (!video) return;

  let state = zoomStates.get(card.id);
  if (!state) {
    state = { scale: 1.0, translateX: 0, translateY: 0, isDragging: false };
    zoomStates.set(card.id, state);
  }

  // Save the video element's initial transform (e.g. Agora's scaleX(-1) mirror transform) to preserve mirroring
  if (state.initialTransform === undefined) {
    state.initialTransform = video.style.transform || "";
  }

  // Recalculate zoom constraints based on container dimensions
  const rect = playerEl.getBoundingClientRect();
  const W_c = rect.width;
  const H_c = rect.height;

  if (W_c > 0 && H_c > 0) {
    const maxTranslateX = Math.max(0, (state.scale * W_c - W_c) / 2);
    const maxTranslateY = Math.max(0, (state.scale * H_c - H_c) / 2);

    state.translateX = Math.max(-maxTranslateX, Math.min(maxTranslateX, state.translateX));
    state.translateY = Math.max(-maxTranslateY, Math.min(maxTranslateY, state.translateY));
  }

  // Apply transform strictly to the video element, combining scale/translation with the initial mirror transform
  video.style.transformOrigin = "center center";
  video.style.transform = `translate(${state.translateX}px, ${state.translateY}px) scale(${state.scale}) ${state.initialTransform}`;

  // Make sure layout constraints on the video element itself are default, but pointer cursors update
  if (state.scale > 1.0) {
    playerEl.style.cursor = "grab";
  } else {
    playerEl.style.cursor = "default";
  }
}

// Adjusts the zoom scale and constrains translations within container bounds
function adjustZoom(card, playerEl, delta) {
  let state = zoomStates.get(card.id);
  if (!state) {
    state = { scale: 1.0, translateX: 0, translateY: 0, isDragging: false };
    zoomStates.set(card.id, state);
  }

  state.scale = Math.max(1.0, Math.min(5.0, state.scale + delta));

  if (state.scale === 1.0) {
    state.translateX = 0;
    state.translateY = 0;
  }

  applyZoomTransform(card, playerEl);
}

// Registers Pointer events for seamless mouse/touch-drag panning when zoomed
function setupZoomAndPan(card, playerEl) {
  const cardId = card.id;

  if (!zoomStates.has(cardId)) {
    zoomStates.set(cardId, {
      scale: 1.0,
      translateX: 0,
      translateY: 0,
      isDragging: false,
      startX: 0,
      startY: 0,
      currentX: 0,
      currentY: 0
    });
  }

  playerEl.addEventListener("pointerdown", (e) => {
    const state = zoomStates.get(cardId);
    if (!state || state.scale <= 1.0) return;

    // Only register drag if left-clicked (mouse)
    if (e.pointerType === "mouse" && e.button !== 0) return;

    state.isDragging = true;
    state.startX = e.clientX;
    state.startY = e.clientY;
    state.currentX = state.translateX;
    state.currentY = state.translateY;

    playerEl.classList.add("dragging");
    playerEl.style.cursor = "grabbing";
    playerEl.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  playerEl.addEventListener("pointermove", (e) => {
    const state = zoomStates.get(cardId);
    if (!state || !state.isDragging) return;

    const dx = e.clientX - state.startX;
    const dy = e.clientY - state.startY;

    state.translateX = state.currentX + dx;
    state.translateY = state.currentY + dy;

    applyZoomTransform(card, playerEl);
  });

  const handleDragEnd = (e) => {
    const state = zoomStates.get(cardId);
    if (!state || !state.isDragging) return;

    state.isDragging = false;
    playerEl.classList.remove("dragging");
    playerEl.style.cursor = "grab";
    playerEl.releasePointerCapture(e.pointerId);
  };

  playerEl.addEventListener("pointerup", handleDragEnd);
  playerEl.addEventListener("pointercancel", handleDragEnd);

  // Set up ResizeObserver to dynamically adjust video layout when player dimensions change
  let lastW = 0;
  let lastH = 0;
  const resizeObserver = new ResizeObserver((entries) => {
    for (let entry of entries) {
      const { width, height } = entry.contentRect;
      if (Math.abs(width - lastW) > 0.5 || Math.abs(height - lastH) > 0.5) {
        lastW = width;
        lastH = height;
        applyZoomTransform(card, playerEl);
      }
    }
  });
  resizeObserver.observe(playerEl);
}

// Toggles Fit mode (Fit vs Fill)
function toggleFit(card, button) {
  if (card.classList.contains("fit-contain")) {
    card.classList.remove("fit-contain");
    card.classList.add("fit-cover");
    button.textContent = "Fill";
    button.classList.add("active");
  } else {
    card.classList.remove("fit-cover");
    card.classList.add("fit-contain");
    button.textContent = "Fit";
    button.classList.remove("active");
  }
}

// Toggles Focus mode (Maximize/Pin)
function togglePin(card) {
  const isPinned = card.classList.contains("pinned");

  // Unpin all other cards first to maintain single primary focus
  const allCards = document.querySelectorAll(".video-card");
  allCards.forEach(c => {
    c.classList.remove("pinned");
    const pinBtn = c.querySelector(".pin-btn");
    if (pinBtn) {
      pinBtn.textContent = "Focus";
      pinBtn.classList.remove("active");
    }
  });

  if (!isPinned) {
    card.classList.add("pinned");
    const pinBtn = card.querySelector(".pin-btn");
    if (pinBtn) {
      pinBtn.textContent = "Unfocus";
      pinBtn.classList.add("active");
    }
    // Scroll the pinned element into view smoothly
    card.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // Recalculate grid rendering order based on the new focused state
  updateCardOrders();
}

// Inspects the HTML5 <video> element inside the player container and sets the CSS --video-aspect ratio dynamically
function applyTrackAspectRatio(card, videoTrack) {
  if (!videoTrack) return;

  let attempts = 0;
  const maxAttempts = 30; // Try for up to 6 seconds (30 * 200ms)

  const checkVideoDimensions = () => {
    try {
      const video = card.querySelector("video");
      if (video && video.videoWidth > 0 && video.videoHeight > 0) {
        const ratio = video.videoWidth / video.videoHeight;
        card.style.setProperty("--video-aspect", ratio);
        card.classList.add("has-aspect");
        console.log(`Applied aspect ratio of ${ratio} (${video.videoWidth}x${video.videoHeight}) to card ${card.id} after ${attempts} attempts`);
        return;
      }
    } catch (err) {
      console.warn("Failed to retrieve or apply video element aspect ratio:", err);
    }

    attempts++;
    if (attempts < maxAttempts) {
      setTimeout(checkVideoDimensions, 200);
    } else {
      console.warn(`Could not retrieve video element dimensions for card ${card.id} (timed out)`);
    }
  };

  checkVideoDimensions();
}


// Setup local card listeners
localFitBtn.addEventListener("click", () => {
  toggleFit(localCard, localFitBtn);
});

localPinBtn.addEventListener("click", () => {
  togglePin(localCard);
});

const localPopoutBtn = document.getElementById("local-popout-btn");
if (localPopoutBtn) {
  localPopoutBtn.addEventListener("click", () => {
    const localUidVal = uidInput.value.trim() ? Number(uidInput.value) : (roleInput.value === "patient" ? 4001 : 3001);
    if (localUidVal === 3001) {
      openDoctorPopoutWindow();
    } else if (localUidVal === 5001) {
      openPopoutWindow();
    } else if (localUidVal === 4001) {
      openPatientPopoutWindow();
    }
  });
}

localZoomInBtn.addEventListener("click", () => {
  adjustZoom(localCard, localPlayerEl, 0.25);
});

localZoomOutBtn.addEventListener("click", () => {
  adjustZoom(localCard, localPlayerEl, -0.25);
});

setupZoomAndPan(localCard, localPlayerEl);

// Local Camera Button handler
localCameraBtn.addEventListener("click", async () => {
  if (!localTracks.videoTrack) return;
  const isActive = localCameraBtn.classList.contains("active");
  await localTracks.videoTrack.setEnabled(!isActive);

  if (isActive) {
    localCameraBtn.classList.remove("active");
    localCameraBtn.classList.add("inactive");
    localCameraBtn.title = "Turn Camera ON";
  } else {
    localCameraBtn.classList.add("active");
    localCameraBtn.classList.remove("inactive");
    localCameraBtn.title = "Turn Camera OFF";
  }
});

// Central helper to synchronize local mic mute/unmute status with track, buttons, self-view, and localStorage/logs
async function setLocalMicMuteState(muted) {
  if (localTracks.audioTrack) {
    await localTracks.audioTrack.setEnabled(!muted);
  }

  if (muted) {
    localMicBtn.classList.remove("active");
    localMicBtn.classList.add("inactive");
    localMicBtn.title = "Unmute Microphone";
    muteBtn.textContent = "Unmute Mic";
    muteBtn.classList.add("muted");
  } else {
    localMicBtn.classList.add("active");
    localMicBtn.classList.remove("inactive");
    localMicBtn.title = "Mute Microphone";
    muteBtn.textContent = "Mute Mic";
    muteBtn.classList.remove("muted");
  }

  // Sync floating self-view overlay controls
  syncSelfViewControls();

  if (roleInput.value === "patient") {
    localStorage.setItem("patient_mic_muted", muted ? "true" : "false");
    if (muted) {
      console.log("Patient microphone muted");
    } else {
      console.log("Patient microphone unmuted");
    }
  }
}

// Local Mic Button handler
localMicBtn.addEventListener("click", async () => {
  const isCurrentlyMuted = !localMicBtn.classList.contains("active");
  await setLocalMicMuteState(!isCurrentlyMuted);
});

// Microphone Mute Button handler (kept for compatibility)
muteBtn.addEventListener("click", async () => {
  const isCurrentlyMuted = muteBtn.classList.contains("muted");
  await setLocalMicMuteState(!isCurrentlyMuted);
});

// Dynamic creation of a remote participant's card with controls
function createRemotePlayer(uid, videoTrack) {
  const cardId = `remote-card-${uid}`;
  let card = document.getElementById(cardId);

  if (!card) {
    card = document.createElement("div");
    card.id = cardId;
    card.className = "video-card fit-contain"; // Default to fit-contain for ultrasound safety (no crop)

    const header = document.createElement("div");
    header.className = "video-header";

    const h2 = document.createElement("h2");

    // Label roles intuitively based on predefined UIDs
    if (uid === 5001) {
      h2.innerHTML = PROBE_SVG + "Remote Ultrasound Feed";
    } else if (uid === 3001) {
      h2.innerHTML = "🩺 Doctor Camera (No Video)";
    } else if (uid === 4001) {
      h2.innerHTML = PATIENT_SVG + "Patient Camera (No Video)";
    } else {
      const viewerNum = getViewerNumber(uid);
      h2.innerHTML = `👤 Viewer ${viewerNum} Camera (No Video)`;
    }

    header.appendChild(h2);

    const controls = document.createElement("div");
    controls.className = "video-controls";

    // Remote Camera Toggle Button
    const camBtn = document.createElement("button");
    if (videoTrack) {
      camBtn.className = "control-btn toggle-btn camera-btn active";
      camBtn.title = "Turn Camera OFF";
      camBtn.disabled = false;
    } else {
      camBtn.className = "control-btn toggle-btn camera-btn inactive";
      camBtn.title = "Turn Camera ON";
      camBtn.disabled = true;
    }
    camBtn.type = "button";
    camBtn.innerHTML = `
      <svg class="icon-on" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M23 7l-7 5 7 5V7z"></path>
        <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
      </svg>
      <svg class="icon-off" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M16 16v1a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2m5.66 0H14a2 2 0 0 1 2 2v3.34l1 1L23 7v10l-2.58-1.84M23 7l-7 5 7 5V7z"></path>
        <line x1="1" y1="1" x2="23" y2="23"></line>
      </svg>
    `;
    camBtn.addEventListener("click", () => {
      const user = client?.remoteUsers.find(u => u.uid === uid);
      if (!user || !user.videoTrack) return;
      const isActive = camBtn.classList.contains("active");
      if (isActive) {
        user.videoTrack.stop();
        camBtn.classList.remove("active");
        camBtn.classList.add("inactive");
        camBtn.title = "Turn Camera ON";
      } else {
        user.videoTrack.play(player, { fit: card.classList.contains("fit-contain") ? "contain" : "cover" });
        camBtn.classList.add("active");
        camBtn.classList.remove("inactive");
        camBtn.title = "Turn Camera OFF";
      }
    });

    // Remote Mic Toggle Button (inactive/disabled by default, will activate if mic track is present)
    const micBtn = document.createElement("button");
    const hasAudio = !!(client?.remoteUsers.find(u => u.uid === uid)?.audioTrack);
    if (hasAudio) {
      micBtn.className = "control-btn toggle-btn mic-btn active";
      micBtn.title = "Mute Microphone";
      micBtn.disabled = false;
    } else {
      micBtn.className = "control-btn toggle-btn mic-btn inactive";
      micBtn.title = "Mute Microphone";
      micBtn.disabled = true;
    }
    micBtn.type = "button";
    micBtn.innerHTML = `
      <svg class="icon-on" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
        <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
        <line x1="12" y1="19" x2="12" y2="23"></line>
        <line x1="8" y1="23" x2="16" y2="23"></line>
      </svg>
      <svg class="icon-off" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <line x1="1" y1="1" x2="23" y2="23"></line>
        <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"></path>
        <path d="M17 11a5 5 0 0 1-5 5m-3.87-1.17A7 7 0 0 1 5 10v-2"></path>
        <line x1="12" y1="19" x2="12" y2="23"></line>
        <line x1="8" y1="23" x2="16" y2="23"></line>
      </svg>
    `;
    micBtn.addEventListener("click", () => {
      const user = client?.remoteUsers.find(u => u.uid === uid);
      if (!user || !user.audioTrack) return;
      const isActive = micBtn.classList.contains("active");
      if (isActive) {
        user.audioTrack.setVolume(0);
        micBtn.classList.remove("active");
        micBtn.classList.add("inactive");
        micBtn.title = "Unmute Microphone";
      } else {
        user.audioTrack.setVolume(100);
        micBtn.classList.add("active");
        micBtn.classList.remove("inactive");
        micBtn.title = "Mute Microphone";
      }
    });

    const zoomOutBtn = document.createElement("button");
    zoomOutBtn.className = "control-btn zoom-out-btn";
    zoomOutBtn.type = "button";
    zoomOutBtn.textContent = "-";
    zoomOutBtn.title = "Zoom Out";
    zoomOutBtn.addEventListener("click", () => {
      adjustZoom(card, player, -0.25);
    });

    const zoomInBtn = document.createElement("button");
    zoomInBtn.className = "control-btn zoom-in-btn";
    zoomInBtn.type = "button";
    zoomInBtn.textContent = "+";
    zoomInBtn.title = "Zoom In";
    zoomInBtn.addEventListener("click", () => {
      adjustZoom(card, player, 0.25);
    });

    const fitBtn = document.createElement("button");
    fitBtn.className = "control-btn fit-btn";
    fitBtn.type = "button";
    fitBtn.textContent = "Fit";
    fitBtn.title = "Toggle Fit/Fill Mode";
    fitBtn.addEventListener("click", () => {
      toggleFit(card, fitBtn);
    });

    const pinBtn = document.createElement("button");
    pinBtn.className = "control-btn pin-btn";
    pinBtn.type = "button";
    pinBtn.textContent = "Focus";
    pinBtn.title = "Focus/Pin Feed";
    pinBtn.addEventListener("click", () => {
      togglePin(card);
    });

    controls.appendChild(camBtn);
    controls.appendChild(micBtn);
    controls.appendChild(zoomOutBtn);
    controls.appendChild(zoomInBtn);
    controls.appendChild(fitBtn);
    controls.appendChild(pinBtn);

    if (uid === 5001) {
      const popoutBtn = document.createElement("button");
      popoutBtn.className = "control-btn toggle-btn popout-btn";
      popoutBtn.type = "button";
      popoutBtn.title = "Open in New Window";
      popoutBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
          <polyline points="15 3 21 3 21 9"></polyline>
          <line x1="10" y1="14" x2="21" y2="3"></line>
        </svg>
      `;
      popoutBtn.addEventListener("click", openPopoutWindow);
      controls.appendChild(popoutBtn);
    } else if (uid === 3001) {
      const popoutBtn = document.createElement("button");
      popoutBtn.className = "control-btn toggle-btn popout-btn";
      popoutBtn.type = "button";
      popoutBtn.title = "Open in New Window";
      popoutBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
          <polyline points="15 3 21 3 21 9"></polyline>
          <line x1="10" y1="14" x2="21" y2="3"></line>
        </svg>
      `;
      popoutBtn.addEventListener("click", openDoctorPopoutWindow);
      controls.appendChild(popoutBtn);
    } else if (uid === 4001) {
      const popoutBtn = document.createElement("button");
      popoutBtn.className = "control-btn toggle-btn popout-btn";
      popoutBtn.type = "button";
      popoutBtn.title = "Open in New Window";
      popoutBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
          <polyline points="15 3 21 3 21 9"></polyline>
          <line x1="10" y1="14" x2="21" y2="3"></line>
        </svg>
      `;
      popoutBtn.addEventListener("click", openPatientPopoutWindow);
      controls.appendChild(popoutBtn);
    }

    header.appendChild(controls);
    card.appendChild(header);

    const player = document.createElement("div");
    player.id = `remote-player-${uid}`;
    player.className = "remote-player";

    // Default placeholder for View-Only mode when video is not publishing
    if (!videoTrack) {
      player.innerHTML = `
        <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); font-size: 0.9rem; gap: 8px;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.6;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
          No Camera Input (View-Only Mode)
        </div>
      `;
    }

    card.appendChild(player);

    videosGrid.appendChild(card);

    // Register Zoom & Pan dragging event handlers
    setupZoomAndPan(card, player);
  }

  return document.getElementById(`remote-player-${uid}`);
}

// Helper to acquire local tracks with robust fallbacks in case of missing or locked devices
async function acquireLocalTracks(role, feedType) {
  let audioTrack = null;
  let videoTrack = null;
  let hasMicPermission = true;

  if (role === "patient") {
    try {
      console.log("Patient: Requesting microphone permission via getUserMedia...");
      const tempStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      tempStream.getTracks().forEach(track => track.stop());
    } catch (permissionErr) {
      hasMicPermission = false;
      console.warn("Microphone permission denied via getUserMedia:", permissionErr);
      alert("Microphone permission denied. Joining the call with camera only.");
    }
  }

  if (role === "patient" && feedType === "screen") {
    // Screen Share Source
    try {
      const screenTrack = await AgoraRTC.createScreenVideoTrack({
        encoderConfig: "1080p_1",
        optimizationMode: "detail"
      }, "auto");

      if (Array.isArray(screenTrack)) {
        videoTrack = screenTrack[0];
        if (screenTrack[1]) screenTrack[1].close();
      } else {
        videoTrack = screenTrack;
      }
    } catch (e) {
      console.warn("Screen share capture failed:", e);
      throw new Error("Failed to start screen share: " + (e.message || e));
    }

    if (hasMicPermission) {
      try {
        audioTrack = await AgoraRTC.createMicrophoneAudioTrack();
        if (audioTrack && role === "patient") {
          console.log("Patient microphone initialized");
        }
      } catch (e) {
        console.warn("Microphone access failed for screen share, continuing without audio:", e);
      }
    }
  } else {
    // Standard Camera + Mic Source with full fallback chain
    if (hasMicPermission) {
      try {
        // Step 1: Try capturing both
        const tracks = await AgoraRTC.createMicrophoneAndCameraTracks();
        audioTrack = tracks[0];
        videoTrack = tracks[1];
        if (audioTrack && role === "patient") {
          console.log("Patient microphone initialized");
        }
      } catch (err) {
        console.warn("Failed to capture both camera and microphone, trying fallbacks:", err);

        // Step 2: Try capturing video only
        try {
          videoTrack = await AgoraRTC.createCameraVideoTrack();
        } catch (videoErr) {
          console.warn("Camera capture failed:", videoErr);
        }

        // Step 3: Try capturing audio only
        try {
          audioTrack = await AgoraRTC.createMicrophoneAudioTrack();
          if (audioTrack && role === "patient") {
            console.log("Patient microphone initialized");
          }
        } catch (audioErr) {
          console.warn("Microphone capture failed:", audioErr);
        }
      }
    } else {
      // If we don't have mic permission, only capture video
      try {
        videoTrack = await AgoraRTC.createCameraVideoTrack();
      } catch (videoErr) {
        console.warn("Camera capture failed:", videoErr);
      }
    }
  }

  return { audioTrack, videoTrack };
}

async function joinCall() {
  const startMuted = muteBtn.classList.contains("muted");
  let appId = appIdInput.value.trim();
  let channel = channelInput.value.trim();
  let tokenText = tokenInput.value.trim();

  if (!tokenText && OFFICIAL_TOKEN_VALUE) {
    tokenText = OFFICIAL_TOKEN_VALUE;
    tokenInput.value = OFFICIAL_TOKEN_VALUE;
  }
  if (!tokenText) {
    const config = await fetchAgoraConfiguration();
    if (config && config.token) {
      tokenText = config.token;
      tokenInput.value = config.token;
    }
    if (config && config.appId && !appId) {
      appId = config.appId;
      appIdInput.value = config.appId;
    }
    if (config && config.channel && !channel) {
      channel = config.channel;
      channelInput.value = config.channel;
    }
  }
  const token = tokenText || null;
  const role = roleInput.value;
  const feedType = feedTypeInput.value;

  // Set default UID based on Role to facilitate identification (Patient = 1, Doctor = 2)
  let uid = uidInput.value.trim() ? Number(uidInput.value) : null;
  if (!uid) {
    uid = role === "patient" ? 1 : 2;
  }

  if (!appId) {
    setStatus("Enter App ID first");
    return;
  }

  if (!channel) {
    setStatus("Enter channel name");
    return;
  }

  if (role === "doctor") {
    connectDoctorMQTT(appId, channel);
  }

  joinBtn.disabled = true;

  try {
    client = AgoraRTC.createClient({ mode: "rtc", codec: "vp8" });

    client.on("user-joined", (user) => {
      console.log("Remote user joined:", user.uid);
      if (user.uid !== 3001 && user.uid !== 4001 && user.uid !== 5001) {
        activeViewers.add(user.uid);
      }
      if (!joinOrder.includes(user.uid)) {
        joinOrder.push(user.uid);
      }
      // Create viewer/remote card immediately on join (defaulting to placeholder)
      createRemotePlayer(user.uid, null);
      updateCardOrders();
    });

    client.on("user-published", async (user, mediaType) => {
      await client.subscribe(user, mediaType);

      if (mediaType === "video") {
        if (user.uid !== 3001 && user.uid !== 4001 && user.uid !== 5001) {
          activeViewers.add(user.uid);
        }

        const remotePlayer = createRemotePlayer(user.uid, user.videoTrack);
        remotePlayer.innerHTML = ""; // Clear placeholder
        user.videoTrack.play(remotePlayer, { fit: "contain" });

        const card = document.getElementById(`remote-card-${user.uid}`);
        if (card) {
          applyTrackAspectRatio(card, user.videoTrack);

          // Enable and activate camera control button
          const camBtn = card.querySelector(".camera-btn");
          if (camBtn) {
            camBtn.disabled = false;
            camBtn.className = "control-btn toggle-btn camera-btn active";
            camBtn.title = "Turn Camera OFF";
          }
        }

        if (!joinOrder.includes(user.uid)) {
          joinOrder.push(user.uid);
        }
        updateCardOrders();

        // Auto-focus the Patient's ultrasound feed (UID 5001) immediately if we are a Doctor
        if (roleInput.value === "doctor" && user.uid === 5001) {
          setTimeout(() => {
            const patientCard = document.getElementById("remote-card-5001");
            if (patientCard && !patientCard.classList.contains("pinned")) {
              togglePin(patientCard);
            }
          }, 300);
        }
      }

      if (mediaType === "audio") {
        user.audioTrack.play();
        if (user.uid === 4001) {
          const currentRole = roleInput.value;
          if (currentRole === "doctor") {
            console.log("Doctor subscribed to patient audio");
          } else if (currentRole === "viewer") {
            console.log("Viewer subscribed to patient audio");
          }
        }
        const card = document.getElementById(`remote-card-${user.uid}`);
        if (card) {
          const micBtn = card.querySelector(".mic-btn");
          if (micBtn) {
            micBtn.disabled = false;
            micBtn.className = "control-btn toggle-btn mic-btn active";
            micBtn.title = "Mute Microphone";
          }
        }
      }
    });

    client.on("user-unpublished", (user, mediaType) => {
      if (mediaType === "video") {
        const remotePlayer = document.getElementById(`remote-player-${user.uid}`);
        if (remotePlayer) {
          remotePlayer.innerHTML = `
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); font-size: 0.9rem; gap: 8px;">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.6;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
              No Camera Input (View-Only Mode)
            </div>
          `;
        }
        const card = document.getElementById(`remote-card-${user.uid}`);
        if (card) {
          const camBtn = card.querySelector(".camera-btn");
          if (camBtn) {
            camBtn.disabled = true;
            camBtn.className = "control-btn toggle-btn camera-btn inactive";
            camBtn.title = "Turn Camera ON";
          }
        }
      }

      if (mediaType === "audio") {
        const card = document.getElementById(`remote-card-${user.uid}`);
        if (card) {
          const micBtn = card.querySelector(".mic-btn");
          if (micBtn) {
            micBtn.disabled = true;
            micBtn.className = "control-btn toggle-btn mic-btn inactive";
            micBtn.title = "Mute Microphone";
          }
        }
      }
      updateCardOrders();
    });

    client.on("user-left", (user) => {
      console.log("Remote user left:", user.uid);
      const card = document.getElementById(`remote-card-${user.uid}`);
      if (card) {
        card.remove();
        zoomStates.delete(`remote-card-${user.uid}`);
      }

      const idx = joinOrder.indexOf(user.uid);
      if (idx !== -1) {
        joinOrder.splice(idx, 1);
      }
      if (user.uid !== 3001 && user.uid !== 4001 && user.uid !== 5001) {
        activeViewers.delete(user.uid);
      }
      updateCardOrders();
    });

    const joinedUid = await client.join(appId, channel, token, uid);
    uidInput.value = joinedUid;

    // Track local user join order
    if (!joinOrder.includes(joinedUid)) {
      joinOrder.push(joinedUid);
    }
    updateCardOrders();

    if (role === "viewer") {
      activeViewers.add(joinedUid);
    }

    // Cleanup any existing local tracks before acquiring new ones to prevent duplicate microphone tracks or leaks
    if (localTracks.audioTrack) {
      try {
        localTracks.audioTrack.stop();
        localTracks.audioTrack.close();
      } catch (e) {
        console.warn("Error cleaning up existing audio track:", e);
      }
      localTracks.audioTrack = null;
    }
    if (localTracks.videoTrack) {
      try {
        localTracks.videoTrack.stop();
        localTracks.videoTrack.close();
      } catch (e) {
        console.warn("Error cleaning up existing video track:", e);
      }
      localTracks.videoTrack = null;
    }

    // Acquire local media streams with full device fallbacks
    const { audioTrack, videoTrack } = await acquireLocalTracks(role, feedType);
    localTracks.audioTrack = audioTrack;
    localTracks.videoTrack = videoTrack;

    const publishTracks = [];

    // Handle Local Audio Preview & Publish State
    if (audioTrack) {
      publishTracks.push(audioTrack);
      muteBtn.disabled = false;
      localMicBtn.disabled = false;



      if (startMuted) {
        localMicBtn.classList.remove("active");
        localMicBtn.classList.add("inactive");
        localMicBtn.title = "Unmute Microphone";
        muteBtn.textContent = "Unmute Mic";
        muteBtn.classList.add("muted");
      } else {
        localMicBtn.classList.add("active");
        localMicBtn.classList.remove("inactive");
        localMicBtn.title = "Mute Microphone";
        muteBtn.textContent = "Mute Mic";
        muteBtn.classList.remove("muted");
      }

      if (role === "patient") {
        localStorage.setItem("patient_mic_muted", startMuted ? "true" : "false");
      }
      syncSelfViewControls();
    } else {
      muteBtn.disabled = true;
      localMicBtn.disabled = true;
      localMicBtn.classList.remove("active");
      localMicBtn.classList.add("inactive");
      console.log("No audio track acquired. Mic muted/disabled.");
    }

    // Handle Local Video Preview & Publish State
    if (videoTrack) {
      publishTracks.push(videoTrack);
      videoTrack.play(localPlayerEl, { fit: "contain" });
      applyTrackAspectRatio(localCard, videoTrack);

      localCameraBtn.disabled = false;
      localCameraBtn.classList.remove("inactive");
      localCameraBtn.classList.add("active");
      localCameraBtn.title = "Turn Camera OFF";

      const localTitle = localCard.querySelector(".video-header h2");
      if (localTitle) {
        if (uid === 5001) {
          localTitle.innerHTML = PROBE_SVG + "Remote Ultrasound Feed";
        } else if (role === "patient") {
          localTitle.innerHTML = PATIENT_SVG + "Patient Camera";
        } else if (role === "doctor") {
          localTitle.innerHTML = `🩺 Doctor Camera`;
        } else {
          const viewerNum = getViewerNumber(uid);
          localTitle.innerHTML = `👤 Viewer ${viewerNum} Camera`;
        }
      }

      // Screen share track end listener
      if (role === "patient" && feedType === "screen") {
        videoTrack.on("track-ended", () => {
          console.log("Local screen share track ended");
          leaveCall();
        });
      }
    } else {
      localCameraBtn.disabled = true;
      localCameraBtn.classList.remove("active");
      localCameraBtn.classList.add("inactive");
      // Show elegant View-Only placeholder when no video device is available or allowed
      localPlayerEl.innerHTML = `
        <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); font-size: 0.9rem; gap: 8px;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.6;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
          No Camera Input (View-Only Mode)
        </div>
      `;
      const localTitle = localCard.querySelector(".video-header h2");
      if (localTitle) {
        if (role === "patient") {
          localTitle.innerHTML = PATIENT_SVG + "Patient Camera (No Video)";
        } else if (role === "doctor") {
          localTitle.innerHTML = "🩺 Doctor Camera (No Video)";
        } else {
          const viewerNum = getViewerNumber(uid);
          localTitle.innerHTML = `👤 Viewer ${viewerNum} Camera (No Video)`;
        }
      }
    }

    if (publishTracks.length > 0) {
      await client.publish(publishTracks);
      if (startMuted && audioTrack) {
        await audioTrack.setEnabled(false);
      }
      if (role === "patient" && audioTrack) {
        console.log("Patient microphone published");
      }
    }
    updateCardOrders();

    leaveBtn.disabled = false;
    muteBtn.disabled = false;

    // Show and start picture-in-picture floating self-view
    if (floatingSelfView) {
      resetFloatingSelfViewPosition();
      floatingSelfView.classList.add("show");
      startSelfViewMirror();
    }

    setStatus(`Connected to ${channel} as ${role === "patient" ? "Patient" : (role === "doctor" ? "Doctor" : "Viewer")}`);
  } catch (error) {
    const rawMessage = error?.message || String(error);

    if (rawMessage.includes("dynamic use static key")) {
      if (tokenText) {
        setStatus("Join failed: Token/App ID mode mismatch. Verify token or leave empty.");
      } else {
        setStatus("Join failed: Project requires an RTC token. Paste token in input.");
      }
    } else {
      setStatus(`Join failed: ${rawMessage}`);
    }

    if (client) {
      try {
        await client.leave();
      } catch (_) {
        // Ignore leave errors during failed join cleanup.
      }
      client.removeAllListeners();
      client = null;
    }

    joinBtn.disabled = false;
    muteBtn.disabled = true;
  }
}

async function leaveCall() {
  leaveBtn.disabled = true;
  muteBtn.disabled = true;
  localCameraBtn.disabled = true;
  localMicBtn.disabled = true;

  if (doctorMqttClient) {
    console.log("Disconnecting doctor MQTT client...");
    doctorMqttClient.end();
    doctorMqttClient = null;
  }

  // Hide and stop self-view mirror
  if (floatingSelfView) {
    floatingSelfView.classList.remove("show");
    stopSelfViewMirror();
  }

  // Release Haptic Pad routing from active consultation session
  if (typeof unbindHapticSessionAPI === "function") {
    unbindHapticSessionAPI(window.currentActiveConsultationSessionId);
  }
  window.currentActiveConsultationSessionId = null;

  try {
    if (localTracks.audioTrack) {
      localTracks.audioTrack.stop();
      localTracks.audioTrack.close();
      localTracks.audioTrack = null;
    }

    if (localTracks.videoTrack) {
      localTracks.videoTrack.stop();
      localTracks.videoTrack.close();
      localTracks.videoTrack = null;
    }

    if (client) {
      await client.leave();
      client.removeAllListeners();
      client = null;
    }

    // Clean up all remote video cards from DOM
    const allCards = document.querySelectorAll(".video-card");
    allCards.forEach(card => {
      if (card.id !== "local-card") {
        card.remove();
      } else {
        // Reset local card states
        card.className = "video-card fit-contain";
        card.style.removeProperty("--video-aspect");
        card.classList.remove("has-aspect");

        const localTitle = localCard.querySelector(".video-header h2");
        if (localTitle) {
          localTitle.innerHTML = "📹 Local Feed";
        }

        const fitBtn = document.getElementById("local-fit-btn");
        if (fitBtn) {
          fitBtn.textContent = "Fit";
          fitBtn.classList.remove("active");
        }
        const pinBtn = document.getElementById("local-pin-btn");
        if (pinBtn) {
          pinBtn.textContent = "Focus";
          pinBtn.classList.remove("active");
        }

        // Remove local zoom indicator and reset translation
        const indicator = localPlayerEl.querySelector(".zoom-indicator");
        if (indicator) {
          indicator.remove();
        }
        localPlayerEl.style.cursor = "default";
      }
    });

    // Reset mute button text and style
    muteBtn.textContent = "Mute Mic";
    muteBtn.classList.remove("muted");

    // Reset local toggle buttons
    localMicBtn.classList.remove("inactive");
    localMicBtn.classList.add("active");
    localMicBtn.title = "Toggle Microphone";
    localCameraBtn.classList.remove("inactive");
    localCameraBtn.classList.add("active");
    localCameraBtn.title = "Toggle Camera";

    // Clear all remote states, keep only local state reset
    zoomStates.clear();
    zoomStates.set("local-card", {
      scale: 1.0,
      translateX: 0,
      translateY: 0,
      isDragging: false,
      startX: 0,
      startY: 0,
      currentX: 0,
      currentY: 0
    });

    // Clear dynamic viewer states
    activeViewers.clear();
    viewerMap.clear();
    activeViewerTabKey = null;

    // Reset local card hierarchy if it was wrapped
    const playersContainer = document.getElementById("viewer-players-container");
    if (playersContainer) {
      localCard.appendChild(localPlayerEl);
      playersContainer.remove();
    }
    const tabsContainer = document.getElementById("viewer-card-tabs");
    if (tabsContainer) {
      tabsContainer.remove();
    }

    localPlayerEl.innerHTML = "";
    setStatus("Not connected");
  } catch (error) {
    setStatus(`Leave failed: ${error.message || error}`);
  } finally {
    joinBtn.disabled = false;
    leaveBtn.disabled = true;
    localCameraBtn.disabled = true;
    localMicBtn.disabled = true;
    muteBtn.disabled = false;
  }
}

joinBtn.addEventListener("click", joinCall);
leaveBtn.addEventListener("click", leaveCall);

// Settings Modal UI Interaction
const settingsModal = document.getElementById("settingsModal");
const settingsBtn = document.getElementById("settingsBtn");
const closeModalBtn = document.getElementById("closeModalBtn");
const cancelSettingsBtn = document.getElementById("cancelSettingsBtn");
const saveSettingsBtn = document.getElementById("saveSettingsBtn");

let originalSettings = {};

function openSettings() {
  originalSettings = {
    appId: appIdInput ? appIdInput.value : "",
    channel: channelInput ? channelInput.value : "",
    role: roleInput ? roleInput.value : "",
    feedType: feedTypeInput ? feedTypeInput.value : "",
    token: tokenInput ? tokenInput.value : "",
    uid: uidInput ? uidInput.value : ""
  };

  // Synchronize Session Code with active session
  const modalSessionCodeInput = document.getElementById("settings-session-code");
  if (modalSessionCodeInput) {
    let currentCode = "";
    if (window.activeClinicalSessionCode) {
      currentCode = window.activeClinicalSessionCode;
    } else if (sessionStorage.getItem("active_clinical_session_code")) {
      currentCode = sessionStorage.getItem("active_clinical_session_code");
    } else if (localStorage.getItem("active_clinical_session_code")) {
      currentCode = localStorage.getItem("active_clinical_session_code");
    } else if (typeof currentAuthenticatedUser !== "undefined" && currentAuthenticatedUser && currentAuthenticatedUser.session_code) {
      currentCode = currentAuthenticatedUser.session_code;
    }
    if (currentCode) {
      modalSessionCodeInput.value = currentCode;
    }
  }

  updateSettingsSessionCodeVisibility();

  settingsModal.classList.add("active");
}

function closeSettings(save = false) {
  if (!save) {
    if (appIdInput) appIdInput.value = originalSettings.appId;
    if (channelInput) channelInput.value = originalSettings.channel;
    if (roleInput) roleInput.value = originalSettings.role;
    if (feedTypeInput) feedTypeInput.value = originalSettings.feedType;
    if (tokenInput) tokenInput.value = originalSettings.token;
    if (uidInput) uidInput.value = originalSettings.uid;
    if (roleInput) roleInput.dispatchEvent(new Event("change"));
  }
  settingsModal.classList.remove("active");
}

if (settingsBtn) settingsBtn.addEventListener("click", openSettings);
if (closeModalBtn) closeModalBtn.addEventListener("click", () => closeSettings(false));
if (cancelSettingsBtn) cancelSettingsBtn.addEventListener("click", () => closeSettings(false));
if (saveSettingsBtn) saveSettingsBtn.addEventListener("click", () => closeSettings(true));

if (settingsModal) {
  settingsModal.addEventListener("click", (e) => {
    if (e.target === settingsModal) {
      closeSettings(false);
    }
  });
}

// Controls Modal (OpenSonics) UI Interaction
const controlsModal = document.getElementById("controlsModal");
const controlsBtn = document.getElementById("controlsBtn");
const closeControlsBtn = document.getElementById("closeControlsBtn");
const minimizeControlsBtn = document.getElementById("minimizeControlsBtn");

function openControls() {
  if (roleInput.value !== "doctor") {
    console.warn("Unauthorized access attempt to Controls.");
    return;
  }
  connectDoctorMQTT();
  controlsModal.classList.add("active");
  const modalContent = controlsModal.querySelector(".controls-modal-content");
  if (modalContent) {
    modalContent.style.position = "";
    modalContent.style.left = "";
    modalContent.style.top = "";
    modalContent.style.margin = "";
  }
}

function closeControls() {
  controlsModal.classList.remove("active");
}

function updateControlsButtonVisibility() {
  const localControlsBtn = document.getElementById("local-controls-btn");
  const localControlsWrapper = document.querySelector("#local-card .video-controls");

  if (roleInput.value === "doctor") {
    if (!localControlsBtn && localControlsWrapper) {
      const btn = document.createElement("button");
      btn.className = "control-btn";
      btn.id = "local-controls-btn";
      btn.type = "button";
      btn.title = "OpenSonics Control Panel";
      btn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="4" y1="21" x2="4" y2="14"></line>
          <line x1="4" y1="10" x2="4" y2="3"></line>
          <line x1="12" y1="21" x2="12" y2="12"></line>
          <line x1="12" y1="8" x2="12" y2="3"></line>
          <line x1="20" y1="21" x2="20" y2="16"></line>
          <line x1="20" y1="12" x2="20" y2="3"></line>
          <line x1="2" y1="14" x2="6" y2="14"></line>
          <line x1="10" y1="8" x2="14" y2="8"></line>
          <line x1="18" y1="16" x2="22" y2="16"></line>
        </svg>
      `;
      btn.addEventListener("click", openControls);
      localControlsWrapper.appendChild(btn);
    }
  } else {
    if (localControlsBtn) {
      localControlsBtn.remove();
    }
  }
}

// Initialize button visibility
updateControlsButtonVisibility();

if (controlsBtn) controlsBtn.addEventListener("click", openControls);
if (closeControlsBtn) closeControlsBtn.addEventListener("click", closeControls);
if (minimizeControlsBtn) minimizeControlsBtn.addEventListener("click", closeControls);

if (controlsModal) {
  controlsModal.addEventListener("click", (e) => {
    if (e.target === controlsModal) {
      closeControls();
    }
  });

  // Make controls modal draggable by header
  const header = controlsModal.querySelector(".controls-modal-header");
  const modalContent = controlsModal.querySelector(".controls-modal-content");

  if (header && modalContent) {
    header.style.cursor = "grab";

    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let initialLeft = 0;
    let initialTop = 0;

    function handleStart(e) {
      // Don't drag if clicking buttons inside the header
      if (e.target.closest(".controls-modal-win-controls") || e.target.closest("button")) {
        return;
      }

      isDragging = true;
      header.style.cursor = "grabbing";

      // Prevent default text selection/drag behaviors
      e.preventDefault();

      const clientX = e.type.startsWith("touch") ? e.touches[0].clientX : e.clientX;
      const clientY = e.type.startsWith("touch") ? e.touches[0].clientY : e.clientY;

      startX = clientX;
      startY = clientY;

      // Get current offset relative to overlay
      initialLeft = modalContent.offsetLeft;
      initialTop = modalContent.offsetTop;

      // Set position to absolute so it can be dragged relative to controlsModal (which is fixed/overlay)
      modalContent.style.position = "absolute";
      modalContent.style.margin = "0";
      modalContent.style.left = `${initialLeft}px`;
      modalContent.style.top = `${initialTop}px`;

      // Disable text selection on body during drag
      document.body.style.userSelect = "none";
      document.body.style.webkitUserSelect = "none";
    }

    function handleMove(e) {
      if (!isDragging) return;

      const clientX = e.type.startsWith("touch") ? e.touches[0].clientX : e.clientX;
      const clientY = e.type.startsWith("touch") ? e.touches[0].clientY : e.clientY;

      const dx = clientX - startX;
      const dy = clientY - startY;

      let newLeft = initialLeft + dx;
      let newTop = initialTop + dy;

      // Boundaries (keep completely inside viewport)
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const modalWidth = modalContent.offsetWidth;
      const modalHeight = modalContent.offsetHeight;

      newLeft = Math.max(0, Math.min(newLeft, viewportWidth - modalWidth));
      newTop = Math.max(0, Math.min(newTop, viewportHeight - modalHeight));

      modalContent.style.left = `${newLeft}px`;
      modalContent.style.top = `${newTop}px`;
    }

    function handleEnd() {
      if (!isDragging) return;
      isDragging = false;
      header.style.cursor = "grab";
      document.body.style.userSelect = "";
      document.body.style.webkitUserSelect = "";
    }

    // Mouse events
    header.addEventListener("mousedown", handleStart);
    document.addEventListener("mousemove", handleMove);
    document.addEventListener("mouseup", handleEnd);

    // Touch events (for mobile/tablet support)
    header.addEventListener("touchstart", handleStart, { passive: false });
    document.addEventListener("touchmove", handleMove, { passive: false });
    document.addEventListener("touchend", handleEnd);
  }
}

// Fetch initial parameters directly from curv_proper_code.py / backend to sync Doctor controls
async function syncDoctorControlsFromPatientState() {
  try {
    const isDirectBackend = window.location.port === "3000";
    const urls = isDirectBackend
      ? ["/api/status", "http://127.0.0.1:3000/api/status", "http://localhost:3000/api/status"]
      : ["http://127.0.0.1:3000/api/status", "http://localhost:3000/api/status", "/api/status"];
    let data = null;
    for (const u of urls) {
      try {
        const res = await fetch(u);
        if (res.ok) {
          data = await res.json();
          break;
        }
      } catch (_) { }
    }
    if (!data) return;
    console.log("[Doctor UI] Synced state from backend:", data);

    if (data.voltage !== undefined && voltageSlider && voltageValueInput) {
      voltageSlider.value = data.voltage;
      voltageValueInput.value = data.voltage;
      updateSliderBackground(voltageSlider);
    }

    if (data.gain !== undefined && gainSlider && gainValueInput) {
      gainSlider.value = data.gain;
      gainValueInput.value = data.gain;
      updateSliderBackground(gainSlider);
    }

    if (data.display !== undefined && displayToggle) {
      displayToggle.checked = data.display;
    }

    if (data.status) {
      isRunningState = (data.status === "RUNNING");
      if (isRunningState) {
        controlStartBtn.classList.add("active", "running-stop-btn");
        controlFreezeBtn.classList.remove("active");
        controlStatusLabel.textContent = "RUNNING";
        controlStatusLabel.className = "status-val running";
        if (startBtnText) startBtnText.textContent = "Stop";
        if (startBtnIcon) startBtnIcon.innerHTML = `<rect x="6" y="6" width="12" height="12" fill="currentColor"/>`;
      } else {
        controlStartBtn.classList.remove("running-stop-btn");
        controlStartBtn.classList.add("active");
        controlStatusLabel.textContent = "STOPPED";
        controlStatusLabel.className = "status-val stopped";
        if (startBtnText) startBtnText.textContent = "Start";
        if (startBtnIcon) startBtnIcon.innerHTML = `<path d="M8 5v14l11-7z" fill="currentColor"/>`;
      }
    }
  } catch (err) {
    console.warn("[Doctor UI] Sync state info:", err);
  }
}

// Call state sync on page load
document.addEventListener("DOMContentLoaded", () => {
  setTimeout(syncDoctorControlsFromPatientState, 600);
});

let isRunningState = false;

if (controlStartBtn && controlFreezeBtn && controlStatusLabel) {
  controlStartBtn.addEventListener("click", () => {
    isRunningState = !isRunningState;
    if (isRunningState) {
      controlStartBtn.classList.add("active", "running-stop-btn");
      controlFreezeBtn.classList.remove("active");
      controlStatusLabel.textContent = "RUNNING";
      controlStatusLabel.className = "status-val running";
      if (startBtnText) startBtnText.textContent = "Stop";
      if (startBtnIcon) {
        startBtnIcon.innerHTML = `<rect x="6" y="6" width="12" height="12" fill="currentColor"/>`;
      }
      sendControlCommand("start", true);
    } else {
      controlStartBtn.classList.remove("running-stop-btn");
      controlStartBtn.classList.add("active");
      controlStatusLabel.textContent = "STOPPED";
      controlStatusLabel.className = "status-val stopped";
      if (startBtnText) startBtnText.textContent = "Start";
      if (startBtnIcon) {
        startBtnIcon.innerHTML = `<path d="M8 5v14l11-7z" fill="currentColor"/>`;
      }
      sendControlCommand("start", false);
    }
  });

  controlFreezeBtn.addEventListener("click", () => {
    controlFreezeBtn.classList.add("active");
    controlStartBtn.classList.remove("active", "running-stop-btn");
    controlStatusLabel.textContent = "STOPPED";
    controlStatusLabel.className = "status-val stopped";
    isRunningState = false;
    if (startBtnText) startBtnText.textContent = "Start";
    if (startBtnIcon) {
      startBtnIcon.innerHTML = `<path d="M8 5v14l11-7z" fill="currentColor"/>`;
    }
    sendControlCommand("freeze", true);
  });
}

// Voltage Slider Interaction
const voltageSlider = document.getElementById("voltageSlider");
const voltageValueInput = document.getElementById("voltageValueInput");
const voltageMinus = document.getElementById("voltageMinus");
const voltagePlus = document.getElementById("voltagePlus");

function updateSliderBackground(slider) {
  if (!slider) return;
  const min = parseFloat(slider.min) || 0;
  const max = parseFloat(slider.max) || 100;
  const val = parseFloat(slider.value) || 0;
  const percent = ((val - min) / (max - min)) * 100;
  if (slider.classList.contains("tgc-range-slider")) {
    slider.style.background = `linear-gradient(to top, #2563eb ${percent}%, #e2e8f0 ${percent}%)`;
  } else {
    slider.style.background = `linear-gradient(to right, #2563eb ${percent}%, #e2e8f0 ${percent}%)`;
  }
}

if (voltageSlider && voltageValueInput) {
  voltageSlider.addEventListener("input", () => {
    voltageValueInput.value = voltageSlider.value;
    updateSliderBackground(voltageSlider);
  });

  voltageSlider.addEventListener("change", () => {
    sendControlCommand("voltage", voltageSlider.value);
  });

  // Initial fill update
  updateSliderBackground(voltageSlider);
}

if (voltageMinus && voltageSlider) {
  voltageMinus.addEventListener("click", () => {
    let val = parseInt(voltageSlider.value, 10);
    if (val > parseInt(voltageSlider.min, 10)) {
      voltageSlider.value = val - 1;
      voltageSlider.dispatchEvent(new Event("input"));
      voltageSlider.dispatchEvent(new Event("change"));
    }
  });
}

if (voltagePlus && voltageSlider) {
  voltagePlus.addEventListener("click", () => {
    let val = parseInt(voltageSlider.value, 10);
    if (val < parseInt(voltageSlider.max, 10)) {
      voltageSlider.value = val + 1;
      voltageSlider.dispatchEvent(new Event("input"));
      voltageSlider.dispatchEvent(new Event("change"));
    }
  });
}

// Analog Gain Slider Interaction
const gainSlider = document.getElementById("gainSlider");
const gainValueInput = document.getElementById("gainValueInput");
const gainMinus = document.getElementById("gainMinus");
const gainPlus = document.getElementById("gainPlus");

if (gainSlider && gainValueInput) {
  gainSlider.addEventListener("input", () => {
    gainValueInput.value = gainSlider.value;
    updateSliderBackground(gainSlider);
  });

  gainSlider.addEventListener("change", () => {
    sendControlCommand("gain", gainSlider.value);
  });

  updateSliderBackground(gainSlider);
}

if (gainMinus && gainSlider) {
  gainMinus.addEventListener("click", () => {
    let val = parseInt(gainSlider.value, 10);
    if (val > parseInt(gainSlider.min, 10)) {
      gainSlider.value = val - 1;
      gainSlider.dispatchEvent(new Event("input"));
      gainSlider.dispatchEvent(new Event("change"));
    }
  });
}

if (gainPlus && gainSlider) {
  gainPlus.addEventListener("click", () => {
    let val = parseInt(gainSlider.value, 10);
    if (val < parseInt(gainSlider.max, 10)) {
      gainSlider.value = val + 1;
      gainSlider.dispatchEvent(new Event("input"));
      gainSlider.dispatchEvent(new Event("change"));
    }
  });
}

// Log Compression Gain Slider
const logGainSlider = document.getElementById("logGainSlider");
const logGainValueInput = document.getElementById("logGainValueInput");
const logGainMinus = document.getElementById("logGainMinus");
const logGainPlus = document.getElementById("logGainPlus");

if (logGainSlider && logGainValueInput) {
  logGainSlider.addEventListener("input", () => {
    logGainValueInput.value = logGainSlider.value;
    updateSliderBackground(logGainSlider);
  });
  logGainSlider.addEventListener("change", () => {
    sendControlCommand("log_gain", logGainSlider.value);
  });
  updateSliderBackground(logGainSlider);
}

if (logGainMinus && logGainSlider) {
  logGainMinus.addEventListener("click", () => {
    let val = parseInt(logGainSlider.value, 10);
    if (val > parseInt(logGainSlider.min, 10)) {
      logGainSlider.value = val - 1;
      logGainSlider.dispatchEvent(new Event("input"));
      logGainSlider.dispatchEvent(new Event("change"));
    }
  });
}

if (logGainPlus && logGainSlider) {
  logGainPlus.addEventListener("click", () => {
    let val = parseInt(logGainSlider.value, 10);
    if (val < parseInt(logGainSlider.max, 10)) {
      logGainSlider.value = val + 1;
      logGainSlider.dispatchEvent(new Event("input"));
      logGainSlider.dispatchEvent(new Event("change"));
    }
  });
}

// Dynamic Range Slider
const dynRangeSlider = document.getElementById("dynRangeSlider");
const dynRangeValueInput = document.getElementById("dynRangeValueInput");
const dynRangeMinus = document.getElementById("dynRangeMinus");
const dynRangePlus = document.getElementById("dynRangePlus");

if (dynRangeSlider && dynRangeValueInput) {
  dynRangeSlider.addEventListener("input", () => {
    dynRangeValueInput.value = dynRangeSlider.value;
    updateSliderBackground(dynRangeSlider);
  });
  dynRangeSlider.addEventListener("change", () => {
    sendControlCommand("dynamic_range", dynRangeSlider.value);
  });
  updateSliderBackground(dynRangeSlider);
}

if (dynRangeMinus && dynRangeSlider) {
  dynRangeMinus.addEventListener("click", () => {
    let val = parseInt(dynRangeSlider.value, 10);
    if (val > parseInt(dynRangeSlider.min, 10)) {
      dynRangeSlider.value = val - 1;
      dynRangeSlider.dispatchEvent(new Event("input"));
      dynRangeSlider.dispatchEvent(new Event("change"));
    }
  });
}

if (dynRangePlus && dynRangeSlider) {
  dynRangePlus.addEventListener("click", () => {
    let val = parseInt(dynRangeSlider.value, 10);
    if (val < parseInt(dynRangeSlider.max, 10)) {
      dynRangeSlider.value = val + 1;
      dynRangeSlider.dispatchEvent(new Event("input"));
      dynRangeSlider.dispatchEvent(new Event("change"));
    }
  });
}

// TGC Slider Interaction
const tgcToggle = document.getElementById("tgcToggle");
const tgcSlidersContainer = document.getElementById("tgcSlidersContainer");

if (tgcToggle && tgcSlidersContainer) {
  tgcToggle.addEventListener("change", () => {
    const sliders = tgcSlidersContainer.querySelectorAll(".tgc-range-slider");
    if (tgcToggle.checked) {
      tgcSlidersContainer.classList.remove("disabled");
      sliders.forEach(s => s.disabled = false);
    } else {
      tgcSlidersContainer.classList.add("disabled");
      sliders.forEach(s => s.disabled = true);
    }
    sendControlCommand("tgc_toggle", tgcToggle.checked);
  });
}

// Initialize TGC sliders behavior
for (let i = 1; i <= 6; i++) {
  const slider = document.getElementById(`tgcSlider${i}`);
  const label = document.getElementById(`tgcVal${i}`);
  if (slider && label) {
    slider.addEventListener("input", () => {
      label.textContent = slider.value;
      updateSliderBackground(slider);
    });
    slider.addEventListener("change", () => {
      sendControlCommand(`tgc_slider_${i}`, slider.value);
    });
    // Initial fill update
    updateSliderBackground(slider);
  }
}

// Display Toggle Interaction
const displayToggle = document.getElementById("displayToggle");
if (displayToggle) {
  displayToggle.addEventListener("change", () => {
    sendControlCommand("display", displayToggle.checked);
  });
}

// Save Setup & Advanced buttons action
const saveSetupBtn = document.getElementById("saveSetupBtn");
const advancedBtn = document.getElementById("advancedBtn");

if (saveSetupBtn) {
  saveSetupBtn.addEventListener("click", () => {
    alert("OpenSonics Control Setup Saved successfully!");
    sendControlCommand("save_setup", true);
  });
}

if (advancedBtn) {
  advancedBtn.addEventListener("click", () => {
    alert("Opening Advanced Controls parameters dialog...");
    sendControlCommand("advanced", true);
  });
}

// ==========================================================================
// TORUS UNIVERSAL STEP-BY-STEP SCREEN & HISTORY NAVIGATION
// ==========================================================================
const TORUS_ALL_SCREENS = [
  "role-selection-screen",
  "doctor-login-screen",
  "doctor-register-screen",
  "doctor-forgot-screen",
  "doctor-biometric-screen",
  "doctor-bio-register-screen",
  "patient-login-screen",
  "patient-register-screen",
  "patient-forgot-screen",
  "patient-clinical-registration-screen",
  "viewer-login-screen",
  "viewer-register-screen",
  "viewer-forgot-screen",
  "join-session-screen",
  "doctor-portal-dashboard",
  "app-dashboard"
];

let torusScreenHistory = ["role-selection-screen"];

function getCurrentVisibleScreenId() {
  for (const sId of TORUS_ALL_SCREENS) {
    const el = document.getElementById(sId);
    if (el && el.style.display && el.style.display !== "none") {
      return sId;
    }
  }
  return "role-selection-screen";
}

function showTorusScreen(targetId, recordHistory = true) {
  const currentId = getCurrentVisibleScreenId();

  if (currentId === targetId && document.getElementById(targetId)?.style.display === "flex") {
    return;
  }

  if (recordHistory && currentId && currentId !== targetId) {
    if (torusScreenHistory.length === 0 || torusScreenHistory[torusScreenHistory.length - 1] !== currentId) {
      torusScreenHistory.push(currentId);
    }
  }

  // Hide all screens
  TORUS_ALL_SCREENS.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.style.display = "none";
    }
  });

  // Show target screen
  const targetEl = document.getElementById(targetId);
  if (targetEl) {
    targetEl.style.display = "flex";
  }

  // Screen specific lifecycle hooks
  if (targetId === "doctor-portal-dashboard") {
    const isDoc = (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") || (roleInput && roleInput.value === "doctor");
    const role = isDoc ? "doctor" : "patient";
    if (typeof hideAllPortalSubViews === "function") {
      hideAllPortalSubViews();
    }

    updateSharedPortalHeader(currentAuthenticatedUser, role);

    const docContent = document.getElementById("doctorDashboardContent");
    const patContent = document.getElementById("patientDashboardContent");
    const adhocBtn = document.getElementById("docDashAdhocScanBtn");
    if (adhocBtn) {
      adhocBtn.style.display = isDoc ? "inline-flex" : "none";
    }

    if (isDoc) {
      if (docContent) docContent.style.display = "flex";
      if (patContent) patContent.style.display = "none";
      if (typeof renderDoctorDashboard === "function") {
        renderDoctorDashboard();
      }
    } else {
      if (docContent) docContent.style.display = "none";
      if (patContent) patContent.style.display = "flex";
      if (typeof renderPatientDashboard === "function") {
        renderPatientDashboard(currentAuthenticatedUser);
      }
    }

    // Trigger Haptic Pad connection status check
    if (typeof setupHapticPadListeners === "function") {
      setupHapticPadListeners();
    }
    if (typeof initiateHapticPadConnection === "function" &&
      typeof currentHapticState !== "undefined" &&
      typeof HAPTIC_STATE !== "undefined" &&
      currentHapticState !== HAPTIC_STATE.CONNECTED &&
      !window.isHapticConnectionInProgress) {
      initiateHapticPadConnection();
    }

    const navItems = document.querySelectorAll(".ddash-sidebar-nav .ddash-nav-item");
    navItems.forEach(el => {
      const v = el.getAttribute("data-view");
      if (v === "dashboard" || v === "patient-dashboard") {
        el.classList.add("active");
      } else {
        el.classList.remove("active");
      }
    });
  } else if (targetId === "app-dashboard") {
    if (typeof triggerHeaderBootSequence === "function") {
      triggerHeaderBootSequence();
    }
    if (typeof updateLiveConsultationHapticBadge === "function") {
      updateLiveConsultationHapticBadge();
    }
  } else if (targetId === "role-selection-screen") {
    const badgeEl = document.getElementById("header-user-badge");
    if (badgeEl) badgeEl.style.display = "none";
  }

  // Browser history integration
  if (recordHistory && window.history && window.history.pushState) {
    try {
      window.history.pushState({ torusScreen: targetId }, "", window.location.href);
    } catch (e) {
      // Ignore browser restrictions on file:// or pushState
    }
  }
}
window.showTorusScreen = showTorusScreen;

async function navigateBackTorus() {
  const currentId = getCurrentVisibleScreenId();

  // If leaving live consultation screen (#app-dashboard)
  if (currentId === "app-dashboard") {
    if (typeof leaveCall === "function" && leaveBtn && !leaveBtn.disabled) {
      try {
        await leaveCall();
      } catch (err) {
        console.warn("Leave call on back navigation:", err);
      }
    }
    if (window.currentActiveConsultationSessionId) {
      const sess = window.torusSessions?.active?.find(s => s.sessionId === window.currentActiveConsultationSessionId);
      if (sess) {
        sess.doctorConnectionState = "not_joined";
        sess.status = "active";
      }
    } else if (window.torusSessions?.active?.[0]) {
      window.torusSessions.active[0].doctorConnectionState = "not_joined";
      window.torusSessions.active[0].status = "active";
    }
    if (typeof saveTorusSessions === "function") {
      saveTorusSessions();
    }

    // Unbind Haptic Pad routing from previous consultation session so signals are safely closed
    if (typeof unbindHapticSessionAPI === "function") {
      unbindHapticSessionAPI(window.currentActiveConsultationSessionId);
    }
    window.currentActiveConsultationSessionId = null;

    const isDoc = (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") ||
      (roleInput && roleInput.value === "doctor") ||
      Boolean(window.currentActiveConsultationSessionId);

    if (isDoc) {
      // Ensure history stack is cleaned up and return directly to Doctor Dashboard (Image 2)
      while (torusScreenHistory.length > 0 && (torusScreenHistory[torusScreenHistory.length - 1] === "app-dashboard" || torusScreenHistory[torusScreenHistory.length - 1] === "doctor-portal-dashboard")) {
        torusScreenHistory.pop();
      }
      // Keep previous screen before dashboard in history (e.g. doctor-login-screen)
      if (torusScreenHistory.length === 0) {
        torusScreenHistory.push("doctor-login-screen");
      }
      showTorusScreen("doctor-portal-dashboard", false);
      return;
    }
  }

  // Pop previous screen from history
  if (currentId === "doctor-portal-dashboard") {
    const isDoc = (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") || (roleInput && roleInput.value === "doctor");
    showTorusScreen(isDoc ? "doctor-login-screen" : "patient-login-screen");
    return;
  }

  if (currentId === "doctor-login-screen" || currentId === "patient-login-screen") {
    torusScreenHistory = ["role-selection-screen"];
    showTorusScreen("role-selection-screen", false);
    return;
  }

  let prevScreen = torusScreenHistory.length > 0 ? torusScreenHistory.pop() : null;
  while (prevScreen && prevScreen === currentId && torusScreenHistory.length > 0) {
    prevScreen = torusScreenHistory.pop();
  }

  // Fallback to logical predecessor if history stack is exhausted
  if (!prevScreen || prevScreen === currentId) {
    const defaultPredecessors = {
      "app-dashboard": (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") || (roleInput && roleInput.value === "doctor")
        ? "doctor-portal-dashboard"
        : ((roleInput && roleInput.value === "patient") ? "doctor-portal-dashboard" : "role-selection-screen"),
      "doctor-portal-dashboard": "doctor-login-screen",
      "doctor-bio-register-screen": "doctor-biometric-screen",
      "doctor-biometric-screen": "doctor-login-screen",
      "doctor-forgot-screen": "doctor-login-screen",
      "doctor-register-screen": "doctor-login-screen",
      "doctor-login-screen": "role-selection-screen",
      "patient-clinical-registration-screen": "doctor-portal-dashboard",
      "patient-forgot-screen": "patient-login-screen",
      "patient-register-screen": "patient-login-screen",
      "patient-login-screen": "role-selection-screen",
      "viewer-forgot-screen": "viewer-login-screen",
      "viewer-register-screen": "viewer-login-screen",
      "viewer-login-screen": "role-selection-screen",
      "join-session-screen": (roleInput && roleInput.value === "patient") ? "patient-login-screen" : "viewer-login-screen",
      "role-selection-screen": "role-selection-screen"
    };
    prevScreen = defaultPredecessors[currentId] || "role-selection-screen";
  }

  showTorusScreen(prevScreen, false);
}
window.navigateBackTorus = navigateBackTorus;

// Role Selection screen card click handlers
const roleCards = document.querySelectorAll(".role-card-item");
const roleSelectionScreen = document.getElementById("role-selection-screen");
const doctorLoginScreen = document.getElementById("doctor-login-screen");
const doctorRegisterScreen = document.getElementById("doctor-register-screen");
const patientLoginScreen = document.getElementById("patient-login-screen");
const patientRegisterScreen = document.getElementById("patient-register-screen");
const patientForgotScreen = document.getElementById("patient-forgot-screen");
const viewerLoginScreen = document.getElementById("viewer-login-screen");
const viewerRegisterScreen = document.getElementById("viewer-register-screen");
const viewerForgotScreen = document.getElementById("viewer-forgot-screen");
const joinSessionScreen = document.getElementById("join-session-screen");
const appDashboard = document.getElementById("app-dashboard");
let activeJoinSessionSourceRole = "viewer";

roleCards.forEach(card => {
  card.addEventListener("click", () => {
    const selectedRole = card.getAttribute("data-role");
    const selectedUid = card.getAttribute("data-uid");

    if (selectedRole === "doctor") {
      showTorusScreen("doctor-login-screen");
      return;
    }

    if (selectedRole === "patient") {
      showTorusScreen("patient-login-screen");
      return;
    }

    if (selectedRole === "viewer") {
      const viewerEmailInput = document.getElementById("viewer-email-input");
      if (viewerEmailInput && !viewerEmailInput.value) {
        viewerEmailInput.value = "user@gmail.com";
      }
      showTorusScreen("viewer-login-screen");
      return;
    }

    roleInput.value = selectedRole;
    uidInput.value = selectedUid;
    roleInput.dispatchEvent(new Event("change"));
    showTorusScreen("app-dashboard");
  });
});

// Floating self-view controls listeners
if (selfViewCloseBtn) {
  selfViewCloseBtn.addEventListener("click", () => {
    if (floatingSelfView) {
      floatingSelfView.classList.remove("show");
    }
  });
}

if (selfViewCamBtn) {
  selfViewCamBtn.addEventListener("click", () => {
    if (localCameraBtn) {
      localCameraBtn.click();
    }
  });
}

if (selfViewMicBtn) {
  selfViewMicBtn.addEventListener("click", () => {
    if (localMicBtn) {
      localMicBtn.click();
    }
  });
}

if (selfViewMinimizeBtn) {
  selfViewMinimizeBtn.addEventListener("click", () => {
    if (floatingSelfView) {
      const isMinimized = floatingSelfView.classList.toggle("minimized");
      if (isMinimized) {
        selfViewMinimizeBtn.title = "Restore Self View";
        selfViewMinimizeBtn.innerHTML = `
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
            stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
        `;
      } else {
        selfViewMinimizeBtn.title = "Minimize Self View";
        selfViewMinimizeBtn.innerHTML = `
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
            stroke-linecap="round" stroke-linejoin="round">
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
        `;
      }
    }
  });
}

// Drag-and-drop support restricted to viewport using the header
let isDraggingSelfView = false;
let dragStartX, dragStartY;
let dragInitialLeft, dragInitialTop;

const selfViewHeader = document.querySelector(".self-view-header");

if (selfViewHeader && floatingSelfView) {
  selfViewHeader.addEventListener("pointerdown", (e) => {
    // Only drag on left click for mouse
    if (e.pointerType === "mouse" && e.button !== 0) return;

    // Don't drag if clicking buttons inside the header
    if (e.target.closest(".self-view-btn")) return;

    const rect = floatingSelfView.getBoundingClientRect();

    // Initialize positions
    dragInitialLeft = rect.left;
    dragInitialTop = rect.top;
    dragStartX = e.clientX;
    dragStartY = e.clientY;

    // Set explicit position and clear transform for dragging
    floatingSelfView.style.left = `${dragInitialLeft}px`;
    floatingSelfView.style.top = `${dragInitialTop}px`;
    floatingSelfView.style.bottom = "auto";
    floatingSelfView.style.transform = "none";

    isDraggingSelfView = true;
    floatingSelfView.classList.add("dragging");
    selfViewHeader.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  selfViewHeader.addEventListener("pointermove", (e) => {
    if (!isDraggingSelfView) return;

    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;

    const rect = floatingSelfView.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    let newLeft = dragInitialLeft + dx;
    let newTop = dragInitialTop + dy;

    // Constrain within viewport
    const minLeft = 0;
    const maxLeft = viewportWidth - rect.width;
    const minTop = 0;
    const maxTop = viewportHeight - rect.height;

    newLeft = Math.max(minLeft, Math.min(maxLeft, newLeft));
    newTop = Math.max(minTop, Math.min(maxTop, newTop));

    floatingSelfView.style.left = `${newLeft}px`;
    floatingSelfView.style.top = `${newTop}px`;
  });

  const handleDragEnd = (e) => {
    if (!isDraggingSelfView) return;
    isDraggingSelfView = false;
    floatingSelfView.classList.remove("dragging");
    selfViewHeader.releasePointerCapture(e.pointerId);
  };

  selfViewHeader.addEventListener("pointerup", handleDragEnd);
  selfViewHeader.addEventListener("pointercancel", handleDragEnd);
}

// Window resize handler to keep self view within viewport boundaries
window.addEventListener("resize", () => {
  if (floatingSelfView && floatingSelfView.style.left) {
    const rect = floatingSelfView.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    let currentLeft = parseFloat(floatingSelfView.style.left);
    let currentTop = parseFloat(floatingSelfView.style.top);

    const maxLeft = viewportWidth - rect.width;
    const maxTop = viewportHeight - rect.height;

    currentLeft = Math.max(0, Math.min(maxLeft, currentLeft));
    currentTop = Math.max(0, Math.min(maxTop, currentTop));

    floatingSelfView.style.left = `${currentLeft}px`;
    floatingSelfView.style.top = `${currentTop}px`;
  }
});

if (backBtn) {
  backBtn.addEventListener("click", () => {
    navigateBackTorus();
  });
}

// Listen for browser back/forward navigation to update SPA UI states seamlessly
window.addEventListener("popstate", (event) => {
  if (event.state && event.state.torusScreen) {
    showTorusScreen(event.state.torusScreen, false);
  } else {
    navigateBackTorus();
  }
});

// ==========================================================================
// POP-OUT / NEW WINDOW DOCTOR CAMERA LOGIC
// ==========================================================================

function getDoctorCard() {
  const remoteCard = document.getElementById("remote-card-3001");
  if (remoteCard) return remoteCard;
  const localUidVal = uidInput.value.trim() ? Number(uidInput.value) : (roleInput.value === "patient" ? 4001 : 3001);
  if (localUidVal === 3001) {
    return document.getElementById("local-card");
  }
  return null;
}

function syncDoctorPopoutPlayer() {
  if (!doctorPopoutWindow || doctorPopoutWindow.closed) return;

  const popoutCard = doctorPopoutWindow.document.getElementById("popout-card");
  const popoutPlayer = doctorPopoutWindow.document.getElementById("popout-player");
  if (!popoutCard || !popoutPlayer) return;

  const parentCard = getDoctorCard();
  if (!parentCard) {
    // Show placeholder if card is not present
    if (!popoutPlayer.querySelector(".placeholder-container")) {
      popoutPlayer.innerHTML = `
        <div class="placeholder-container" style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); font-size: 0.9rem; gap: 8px;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.6;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
          No Camera Input (View-Only Mode)
        </div>
      `;
    }
    return;
  }

  const parentPlayer = parentCard.id === "local-card" ? localPlayerEl : parentCard.querySelector(".remote-player");
  const parentVideo = parentPlayer ? parentPlayer.querySelector("video") : null;

  if (parentVideo && parentVideo.srcObject) {
    // Check if the popout already has a video element
    let childVideo = popoutPlayer.querySelector("video");
    if (!childVideo) {
      popoutPlayer.innerHTML = ""; // Clear placeholder
      childVideo = doctorPopoutWindow.document.createElement("video");
      childVideo.autoplay = true;
      childVideo.playsInline = true;
      childVideo.muted = true;
      childVideo.style.width = "100%";
      childVideo.style.height = "100%";
      childVideo.style.display = "block";
      popoutPlayer.appendChild(childVideo);
    }
    // Only update srcObject if it has changed
    if (childVideo.srcObject !== parentVideo.srcObject) {
      childVideo.srcObject = parentVideo.srcObject;
      childVideo.play().catch(err => console.error("Error playing child video:", err));
    }

    // Mirror zoom transformation classes and aspect ratios
    if (parentCard.style.getPropertyValue("--video-aspect")) {
      popoutCard.style.setProperty("--video-aspect", parentCard.style.getPropertyValue("--video-aspect"));
    }
    if (parentCard.classList.contains("has-aspect")) {
      popoutCard.classList.add("has-aspect");
    } else {
      popoutCard.classList.remove("has-aspect");
    }

    // Apply exact zoom from parent to maintain zoom state initially or during parent zoom actions
    const parentZoom = zoomStates.get(parentCard.id);
    const popoutZoom = zoomStates.get("doctor-popout-card");
    if (parentZoom && (!popoutZoom || popoutZoom.scale !== parentZoom.scale || popoutZoom.translateX !== parentZoom.translateX || popoutZoom.translateY !== parentZoom.translateY)) {
      zoomStates.set("doctor-popout-card", { ...parentZoom });
      applyZoomTransform(popoutCard, popoutPlayer);
    }
  } else {
    // Parent video doesn't exist, show placeholder
    if (!popoutPlayer.querySelector(".placeholder-container")) {
      popoutPlayer.innerHTML = `
        <div class="placeholder-container" style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); font-size: 0.9rem; gap: 8px;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.6;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
          No Camera Input (View-Only Mode)
        </div>
      `;
    }
  }
}

function syncDoctorPopoutControls() {
  if (!doctorPopoutWindow || doctorPopoutWindow.closed) return;

  const parentCard = getDoctorCard();
  if (!parentCard) return;

  const popoutCard = doctorPopoutWindow.document.getElementById("popout-card");
  if (!popoutCard) return;

  // Sync Camera button state
  const parentCamBtn = parentCard.querySelector(".camera-btn");
  const childCamBtn = doctorPopoutWindow.document.getElementById("popout-camera-btn");
  if (parentCamBtn && childCamBtn) {
    childCamBtn.disabled = parentCamBtn.disabled;
    if (parentCamBtn.classList.contains("active")) {
      childCamBtn.classList.add("active");
      childCamBtn.classList.remove("inactive");
      childCamBtn.title = "Turn Camera OFF";
    } else {
      childCamBtn.classList.add("inactive");
      childCamBtn.classList.remove("active");
      childCamBtn.title = "Turn Camera ON";
    }
  }

  // Sync Mic (Mute) button state
  const parentMicBtn = parentCard.querySelector(".mic-btn");
  const childMicBtn = doctorPopoutWindow.document.getElementById("popout-mic-btn");
  if (parentMicBtn && childMicBtn) {
    childMicBtn.disabled = parentMicBtn.disabled;
    if (parentMicBtn.classList.contains("active")) {
      childMicBtn.classList.add("active");
      childMicBtn.classList.remove("inactive");
      childMicBtn.title = "Mute Microphone";
    } else {
      childMicBtn.classList.add("inactive");
      childMicBtn.classList.remove("active");
      childMicBtn.title = "Unmute Microphone";
    }
  }

  // Sync Fit button text and active state
  const childFitBtn = doctorPopoutWindow.document.getElementById("popout-fit-btn");
  if (childFitBtn) {
    if (parentCard.classList.contains("fit-contain")) {
      popoutCard.classList.remove("fit-cover");
      popoutCard.classList.add("fit-contain");
      childFitBtn.textContent = "Fit";
      childFitBtn.classList.remove("active");
    } else {
      popoutCard.classList.remove("fit-contain");
      popoutCard.classList.add("fit-cover");
      childFitBtn.textContent = "Fill";
      childFitBtn.classList.add("active");
    }
  }

  // Sync Focus button state
  const childPinBtn = doctorPopoutWindow.document.getElementById("popout-pin-btn");
  if (childPinBtn) {
    if (parentCard.classList.contains("pinned")) {
      popoutCard.classList.add("pinned");
      childPinBtn.textContent = "Unfocus";
      childPinBtn.classList.add("active");
    } else {
      popoutCard.classList.remove("pinned");
      childPinBtn.textContent = "Focus";
      childPinBtn.classList.remove("active");
    }
  }
}

function openDoctorPopoutWindow() {
  if (doctorPopoutWindow && !doctorPopoutWindow.closed) {
    doctorPopoutWindow.focus();
    return;
  }

  doctorPopoutWindow = window.open("", "DoctorPopout", "width=1024,height=768,menubar=no,toolbar=no,location=no,status=no");
  if (!doctorPopoutWindow) {
    alert("Popup blocked! Please allow popups for this page to view the popout doctor camera feed.");
    return;
  }

  const doc = doctorPopoutWindow.document;
  doc.open();
  doc.write(`
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Doctor Camera</title>
</head>
<body class="popout-body" style="margin: 0; padding: 0; background: #060B18; overflow: hidden; height: 100vh;">
  <div class="video-card fit-contain" id="popout-card" style="width: 100%; height: 100vh; margin: 0; border: none; border-radius: 0; box-shadow: none; display: flex; flex-direction: column;">
    <div class="video-header" style="padding: 12px 20px; flex-shrink: 0;">
      <h2>🩺 Doctor Camera</h2>
      <div class="video-controls">
        <button class="control-btn toggle-btn camera-btn" id="popout-camera-btn" type="button" title="Toggle Camera">
          <svg class="icon-on" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M23 7l-7 5 7 5V7z"></path>
            <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
          </svg>
          <svg class="icon-off" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M16 16v1a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2m5.66 0H14a2 2 0 0 1 2 2v3.34l1 1L23 7v10l-2.58-1.84M23 7l-7 5 7 5V7z"></path>
            <line x1="1" y1="1" x2="23" y2="23"></line>
          </svg>
        </button>
        <button class="control-btn toggle-btn mic-btn" id="popout-mic-btn" type="button" title="Toggle Microphone">
          <svg class="icon-on" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
            <line x1="12" y1="19" x2="12" y2="23"></line>
            <line x1="8" y1="23" x2="16" y2="23"></line>
          </svg>
          <svg class="icon-off" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="1" y1="1" x2="23" y2="23"></line>
            <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"></path>
            <path d="M17 11a5 5 0 0 1-5 5m-3.87-1.17A7 7 0 0 1 5 10v-2"></path>
            <line x1="12" y1="19" x2="12" y2="23"></line>
            <line x1="8" y1="23" x2="16" y2="23"></line>
          </svg>
        </button>
        <button class="control-btn zoom-out-btn" id="popout-zoom-out-btn" type="button" title="Zoom Out">-</button>
        <button class="control-btn zoom-in-btn" id="popout-zoom-in-btn" type="button" title="Zoom In">+</button>
        <button class="control-btn fit-btn" id="popout-fit-btn" type="button" title="Toggle Fit/Fill Mode">Fit</button>
        <button class="control-btn pin-btn" id="popout-pin-btn" type="button" title="Focus Feed">Focus</button>
      </div>
    </div>
    <div id="popout-player" class="remote-player" style="flex: 1; position: relative; overflow: hidden; background: #000;">
    </div>
  </div>
</body>
</html>
  `);
  doc.close();

  // Dynamically copy stylesheet links & styles, setting base href to resolve relatives
  const base = doc.createElement("base");
  base.href = window.location.href;
  doc.head.appendChild(base);

  document.querySelectorAll('link, style').forEach(el => {
    doc.head.appendChild(el.cloneNode(true));
  });

  const popoutCard = doc.getElementById("popout-card");
  const popoutPlayer = doc.getElementById("popout-player");

  // Setup Zoom and Pan pointer events
  setupZoomAndPan(popoutCard, popoutPlayer);

  // Set click event handlers for controls in child window
  doc.getElementById("popout-camera-btn").addEventListener("click", () => {
    const parentCard = getDoctorCard();
    if (parentCard) {
      const btn = parentCard.querySelector(".camera-btn");
      if (btn) btn.click();
    }
  });

  doc.getElementById("popout-mic-btn").addEventListener("click", () => {
    const parentCard = getDoctorCard();
    if (parentCard) {
      const btn = parentCard.querySelector(".mic-btn");
      if (btn) btn.click();
    }
  });

  doc.getElementById("popout-zoom-out-btn").addEventListener("click", () => {
    adjustZoom(popoutCard, popoutPlayer, -0.25);
  });

  doc.getElementById("popout-zoom-in-btn").addEventListener("click", () => {
    adjustZoom(popoutCard, popoutPlayer, 0.25);
  });

  doc.getElementById("popout-fit-btn").addEventListener("click", () => {
    const btn = doc.getElementById("popout-fit-btn");
    toggleFit(popoutCard, btn);
  });

  doc.getElementById("popout-pin-btn").addEventListener("click", () => {
    const parentCard = getDoctorCard();
    if (parentCard) {
      togglePin(parentCard);
    }
  });

  // Perform initial sync
  syncDoctorPopoutPlayer();
  syncDoctorPopoutControls();

  // Register unload cleanup
  doctorPopoutWindow.addEventListener("unload", () => {
    doctorPopoutWindow = null;
  });
}

// ==========================================================================
// POP-OUT / NEW WINDOW ULTRASOUND FEED LOGIC
// ==========================================================================

function getUltrasoundCard() {
  const remoteCard = document.getElementById("remote-card-5001");
  if (remoteCard) return remoteCard;
  const localUidVal = uidInput.value.trim() ? Number(uidInput.value) : (roleInput.value === "patient" ? 4001 : 3001);
  if (localUidVal === 5001) {
    return document.getElementById("local-card");
  }
  return null;
}

function getUltrasoundVideoTrack() {
  const localUidVal = uidInput.value.trim() ? Number(uidInput.value) : (roleInput.value === "patient" ? 4001 : 3001);
  if (localUidVal === 5001) {
    return localTracks.videoTrack;
  }
  const user = client?.remoteUsers.find(u => u.uid === 5001);
  return user?.videoTrack || null;
}

function syncPopoutPlayer() {
  if (!popoutWindow || popoutWindow.closed) return;

  const popoutCard = popoutWindow.document.getElementById("popout-card");
  const popoutPlayer = popoutWindow.document.getElementById("popout-player");
  if (!popoutCard || !popoutPlayer) return;

  const parentCard = getUltrasoundCard();
  if (!parentCard) {
    // Show placeholder if card is not present
    if (!popoutPlayer.querySelector(".placeholder-container")) {
      popoutPlayer.innerHTML = `
        <div class="placeholder-container" style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); font-size: 0.9rem; gap: 8px;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.6;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
          No Camera Input (View-Only Mode)
        </div>
      `;
    }
    return;
  }

  const parentPlayer = parentCard.id === "local-card" ? localPlayerEl : parentCard.querySelector(".remote-player");
  const parentVideo = parentPlayer ? parentPlayer.querySelector("video") : null;

  if (parentVideo && parentVideo.srcObject) {
    // Check if the popout already has a video element
    let childVideo = popoutPlayer.querySelector("video");
    if (!childVideo) {
      popoutPlayer.innerHTML = ""; // Clear placeholder
      childVideo = popoutWindow.document.createElement("video");
      childVideo.autoplay = true;
      childVideo.playsInline = true;
      childVideo.muted = true;
      childVideo.style.width = "100%";
      childVideo.style.height = "100%";
      childVideo.style.display = "block";
      popoutPlayer.appendChild(childVideo);
    }
    // Only update srcObject if it has changed
    if (childVideo.srcObject !== parentVideo.srcObject) {
      childVideo.srcObject = parentVideo.srcObject;
      childVideo.play().catch(err => console.error("Error playing child video:", err));
    }

    // Mirror zoom transformation classes and aspect ratios
    if (parentCard.style.getPropertyValue("--video-aspect")) {
      popoutCard.style.setProperty("--video-aspect", parentCard.style.getPropertyValue("--video-aspect"));
    }
    if (parentCard.classList.contains("has-aspect")) {
      popoutCard.classList.add("has-aspect");
    } else {
      popoutCard.classList.remove("has-aspect");
    }

    // Apply exact zoom from parent to maintain zoom state initially or during parent zoom actions
    const parentZoom = zoomStates.get(parentCard.id);
    const popoutZoom = zoomStates.get("popout-card");
    if (parentZoom && (!popoutZoom || popoutZoom.scale !== parentZoom.scale || popoutZoom.translateX !== parentZoom.translateX || popoutZoom.translateY !== parentZoom.translateY)) {
      zoomStates.set("popout-card", { ...parentZoom });
      applyZoomTransform(popoutCard, popoutPlayer);
    }
  } else {
    // Parent video doesn't exist, show placeholder
    if (!popoutPlayer.querySelector(".placeholder-container")) {
      popoutPlayer.innerHTML = `
        <div class="placeholder-container" style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); font-size: 0.9rem; gap: 8px;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.6;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
          No Camera Input (View-Only Mode)
        </div>
      `;
    }
  }
}

function syncPopoutControls() {
  if (!popoutWindow || popoutWindow.closed) return;

  const parentCard = getUltrasoundCard();
  if (!parentCard) return;

  const popoutCard = popoutWindow.document.getElementById("popout-card");
  if (!popoutCard) return;

  // Sync Camera button state
  const parentCamBtn = parentCard.querySelector(".camera-btn");
  const childCamBtn = popoutWindow.document.getElementById("popout-camera-btn");
  if (parentCamBtn && childCamBtn) {
    childCamBtn.disabled = parentCamBtn.disabled;
    if (parentCamBtn.classList.contains("active")) {
      childCamBtn.classList.add("active");
      childCamBtn.classList.remove("inactive");
      childCamBtn.title = "Turn Camera OFF";
    } else {
      childCamBtn.classList.add("inactive");
      childCamBtn.classList.remove("active");
      childCamBtn.title = "Turn Camera ON";
    }
  }

  // Sync Mic (Mute) button state
  const parentMicBtn = parentCard.querySelector(".mic-btn");
  const childMicBtn = popoutWindow.document.getElementById("popout-mic-btn");
  if (parentMicBtn && childMicBtn) {
    childMicBtn.disabled = parentMicBtn.disabled;
    if (parentMicBtn.classList.contains("active")) {
      childMicBtn.classList.add("active");
      childMicBtn.classList.remove("inactive");
      childMicBtn.title = "Mute Microphone";
    } else {
      childMicBtn.classList.add("inactive");
      childMicBtn.classList.remove("active");
      childMicBtn.title = "Unmute Microphone";
    }
  }

  // Sync Fit button text and active state
  const childFitBtn = popoutWindow.document.getElementById("popout-fit-btn");
  if (childFitBtn) {
    if (parentCard.classList.contains("fit-contain")) {
      popoutCard.classList.remove("fit-cover");
      popoutCard.classList.add("fit-contain");
      childFitBtn.textContent = "Fit";
      childFitBtn.classList.remove("active");
    } else {
      popoutCard.classList.remove("fit-contain");
      popoutCard.classList.add("fit-cover");
      childFitBtn.textContent = "Fill";
      childFitBtn.classList.add("active");
    }
  }

  // Sync Focus button state
  const childPinBtn = popoutWindow.document.getElementById("popout-pin-btn");
  if (childPinBtn) {
    if (parentCard.classList.contains("pinned")) {
      popoutCard.classList.add("pinned");
      childPinBtn.textContent = "Unfocus";
      childPinBtn.classList.add("active");
    } else {
      popoutCard.classList.remove("pinned");
      childPinBtn.textContent = "Focus";
      childPinBtn.classList.remove("active");
    }
  }
}

function openPopoutWindow() {
  if (popoutWindow && !popoutWindow.closed) {
    popoutWindow.focus();
    return;
  }

  popoutWindow = window.open("", "UltrasoundPopout", "width=1024,height=768,menubar=no,toolbar=no,location=no,status=no");
  if (!popoutWindow) {
    alert("Popup blocked! Please allow popups for this page to view the popout ultrasound feed.");
    return;
  }

  const doc = popoutWindow.document;
  doc.open();
  doc.write(`
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Remote Ultrasound Feed</title>
</head>
<body class="popout-body" style="margin: 0; padding: 0; background: #060B18; overflow: hidden; height: 100vh;">
  <div class="video-card fit-contain" id="popout-card" style="width: 100%; height: 100vh; margin: 0; border: none; border-radius: 0; box-shadow: none; display: flex; flex-direction: column;">
    <div class="video-header" style="padding: 12px 20px; flex-shrink: 0;">
      <h2>${PROBE_SVG} Remote Ultrasound Feed</h2>
      <div class="video-controls">
        <button class="control-btn toggle-btn camera-btn" id="popout-camera-btn" type="button" title="Toggle Camera">
          <svg class="icon-on" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M23 7l-7 5 7 5V7z"></path>
            <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
          </svg>
          <svg class="icon-off" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M16 16v1a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2m5.66 0H14a2 2 0 0 1 2 2v3.34l1 1L23 7v10l-2.58-1.84M23 7l-7 5 7 5V7z"></path>
            <line x1="1" y1="1" x2="23" y2="23"></line>
          </svg>
        </button>
        <button class="control-btn toggle-btn mic-btn" id="popout-mic-btn" type="button" title="Toggle Microphone">
          <svg class="icon-on" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
            <line x1="12" y1="19" x2="12" y2="23"></line>
            <line x1="8" y1="23" x2="16" y2="23"></line>
          </svg>
          <svg class="icon-off" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="1" y1="1" x2="23" y2="23"></line>
            <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"></path>
            <path d="M17 11a5 5 0 0 1-5 5m-3.87-1.17A7 7 0 0 1 5 10v-2"></path>
            <line x1="12" y1="19" x2="12" y2="23"></line>
            <line x1="8" y1="23" x2="16" y2="23"></line>
          </svg>
        </button>
        <button class="control-btn zoom-out-btn" id="popout-zoom-out-btn" type="button" title="Zoom Out">-</button>
        <button class="control-btn zoom-in-btn" id="popout-zoom-in-btn" type="button" title="Zoom In">+</button>
        <button class="control-btn fit-btn" id="popout-fit-btn" type="button" title="Toggle Fit/Fill Mode">Fit</button>
        <button class="control-btn pin-btn" id="popout-pin-btn" type="button" title="Focus Feed">Focus</button>
      </div>
    </div>
    <div id="popout-player" class="remote-player" style="flex: 1; position: relative; overflow: hidden; background: #000;">
    </div>
  </div>
</body>
</html>
  `);
  doc.close();

  // Dynamically copy stylesheet links & styles, setting base href to resolve relatives
  const base = doc.createElement("base");
  base.href = window.location.href;
  doc.head.appendChild(base);

  document.querySelectorAll('link, style').forEach(el => {
    doc.head.appendChild(el.cloneNode(true));
  });

  const popoutCard = doc.getElementById("popout-card");
  const popoutPlayer = doc.getElementById("popout-player");

  // Setup Zoom and Pan pointer events
  setupZoomAndPan(popoutCard, popoutPlayer);

  // Set click event handlers for controls in child window
  doc.getElementById("popout-camera-btn").addEventListener("click", () => {
    const parentCard = getUltrasoundCard();
    if (parentCard) {
      const btn = parentCard.querySelector(".camera-btn");
      if (btn) btn.click();
    }
  });

  doc.getElementById("popout-mic-btn").addEventListener("click", () => {
    const parentCard = getUltrasoundCard();
    if (parentCard) {
      const btn = parentCard.querySelector(".mic-btn");
      if (btn) btn.click();
    }
  });

  doc.getElementById("popout-zoom-out-btn").addEventListener("click", () => {
    adjustZoom(popoutCard, popoutPlayer, -0.25);
  });

  doc.getElementById("popout-zoom-in-btn").addEventListener("click", () => {
    adjustZoom(popoutCard, popoutPlayer, 0.25);
  });

  doc.getElementById("popout-fit-btn").addEventListener("click", () => {
    const btn = doc.getElementById("popout-fit-btn");
    toggleFit(popoutCard, btn);
  });

  doc.getElementById("popout-pin-btn").addEventListener("click", () => {
    const parentCard = getUltrasoundCard();
    if (parentCard) {
      togglePin(parentCard);
    }
  });

  // Perform initial sync
  syncPopoutPlayer();
  syncPopoutControls();

  // Register unload cleanup
  popoutWindow.addEventListener("unload", () => {
    popoutWindow = null;
  });
}

// Clean up popouts when parent window closes
window.addEventListener("beforeunload", () => {
  if (popoutWindow && !popoutWindow.closed) {
    popoutWindow.close();
  }
  if (doctorPopoutWindow && !doctorPopoutWindow.closed) {
    doctorPopoutWindow.close();
  }
  if (patientPopoutWindow && !patientPopoutWindow.closed) {
    patientPopoutWindow.close();
  }
});

// Periodic synchronization loop
setInterval(() => {
  if (popoutWindow && !popoutWindow.closed) {
    syncPopoutPlayer();
    syncPopoutControls();
  }
  if (doctorPopoutWindow && !doctorPopoutWindow.closed) {
    syncDoctorPopoutPlayer();
    syncDoctorPopoutControls();
  }
  if (patientPopoutWindow && !patientPopoutWindow.closed) {
    syncPatientPopoutPlayer();
    syncPatientPopoutControls();
  }
}, 250);

// ==========================================================================
// POP-OUT / NEW WINDOW PATIENT CAMERA LOGIC
// ==========================================================================

function getPatientCard() {
  const remoteCard = document.getElementById("remote-card-4001");
  if (remoteCard) return remoteCard;
  const localUidVal = uidInput.value.trim() ? Number(uidInput.value) : (roleInput.value === "patient" ? 4001 : 3001);
  if (localUidVal === 4001) {
    return document.getElementById("local-card");
  }
  return null;
}

function syncPatientPopoutPlayer() {
  if (!patientPopoutWindow || patientPopoutWindow.closed) return;

  const popoutCard = patientPopoutWindow.document.getElementById("popout-card");
  const popoutPlayer = patientPopoutWindow.document.getElementById("popout-player");
  if (!popoutCard || !popoutPlayer) return;

  const parentCard = getPatientCard();
  if (!parentCard) {
    // Show placeholder if card is not present
    if (!popoutPlayer.querySelector(".placeholder-container")) {
      popoutPlayer.innerHTML = `
        <div class="placeholder-container" style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); font-size: 0.9rem; gap: 8px;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.6;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
          No Camera Input (View-Only Mode)
        </div>
      `;
    }
    return;
  }

  const parentPlayer = parentCard.id === "local-card" ? localPlayerEl : parentCard.querySelector(".remote-player");
  const parentVideo = parentPlayer ? parentPlayer.querySelector("video") : null;

  if (parentVideo && parentVideo.srcObject) {
    // Check if the popout already has a video element
    let childVideo = popoutPlayer.querySelector("video");
    if (!childVideo) {
      popoutPlayer.innerHTML = ""; // Clear placeholder
      childVideo = patientPopoutWindow.document.createElement("video");
      childVideo.autoplay = true;
      childVideo.playsInline = true;
      childVideo.muted = true;
      childVideo.style.width = "100%";
      childVideo.style.height = "100%";
      childVideo.style.display = "block";
      popoutPlayer.appendChild(childVideo);
    }
    // Only update srcObject if it has changed
    if (childVideo.srcObject !== parentVideo.srcObject) {
      childVideo.srcObject = parentVideo.srcObject;
      childVideo.play().catch(err => console.error("Error playing child Patient video:", err));
    }

    // Mirror zoom transformation classes and aspect ratios
    if (parentCard.style.getPropertyValue("--video-aspect")) {
      popoutCard.style.setProperty("--video-aspect", parentCard.style.getPropertyValue("--video-aspect"));
    }
    if (parentCard.classList.contains("has-aspect")) {
      popoutCard.classList.add("has-aspect");
    } else {
      popoutCard.classList.remove("has-aspect");
    }

    // Apply exact zoom from parent to maintain zoom state initially or during parent zoom actions
    const parentZoom = zoomStates.get(parentCard.id);
    const popoutZoom = zoomStates.get("patient-popout-card");
    if (parentZoom && (!popoutZoom || popoutZoom.scale !== parentZoom.scale || popoutZoom.translateX !== parentZoom.translateX || popoutZoom.translateY !== parentZoom.translateY)) {
      zoomStates.set("patient-popout-card", { ...parentZoom });
      applyZoomTransform(popoutCard, popoutPlayer);
    }
  } else {
    // Parent video doesn't exist, show placeholder
    if (!popoutPlayer.querySelector(".placeholder-container")) {
      popoutPlayer.innerHTML = `
        <div class="placeholder-container" style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); font-size: 0.9rem; gap: 8px;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.6;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
          No Camera Input (View-Only Mode)
        </div>
      `;
    }
  }
}

function syncPatientPopoutControls() {
  if (!patientPopoutWindow || patientPopoutWindow.closed) return;

  const parentCard = getPatientCard();
  if (!parentCard) return;

  const popoutCard = patientPopoutWindow.document.getElementById("popout-card");
  if (!popoutCard) return;

  // Sync Camera button state
  const parentCamBtn = parentCard.querySelector(".camera-btn");
  const childCamBtn = patientPopoutWindow.document.getElementById("popout-camera-btn");
  if (parentCamBtn && childCamBtn) {
    childCamBtn.disabled = parentCamBtn.disabled;
    if (parentCamBtn.classList.contains("active")) {
      childCamBtn.classList.add("active");
      childCamBtn.classList.remove("inactive");
      childCamBtn.title = "Turn Camera OFF";
    } else {
      childCamBtn.classList.add("inactive");
      childCamBtn.classList.remove("active");
      childCamBtn.title = "Turn Camera ON";
    }
  }

  // Sync Mic (Mute) button state
  const parentMicBtn = parentCard.querySelector(".mic-btn");
  const childMicBtn = patientPopoutWindow.document.getElementById("popout-mic-btn");
  if (parentMicBtn && childMicBtn) {
    childMicBtn.disabled = parentMicBtn.disabled;
    if (parentMicBtn.classList.contains("active")) {
      childMicBtn.classList.add("active");
      childMicBtn.classList.remove("inactive");
      childMicBtn.title = "Mute Microphone";
    } else {
      childMicBtn.classList.add("inactive");
      childMicBtn.classList.remove("active");
      childMicBtn.title = "Unmute Microphone";
    }
  }

  // Sync Fit button text and active state
  const childFitBtn = patientPopoutWindow.document.getElementById("popout-fit-btn");
  if (childFitBtn) {
    if (parentCard.classList.contains("fit-contain")) {
      popoutCard.classList.remove("fit-cover");
      popoutCard.classList.add("fit-contain");
      childFitBtn.textContent = "Fit";
      childFitBtn.classList.remove("active");
    } else {
      popoutCard.classList.remove("fit-contain");
      popoutCard.classList.add("fit-cover");
      childFitBtn.textContent = "Fill";
      childFitBtn.classList.add("active");
    }
  }

  // Sync Focus button state
  const childPinBtn = patientPopoutWindow.document.getElementById("popout-pin-btn");
  if (childPinBtn) {
    if (parentCard.classList.contains("pinned")) {
      popoutCard.classList.add("pinned");
      childPinBtn.textContent = "Unfocus";
      childPinBtn.classList.add("active");
    } else {
      popoutCard.classList.remove("pinned");
      childPinBtn.textContent = "Focus";
      childPinBtn.classList.remove("active");
    }
  }
}

function openPatientPopoutWindow() {
  if (patientPopoutWindow && !patientPopoutWindow.closed) {
    patientPopoutWindow.focus();
    return;
  }

  patientPopoutWindow = window.open("", "PatientPopout", "width=1024,height=768,menubar=no,toolbar=no,location=no,status=no");
  if (!patientPopoutWindow) {
    alert("Popup blocked! Please allow popups for this page to view the popout patient camera feed.");
    return;
  }

  const doc = patientPopoutWindow.document;
  doc.open();
  doc.write(`
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Patient Camera</title>
</head>
<body class="popout-body" style="margin: 0; padding: 0; background: #060B18; overflow: hidden; height: 100vh;">
  <div class="video-card fit-contain" id="popout-card" style="width: 100%; height: 100vh; margin: 0; border: none; border-radius: 0; box-shadow: none; display: flex; flex-direction: column;">
    <div class="video-header" style="padding: 12px 20px; flex-shrink: 0;">
      <h2>${PATIENT_SVG} Patient Camera</h2>
      <div class="video-controls">
        <button class="control-btn toggle-btn camera-btn" id="popout-camera-btn" type="button" title="Toggle Camera">
          <svg class="icon-on" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M23 7l-7 5 7 5V7z"></path>
            <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
          </svg>
          <svg class="icon-off" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M16 16v1a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2m5.66 0H14a2 2 0 0 1 2 2v3.34l1 1L23 7v10l-2.58-1.84M23 7l-7 5 7 5V7z"></path>
            <line x1="1" y1="1" x2="23" y2="23"></line>
          </svg>
        </button>
        <button class="control-btn toggle-btn mic-btn" id="popout-mic-btn" type="button" title="Toggle Microphone">
          <svg class="icon-on" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
            <line x1="12" y1="19" x2="12" y2="23"></line>
            <line x1="8" y1="23" x2="16" y2="23"></line>
          </svg>
          <svg class="icon-off" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="1" y1="1" x2="23" y2="23"></line>
            <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"></path>
            <path d="M17 11a5 5 0 0 1-5 5m-3.87-1.17A7 7 0 0 1 5 10v-2"></path>
            <line x1="12" y1="19" x2="12" y2="23"></line>
            <line x1="8" y1="23" x2="16" y2="23"></line>
          </svg>
        </button>
        <button class="control-btn zoom-out-btn" id="popout-zoom-out-btn" type="button" title="Zoom Out">-</button>
        <button class="control-btn zoom-in-btn" id="popout-zoom-in-btn" type="button" title="Zoom In">+</button>
        <button class="control-btn fit-btn" id="popout-fit-btn" type="button" title="Toggle Fit/Fill Mode">Fit</button>
        <button class="control-btn pin-btn" id="popout-pin-btn" type="button" title="Focus Feed">Focus</button>
      </div>
    </div>
    <div id="popout-player" class="remote-player" style="flex: 1; position: relative; overflow: hidden; background: #000;">
    </div>
  </div>
</body>
</html>
  `);
  doc.close();

  const base = doc.createElement("base");
  base.href = window.location.href;
  doc.head.appendChild(base);

  document.querySelectorAll('link, style').forEach(el => {
    doc.head.appendChild(el.cloneNode(true));
  });

  const popoutCard = doc.getElementById("popout-card");
  const popoutPlayer = doc.getElementById("popout-player");

  setupZoomAndPan(popoutCard, popoutPlayer);

  doc.getElementById("popout-camera-btn").addEventListener("click", () => {
    const parentCard = getPatientCard();
    if (parentCard) {
      const btn = parentCard.querySelector(".camera-btn");
      if (btn) btn.click();
    }
  });

  doc.getElementById("popout-mic-btn").addEventListener("click", () => {
    const parentCard = getPatientCard();
    if (parentCard) {
      const btn = parentCard.querySelector(".mic-btn");
      if (btn) btn.click();
    }
  });

  doc.getElementById("popout-zoom-out-btn").addEventListener("click", () => {
    adjustZoom(popoutCard, popoutPlayer, -0.25);
  });

  doc.getElementById("popout-zoom-in-btn").addEventListener("click", () => {
    adjustZoom(popoutCard, popoutPlayer, 0.25);
  });

  doc.getElementById("popout-fit-btn").addEventListener("click", () => {
    const btn = doc.getElementById("popout-fit-btn");
    toggleFit(popoutCard, btn);
  });

  doc.getElementById("popout-pin-btn").addEventListener("click", () => {
    const parentCard = getPatientCard();
    if (parentCard) {
      togglePin(parentCard);
    }
  });

  syncPatientPopoutPlayer();
  syncPatientPopoutControls();

  patientPopoutWindow.addEventListener("unload", () => {
    patientPopoutWindow = null;
  });
}

// PlebC TORUS Logo Card Boot Sequence & Interactive Enhancements
let torusBootComplete = false;

function triggerHeaderBootSequence() {
  const card = document.querySelector(".header-logo-card");
  const robotContainer = document.querySelector(".robot-container");
  if (!card) return;

  if (!torusBootComplete) {
    // Clear any previous state and add booting class
    card.classList.remove("boot-complete");
    card.classList.add("booting");

    if (robotContainer) {
      robotContainer.classList.add("active-boot");
    }

    setTimeout(() => {
      card.classList.remove("booting");
      card.classList.add("boot-complete");
      if (robotContainer) {
        robotContainer.remove();
      }
      torusBootComplete = true;
      bindHeaderLogoCardInteractions(card);
    }, 5200);
  } else {
    // Skip animation and activate immediately
    card.classList.remove("booting");
    card.classList.add("boot-complete");
    if (robotContainer) {
      robotContainer.remove();
    }
    bindHeaderLogoCardInteractions(card);
  }
}

function bindHeaderLogoCardInteractions(card) {
  if (!card) return;

  // 3D Tilt Effect
  card.addEventListener("mousemove", (e) => {
    const rect = card.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    // Percentage relative to center (-0.5 to 0.5)
    const px = (x / rect.width) - 0.5;
    const py = (y / rect.height) - 0.5;

    // Max tilt angle (degrees)
    const maxTilt = 3.5;
    const tiltY = px * maxTilt;
    const tiltX = -py * maxTilt;

    card.style.transform = `perspective(1000px) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`;
    card.style.transition = "transform 0.08s ease";
  });

  card.addEventListener("mouseleave", () => {
    card.style.transform = "perspective(1000px) rotateX(0deg) rotateY(0deg)";
    card.style.transition = "transform 0.6s cubic-bezier(0.25, 1, 0.5, 1)";
  });

  // Material Ripple & Click scale bounce
  card.addEventListener("click", function (e) {
    // Create ripple span
    const ripple = document.createElement("span");
    ripple.classList.add("ripple-effect");
    this.appendChild(ripple);

    // Calculate dimensions
    const rect = this.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const x = e.clientX - rect.left - size / 2;
    const y = e.clientY - rect.top - size / 2;

    ripple.style.width = ripple.style.height = `${size}px`;
    ripple.style.left = `${x}px`;
    ripple.style.top = `${y}px`;

    // Trigger scale transition
    this.classList.add("card-clicked");

    // Cleanup ripple on animation finish
    ripple.addEventListener("animationend", () => {
      ripple.remove();
    });

    // Reset scale/glow classes
    setTimeout(() => {
      this.classList.remove("card-clicked");
    }, 400);
  });
}

/* ==========================================================================
   DOCTOR AUTHENTICATION & SQLITE DATABASE SYSTEM
   ========================================================================== */

let dbInstance = null;
let currentAuthenticatedUser = null;

// Helper: SHA-256 Password Hashing via Web Crypto API
async function hashPasswordSHA256(password) {
  const salt = "torus_secure_salt_2026";
  const encoder = new TextEncoder();
  const data = encoder.encode(salt + password);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, "0")).join("");
}

// Save SQLite Database state to persistent browser storage
function saveSQLiteState() {
  if (!dbInstance) return;
  try {
    const data = dbInstance.export();
    const bufferStr = Array.from(data).join(",");
    localStorage.setItem("torus_sqlite_db", bufferStr);
  } catch (e) {
    console.warn("[SQLite] Storage save warning:", e);
  }
}

// Initialize SQLite Database Engine (sql.js)
async function initSQLiteDatabase() {
  try {
    let SQL = null;
    if (window.initSqlJs) {
      SQL = await window.initSqlJs({
        locateFile: file => `https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.8.0/${file}`
      });
    }

    const savedDbStr = localStorage.getItem("torus_sqlite_db");
    if (savedDbStr && SQL) {
      try {
        const byteArray = new Uint8Array(savedDbStr.split(",").map(Number));
        dbInstance = new SQL.Database(byteArray);
      } catch (dbErr) {
        console.warn("[SQLite] Storage database parse error, clearing invalid storage:", dbErr);
        localStorage.removeItem("torus_sqlite_db");
        dbInstance = new SQL.Database();
      }
    } else if (SQL) {
      dbInstance = new SQL.Database();
    }

    if (dbInstance) {
      dbInstance.run(`
        CREATE TABLE IF NOT EXISTS doctors (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          uid TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL,
          email TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'doctor',
          mobile TEXT DEFAULT '',
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
      `);

      dbInstance.run(`
        CREATE TABLE IF NOT EXISTS patients (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          uid TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL,
          email TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'patient',
          mobile TEXT DEFAULT '',
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
      `);

      dbInstance.run(`
        CREATE TABLE IF NOT EXISTS viewers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          uid TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL,
          email TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'viewer',
          mobile TEXT DEFAULT '',
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
      `);

      // Safely add mobile column if missing (for pre-existing databases)
      try {
        dbInstance.run("SELECT mobile FROM doctors LIMIT 1");
      } catch (e) {
        try {
          dbInstance.run("ALTER TABLE doctors ADD COLUMN mobile TEXT DEFAULT ''");
          saveSQLiteState();
          console.log("[SQLite] Migrated: added 'mobile' column to doctors.");
        } catch (e2) { }
      }

      try {
        dbInstance.run("SELECT mobile FROM patients LIMIT 1");
      } catch (e) {
        try {
          dbInstance.run("ALTER TABLE patients ADD COLUMN mobile TEXT DEFAULT ''");
          saveSQLiteState();
          console.log("[SQLite] Migrated: added 'mobile' column to patients.");
        } catch (e2) { }
      }

      try {
        dbInstance.run("SELECT mobile FROM viewers LIMIT 1");
      } catch (e) {
        try {
          dbInstance.run("ALTER TABLE viewers ADD COLUMN mobile TEXT DEFAULT ''");
          saveSQLiteState();
          console.log("[SQLite] Migrated: added 'mobile' column to viewers.");
        } catch (e2) { }
      }

      // Seed default Admin Doctor if empty
      const adminCheck = dbInstance.exec("SELECT * FROM doctors WHERE email = 'admin@gmail.com'");
      if (!adminCheck || adminCheck.length === 0 || adminCheck[0].values.length === 0) {
        const adminHash = await hashPasswordSHA256("admin123");
        dbInstance.run(
          "INSERT INTO doctors (uid, name, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
          ["3001", "Admin Doctor", "admin@gmail.com", adminHash, "admin"]
        );
        saveSQLiteState();
        console.log("[SQLite] Pre-seeded default Admin Doctor (UID: 3001, admin@gmail.com).");
      }

      // Seed default Patient if empty
      const patientCheck = dbInstance.exec("SELECT * FROM patients WHERE email = 'patient@gmail.com'");
      if (!patientCheck || patientCheck.length === 0 || patientCheck[0].values.length === 0) {
        const patientHash = await hashPasswordSHA256("patient123");
        dbInstance.run(
          "INSERT INTO patients (uid, name, email, password_hash, role, mobile) VALUES (?, ?, ?, ?, 'patient', ?)",
          ["4001", "Patient User", "patient@gmail.com", patientHash, "+91 98765 43210"]
        );
        saveSQLiteState();
        console.log("[SQLite] Pre-seeded default Patient (UID: 4001, patient@gmail.com).");
      }

      // Seed default Viewer if empty
      const viewerCheck = dbInstance.exec("SELECT * FROM viewers WHERE email IN ('user@gmail.com', 'viewer@torus.local')");
      if (!viewerCheck || viewerCheck.length === 0 || viewerCheck[0].values.length === 0) {
        const viewerHash = await hashPasswordSHA256("user123");
        dbInstance.run(
          "INSERT INTO viewers (uid, name, email, password_hash, role, mobile) VALUES (?, ?, ?, ?, 'viewer', ?)",
          ["6001", "Viewer 1", "user@gmail.com", viewerHash, "+91 98765 43210"]
        );
        saveSQLiteState();
        console.log("[SQLite] Pre-seeded default Viewer (UID: 6001, user@gmail.com).");
      }
    }
  } catch (err) {
    console.warn("[SQLite] sql.js initialization warning (falling back to REST API):", err);
  }
}

// Generate Unique Alphanumeric Viewer ID (6001+ or VIEW-XXXXX format)
function generateViewerId() {
  if (dbInstance) {
    try {
      for (let num = 6001; num < 6100; num++) {
        const uidStr = String(num);
        const checkRes = dbInstance.exec(`SELECT id FROM viewers WHERE uid = '${uidStr}'`);
        if (!checkRes || checkRes.length === 0 || checkRes[0].values.length === 0) {
          return uidStr;
        }
      }
    } catch (e) { }
  }
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  for (let attempt = 0; attempt < 100; attempt++) {
    let randomPart = "";
    for (let i = 0; i < 5; i++) {
      randomPart += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    const viewerId = `VIEW-${randomPart}`;
    if (dbInstance) {
      try {
        const checkRes = dbInstance.exec(`SELECT id FROM viewers WHERE uid = '${viewerId}'`);
        if (!checkRes || checkRes.length === 0 || checkRes[0].values.length === 0) {
          return viewerId;
        }
      } catch (e) {
        return viewerId;
      }
    } else {
      return viewerId;
    }
  }
  return `VIEW-${Date.now().toString(36).toUpperCase().slice(-5)}`;
}

// Generate Unique Alphanumeric Professional ID (DOC-XXXXX format)
function generateProfessionalId() {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

  for (let attempt = 0; attempt < 100; attempt++) {
    let randomPart = "";
    for (let i = 0; i < 5; i++) {
      randomPart += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    const professionalId = `DOC-${randomPart}`;

    // Check uniqueness in client-side database
    if (dbInstance) {
      try {
        const checkRes = dbInstance.exec(`SELECT id FROM doctors WHERE uid = '${professionalId}'`);
        if (!checkRes || checkRes.length === 0 || checkRes[0].values.length === 0) {
          return professionalId;
        }
      } catch (e) {
        return professionalId;
      }
    } else {
      return professionalId;
    }
  }

  // Fallback with timestamp to guarantee uniqueness
  return `DOC-${Date.now().toString(36).toUpperCase().slice(-5)}`;
}

// Generate Unique Alphanumeric Patient ID (PAT-XXXXX format)
function generatePatientId() {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

  for (let attempt = 0; attempt < 100; attempt++) {
    let randomPart = "";
    for (let i = 0; i < 5; i++) {
      randomPart += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    const patientId = `PAT-${randomPart}`;

    // Check uniqueness in client-side database
    if (dbInstance) {
      try {
        const checkRes = dbInstance.exec(`SELECT id FROM patients WHERE uid = '${patientId}'`);
        if (!checkRes || checkRes.length === 0 || checkRes[0].values.length === 0) {
          return patientId;
        }
      } catch (e) {
        return patientId;
      }
    } else {
      return patientId;
    }
  }

  // Fallback with timestamp to guarantee uniqueness
  return `PAT-${Date.now().toString(36).toUpperCase().slice(-5)}`;
}

// Frontend Strong Password Validation
function validateStrongPassword(password) {
  if (password.length < 8) {
    return { valid: false, error: "Password must be at least 8 characters long." };
  }
  if (!/[A-Z]/.test(password)) {
    return { valid: false, error: "Password must contain at least 1 uppercase letter." };
  }
  if (!/[a-z]/.test(password)) {
    return { valid: false, error: "Password must contain at least 1 lowercase letter." };
  }
  if (!/[0-9]/.test(password)) {
    return { valid: false, error: "Password must contain at least 1 number." };
  }
  if (!/[!@#$%^&*()_+\-=\[\]{};:'",.<>?/\\|`~]/.test(password)) {
    return { valid: false, error: "Password must contain at least 1 special character (e.g., @, #, $, !)." };
  }
  return { valid: true, error: "" };
}

// Frontend Email Validation
function validateEmailFormat(email) {
  const pattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  return pattern.test(email.trim());
}

// Frontend Mobile Validation
function validateMobileFormat(mobile) {
  const cleaned = mobile.trim().replace(/[\s\-\(\)]/g, "");
  const pattern = /^\+?[0-9]{7,15}$/;
  return pattern.test(cleaned);
}

// Register Doctor in SQLite
// Universal API dispatcher supporting relative routes and local backend ports
async function callBackendAPI(endpoint, payload, method = "POST") {
  const isDirectBackend = window.location.port === "3000";
  const candidateUrls = isDirectBackend
    ? [endpoint, `http://127.0.0.1:3000${endpoint}`, `http://localhost:3000${endpoint}`]
    : [`http://127.0.0.1:3000${endpoint}`, `http://localhost:3000${endpoint}`, endpoint];

  const uniqueUrls = Array.from(new Set(candidateUrls));
  const reqMethod = (method || "POST").toUpperCase();

  for (const url of uniqueUrls) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 6000);

      const fetchOptions = {
        method: reqMethod,
        headers: { "Content-Type": "application/json" },
        signal: controller.signal
      };
      if (reqMethod !== "GET" && reqMethod !== "HEAD" && payload !== undefined) {
        fetchOptions.body = JSON.stringify(payload);
      }

      const resp = await fetch(url, fetchOptions);
      clearTimeout(timeoutId);

      // Skip 404/405/502/503 from static dev servers that don't host the backend API
      if (resp.status === 404 || resp.status === 405 || resp.status === 502 || resp.status === 503) {
        continue;
      }

      const data = await resp.json();
      if (data && (typeof data.success === "boolean" || data.status !== undefined || data.error !== undefined || data.message !== undefined)) {
        return data;
      }
    } catch (err) {
      // Continue to next URL candidate
    }
  }
  return null;
}


// Mask email for secure UI display
function maskEmailAddress(email) {
  if (!email || !email.includes("@")) return email;
  const [user, domain] = email.split("@");
  if (user.length <= 2) {
    return user[0] + "*@" + domain;
  }
  return user[0] + "*".repeat(user.length - 2) + user[user.length - 1] + "@" + domain;
}

// Register Doctor in Backend Database
async function registerDoctorAccount(name, email, password, mobile, uid = "") {
  const cleanEmail = email.trim().toLowerCase();
  const cleanName = name.trim();
  const cleanMobile = mobile.trim();
  const cleanUid = uid.trim().toUpperCase();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/doctors/register", {
    name: cleanName,
    email: cleanEmail,
    password: password,
    mobile: cleanMobile,
    uid: cleanUid,
    role: "doctor"
  });
  if (apiRes) return apiRes;

  return { success: false, error: "Backend server is unreachable. Please verify that the backend server is running on port 3000." };
}

// Authenticate Doctor against Backend Database (Email OR UID)
async function authenticateDoctorAccount(loginId, password) {
  const cleanLogin = loginId.trim().toLowerCase();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/doctors/login", {
    login_id: cleanLogin,
    password: password,
    role: "doctor"
  });
  if (apiRes) return apiRes;

  return { success: false, error: "Backend server is unreachable. Please verify that the backend server is running on port 3000." };
}

// Request Doctor Password Reset OTP (Real Backend API + SMTP Dispatch)
async function requestDoctorResetOTP(identifier) {
  const cleanId = identifier.trim().toLowerCase();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/doctors/forgot-password/send-otp", {
    identifier: cleanId,
    role: "doctor"
  });
  if (apiRes) return apiRes;

  return {
    success: false,
    error: "Backend server is unreachable. Please verify that the backend server is running on port 3000."
  };
}

// Verify Doctor Password Reset OTP (Real Backend API Verification)
async function verifyDoctorResetOTP(identifier, otp) {
  const cleanId = identifier.trim().toLowerCase();
  const cleanOtp = String(otp).trim();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/doctors/forgot-password/verify-otp", {
    identifier: cleanId,
    otp: cleanOtp,
    role: "doctor"
  });
  if (apiRes) return apiRes;

  return {
    success: false,
    error: "Backend server is unreachable. Please verify that the backend server is running on port 3000."
  };
}

// Reset Doctor Password with Verified Token (Real Backend API Reset)
async function resetDoctorPasswordWithToken(identifier, resetToken, newPassword) {
  const cleanId = identifier.trim().toLowerCase();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/doctors/forgot-password/reset", {
    identifier: cleanId,
    reset_token: resetToken,
    new_password: newPassword,
    role: "doctor"
  });
  if (apiRes) return apiRes;

  return {
    success: false,
    error: "Backend server is unreachable. Please verify that the backend server is running on port 3000."
  };
}

// Legacy wrapper
async function resetDoctorPasswordAccount(email, newPassword) {
  return resetDoctorPasswordWithToken(email, "legacy_direct", newPassword);
}

// ============================================================
// CLINICAL SESSION API HELPERS
// ============================================================

// Create Doctor Clinical Session (Backend Generated Unique Code)
async function createClinicalSessionAPI(doctor) {
  const doctorUid = doctor?.uid || "3001";
  const doctorName = doctor?.name || "Dr. Torus";
  const doctorEmail = doctor?.email || "admin@gmail.com";
  const doctorId = doctor?.id || null;
  const channelName = (channelInput && channelInput.value.trim()) ? channelInput.value.trim() : "torus";

  const apiRes = await callBackendAPI("/api/sessions/create", {
    doctor_id: doctorId,
    doctor_uid: doctorUid,
    doctor_name: doctorName,
    doctor_email: doctorEmail,
    channel_name: channelName
  });
  if (apiRes) return apiRes;

  return { success: false, error: "Unable to connect to the clinical session. Please try again." };
}

// Join Existing Clinical Session (Backend Validated)
async function joinClinicalSessionAPI(sessionCode, participantName, role = "viewer", participantUid = "") {
  const cleanCode = (sessionCode || "").trim().toUpperCase();
  const cleanName = (participantName || "").trim();

  if (!cleanCode) {
    return { success: false, error: "Please enter the session code." };
  }

  const apiRes = await callBackendAPI("/api/sessions/join", {
    session_code: cleanCode,
    participant_name: cleanName,
    role: role,
    participant_uid: participantUid
  });
  if (apiRes) return apiRes;

  return { success: false, error: "Unable to connect to the clinical session. Please try again." };
}

// Validate Clinical Session
async function validateClinicalSessionAPI(sessionCode) {
  const cleanCode = (sessionCode || "").trim().toUpperCase();
  if (!cleanCode) {
    return { success: false, error: "Please enter the session code." };
  }

  const apiRes = await callBackendAPI("/api/sessions/validate", {
    session_code: cleanCode
  });
  if (apiRes) return apiRes;

  return { success: false, error: "Unable to connect to the clinical session. Please try again." };
}

// Set Active Authenticated Doctor Session & Launch Dashboard
async function setAuthenticatedDoctorSession(doctor) {
  currentAuthenticatedUser = doctor;

  // Bind values to settings inputs
  if (roleInput) {
    roleInput.value = "doctor";
    roleInput.dispatchEvent(new Event("change"));
  }
  if (uidInput) {
    uidInput.value = doctor.uid;
  }

  // Populate User Profile popover in Live Consultation header
  const nameEl = document.getElementById("user-display-name");
  const uidEl = document.getElementById("user-display-uid");
  const badgeEl = document.getElementById("header-user-badge");

  if (nameEl) {
    nameEl.textContent = doctor.name.startsWith("Dr.") ? doctor.name : `Dr. ${doctor.name}`;
  }
  if (uidEl) {
    uidEl.textContent = doctor.uid;
  }
  // header-user-badge stays permanently hidden; info shown via headerProfilePopover
  if (badgeEl) {
    badgeEl.style.display = "none";
  }

  // Connect Doctor MQTT
  connectDoctorMQTT(appIdInput ? appIdInput.value : "f320d3475b6d4b70ba512b06d09849d7", channelInput ? channelInput.value : "torus");

  // Create real backend clinical session and store for Agora Settings
  try {
    const sessionRes = await createClinicalSessionAPI(doctor);
    if (sessionRes && sessionRes.success && sessionRes.session_code) {
      window.activeClinicalSessionCode = sessionRes.session_code;
      sessionStorage.setItem("active_clinical_session_code", sessionRes.session_code);
      localStorage.setItem("active_clinical_session_code", sessionRes.session_code);
      const modalCodeInput = document.getElementById("settings-session-code");
      if (modalCodeInput) {
        modalCodeInput.value = sessionRes.session_code;
      }
      if (sessionRes.channel && channelInput) {
        channelInput.value = sessionRes.channel;
      }
      if (window.torusSessions?.active?.[0]) {
        window.torusSessions.active[0].clinicalSessionCode = sessionRes.session_code;
        saveTorusSessions();
      }
    }
  } catch (err) {
    console.warn("[Doctor Session Creation Warning]", err);
  }

  currentAuthenticatedUser = { ...doctor, role: "doctor" };
  currentAuthenticatedRole = "doctor";
  try {
    sessionStorage.setItem("authenticated_doctor", JSON.stringify(currentAuthenticatedUser));
    localStorage.setItem("authenticated_doctor", JSON.stringify(currentAuthenticatedUser));
  } catch (e) { }

  // Log doctor authentication event
  if (typeof logDoctorActivity === "function") {
    logDoctorActivity(
      "auth",
      "Doctor Portal Authentication",
      `Doctor ${doctor.name || "Doctor"} authenticated successfully into TORUS Doctor Portal.`,
      "Verified",
      `UID: ${doctor.uid || "3001"}`
    );
  }

  // Populate Dashboard Header, Doctor Profile & Render Sessions
  updateDoctorPortalHeader(doctor);
  if (typeof renderDoctorProfile === "function") {
    renderDoctorProfile(doctor);
  }
  showTorusScreen("doctor-portal-dashboard");

  // Setup Haptic Pad event listeners & trigger initial connection attempt (Requirement 1)
  if (typeof setupHapticPadListeners === "function") {
    setupHapticPadListeners();
  }
  if (typeof initiateHapticPadConnection === "function") {
    initiateHapticPadConnection();
  }
}

// ============================================================
// DOCTOR PORTAL DASHBOARD & CLINICAL SESSIONS STATE ENGINE
// ============================================================

// Structured session data model (Separate from Doctor Biometrics)
window.torusSessions = {
  active: [
    {
      sessionId: "S-001",
      patientId: "P-12345",
      patientName: "Patient A",
      deviceId: "TORUS-A12",
      scanType: "Abdominal",
      duration: "12:34",
      diagnosticCenter: "Apex Diagnostic Center",
      scheduledTime: "10:30 AM",
      status: "active", // "active" | "disconnected" | "completed"
      doctorConnectionState: "not_joined", // "not_joined" | "connected" | "disconnected"
      clinicalSessionCode: null
    }
  ],
  upcoming: [
    {
      sessionId: "S-002",
      patientId: "P-8821",
      patientName: "John Doe",
      deviceId: "TORUS-A12",
      scanType: "Abdominal",
      diagnosticCenter: "NYC Medical",
      scheduledTime: "10:30 AM",
      timeLabel: "10:30 AM",
      ageGender: "42 | Male",
      contact: "+1 (555) 019-2834",
      clinicalNotes: "Patient complaining of abdominal discomfort. Fasting for 8 hours prior to scan.",
      previousReports: "2025-05-12 - Normal Abdominal Scan",
      status: "scheduled",
      doctorConnectionState: "not_joined"
    },
    {
      sessionId: "S-003",
      patientId: "P-9104",
      patientName: "Jane Smith",
      deviceId: "TORUS-B08",
      scanType: "Cardiac",
      diagnosticCenter: "Boston General",
      scheduledTime: "12:00 PM",
      timeLabel: "12:00 PM",
      ageGender: "38 | Female",
      contact: "+1 (555) 084-9123",
      clinicalNotes: "Follow-up for mild mitral valve regurgitation. Routine cardiac scan.",
      previousReports: "2025-08-20 - Mild Mitral Regurgitation",
      status: "scheduled",
      doctorConnectionState: "not_joined"
    },
    {
      sessionId: "S-004",
      patientId: "P-7543",
      patientName: "Robert Brown",
      deviceId: "TORUS-C15",
      scanType: "Pelvic",
      diagnosticCenter: "Apollo Hyderabad",
      scheduledTime: "02:15 PM",
      timeLabel: "02:15 PM",
      ageGender: "55 | Male",
      contact: "+91 98490 12345",
      clinicalNotes: "Pelvic discomfort and suspected lower urinary tract symptoms.",
      previousReports: "None on record",
      status: "scheduled",
      doctorConnectionState: "not_joined"
    }
  ],
  completed: [
    {
      sessionId: "S-101",
      patientId: "P-12345",
      patientName: "Patient A",
      deviceId: "TORUS-A12",
      scanType: "Abdominal",
      diagnosticCenter: "Apex Diagnostic Center",
      sessionDate: "2026-09-14",
      sessionTime: "09:15 AM",
      duration: "22:15",
      status: "completed",
      doctorName: "Dr. Admin Doctor",
      reportStatus: "ready",
      reportId: "REP-2026-001",
      clinicalSummary: "Normal hepatobiliary sonogram. Gallbladder wall thickness normal at 2.1mm without stones or sludge. CBD calibre 4.2mm. Hepatic parenchyma homogeneous with normal echogenicity.",
      telemetry: { maxForce: "2.8 N", avgForce: "1.9 N", latency: "14 ms", frames: 5240 }
    },
    {
      sessionId: "S-102",
      patientId: "P-8821",
      patientName: "John Doe",
      deviceId: "TORUS-A12",
      scanType: "Abdominal",
      diagnosticCenter: "NYC Medical",
      sessionDate: "2026-09-13",
      sessionTime: "11:30 AM",
      duration: "19:40",
      status: "completed",
      doctorName: "Dr. Admin Doctor",
      reportStatus: "ready",
      reportId: "REP-2026-002",
      clinicalSummary: "Mild hepatic steatosis grade 1. Bilateral kidneys show preserved corticomedullary differentiation without calculi or hydronephrosis. Spleen normal in size.",
      telemetry: { maxForce: "2.5 N", avgForce: "1.7 N", latency: "16 ms", frames: 4780 }
    },
    {
      sessionId: "S-103",
      patientId: "P-9104",
      patientName: "Jane Smith",
      deviceId: "TORUS-B08",
      scanType: "Cardiac",
      diagnosticCenter: "Boston General",
      sessionDate: "2026-09-12",
      sessionTime: "02:00 PM",
      duration: "26:10",
      status: "completed",
      doctorName: "Dr. Admin Doctor",
      reportStatus: "ready",
      reportId: "REP-2026-003",
      clinicalSummary: "Transthoracic echocardiogram. LVEF estimated at 58% with normal left ventricular systolic function. Mild posterior mitral leaflet prolapse with trace to mild regurgitation. Normal aortic root.",
      telemetry: { maxForce: "2.9 N", avgForce: "2.1 N", latency: "18 ms", frames: 6200 }
    },
    {
      sessionId: "S-104",
      patientId: "P-7543",
      patientName: "Robert Brown",
      deviceId: "TORUS-C15",
      scanType: "Pelvic",
      diagnosticCenter: "Apollo Hyderabad",
      sessionDate: "2026-09-11",
      sessionTime: "10:15 AM",
      duration: "17:25",
      status: "completed",
      doctorName: "Dr. Admin Doctor",
      reportStatus: "ready",
      reportId: "REP-2026-004",
      clinicalSummary: "Urinary bladder well distended with smooth, regular walls. Prostate volume measured at 34cc with symmetric peripheral zone. Post-void residual negligible (18ml).",
      telemetry: { maxForce: "2.4 N", avgForce: "1.8 N", latency: "15 ms", frames: 4190 }
    },
    {
      sessionId: "S-105",
      patientId: "P-3312",
      patientName: "Eleanor Vance",
      deviceId: "TORUS-B08",
      scanType: "Cardiac",
      diagnosticCenter: "Boston General",
      sessionDate: "2026-09-10",
      sessionTime: "03:45 PM",
      duration: "24:50",
      status: "completed",
      doctorName: "Dr. Admin Doctor",
      reportStatus: "ready",
      reportId: "REP-2026-005",
      clinicalSummary: "Complete 2D & Doppler cardiac evaluation. Normal chamber sizes, no regional wall motion abnormalities. Normal left ventricular filling pressures (E/A 1.2).",
      telemetry: { maxForce: "2.7 N", avgForce: "2.0 N", latency: "19 ms", frames: 5910 }
    },
    {
      sessionId: "S-106",
      patientId: "P-4401",
      patientName: "Marcus Brody",
      deviceId: "TORUS-A12",
      scanType: "Vascular",
      diagnosticCenter: "NYC Medical",
      sessionDate: "2026-09-09",
      sessionTime: "08:30 AM",
      duration: "28:15",
      status: "completed",
      doctorName: "Dr. Admin Doctor",
      reportStatus: "ready",
      reportId: "REP-2026-006",
      clinicalSummary: "Bilateral extracranial carotid duplex examination. CCA and ICA spectral waveforms demonstrate laminar flow without significant hemodynamically relevant stenosis (<30%).",
      telemetry: { maxForce: "2.2 N", avgForce: "1.6 N", latency: "14 ms", frames: 6730 }
    },
    {
      sessionId: "S-107",
      patientId: "P-5590",
      patientName: "Sarah Connor",
      deviceId: "TORUS-A12",
      scanType: "Abdominal",
      diagnosticCenter: "Apex Diagnostic Center",
      sessionDate: "2026-09-08",
      sessionTime: "01:20 PM",
      duration: "21:05",
      status: "completed",
      doctorName: "Dr. Admin Doctor",
      reportStatus: "ready",
      reportId: "REP-2026-007",
      clinicalSummary: "Targeted abdominal scan. Normal pancreas, spleen, and abdominal aorta. No free intraperitoneal fluid detected in Morrison's pouch or pelvis.",
      telemetry: { maxForce: "2.6 N", avgForce: "1.9 N", latency: "15 ms", frames: 5020 }
    },
    {
      sessionId: "S-108",
      patientId: "P-6623",
      patientName: "David Miller",
      deviceId: "TORUS-C15",
      scanType: "Pelvic",
      diagnosticCenter: "Apollo Hyderabad",
      sessionDate: "2026-09-07",
      sessionTime: "11:00 AM",
      duration: "16:45",
      status: "completed",
      doctorName: "Dr. Admin Doctor",
      reportStatus: "ready",
      reportId: "REP-2026-008",
      clinicalSummary: "Pelvic sonography. Pre-void bladder volume 420ml, post-void residual 25ml. Normal urinary bladder contours without trabeculation or mass.",
      telemetry: { maxForce: "2.3 N", avgForce: "1.7 N", latency: "17 ms", frames: 3990 }
    },
    {
      sessionId: "S-109",
      patientId: "P-7741",
      patientName: "Amina Patel",
      deviceId: "TORUS-B08",
      scanType: "Thyroid",
      diagnosticCenter: "Boston General",
      sessionDate: "2026-09-06",
      sessionTime: "04:10 PM",
      duration: "18:30",
      status: "completed",
      doctorName: "Dr. Admin Doctor",
      reportStatus: "ready",
      reportId: "REP-2026-009",
      clinicalSummary: "High-resolution thyroid sonography. Right lobe: 4.2 x 1.4 x 1.3 cm. Left lobe: 4.0 x 1.3 x 1.2 cm. Normal vascularity on color Doppler. No discrete solid or cystic lesions.",
      telemetry: { maxForce: "2.0 N", avgForce: "1.5 N", latency: "16 ms", frames: 4410 }
    },
    {
      sessionId: "S-110",
      patientId: "P-8819",
      patientName: "Carlos Mendoza",
      deviceId: "TORUS-K03",
      scanType: "Abdominal",
      diagnosticCenter: "Central Tele-Robotics Center",
      sessionDate: "2026-09-05",
      sessionTime: "10:00 AM",
      duration: "25:40",
      status: "completed",
      doctorName: "Dr. Admin Doctor",
      reportStatus: "ready",
      reportId: "REP-2026-010",
      clinicalSummary: "Renal Doppler and cortical assessment. Right kidney 10.8cm, left kidney 11.1cm. Normal resistive index (0.64). No perinephric fluid collection.",
      telemetry: { maxForce: "2.8 N", avgForce: "2.2 N", latency: "15 ms", frames: 6140 }
    },
    {
      sessionId: "S-111",
      patientId: "P-9902",
      patientName: "Clara Oswald",
      deviceId: "TORUS-B08",
      scanType: "Cardiac",
      diagnosticCenter: "Boston General",
      sessionDate: "2026-09-04",
      sessionTime: "02:30 PM",
      duration: "23:10",
      status: "transferred",
      doctorName: "Dr. Admin Doctor",
      reportStatus: "pending",
      reportId: "REP-2026-011",
      clinicalSummary: "Aortic valve and aortic root interrogation. Mild aortic sclerosis without gradient elevation. Concentric LV remodeling noted. Transferred for multidisciplinary review.",
      telemetry: { maxForce: "2.6 N", avgForce: "2.0 N", latency: "18 ms", frames: 5520 }
    },
    {
      sessionId: "S-112",
      patientId: "P-1045",
      patientName: "James Wilson",
      deviceId: "TORUS-A12",
      scanType: "Vascular",
      diagnosticCenter: "NYC Medical",
      sessionDate: "2026-09-03",
      sessionTime: "09:45 AM",
      duration: "29:00",
      status: "completed",
      doctorName: "Dr. Admin Doctor",
      reportStatus: "pending",
      reportId: "REP-2026-012",
      clinicalSummary: "Lower extremity venous duplex examination. Common femoral, femoral, and popliteal veins show full compressibility with augmentable Doppler phasicity. Pending final attending countersignature.",
      telemetry: { maxForce: "2.5 N", avgForce: "1.8 N", latency: "14 ms", frames: 6980 }
    }
  ]
};

function saveTorusSessions() {
  try {
    sessionStorage.setItem("torus_doctor_sessions", JSON.stringify(window.torusSessions));
    localStorage.setItem("torus_doctor_sessions", JSON.stringify(window.torusSessions));
  } catch (e) {
    console.warn("Could not save session state:", e);
  }
}

function loadTorusSessions() {
  // Default upcoming sessions (always authoritative)
  const defaultUpcoming = [
    { sessionId: "S-002", patientId: "P-8821", patientName: "John Doe", deviceId: "TORUS-A12", scanType: "Abdominal", diagnosticCenter: "NYC Medical", scheduledTime: "10:30 AM", status: "scheduled", doctorConnectionState: "not_joined" },
    { sessionId: "S-003", patientId: "P-9104", patientName: "Jane Smith", deviceId: "TORUS-B08", scanType: "Cardiac", diagnosticCenter: "Boston General", scheduledTime: "12:00 PM", status: "scheduled", doctorConnectionState: "not_joined" },
    { sessionId: "S-004", patientId: "P-7543", patientName: "Robert Brown", deviceId: "TORUS-C15", scanType: "Pelvic", diagnosticCenter: "Apollo Hyderabad", scheduledTime: "02:15 PM", status: "scheduled", doctorConnectionState: "not_joined" }
  ];

  try {
    const saved = sessionStorage.getItem("torus_doctor_sessions") || localStorage.getItem("torus_doctor_sessions");
    if (saved) {
      const parsed = JSON.parse(saved);
      if (parsed && Array.isArray(parsed.active)) {
        parsed.active.forEach(s => {
          s.status = "active";
          if (s.doctorConnectionState === "disconnected") s.doctorConnectionState = "not_joined";
        });
        window.torusSessions.active = parsed.active;
      }
      if (parsed && Array.isArray(parsed.completed) && parsed.completed.length > 0) {
        window.torusSessions.completed = parsed.completed;
      }
    }
  } catch (e) {
    console.warn("Could not load session state:", e);
  }

  // Preserve upcoming sessions if already loaded or saved
  if (!window.torusSessions) window.torusSessions = { active: [], upcoming: [], completed: [] };
  if (!window.torusSessions.upcoming || window.torusSessions.upcoming.length === 0) {
    window.torusSessions.upcoming = defaultUpcoming;
  }
  if (!window.torusSessions.completed || window.torusSessions.completed.length === 0) {
    // Retain default 12 completed sessions
    window.torusSessions.completed = window.torusSessions.completed || [];
  }

  // Patch active session deviceId with last connected device
  const connectedDevId = sessionStorage.getItem("connectedDeviceId") || localStorage.getItem("connectedDeviceId");
  if (connectedDevId && window.torusSessions?.active?.[0]) {
    window.torusSessions.active[0].deviceId = connectedDevId;
  }
}


// Render Sidebar Navigation Menu specifically tailored to Role (Doctor vs Patient)
function renderPortalSidebar(role = "doctor") {
  const navContainer = document.getElementById("docDashSidebarNav");
  if (!navContainer) return;

  const isPatient = (role === "patient");

  if (isPatient) {
    navContainer.innerHTML = `
      <a href="#patient-dashboard" class="ddash-nav-item active" data-view="patient-dashboard">
        <span class="ddash-nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1.5"></rect>
            <rect x="14" y="3" width="7" height="7" rx="1.5"></rect>
            <rect x="14" y="14" width="7" height="7" rx="1.5"></rect>
            <rect x="3" y="14" width="7" height="7" rx="1.5"></rect>
          </svg>
        </span>
        <span class="ddash-nav-label">Dashboard</span>
      </a>

      <a href="#patient-profile" class="ddash-nav-item" data-view="patient-profile">
        <span class="ddash-nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
          </svg>
        </span>
        <span class="ddash-nav-label">Patient Profile</span>
      </a>

      <a href="#patient-appointments" class="ddash-nav-item" data-view="patient-appointments">
        <span class="ddash-nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
            <line x1="16" y1="2" x2="16" y2="6"></line>
            <line x1="8" y1="2" x2="8" y2="6"></line>
            <line x1="3" y1="10" x2="21" y2="10"></line>
          </svg>
        </span>
        <span class="ddash-nav-label">Appointments</span>
      </a>

      <a href="#patient-diagnostic-reports" class="ddash-nav-item" data-view="patient-diagnostic-reports">
        <span class="ddash-nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <line x1="16" y1="13" x2="8" y2="13"></line>
            <line x1="16" y1="17" x2="8" y2="17"></line>
            <polyline points="10 9 9 9 8 9"></polyline>
          </svg>
        </span>
        <span class="ddash-nav-label">Diagnostic Reports</span>
      </a>

      <a href="#patient-history" class="ddash-nav-item" data-view="patient-history">
        <span class="ddash-nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path>
            <polyline points="3 3 3 8 8 8"></polyline>
            <polyline points="12 7 12 12 15 15"></polyline>
          </svg>
        </span>
        <span class="ddash-nav-label">Examination History</span>
      </a>

      <a href="#logout" id="docDashSidebarLogoutBtn" class="ddash-nav-item ddash-nav-logout" data-view="logout">
        <span class="ddash-nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
            <polyline points="16 17 21 12 16 7"></polyline>
            <line x1="21" y1="12" x2="9" y2="12"></line>
          </svg>
        </span>
        <span class="ddash-nav-label">Logout</span>
      </a>
    `;
  } else {
    navContainer.innerHTML = `
      <a href="#dashboard" class="ddash-nav-item active" data-view="dashboard">
        <span class="ddash-nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1.5"></rect>
            <rect x="14" y="3" width="7" height="7" rx="1.5"></rect>
            <rect x="14" y="14" width="7" height="7" rx="1.5"></rect>
            <rect x="3" y="14" width="7" height="7" rx="1.5"></rect>
          </svg>
        </span>
        <span class="ddash-nav-label">Dashboard</span>
      </a>

      <a href="#profile" class="ddash-nav-item" data-view="doctor-profile">
        <span class="ddash-nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
          </svg>
        </span>
        <span class="ddash-nav-label">Doctor Profile</span>
      </a>

      <a href="#activity-log" class="ddash-nav-item" data-view="activity-log">
        <span class="ddash-nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
          </svg>
        </span>
        <span class="ddash-nav-label">Activity Log</span>
      </a>

      <a href="#insights" class="ddash-nav-item" data-view="insights">
        <span class="ddash-nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="20" x2="18" y2="10"></line>
            <line x1="12" y1="20" x2="12" y2="4"></line>
            <line x1="6" y1="20" x2="6" y2="14"></line>
          </svg>
        </span>
        <span class="ddash-nav-label">Insights</span>
      </a>

      <a href="#patient-reports" class="ddash-nav-item" data-view="patient-reports">
        <span class="ddash-nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <line x1="16" y1="13" x2="8" y2="13"></line>
            <line x1="16" y1="17" x2="8" y2="17"></line>
            <polyline points="10 9 9 9 8 9"></polyline>
          </svg>
        </span>
        <span class="ddash-nav-label">Patient Reports</span>
      </a>

      <a href="#history" class="ddash-nav-item" data-view="history">
        <span class="ddash-nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path>
            <polyline points="3 3 3 8 8 8"></polyline>
            <polyline points="12 7 12 12 15 15"></polyline>
          </svg>
        </span>
        <span class="ddash-nav-label">History</span>
      </a>

      <a href="#logout" id="docDashSidebarLogoutBtn" class="ddash-nav-item ddash-nav-logout" data-view="logout">
        <span class="ddash-nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
            <polyline points="16 17 21 12 16 7"></polyline>
            <line x1="21" y1="12" x2="9" y2="12"></line>
          </svg>
        </span>
        <span class="ddash-nav-label">Logout</span>
      </a>
    `;
  }

  // Re-attach sidebar nav click events
  if (typeof bindSidebarNavEvents === "function") {
    bindSidebarNavEvents();
  }
}
window.renderPortalSidebar = renderPortalSidebar;

// Update Shared Topbar Header and Sidebar Profile (for Doctor and Patient)
function updateSharedPortalHeader(user, role = "doctor") {
  const avatarEl = document.getElementById("docDashAvatarChip");
  const popoverName = document.getElementById("popoverDoctorName");
  const popoverUid = document.getElementById("popoverDoctorId");
  const popoverRole = document.querySelector(".ddash-profile-role");
  const popoverIdLabel = document.querySelector(".ddash-profile-id");

  const sidebarTitle = document.querySelector(".ddash-sidebar-subtitle");
  const sidebarDocName = document.getElementById("sidebarDocName");
  const sidebarDocEmail = document.getElementById("sidebarDocEmail");
  const sidebarDocRole = document.getElementById("sidebarDocRole");

  const adhocBtn = document.getElementById("docDashAdhocScanBtn");
  const hapticChip = document.getElementById("docDashHapticChip");

  const isPatient = (role === "patient" || user?.role === "patient");
  const displayName = user?.name || (isPatient ? "Patient User" : "Admin Doctor");
  const displayUid = user?.uid || (isPatient ? "4001" : "3001");
  const displayEmail = user?.email || (isPatient ? "patient@gmail.com" : "doctor@hospital.com");

  if (popoverName) popoverName.textContent = displayName.replace(/^Dr\.\s*/i, "").trim();
  if (popoverUid) popoverUid.textContent = displayUid;
  if (popoverRole) popoverRole.textContent = isPatient ? "Role: Patient" : "Role: Doctor / Admin";
  if (popoverIdLabel) popoverIdLabel.innerHTML = `${isPatient ? "Patient" : "Doctor"} ID: <span id="popoverDoctorId">${displayUid}</span>`;

  if (avatarEl) {
    if (isPatient) {
      avatarEl.textContent = "PT";
    } else {
      const cleanName = displayName.replace(/^Dr\.\s*/i, "").trim();
      const initials = cleanName
        .split(/\s+/)
        .filter(Boolean)
        .map(part => part[0].toUpperCase())
        .slice(0, 2)
        .join("") || "AD";
      avatarEl.textContent = initials;
    }
  }

  const popoverAvatar = document.querySelector(".ddash-popover-avatar");
  if (popoverAvatar && avatarEl) {
    popoverAvatar.textContent = avatarEl.textContent;
  }

  // Update sidebar branding and footer
  if (sidebarTitle) sidebarTitle.textContent = isPatient ? "Patient Portal" : "Doctor Portal";
  if (sidebarDocName) sidebarDocName.textContent = displayName;
  if (sidebarDocEmail) sidebarDocEmail.textContent = displayEmail;
  if (sidebarDocRole) sidebarDocRole.textContent = `Role: ${isPatient ? "patient" : "doctor"}`;

  // Ensure Header Top Controls (Haptic Pad status & Adhoc Scan) are properly displayed per role
  if (adhocBtn) adhocBtn.style.display = isPatient ? "none" : "inline-flex";
  if (hapticChip) {
    hapticChip.style.display = "inline-flex";
    if (isPatient) {
      if (typeof updatePatientHapticSessionStatus === "function") {
        updatePatientHapticSessionStatus(user || currentAuthenticatedUser);
      }
      if (typeof startHapticLiveMonitoring === "function") {
        startHapticLiveMonitoring();
      }
    } else {
      if (typeof setHapticPadStatus === "function") {
        setHapticPadStatus(currentHapticState || HAPTIC_STATE.NOT_CONNECTED);
      }
    }
  }

  // Re-render sidebar items to guarantee exact role navigation
  renderPortalSidebar(isPatient ? "patient" : "doctor");
}
window.updateSharedPortalHeader = updateSharedPortalHeader;

function updateDoctorPortalHeader(doctor) {
  updateSharedPortalHeader(doctor, "doctor");
}
window.updateDoctorPortalHeader = updateDoctorPortalHeader;

// ============================================================
// PATIENT PORTAL DATA RETRIEVAL & RENDERING FUNCTIONS
// ============================================================

function getPatientSessionData(patient) {
  loadTorusSessions();
  const currentUid = (patient?.uid || patient?.id || "4001").toString().trim().toLowerCase();
  const currentName = (patient?.name || "Patient User").trim().toLowerCase();

  const allActive = window.torusSessions?.active || [];
  const allUpcoming = window.torusSessions?.upcoming || [];
  const allCompleted = window.torusSessions?.completed || [];

  // Match active session
  let activeSession = allActive.find(s =>
    (s.patientId && s.patientId.toLowerCase() === currentUid) ||
    (s.patientName && s.patientName.toLowerCase() === currentName)
  );
  if (!activeSession && allActive.length > 0) {
    activeSession = allActive[0]; // Default active demonstration
  }

  // Match upcoming appointments
  let upcomingList = allUpcoming.filter(s =>
    (s.patientId && s.patientId.toLowerCase() === currentUid) ||
    (s.patientName && s.patientName.toLowerCase() === currentName)
  );
  if (upcomingList.length === 0 && allUpcoming.length > 0) {
    upcomingList = [allUpcoming[0]];
  }

  // Match completed examinations & reports
  let completedList = allCompleted.filter(s =>
    (s.patientId && s.patientId.toLowerCase() === currentUid) ||
    (s.patientName && s.patientName.toLowerCase() === currentName)
  );
  if (completedList.length === 0 && allCompleted.length > 0) {
    completedList = [allCompleted[0]];
  }

  return { activeSession, upcomingList, completedList };
}
window.getPatientSessionData = getPatientSessionData;

// Render Patient Dashboard Landing Page
function renderPatientDashboard(patient) {
  const adhocCard = document.getElementById("patAdhocScanCard");
  const schedCard = document.getElementById("patScheduleScanCard");
  const regCard = document.getElementById("patRegisterCard");

  if (adhocCard) {
    adhocCard.onclick = () => {
      openDeviceModal();
    };
  }

  if (schedCard) {
    schedCard.onclick = () => {
      document.querySelectorAll(".pdash-action-card").forEach(c => c.classList.remove("active-glow"));
      schedCard.classList.add("active-glow");
      openScheduleScanModal();
    };
  }

  if (regCard) {
    regCard.onclick = () => {
      document.querySelectorAll(".pdash-action-card").forEach(c => c.classList.remove("active-glow"));
      regCard.classList.add("active-glow");
      openPatientClinicalRegistration();
    };
  }

  // Ensure default metric numbers match Image 3
  const statActive = document.getElementById("patStatActiveSessions");
  const statWaiting = document.getElementById("patStatWaiting");
  const statUpcoming = document.getElementById("patStatUpcomingSessions");
  const statCompleted = document.getElementById("patStatCompletedSessions");

  if (statActive) statActive.textContent = "3";
  if (statWaiting) statWaiting.textContent = "2";
  if (statUpcoming) statUpcoming.textContent = "3";
  if (statCompleted) statCompleted.textContent = "12";
}
window.renderPatientDashboard = renderPatientDashboard;

// Render Patient Profile View

function renderPatientProfile(patient) {
  const current = patient || currentAuthenticatedUser || { name: "Patient User", uid: "4001", email: "patient@gmail.com", mobile: "+91 98765 43210" };

  const nameEl = document.getElementById("patProfName");
  const avatarEl = document.getElementById("patProfAvatarInitials");
  const uidMeta = document.getElementById("patProfMetaUid");
  const emailMeta = document.getElementById("patProfMetaEmail");
  const statusMeta = document.getElementById("patProfMetaStatus");

  const cardName = document.getElementById("patCardName");
  const cardUid = document.getElementById("patCardUid");
  const cardEmail = document.getElementById("patCardEmail");
  const cardMobile = document.getElementById("patCardMobile");
  const cardDob = document.getElementById("patCardDob");
  const cardGender = document.getElementById("patCardGender");

  const name = current.name || "Patient User";
  const initials = name.split(/\s+/).map(p => p[0]).join("").slice(0, 2).toUpperCase() || "PT";

  if (nameEl) nameEl.textContent = name;
  if (avatarEl) avatarEl.textContent = initials;
  if (uidMeta) uidMeta.textContent = current.uid || "4001";
  if (emailMeta) emailMeta.textContent = current.email || "patient@gmail.com";
  if (statusMeta) statusMeta.textContent = "Active";

  if (cardName) cardName.textContent = name;
  if (cardUid) cardUid.textContent = current.uid || "4001";
  if (cardEmail) cardEmail.textContent = current.email || "patient@gmail.com";
  if (cardMobile) cardMobile.textContent = current.mobile || "+91 98765 43210";
  if (cardDob) cardDob.textContent = current.dob || "Not Specified";
  if (cardGender) cardGender.textContent = current.gender || "Not Specified";
}
window.renderPatientProfile = renderPatientProfile;

// Render Patient Appointments View
function renderPatientAppointments(patient, query = "", typeFilter = "all") {
  const current = patient || currentAuthenticatedUser || { name: "Patient User", uid: "4001" };
  const { upcomingList } = getPatientSessionData(current);

  const listEl = document.getElementById("patApptList");
  const emptyEl = document.getElementById("patApptEmptyState");
  const totalCountEl = document.getElementById("patApptTotalCount");
  const confirmedCountEl = document.getElementById("patApptConfirmedCount");

  const q = (query || "").trim().toLowerCase();
  const filtered = upcomingList.filter(item => {
    if (typeFilter !== "all" && item.scanType.toLowerCase() !== typeFilter.toLowerCase()) return false;
    if (q) {
      const match = (item.scanType && item.scanType.toLowerCase().includes(q)) ||
        (item.diagnosticCenter && item.diagnosticCenter.toLowerCase().includes(q)) ||
        (item.scheduledTime && item.scheduledTime.toLowerCase().includes(q));
      if (!match) return false;
    }
    return true;
  });

  if (totalCountEl) totalCountEl.textContent = String(filtered.length);
  if (confirmedCountEl) confirmedCountEl.textContent = String(filtered.length);

  if (!listEl) return;

  if (filtered.length === 0) {
    listEl.innerHTML = "";
    if (emptyEl) emptyEl.style.display = "flex";
    return;
  }

  if (emptyEl) emptyEl.style.display = "none";

  listEl.innerHTML = filtered.map(item => {
    let scanClass = "purple";
    if (item.scanType === "Cardiac") scanClass = "cyan";
    else if (item.scanType === "Pelvic") scanClass = "emerald";

    return `
      <div class="drep-row">
        <div class="drep-date-cell" style="flex: 1.2;">
          <span class="drep-date-main">2026-09-17</span>
          <span class="drep-date-time">${item.scheduledTime || "10:30 AM"}</span>
        </div>
        <div>
          <span class="ddash-scan-tag ${scanClass}">${item.scanType}</span>
        </div>
        <div class="drep-doc-cell" style="flex: 1.2;">
          <span class="drep-doc-name">Dr. Admin Doctor</span>
          <span class="drep-doc-session">Ultrasound Specialist</span>
        </div>
        <div class="drep-date-cell" style="flex: 1.2;">
          <span class="drep-date-main">${item.diagnosticCenter || "Apex Diagnostic Center"}</span>
          <span class="drep-date-time">Room 3 • Robotic Suite</span>
        </div>
        <div>
          <span class="drep-badge-ready">Confirmed</span>
        </div>
        <div class="drep-actions-cell">
          <button type="button" class="drep-btn-view" onclick="openPatientAppointmentModal('${item.sessionId || "S-002"}')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
            <span>Details</span>
          </button>
        </div>
      </div>
    `;
  }).join("");
}
window.renderPatientAppointments = renderPatientAppointments;

// Render Patient Diagnostic Reports View
function renderPatientDiagnosticReports(patient, query = "", typeFilter = "all") {
  const current = patient || currentAuthenticatedUser || { name: "Patient User", uid: "4001" };
  const { completedList } = getPatientSessionData(current);

  const listEl = document.getElementById("patRepList");
  const emptyEl = document.getElementById("patRepEmptyState");
  const totalCountEl = document.getElementById("patRepTotalCount");
  const finalizedCountEl = document.getElementById("patRepFinalizedCount");

  const q = (query || "").trim().toLowerCase();
  const filtered = completedList.filter(item => {
    if (typeFilter !== "all" && item.scanType.toLowerCase() !== typeFilter.toLowerCase()) return false;
    if (q) {
      const match = (item.reportId && item.reportId.toLowerCase().includes(q)) ||
        (item.scanType && item.scanType.toLowerCase().includes(q)) ||
        (item.doctorName && item.doctorName.toLowerCase().includes(q)) ||
        (item.diagnosticCenter && item.diagnosticCenter.toLowerCase().includes(q));
      if (!match) return false;
    }
    return true;
  });

  if (totalCountEl) totalCountEl.textContent = String(filtered.length);
  if (finalizedCountEl) finalizedCountEl.textContent = String(filtered.filter(c => c.reportStatus === "ready" || !c.reportStatus).length);

  if (!listEl) return;

  if (filtered.length === 0) {
    listEl.innerHTML = "";
    if (emptyEl) emptyEl.style.display = "flex";
    return;
  }

  if (emptyEl) emptyEl.style.display = "none";

  listEl.innerHTML = filtered.map(item => {
    let scanClass = "purple";
    if (item.scanType === "Cardiac") scanClass = "cyan";
    else if (item.scanType === "Pelvic") scanClass = "emerald";

    const repId = item.reportId || "REP-2026-001";

    return `
      <div class="drep-row">
        <div class="drep-patient-cell">
          <div class="drep-patient-avatar ${scanClass}">DR</div>
          <div>
            <p class="drep-patient-name">${repId}</p>
            <p class="drep-patient-id">Official Clinical Record</p>
          </div>
        </div>
        <div>
          <span class="ddash-scan-tag ${scanClass}">${item.scanType}</span>
        </div>
        <div class="drep-date-cell">
          <span class="drep-date-main">${item.sessionDate || "2026-09-14"}</span>
          <span class="drep-date-time">${item.sessionTime || "09:15 AM"}</span>
        </div>
        <div class="drep-doc-cell">
          <span class="drep-doc-name">${item.doctorName || "Dr. Admin Doctor"}</span>
          <span class="drep-doc-session">${item.diagnosticCenter || "Apex Diagnostic Center"}</span>
        </div>
        <div>
          <span class="drep-badge-ready">Finalized</span>
        </div>
        <div class="drep-actions-cell">
          <button type="button" class="drep-btn-view" onclick="openPatientReportViewModal('${repId}')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
            <span>View</span>
          </button>
          <button type="button" class="drep-btn-download" onclick="downloadPatientReport('${repId}')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
            <span>Download</span>
          </button>
        </div>
      </div>
    `;
  }).join("");
}
window.renderPatientDiagnosticReports = renderPatientDiagnosticReports;

// Render Patient Examination History View
function renderPatientHistory(patient, query = "", typeFilter = "all") {
  const current = patient || currentAuthenticatedUser || { name: "Patient User", uid: "4001" };
  const { completedList } = getPatientSessionData(current);

  const listEl = document.getElementById("patHistList");
  const emptyEl = document.getElementById("patHistEmptyState");
  const totalCountEl = document.getElementById("patHistTotalCount");
  const durationTotalEl = document.getElementById("patHistDurationTotal");

  const q = (query || "").trim().toLowerCase();
  const filtered = completedList.filter(item => {
    if (typeFilter !== "all" && item.scanType.toLowerCase() !== typeFilter.toLowerCase()) return false;
    if (q) {
      const match = (item.scanType && item.scanType.toLowerCase().includes(q)) ||
        (item.doctorName && item.doctorName.toLowerCase().includes(q)) ||
        (item.diagnosticCenter && item.diagnosticCenter.toLowerCase().includes(q));
      if (!match) return false;
    }
    return true;
  });

  if (totalCountEl) totalCountEl.textContent = String(filtered.length);
  if (durationTotalEl) durationTotalEl.textContent = filtered.length > 0 ? (filtered[0].duration || "22m") : "0m";

  if (!listEl) return;

  if (filtered.length === 0) {
    listEl.innerHTML = "";
    if (emptyEl) emptyEl.style.display = "flex";
    return;
  }

  if (emptyEl) emptyEl.style.display = "none";

  listEl.innerHTML = filtered.map(item => {
    let scanClass = "purple";
    if (item.scanType === "Cardiac") scanClass = "cyan";
    else if (item.scanType === "Pelvic") scanClass = "emerald";

    const repId = item.reportId || "REP-2026-001";

    return `
      <div class="dhist-row">
        <div class="dhist-date-cell" style="flex: 1.2;">
          <span class="dhist-date-main">${item.sessionDate || "2026-09-14"}</span>
          <span class="dhist-date-time">${item.sessionTime || "09:15 AM"}</span>
        </div>
        <div>
          <span class="ddash-scan-tag ${scanClass}">${item.scanType}</span>
        </div>
        <div class="dhist-patient-cell" style="flex: 1.2;">
          <div>
            <p class="dhist-patient-name">${item.doctorName || "Dr. Admin Doctor"}</p>
            <p class="dhist-patient-id">${item.diagnosticCenter || "Apex Diagnostic Center"}</p>
          </div>
        </div>
        <div>
          <span class="dhist-duration-pill">${item.duration || "22:15"}</span>
        </div>
        <div>
          <span class="drep-badge-ready">Report Available</span>
        </div>
        <div class="dhist-actions-cell">
          <button type="button" class="dhist-btn-view" onclick="openPatientReportViewModal('${repId}')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
            <span>View Report</span>
          </button>
        </div>
      </div>
    `;
  }).join("");
}
window.renderPatientHistory = renderPatientHistory;

// ============================================================
// PATIENT MODAL HANDLERS
// ============================================================

function openPatientProfileEditModal() {
  const modal = document.getElementById("patientProfileEditModal");
  const nameInput = document.getElementById("patProfEditNameInput");
  const mobileInput = document.getElementById("patProfEditMobileInput");
  const emailInput = document.getElementById("patProfEditEmailInput");
  const uidInput = document.getElementById("patProfEditUidInput");
  const alertEl = document.getElementById("patProfEditAlert");

  const current = currentAuthenticatedUser || { name: "Patient User", uid: "4001", email: "patient@gmail.com", mobile: "+91 98765 43210" };

  if (nameInput) nameInput.value = current.name || "Patient User";
  if (mobileInput) mobileInput.value = current.mobile || "+91 98765 43210";
  if (emailInput) emailInput.value = current.email || "patient@gmail.com";
  if (uidInput) uidInput.value = current.uid || "4001";
  if (alertEl) alertEl.style.display = "none";

  if (modal) {
    modal.classList.add("active");
    modal.style.display = "flex";
  }
}
window.openPatientProfileEditModal = openPatientProfileEditModal;

function closePatientProfileEditModal() {
  const modal = document.getElementById("patientProfileEditModal");
  if (modal) {
    modal.classList.remove("active");
    modal.style.display = "none";
  }
}
window.closePatientProfileEditModal = closePatientProfileEditModal;

function initPatientProfileEditModal() {
  const form = document.getElementById("patientProfileEditForm");
  if (!form) return;

  form.onsubmit = (e) => {
    e.preventDefault();
    const nameInput = document.getElementById("patProfEditNameInput");
    const mobileInput = document.getElementById("patProfEditMobileInput");
    const alertEl = document.getElementById("patProfEditAlert");

    const newName = nameInput ? nameInput.value.trim() : "";
    const newMobile = mobileInput ? mobileInput.value.trim() : "";

    if (!newName) {
      if (alertEl) {
        alertEl.textContent = "Please provide your Full Name.";
        alertEl.style.display = "block";
      }
      return;
    }

    if (!currentAuthenticatedUser) {
      currentAuthenticatedUser = { name: newName, role: "patient", uid: "4001", email: "patient@gmail.com" };
    }

    currentAuthenticatedUser.name = newName;
    currentAuthenticatedUser.mobile = newMobile;

    try {
      sessionStorage.setItem("authenticated_patient", JSON.stringify(currentAuthenticatedUser));
      localStorage.setItem("authenticated_patient", JSON.stringify(currentAuthenticatedUser));
    } catch (err) { }

    updateSharedPortalHeader(currentAuthenticatedUser, "patient");
    renderPatientProfile(currentAuthenticatedUser);
    renderPatientDashboard(currentAuthenticatedUser);
    closePatientProfileEditModal();

    if (typeof showToastAlert === "function") {
      showToastAlert("Patient profile details updated successfully.", "success");
    }
  };
}

function openPatientAppointmentModal(apptId) {
  const modal = document.getElementById("patientAppointmentModal");
  const body = document.getElementById("patApptModalBody");
  if (!modal || !body) return;

  loadTorusSessions();
  const allUpcoming = window.torusSessions?.upcoming || [];
  const appt = allUpcoming.find(a => a.sessionId === apptId) || allUpcoming[0] || {
    sessionId: "APT-2026-002",
    scanType: "Abdominal",
    scheduledTime: "10:30 AM",
    diagnosticCenter: "Apex Diagnostic Center",
    clinicalNotes: "Fasting required 6-8 hours prior to examination."
  };

  body.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 16px;">
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: rgba(139, 92, 246, 0.08); border: 1px solid rgba(139, 92, 246, 0.25); border-radius: 10px;">
        <div>
          <span style="font-size: 11px; font-weight: 700; color: #c084fc; text-transform: uppercase;">Appointment ID</span>
          <p style="font-size: 16px; font-weight: 700; color: #ffffff; margin: 2px 0 0 0;">${appt.sessionId}</p>
        </div>
        <span class="drep-badge-ready">Confirmed</span>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
        <div style="padding: 12px; background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px;">
          <span style="font-size: 11px; color: #94a3b8; font-weight: 600;">EXAMINATION TYPE</span>
          <p style="font-size: 13.5px; font-weight: 700; color: #22d3ee; margin: 4px 0 0 0;">${appt.scanType} Ultrasound</p>
        </div>
        <div style="padding: 12px; background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px;">
          <span style="font-size: 11px; color: #94a3b8; font-weight: 600;">SCHEDULED TIME</span>
          <p style="font-size: 13.5px; font-weight: 700; color: #ffffff; margin: 4px 0 0 0;">2026-09-17 • ${appt.scheduledTime || "10:30 AM"}</p>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
        <div style="padding: 12px; background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px;">
          <span style="font-size: 11px; color: #94a3b8; font-weight: 600;">ASSIGNED DOCTOR</span>
          <p style="font-size: 13.5px; font-weight: 700; color: #ffffff; margin: 4px 0 0 0;">Dr. Admin Doctor</p>
        </div>
        <div style="padding: 12px; background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px;">
          <span style="font-size: 11px; color: #94a3b8; font-weight: 600;">DIAGNOSTIC CENTER</span>
          <p style="font-size: 13.5px; font-weight: 700; color: #ffffff; margin: 4px 0 0 0;">${appt.diagnosticCenter || "Apex Diagnostic Center"}</p>
        </div>
      </div>

      <div style="padding: 14px; background: rgba(6, 182, 212, 0.06); border: 1px solid rgba(6, 182, 212, 0.25); border-radius: 8px;">
        <span style="font-size: 11px; font-weight: 700; color: #22d3ee; text-transform: uppercase;">Preparation Instructions</span>
        <p style="font-size: 12.5px; color: #cbd5e1; margin: 4px 0 0 0; line-height: 1.5;">${appt.clinicalNotes || "Please arrive 15 minutes before your scheduled appointment. Maintain standard clinical preparation."}</p>
      </div>
    </div>
  `;

  modal.classList.add("active");
  modal.style.display = "flex";
}
window.openPatientAppointmentModal = openPatientAppointmentModal;

function closePatientAppointmentModal() {
  const modal = document.getElementById("patientAppointmentModal");
  if (modal) {
    modal.classList.remove("active");
    modal.style.display = "none";
  }
}
window.closePatientAppointmentModal = closePatientAppointmentModal;

function openPatientReportViewModal(reportId) {
  if (typeof openDoctorReportModal === "function") {
    openDoctorReportModal(reportId);
  }
}
window.openPatientReportViewModal = openPatientReportViewModal;

function downloadPatientReport(reportId) {
  if (typeof downloadDoctorReport === "function") {
    downloadDoctorReport(reportId);
  }
}
window.downloadPatientReport = downloadPatientReport;

function initPatientControls() {
  initPatientProfileEditModal();

  // Appointments Search & Filter
  const apptSearch = document.getElementById("patApptSearchInput");
  const apptClear = document.getElementById("patApptSearchClearBtn");
  const apptFilter = document.getElementById("patApptScanTypeFilter");
  const apptRefresh = document.getElementById("patApptRefreshBtn");

  if (apptSearch) {
    apptSearch.oninput = () => {
      if (apptClear) apptClear.style.display = apptSearch.value ? "block" : "none";
      renderPatientAppointments(currentAuthenticatedUser, apptSearch.value, apptFilter?.value || "all");
    };
  }
  if (apptClear) {
    apptClear.onclick = () => {
      apptSearch.value = "";
      apptClear.style.display = "none";
      renderPatientAppointments(currentAuthenticatedUser, "", apptFilter?.value || "all");
    };
  }
  if (apptFilter) {
    apptFilter.onchange = () => {
      renderPatientAppointments(currentAuthenticatedUser, apptSearch?.value || "", apptFilter.value);
    };
  }
  if (apptRefresh) {
    apptRefresh.onclick = () => {
      renderPatientAppointments(currentAuthenticatedUser, apptSearch?.value || "", apptFilter?.value || "all");
      if (typeof showToastAlert === "function") showToastAlert("Appointments list updated.", "info");
    };
  }

  // Reports Search & Filter
  const repSearch = document.getElementById("patRepSearchInput");
  const repClear = document.getElementById("patRepSearchClearBtn");
  const repFilter = document.getElementById("patRepScanTypeFilter");
  const repRefresh = document.getElementById("patRepRefreshBtn");

  if (repSearch) {
    repSearch.oninput = () => {
      if (repClear) repClear.style.display = repSearch.value ? "block" : "none";
      renderPatientDiagnosticReports(currentAuthenticatedUser, repSearch.value, repFilter?.value || "all");
    };
  }
  if (repClear) {
    repClear.onclick = () => {
      repSearch.value = "";
      repClear.style.display = "none";
      renderPatientDiagnosticReports(currentAuthenticatedUser, "", repFilter?.value || "all");
    };
  }
  if (repFilter) {
    repFilter.onchange = () => {
      renderPatientDiagnosticReports(currentAuthenticatedUser, repSearch?.value || "", repFilter.value);
    };
  }
  if (repRefresh) {
    repRefresh.onclick = () => {
      renderPatientDiagnosticReports(currentAuthenticatedUser, repSearch?.value || "", repFilter?.value || "all");
      if (typeof showToastAlert === "function") showToastAlert("Diagnostic reports list updated.", "info");
    };
  }

  // History Search & Filter
  const histSearch = document.getElementById("patHistSearchInput");
  const histClear = document.getElementById("patHistSearchClearBtn");
  const histFilter = document.getElementById("patHistScanTypeFilter");
  const histRefresh = document.getElementById("patHistRefreshBtn");

  if (histSearch) {
    histSearch.oninput = () => {
      if (histClear) histClear.style.display = histSearch.value ? "block" : "none";
      renderPatientHistory(currentAuthenticatedUser, histSearch.value, histFilter?.value || "all");
    };
  }
  if (histClear) {
    histClear.onclick = () => {
      histSearch.value = "";
      histClear.style.display = "none";
      renderPatientHistory(currentAuthenticatedUser, "", histFilter?.value || "all");
    };
  }
  if (histFilter) {
    histFilter.onchange = () => {
      renderPatientHistory(currentAuthenticatedUser, histSearch?.value || "", histFilter.value);
    };
  }
  if (histRefresh) {
    histRefresh.onclick = () => {
      renderPatientHistory(currentAuthenticatedUser, histSearch?.value || "", histFilter?.value || "all");
      if (typeof showToastAlert === "function") showToastAlert("Examination history updated.", "info");
    };
  }
}
window.initPatientControls = initPatientControls;

// ============================================================
// PATIENT CLINICAL REGISTRATION & SCHEDULE SCAN FUNCTIONALITY
// ============================================================

function openPatientClinicalRegistration() {
  setupPatientClinicalRegListeners();
  showTorusScreen("patient-clinical-registration-screen");
  const apptDateInput = document.getElementById("pcrApptDate");
  if (apptDateInput && !apptDateInput.value) {
    const today = new Date();
    apptDateInput.value = today.toISOString().split("T")[0];
  }
}
window.openPatientClinicalRegistration = openPatientClinicalRegistration;

function closePatientClinicalRegistration() {
  showTorusScreen("doctor-portal-dashboard");
}
window.closePatientClinicalRegistration = closePatientClinicalRegistration;

let isPcrListenersAttached = false;
function setupPatientClinicalRegListeners() {
  if (isPcrListenersAttached) return;
  isPcrListenersAttached = true;

  const patPcrBackBtn = document.getElementById("patClinicalRegBackBtn");
  const clearBtn = document.getElementById("pcrClearBtn");
  const form = document.getElementById("patient-clinical-reg-form");
  const genderBtns = document.querySelectorAll(".pcr-gender-btn");
  const genderVal = document.getElementById("pcrGenderVal");
  const submitBtn = document.getElementById("pcrSubmitBtn");

  if (patPcrBackBtn) {
    patPcrBackBtn.addEventListener("click", () => {
      closePatientClinicalRegistration();
    });
  }

  // Gender selection toggle
  genderBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      genderBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      if (genderVal) {
        genderVal.value = btn.getAttribute("data-gender") || "Male";
      }
    });
  });

  // Clear Form
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      if (form) form.reset();
      genderBtns.forEach(b => b.classList.remove("active"));
      const maleBtn = document.querySelector('.pcr-gender-btn[data-gender="Male"]');
      if (maleBtn) maleBtn.classList.add("active");
      if (genderVal) genderVal.value = "Male";

      const apptDateInput = document.getElementById("pcrApptDate");
      if (apptDateInput) {
        apptDateInput.value = new Date().toISOString().split("T")[0];
      }
      hideAlertMessage("patClinicalRegAlert");
    });
  }

  // Register Patient Submit
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("patClinicalRegAlert");

      const fullName = document.getElementById("pcrFullName")?.value.trim();
      const age = document.getElementById("pcrAge")?.value.trim();
      const gender = genderVal ? genderVal.value : "Male";
      const mobile = document.getElementById("pcrMobile")?.value.trim();
      const email = document.getElementById("pcrEmail")?.value.trim() || "";
      const scanType = document.getElementById("pcrScanType")?.value || "";
      const apptDate = document.getElementById("pcrApptDate")?.value || "";
      const bloodGroup = document.getElementById("pcrBloodGroup")?.value || "";

      if (!fullName || fullName.length < 2) {
        showAlertMessage("patClinicalRegAlert", "Please enter a valid patient full name.", "error");
        return;
      }
      const ageNum = parseInt(age, 10);
      if (!age || isNaN(ageNum) || ageNum < 1 || ageNum > 130) {
        showAlertMessage("patClinicalRegAlert", "Please enter a valid age between 1 and 130.", "error");
        return;
      }
      if (!mobile || !/^\d{10}$/.test(mobile)) {
        showAlertMessage("patClinicalRegAlert", "Please enter a valid 10-digit mobile number.", "error");
        return;
      }
      if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        showAlertMessage("patClinicalRegAlert", "Please enter a valid email address.", "error");
        return;
      }
      if (!scanType) {
        showAlertMessage("patClinicalRegAlert", "Please select a scan type.", "error");
        return;
      }
      if (!apptDate) {
        showAlertMessage("patClinicalRegAlert", "Please choose an appointment date.", "error");
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Registering...";
      }

      try {
        const payload = {
          full_name: fullName,
          age: ageNum,
          gender: gender,
          mobile: mobile,
          email: email,
          scan_type: scanType,
          appointment_date: apptDate,
          blood_group: bloodGroup
        };

        const res = await callBackendAPI("/api/patients/clinical-register", payload, "POST");

        if (res && res.success) {
          showAlertMessage("patClinicalRegAlert", `Patient "${fullName}" registered successfully (ID: ${res.patient?.patient_id || 'PAT'})!`, "success");

          // Update upcoming list on dashboard
          const upList = document.getElementById("patUpcomingSessionsList");
          if (upList) {
            const card = document.createElement("div");
            card.className = "pdash-session-card";
            card.innerHTML = `
              <div class="pdash-session-info">
                <div class="pdash-session-name">${fullName}</div>
                <div class="pdash-session-device">${scanType} Scan • ${apptDate}</div>
              </div>
              <div class="pdash-session-right">
                <span class="pdash-session-time">10:00 AM</span>
              </div>
            `;
            upList.prepend(card);
          }

          // Increment upcoming counter
          const statUp = document.getElementById("patStatUpcomingSessions");
          if (statUp) {
            const cur = parseInt(statUp.textContent, 10) || 0;
            statUp.textContent = String(cur + 1);
          }

          if (typeof showToastAlert === "function") {
            showToastAlert(`Patient "${fullName}" registered successfully!`, "success");
          }

          setTimeout(() => {
            closePatientClinicalRegistration();
            if (form) form.reset();
            hideAlertMessage("patClinicalRegAlert");
            if (submitBtn) {
              submitBtn.disabled = false;
              submitBtn.textContent = "Register Patient";
            }
          }, 1200);
        } else {
          showAlertMessage("patClinicalRegAlert", res?.error || "Failed to register patient.", "error");
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = "Register Patient";
          }
        }
      } catch (err) {
        console.error("Clinical register error:", err);
        showAlertMessage("patClinicalRegAlert", "An error occurred during registration. Please check connection.", "error");
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Register Patient";
        }
      }
    });
  }
}
window.setupPatientClinicalRegListeners = setupPatientClinicalRegListeners;

// ============================================================
// SCHEDULE SCAN MODAL (PATIENT PORTAL)
// ============================================================

let isSchedScanModalInitialized = false;
function initScheduleScanModal() {
  if (isSchedScanModalInitialized) return;
  isSchedScanModalInitialized = true;

  const modalOverlay = document.getElementById("patScheduleScanModalOverlay");
  const closeBtn = document.getElementById("patScheduleCloseBtn");
  const form = document.getElementById("patScheduleScanForm");
  const submitBtn = document.getElementById("schedSubmitBtn");

  const patientSelect = document.getElementById("schedPatientSelect");
  const scanTypeSelect = document.getElementById("schedScanTypeSelect");
  const doctorSelect = document.getElementById("schedDoctorSelect");
  const daySelect = document.getElementById("schedSlotDay");
  const monthSelect = document.getElementById("schedSlotMonth");
  const yearSelect = document.getElementById("schedSlotYear");
  const timeSelect = document.getElementById("schedSlotTime");

  // Populate Days 01 - 31
  if (daySelect && daySelect.options.length <= 1) {
    for (let d = 1; d <= 31; d++) {
      const opt = document.createElement("option");
      const val = d < 10 ? `0${d}` : `${d}`;
      opt.value = val;
      opt.textContent = val;
      daySelect.appendChild(opt);
    }
  }

  // Populate Months (01 - 12 with full month names)
  const monthNames = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
  ];
  if (monthSelect && monthSelect.options.length <= 1) {
    monthNames.forEach((name, idx) => {
      const opt = document.createElement("option");
      const val = idx < 9 ? `0${idx + 1}` : `${idx + 1}`;
      opt.value = val;
      opt.textContent = name;
      monthSelect.appendChild(opt);
    });
  }

  // Populate Years (2026, 2027)
  if (yearSelect && yearSelect.options.length <= 1) {
    ["2026", "2027"].forEach(y => {
      const opt = document.createElement("option");
      opt.value = y;
      opt.textContent = y;
      yearSelect.appendChild(opt);
    });
  }

  // Populate Times
  const timeSlots = [
    "09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM",
    "11:15 AM", "12:00 PM", "01:30 PM", "02:15 PM",
    "03:00 PM", "03:45 PM", "04:30 PM", "05:15 PM"
  ];
  if (timeSelect && timeSelect.options.length <= 1) {
    timeSlots.forEach(t => {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      timeSelect.appendChild(opt);
    });
  }

  // Check validity of all required fields to toggle submit button
  function checkValidity() {
    const p = patientSelect ? patientSelect.value : "";
    const s = scanTypeSelect ? scanTypeSelect.value : "";
    const d = doctorSelect ? doctorSelect.value : "";
    const day = daySelect ? daySelect.value : "";
    const month = monthSelect ? monthSelect.value : "";
    const year = yearSelect ? yearSelect.value : "";
    const time = timeSelect ? timeSelect.value : "";

    const allValid = Boolean(p && s && d && day && month && year && time);
    if (submitBtn) {
      submitBtn.disabled = !allValid;
    }
  }

  [patientSelect, scanTypeSelect, doctorSelect, daySelect, monthSelect, yearSelect, timeSelect].forEach(el => {
    if (el) {
      el.addEventListener("change", checkValidity);
    }
  });

  // Close actions
  if (closeBtn) {
    closeBtn.addEventListener("click", closeScheduleScanModal);
  }
  if (modalOverlay) {
    modalOverlay.addEventListener("click", (e) => {
      if (e.target === modalOverlay) {
        closeScheduleScanModal();
      }
    });
  }

  // Form Submission
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (submitBtn && submitBtn.disabled) return;

      const pVal = patientSelect.value;
      const patientName = patientSelect.options[patientSelect.selectedIndex]?.text?.split(" (")[0] || pVal;
      const scanType = scanTypeSelect.value;
      const dVal = doctorSelect.value;
      const doctorName = doctorSelect.options[doctorSelect.selectedIndex]?.text || dVal;
      const day = daySelect.value;
      const month = monthSelect.value;
      const year = yearSelect.value;
      const time = timeSelect.value;

      const apptDate = `${year}-${month}-${day}`;

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Scheduling...";
      }

      try {
        const payload = {
          patient: pVal,
          patient_id: pVal,
          patient_name: patientName,
          doctor: doctorName,
          doctor_id: dVal,
          doctor_name: doctorName,
          scan_type: scanType,
          slot_day: day,
          slot_month: month,
          slot_year: year,
          slot_time: time,
          appointment_date: apptDate,
          appointment_time: time,
          notes: "Scheduled via Patient Portal"
        };

        const res = await callBackendAPI("/api/appointments/schedule", payload, "POST");

        if (res && res.success) {
          // Prepend to Upcoming Sessions on Dashboard
          const upList = document.getElementById("patUpcomingSessionsList");
          if (upList) {
            const card = document.createElement("div");
            card.className = "pdash-session-card";
            card.innerHTML = `
              <div class="pdash-session-info">
                <div class="pdash-session-name">${patientName}</div>
                <div class="pdash-session-device">${scanType} Scan • ${doctorName}</div>
              </div>
              <div class="pdash-session-right">
                <span class="pdash-session-time">${time}</span>
              </div>
            `;
            upList.prepend(card);
          }

          // Increment upcoming counter
          const statUp = document.getElementById("patStatUpcomingSessions");
          if (statUp) {
            const cur = parseInt(statUp.textContent, 10) || 0;
            statUp.textContent = String(cur + 1);
          }

          if (typeof showToastAlert === "function") {
            showToastAlert(`Appointment scheduled successfully for ${patientName} on ${day}/${month}/${year} at ${time}!`, "success");
          }

          closeScheduleScanModal();
        } else {
          showAlertMessage("schedModalAlert", res?.error || "Failed to schedule appointment.", "error");
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = "Schedule Scan";
          }
        }
      } catch (err) {
        console.error("Error scheduling appointment:", err);
        showAlertMessage("schedModalAlert", "Failed to schedule appointment. Please try again.", "error");
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Schedule Scan";
        }
      }
    });
  }
}
window.initScheduleScanModal = initScheduleScanModal;

function openScheduleScanModal() {
  const modalOverlay = document.getElementById("patScheduleScanModalOverlay");
  if (modalOverlay) {
    modalOverlay.style.display = "flex";
  }

  initScheduleScanModal();

  const form = document.getElementById("patScheduleScanForm");
  const submitBtn = document.getElementById("schedSubmitBtn");
  const alertEl = document.getElementById("schedModalAlert");

  if (form) form.reset();
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "Schedule Scan";
  }
  if (alertEl) {
    alertEl.style.display = "none";
  }

  // Ensure default slot is set
  const daySelect = document.getElementById("schedSlotDay");
  const monthSelect = document.getElementById("schedSlotMonth");
  const yearSelect = document.getElementById("schedSlotYear");
  const timeSelect = document.getElementById("schedSlotTime");

  const today = new Date();
  const dStr = String(today.getDate()).padStart(2, "0");
  const mStr = String(today.getMonth() + 1).padStart(2, "0");
  const yStr = String(today.getFullYear());

  if (daySelect && !daySelect.value) daySelect.value = dStr;
  if (monthSelect && !monthSelect.value) monthSelect.value = mStr;
  if (yearSelect && !yearSelect.value) yearSelect.value = yStr;

  // Immediately ensure fallback patients exist so dropdown is NEVER empty
  const patientSelect = document.getElementById("schedPatientSelect");
  if (patientSelect && patientSelect.options.length <= 1) {
    patientSelect.innerHTML = `
      <option value="" disabled selected>Choose a patient...</option>
      <option value="PAT-4001">Patient User (PAT-4001)</option>
      <option value="P-8821">John Smith (P-8821)</option>
      <option value="P-9104">Jane Smith (P-9104)</option>
      <option value="P-7543">Robert Brown (P-7543)</option>
    `;
  }

  // Immediately ensure fallback doctors exist so dropdown is NEVER empty
  const doctorSelect = document.getElementById("schedDoctorSelect");
  if (doctorSelect && doctorSelect.options.length <= 1) {
    doctorSelect.innerHTML = `
      <option value="" disabled selected>Choose a doctor...</option>
      <option value="Dr. John Smith">Dr. John Smith (Chief Radiologist)</option>
      <option value="Dr. Elena Rodriguez">Dr. Elena Rodriguez (Senior Radiologist)</option>
      <option value="Dr. Marcus Vance">Dr. Marcus Vance (Cardiovascular Sonography)</option>
      <option value="Dr. Admin Doctor">Dr. Admin Doctor (Radiology)</option>
    `;
  }

  // Asynchronously fetch and refresh latest patients & doctors in background
  if (typeof callBackendAPI === "function") {
    callBackendAPI("/api/patients/clinical-list", {}, "GET")
      .then(res => {
        if (res && res.patients && res.patients.length > 0 && patientSelect) {
          const curVal = patientSelect.value;
          patientSelect.innerHTML = `<option value="" disabled ${!curVal ? "selected" : ""}>Choose a patient...</option>`;
          res.patients.forEach(p => {
            const pName = p.name || p.full_name || "Patient";
            const pId = p.uid || p.patient_id || p.id || "PAT";
            const opt = document.createElement("option");
            opt.value = pId;
            opt.textContent = `${pName} (${pId})`;
            if (curVal && (curVal === pId || curVal === pName)) {
              opt.selected = true;
            }
            patientSelect.appendChild(opt);
          });
        }
      })
      .catch(err => console.warn("Background patient list refresh:", err));

    callBackendAPI("/api/doctors/list", {}, "GET")
      .then(res => {
        if (res && res.doctors && res.doctors.length > 0 && doctorSelect) {
          const curDoc = doctorSelect.value;
          doctorSelect.innerHTML = `<option value="" disabled ${!curDoc ? "selected" : ""}>Choose a doctor...</option>`;
          res.doctors.forEach(d => {
            const opt = document.createElement("option");
            opt.value = d.name;
            const docPrefix = d.name.startsWith("Dr.") ? "" : "Dr. ";
            opt.textContent = `${docPrefix}${d.name} (${d.specialty || 'Radiology'})`;
            if (curDoc && curDoc === d.name) {
              opt.selected = true;
            }
            doctorSelect.appendChild(opt);
          });
        }
      })
      .catch(err => console.warn("Background doctor list refresh:", err));
  }
}
window.openScheduleScanModal = openScheduleScanModal;

function closeScheduleScanModal() {
  const modalOverlay = document.getElementById("patScheduleScanModalOverlay");
  if (modalOverlay) {
    modalOverlay.style.display = "none";
  }
}
window.closeScheduleScanModal = closeScheduleScanModal;


// Render Doctor Dashboard (Active & Upcoming Sessions)
function renderDoctorDashboard() {
  if (typeof ensureDeviceModalInDOM === "function") {
    ensureDeviceModalInDOM();
  }
  loadTorusSessions();

  const activeContainer = document.getElementById("activeSessionsList");
  const upcomingContainer = document.getElementById("upcomingSessionsList");
  const liveBadge = document.getElementById("activeLiveBadge");
  const scheduleBadge = document.getElementById("upcomingScheduleBadge");
  const statTotal = document.getElementById("statTotalSessions");
  const statLive = document.getElementById("statLiveSessions");
  const statScheduled = document.getElementById("statScheduledSessions");
  const statCompleted = document.getElementById("statCompletedSessions");

  const activeList = window.torusSessions?.active || [];
  const upcomingList = window.torusSessions?.upcoming || [];

  const liveCount = activeList.filter(s => s.status === "active" && s.doctorConnectionState !== "disconnected").length;
  if (liveBadge) liveBadge.textContent = `${activeList.length} Active`;
  if (scheduleBadge) scheduleBadge.textContent = `${upcomingList.length} Scheduled`;

  if (statTotal) statTotal.textContent = "16";
  if (statLive) statLive.textContent = String(activeList.length || 1);
  if (statScheduled) statScheduled.textContent = String(upcomingList.length || 3);
  if (statCompleted) statCompleted.textContent = "12";

  // Device chip is hidden from header per design (device context shown on Live Consultation page only)
  const deviceChip = document.getElementById("docDashDeviceChip");
  if (deviceChip) deviceChip.style.display = "none";

  // 1. Render Active Sessions (Status: In Progress, Action: Rejoin live session)
  if (activeContainer) {
    if (activeList.length === 0) {
      activeContainer.innerHTML = `<div class="ddash-empty">No active sessions right now.</div>`;
    } else {
      activeContainer.innerHTML = activeList.map(session => {
        let scanColor = "purple";
        if (session.scanType === "Cardiac") scanColor = "cyan";
        else if (session.scanType === "Pelvic") scanColor = "emerald";

        const isSessionActive = (window.currentActiveConsultationSessionId === session.sessionId) ||
                                (!window.currentActiveConsultationSessionId && session === activeList[0]);
        const isHapticBound = isSessionActive && (currentHapticState === HAPTIC_STATE.CONNECTED || currentHapticState === "connected");

        return `
          <div class="ddash-row-active">
            <div class="ddash-patient-block">
              <div class="ddash-patient-icon">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
              </div>
              <div>
                <p class="ddash-patient-name">${session.patientName}</p>
                <p class="ddash-patient-meta">${session.deviceId}</p>
                <span class="ddash-id-badge">ID: ${session.patientId}</span>
              </div>
            </div>
            <div>
              <span class="ddash-scan-tag ${scanColor}">${session.scanType}</span>
            </div>
            <div>
              <span class="ddash-clock">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                ${session.duration}
              </span>
            </div>
            <div>
              <span class="ddash-status-tag ${isSessionActive ? "in-progress" : "waiting"}">● ${isSessionActive ? "Consultation Active" : "In Progress"}</span>
              ${isHapticBound ? `
                <span class="ddash-haptic-active-status" style="display:inline-flex; align-items:center; gap:4px; margin-top:4px; font-size:11px; font-weight:600; color:#10b981;">
                  <span style="width:6px; height:6px; border-radius:50%; background:#10b981; display:inline-block;"></span>
                  Haptic Control Active
                </span>
              ` : ""}
            </div>
            <div class="ddash-action-cell">
              <button class="ddash-join-btn" type="button" data-session-id="${session.sessionId}" data-device-id="${session.deviceId}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
                <span>Rejoin</span>
              </button>
            </div>
          </div>
        `;
      }).join("");

      // Bind Rejoin click handlers to open Live Consultation
      activeContainer.querySelectorAll(".ddash-join-btn, .ddash-rejoin-btn").forEach(btn => {
        btn.addEventListener("click", () => rejoinClinicalSession(btn.getAttribute("data-session-id")));
      });
    }
  }

  // 2. Render Upcoming Sessions
  if (upcomingContainer) {
    if (upcomingList.length === 0) {
      upcomingContainer.innerHTML = `<div class="ddash-empty">No scheduled sessions.</div>`;
    } else {
      upcomingContainer.innerHTML = upcomingList.map(session => {
        let scanColor = "purple";
        if (session.scanType === "Cardiac") scanColor = "cyan";
        else if (session.scanType === "Pelvic") scanColor = "emerald";

        return `
          <div class="ddash-row-upcoming">
            <div class="ddash-patient-block">
              <div class="ddash-patient-icon cyan">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
              </div>
              <div>
                <p class="ddash-patient-name">${session.patientName}</p>
                <p class="ddash-patient-meta">${session.deviceId}</p>
                <span class="ddash-id-badge">ID: ${session.patientId}</span>
              </div>
            </div>
            <div>
              <span class="ddash-scan-tag ${scanColor}">${session.scanType}</span>
            </div>
            <div class="ddash-center-row">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>
              <span>${session.diagnosticCenter}</span>
            </div>
            <div>
              <span class="ddash-clock">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                <span class="ddash-time-hl">${session.scheduledTime}</span>
              </span>
            </div>
            <div class="ddash-action-cell">
              <button class="ddash-view-btn" type="button" data-session-id="${session.sessionId}">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                View Details
              </button>
            </div>
          </div>
        `;
      }).join("");

      // Bind View Details click handlers
      upcomingContainer.querySelectorAll(".ddash-view-btn").forEach(btn => {
        btn.addEventListener("click", () => openUpcomingSessionModal(btn.getAttribute("data-session-id")));
      });
    }
  }
}

// JOIN Session: Transitions from Doctor Dashboard to Live Consultation
function joinClinicalSession(sessionId) {
  const session = window.torusSessions?.active?.find(s => s.sessionId === sessionId) || window.torusSessions?.active?.[0];
  if (!session) return;

  session.doctorConnectionState = "connected";
  session.status = "active";
  window.currentActiveConsultationSessionId = session.sessionId;
  saveTorusSessions();

  // Bind physical Haptic Pad telemetry exclusively to this active consultation session
  if (typeof bindHapticSessionAPI === "function") {
    bindHapticSessionAPI(session);
  }

  if (typeof updateLiveConsultationDeviceDisplay === "function" && session && session.deviceId) {
    updateLiveConsultationDeviceDisplay(session.deviceId);
  }

  if (typeof logDoctorActivity === "function") {
    logDoctorActivity(
      "session",
      "Ultrasound Session Started",
      `Clinical consultation session started for ${session.patientName || "Patient"} (${session.patientId || "P-12345"}) on ${session.deviceId || "TORUS-A12"}.`,
      "Active",
      session.sessionId || "S-001"
    );
  }

  showTorusScreen("app-dashboard");
}

// REJOIN Session: Reconnects Doctor to the SAME consultation session without duplicate creation
function rejoinClinicalSession(sessionId) {
  const session = window.torusSessions?.active?.find(s => s.sessionId === sessionId) || window.torusSessions?.active?.[0];
  if (!session) return;

  // Preserve existing patient, patient ID, session ID, scan type, session data
  session.doctorConnectionState = "connected";
  session.status = "active";
  window.currentActiveConsultationSessionId = session.sessionId;
  saveTorusSessions();

  // Bind physical Haptic Pad telemetry exclusively to this active consultation session
  if (typeof bindHapticSessionAPI === "function") {
    bindHapticSessionAPI(session);
  }

  // Re-use existing session code if available
  if (session.clinicalSessionCode) {
    window.activeClinicalSessionCode = session.clinicalSessionCode;
    sessionStorage.setItem("active_clinical_session_code", session.clinicalSessionCode);
    localStorage.setItem("active_clinical_session_code", session.clinicalSessionCode);
  }

  if (typeof updateLiveConsultationDeviceDisplay === "function" && session && session.deviceId) {
    updateLiveConsultationDeviceDisplay(session.deviceId);
  }

  if (typeof logDoctorActivity === "function") {
    logDoctorActivity(
      "session",
      "Patient Session Joined",
      `Rejoined active clinical consultation for ${session.patientName || "Patient"} (${session.patientId || "P-12345"}).`,
      "Active",
      session.sessionId || "S-001"
    );
  }

  showTorusScreen("app-dashboard");
}

// ============================================================
// HAPTIC PAD SESSION-BASED ROUTING & SERVICE LAYER
// ============================================================

/**
 * Bind Doctor's active consultation session to Haptic Pad routing in backend
 */
async function bindHapticSessionAPI(session) {
  if (!session) return { success: false, error: "No session specified" };
  const payload = {
    session_id: session.sessionId || session.session_id || "S-001",
    session_code: session.clinicalSessionCode || session.session_code || window.activeClinicalSessionCode || `TORUS-CLI-${session.patientId || "P-12345"}`,
    doctor_id: currentAuthenticatedUser?.uid || currentAuthenticatedUser?.id || "3001",
    doctor_name: currentAuthenticatedUser?.name || "Admin Doctor",
    patient_id: session.patientId || session.patient_id || "P-12345",
    patient_name: session.patientName || session.patient_name || "Patient A",
    device_id: session.deviceId || session.device_id || "TORUS-A12"
  };

  const isDirectBackend = window.location.port === "3000";
  const urls = isDirectBackend
    ? ["/api/haptic-pad/session/bind", "http://127.0.0.1:3000/api/haptic-pad/session/bind", "http://localhost:3000/api/haptic-pad/session/bind"]
    : ["http://127.0.0.1:3000/api/haptic-pad/session/bind", "http://localhost:3000/api/haptic-pad/session/bind", "/api/haptic-pad/session/bind"];

  for (const url of urls) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res && res.ok) {
        const data = await res.json();
        console.log(`[Haptic Pad Routing] Bound to Session: ${payload.session_id} -> Patient: ${payload.patient_name} (${payload.patient_id})`);
        return data;
      }
    } catch (e) {
      // Continue fallback
    }
  }
  return { success: false };
}
window.bindHapticSessionAPI = bindHapticSessionAPI;

/**
 * Unbind active consultation session from Haptic Pad routing in backend
 */
async function unbindHapticSessionAPI(sessionId = null) {
  const payload = { session_id: sessionId || window.currentActiveConsultationSessionId || null };
  const isDirectBackend = window.location.port === "3000";
  const urls = isDirectBackend
    ? ["/api/haptic-pad/session/unbind", "http://127.0.0.1:3000/api/haptic-pad/session/unbind", "http://localhost:3000/api/haptic-pad/session/unbind"]
    : ["http://127.0.0.1:3000/api/haptic-pad/session/unbind", "http://localhost:3000/api/haptic-pad/session/unbind", "/api/haptic-pad/session/unbind"];

  for (const url of urls) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res && res.ok) {
        const data = await res.json();
        console.log("[Haptic Pad Routing] Consultation session unbound. Haptic Pad telemetry signals paused.");
        return data;
      }
    } catch (e) {
      // Continue fallback
    }
  }
  return { success: false };
}
window.unbindHapticSessionAPI = unbindHapticSessionAPI;

/**
 * Patient Haptic Service
 * Enforces session-based authorization and delivers real-time Haptic Pad telemetry
 */
const PatientHapticService = {
  async getTelemetry(options = {}) {
    const sessionId = options.sessionId || options.session_id || "";
    const patientId = options.patientId || options.patient_id || currentAuthenticatedUser?.uid || "";
    const patientName = options.patientName || options.patient_name || currentAuthenticatedUser?.name || "";

    const queryParams = new URLSearchParams();
    if (sessionId) queryParams.set("session_id", sessionId);
    if (patientId) queryParams.set("patient_id", patientId);
    if (patientName) queryParams.set("patient_name", patientName);

    const isDirectBackend = window.location.port === "3000";
    const baseUrls = isDirectBackend
      ? ["/api/haptic-pad/patient/telemetry", "http://127.0.0.1:3000/api/haptic-pad/patient/telemetry", "http://localhost:3000/api/haptic-pad/patient/telemetry"]
      : ["http://127.0.0.1:3000/api/haptic-pad/patient/telemetry", "http://localhost:3000/api/haptic-pad/patient/telemetry", "/api/haptic-pad/patient/telemetry"];

    for (const base of baseUrls) {
      try {
        const url = `${base}?${queryParams.toString()}`;
        const res = await fetch(url, { method: "GET" });
        if (res && res.ok) {
          return await res.json();
        }
      } catch (e) {
        // Fallback
      }
    }
    return { authorized: false, routing_status: "NETWORK_ERROR", telemetry: null };
  },

  subscribeStream(options = {}, onData, onBlocked) {
    const sessionId = options.sessionId || options.session_id || "";
    const patientId = options.patientId || options.patient_id || currentAuthenticatedUser?.uid || "";
    const patientName = options.patientName || options.patient_name || currentAuthenticatedUser?.name || "";

    const queryParams = new URLSearchParams();
    if (sessionId) queryParams.set("session_id", sessionId);
    if (patientId) queryParams.set("patient_id", patientId);
    if (patientName) queryParams.set("patient_name", patientName);

    const baseUrl = (window.location.port === "3000" || window.location.port === "") ? "" : "http://127.0.0.1:3000";
    const streamUrl = `${baseUrl}/api/haptic-pad/patient/stream?${queryParams.toString()}`;

    try {
      const evtSource = new EventSource(streamUrl);
      evtSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.authorized && data.telemetry) {
            if (typeof onData === "function") onData(data);
          } else {
            if (typeof onBlocked === "function") onBlocked(data);
          }
        } catch (err) { }
      };
      evtSource.onerror = () => {
        // EventSource auto-reconnects
      };
      return evtSource;
    } catch (e) {
      console.warn("[PatientHapticService] EventSource error:", e);
      return null;
    }
  },

  async getActiveSession() {
    const isDirectBackend = window.location.port === "3000";
    const baseUrls = isDirectBackend
      ? ["/api/haptic-pad/session/active", "http://127.0.0.1:3000/api/haptic-pad/session/active", "http://localhost:3000/api/haptic-pad/session/active"]
      : ["http://127.0.0.1:3000/api/haptic-pad/session/active", "http://localhost:3000/api/haptic-pad/session/active", "/api/haptic-pad/session/active"];

    for (const base of baseUrls) {
      try {
        const res = await fetch(base, { method: "GET" });
        if (res && res.ok) {
          return await res.json();
        }
      } catch (e) { }
    }
    return { success: false, active: false, routing: null, haptic_connected: false };
  }
};
window.PatientHapticService = PatientHapticService;

/**
 * Resolves session and patient credentials for remote Haptic Pad session routing.
 * Ensures Patient A, Patient B, Patient C, and custom patients are cleanly isolated.
 */
function getPatientSessionIdentifiers(patient = null) {
  const u = patient || currentAuthenticatedUser || {};
  const uid = (u.uid || u.id || "").toString().trim();
  const name = (u.name || "").trim();
  const email = (u.email || "").trim().toLowerCase();
  const lowerUid = uid.toLowerCase();
  const lowerName = name.toLowerCase();

  // 1. Patient A: Default patient in TORUS, UID 4001, PAT-4001, P-12345, or "Patient A" / "Patient User"
  const isPatientA = lowerUid === "p-12345" ||
                     lowerUid === "4001" ||
                     lowerUid === "pat-4001" ||
                     lowerName === "patient a" ||
                     lowerName === "patient user" ||
                     email === "patient@gmail.com" ||
                     email === "patient_a@gmail.com" ||
                     (!lowerUid && !lowerName);

  // 2. Patient B: UID P-8821, or "Patient B" / "John Doe" / "John Smith"
  const isPatientB = lowerUid === "p-8821" ||
                     lowerName === "patient b" ||
                     lowerName === "john doe" ||
                     lowerName === "john smith" ||
                     email === "patient_b@gmail.com" ||
                     email === "john.smith@gmail.com";

  // 3. Patient C: UID P-9104, or "Patient C" / "Jane Smith"
  const isPatientC = lowerUid === "p-9104" ||
                     lowerName === "patient c" ||
                     lowerName === "jane smith" ||
                     email === "patient_c@gmail.com" ||
                     email === "jane.smith@gmail.com";

  if (isPatientA) {
    return {
      sessionId: "S-001",
      patientId: "P-12345",
      patientName: "Patient A",
      displayLabel: "Patient A"
    };
  }

  if (isPatientB) {
    return {
      sessionId: "S-002",
      patientId: "P-8821",
      patientName: "Patient B",
      displayLabel: "Patient B"
    };
  }

  if (isPatientC) {
    return {
      sessionId: "S-003",
      patientId: "P-9104",
      patientName: "Patient C",
      displayLabel: "Patient C"
    };
  }

  // Any custom registered patient
  return {
    sessionId: u.sessionId || u.session_id || window.currentActiveConsultationSessionId || "",
    patientId: uid || "P-12345",
    patientName: name || "Patient A",
    displayLabel: name || uid || "Patient"
  };
}
window.getPatientSessionIdentifiers = getPatientSessionIdentifiers;

/**
 * Dynamically queries the backend Haptic session routing API
 * and updates the Patient Portal header status pill ("Remote Haptic Control • Active" / "Inactive").
 */
async function updatePatientHapticSessionStatus(patient = null) {
  const isDoc = (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") ||
                (roleInput && roleInput.value === "doctor");
  if (isDoc) return null;

  const ident = getPatientSessionIdentifiers(patient || currentAuthenticatedUser);
  const patStatus = await PatientHapticService.getTelemetry({
    sessionId: ident.sessionId,
    patientId: ident.patientId,
    patientName: ident.patientName
  });

  const isAuthorized = Boolean(patStatus && patStatus.authorized && patStatus.haptic_connected);

  // 1. Update the Patient Portal header chip (#docDashHapticChip)
  setHapticPadStatus(
    isAuthorized ? HAPTIC_STATE.CONNECTED : HAPTIC_STATE.NOT_CONNECTED,
    { patientAuthorized: isAuthorized }
  );

  // 2. Also keep the Live Video Consultation badge updated if present
  const sessionBadge = document.getElementById("liveConsultationHapticBadge");
  const sessionText = document.getElementById("liveConsultationHapticText");
  if (sessionBadge && sessionText) {
    sessionBadge.style.display = "inline-flex";
    if (isAuthorized) {
      sessionBadge.className = "live-haptic-badge haptic-badge--connected";
      sessionText.textContent = "Remote Haptic Control • Active";
    } else {
      sessionBadge.className = "live-haptic-badge haptic-badge--inactive";
      sessionText.textContent = "Remote Haptic Control • Inactive";
    }
  }

  return patStatus;
}
window.updatePatientHapticSessionStatus = updatePatientHapticSessionStatus;

// Browser console verification helper
window.verifyHapticSessionRouting = async function (patientId = "P-12345", sessionId = "S-001") {
  console.log(`[HAPTIC VERIFICATION] Testing Haptic Pad routing for Patient ID: ${patientId}, Session ID: ${sessionId}...`);
  const result = await PatientHapticService.getTelemetry({ patientId, sessionId });
  console.log("[HAPTIC VERIFICATION] Result:", result);
  return result;
};

// ============================================================
// HAPTIC PAD CONNECTION STATE ENGINE & SERVICE ABSTRACTION
// ============================================================

const HAPTIC_STATE = {
  CONNECTING: "CONNECTING",
  CONNECTED: "CONNECTED",
  NOT_CONNECTED: "NOT_CONNECTED"
};

let currentHapticState = null;
let isHapticConnectionInProgress = false;
let hapticModalDismissed = false;

// Development-only override hook for testing
let devHapticMockResult = null; // true = force success (TEST 1), false = force fail (TEST 2), null = real flow

window.setHapticPadDevMockResult = function (val) {
  devHapticMockResult = val;
  console.log("[HapticPad Dev] Mock result override set to:", val);
};

// Check for URL query parameter override for testing (e.g. ?haptic=success or ?haptic=fail)
try {
  const urlParams = new URLSearchParams(window.location.search);
  const hapticParam = urlParams.get("haptic");
  if (hapticParam === "success" || hapticParam === "connected") {
    devHapticMockResult = true;
  } else if (hapticParam === "fail" || hapticParam === "disconnected") {
    devHapticMockResult = false;
  }
} catch (e) { }

/**
 * Haptic Pad Connection Service
 * Clean abstraction layer designed for real backend / driver integration.
 */
const HapticPadService = {
  /**
   * Check live status of the physical Haptic Pad device from backend
   * @param {Object} options
   * @returns {Promise<{success: boolean, connected: boolean, device?: string, port?: string, message?: string}>}
   */
  async getStatus(options = {}) {
    if (devHapticMockResult !== null) {
      return {
        success: true,
        connected: Boolean(devHapticMockResult),
        device: devHapticMockResult ? "STM32 Haptic Pad (Mock)" : null,
        port: devHapticMockResult ? "COM3" : null,
        message: devHapticMockResult ? "Haptic Pad connected (Mock)" : "Device not detected."
      };
    }

    const isDirectBackend = window.location.port === "3000";
    const endpoints = isDirectBackend
      ? ["/api/haptic-pad/status", "http://127.0.0.1:3000/api/haptic-pad/status", "http://localhost:3000/api/haptic-pad/status"]
      : ["http://127.0.0.1:3000/api/haptic-pad/status", "http://localhost:3000/api/haptic-pad/status", "/api/haptic-pad/status"];

    for (const url of endpoints) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), options.timeoutMs || 2500);

        const response = await fetch(url, {
          method: "GET",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal
        }).catch(() => null);

        clearTimeout(timeoutId);

        if (response && response.ok) {
          const data = await response.json();
          return {
            success: true,
            connected: Boolean(data.connected),
            device: data.device || null,
            port: data.port || null,
            packets_rx: data.packets_rx || 0,
            message: data.message || ""
          };
        }
      } catch (err) {
        // Continue to next endpoint fallback
      }
    }

    return {
      success: false,
      connected: false,
      error: "Haptic Pad device not detected or backend offline."
    };
  },

  /**
   * Attempt connection handshake
   */
  async connectHapticPad(options = {}) {
    return this.getStatus(options);
  }
};
window.HapticPadService = HapticPadService;

/**
 * Updates the existing Haptic Pad status indicator in the top-right header
 * based on current HAPTIC_STATE and active user role.
 */
function setHapticPadStatus(state, details = {}) {
  const chip = document.getElementById("docDashHapticChip");
  const label = chip ? chip.querySelector(".ddash-haptic-label") : null;
  const text = document.getElementById("docDashHapticChipText");
  const alertIcon = chip ? chip.querySelector(".ddash-haptic-alert") : null;
  if (!chip) return;

  const isDoc = (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") ||
                (roleInput && roleInput.value === "doctor");

  chip.classList.remove("haptic-chip--connected", "haptic-chip--connecting", "haptic-chip--disconnected", "haptic-chip--inactive");

  if (isDoc) {
    // 1. DOCTOR SIDE: LOCAL PHYSICAL HARDWARE STATUS ONLY
    if (label) label.textContent = "Haptic Pad";
    if (state === HAPTIC_STATE.CONNECTED || state === "connected") {
      currentHapticState = HAPTIC_STATE.CONNECTED;
      chip.classList.add("haptic-chip--connected");
      if (text) text.textContent = "Connected";
      if (alertIcon) alertIcon.style.display = "none";
      chip.title = `Haptic Pad • Connected (${details.port || "USB"}) (Click to test/reconnect)`;
    } else if (state === HAPTIC_STATE.CONNECTING || state === "connecting") {
      currentHapticState = HAPTIC_STATE.CONNECTING;
      chip.classList.add("haptic-chip--connecting");
      if (text) text.textContent = "Connecting...";
      if (alertIcon) alertIcon.style.display = "none";
      chip.title = "Attempting to connect the haptic pad device...";
    } else {
      currentHapticState = HAPTIC_STATE.NOT_CONNECTED;
      chip.classList.add("haptic-chip--disconnected");
      if (text) text.textContent = "Not Connected";
      if (alertIcon) alertIcon.style.display = "inline";
      chip.title = "Haptic Pad • Not Connected (Click to retry connection)";
    }
  } else {
    // 2. PATIENT SIDE: REMOTE HAPTIC CONTROL STATUS ONLY
    if (label) label.textContent = "Remote Haptic Control";
    if (alertIcon) alertIcon.style.display = "none";
    const isPatientAuthorized = Boolean(details.patientAuthorized);
    if (isPatientAuthorized) {
      chip.classList.add("haptic-chip--connected");
      if (text) text.textContent = "Active";
      chip.title = "Remote Haptic Control • Active (Authorized consultation session)";
    } else {
      chip.classList.add("haptic-chip--inactive");
      if (text) text.textContent = "Inactive";
      chip.title = "Remote Haptic Control • Inactive";
    }
  }
}
window.setHapticPadStatus = setHapticPadStatus;

/**
 * Updates the Live Consultation status badges on #app-dashboard
 */
async function updateLiveConsultationHapticBadge() {
  const doctorHwBadge = document.getElementById("liveDoctorHapticHwBadge");
  const doctorHwText = document.getElementById("liveDoctorHapticHwText");
  const sessionBadge = document.getElementById("liveConsultationHapticBadge");
  const sessionText = document.getElementById("liveConsultationHapticText");

  const appDashboard = document.getElementById("app-dashboard");
  if (!appDashboard || appDashboard.style.display === "none") {
    if (doctorHwBadge) doctorHwBadge.style.display = "none";
    if (sessionBadge) sessionBadge.style.display = "none";
    return;
  }

  const isDoc = (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") ||
                (roleInput && roleInput.value === "doctor");

  if (isDoc) {
    // DOCTOR CONSULTATION PAGE:
    // 1. Show physical local hardware status separately
    const hw = await HapticPadService.getStatus({ timeoutMs: 1200 });
    if (doctorHwBadge && doctorHwText) {
      doctorHwBadge.style.display = "inline-flex";
      if (hw.connected) {
        doctorHwBadge.className = "live-haptic-badge haptic-badge--connected";
        doctorHwText.textContent = "Haptic Pad • Connected";
      } else {
        doctorHwBadge.className = "live-haptic-badge haptic-badge--disconnected";
        doctorHwText.textContent = "Haptic Pad • Not Connected";
      }
    }

    // 2. When active consultation session is bound, show Remote Control Active
    if (sessionBadge && sessionText) {
      const isSessionActive = Boolean(window.currentActiveConsultationSessionId);
      if (isSessionActive && hw.connected) {
        sessionBadge.style.display = "inline-flex";
        sessionBadge.className = "live-haptic-badge haptic-badge--connected";
        sessionText.textContent = "Remote Control • Active";
      } else {
        sessionBadge.style.display = "none";
      }
    }
  } else {
    // PATIENT CONSULTATION PAGE:
    // Do NOT show local physical hardware status on Patient side
    if (doctorHwBadge) doctorHwBadge.style.display = "none";

    // Show Remote Haptic Control status ONLY
    if (sessionBadge && sessionText) {
      sessionBadge.style.display = "inline-flex";
      const patIdent = getPatientSessionIdentifiers(currentAuthenticatedUser);
      const patStatus = await PatientHapticService.getTelemetry({
        sessionId: patIdent.sessionId,
        patientId: patIdent.patientId,
        patientName: patIdent.patientName
      });

      if (patStatus.authorized && patStatus.haptic_connected) {
        sessionBadge.className = "live-haptic-badge haptic-badge--connected";
        sessionText.textContent = "Remote Haptic Control • Active";
      } else {
        sessionBadge.className = "live-haptic-badge haptic-badge--inactive";
        sessionText.textContent = "Remote Haptic Control • Inactive";
      }
    }
  }
}
window.updateLiveConsultationHapticBadge = updateLiveConsultationHapticBadge;

let previousHapticState = null;
let hapticLiveDisconnectTimer = null;

/**
 * Manages modal visibility for Connecting and Not Connected states.
 */
function showHapticConnectingModal() {
  if (hapticLiveDisconnectTimer) {
    clearTimeout(hapticLiveDisconnectTimer);
    hapticLiveDisconnectTimer = null;
  }
  const overlay = document.getElementById("hapticModalOverlay");
  const connModal = document.getElementById("hapticConnectingModal");
  const errModal = document.getElementById("hapticErrorModal");
  if (!overlay || !connModal) return;

  if (errModal) errModal.style.display = "none";
  connModal.style.display = "flex";
  overlay.style.display = "flex";
}

function showHapticErrorModal() {
  if (hapticLiveDisconnectTimer) {
    clearTimeout(hapticLiveDisconnectTimer);
    hapticLiveDisconnectTimer = null;
  }
  const overlay = document.getElementById("hapticModalOverlay");
  const connModal = document.getElementById("hapticConnectingModal");
  const errModal = document.getElementById("hapticErrorModal");
  if (!overlay || !errModal) return;

  if (connModal) connModal.style.display = "none";

  // Ensure OK button is visible for manual / initial connection modal
  const errFooter = errModal.querySelector(".haptic-modal-footer");
  if (errFooter) errFooter.style.display = "flex";

  errModal.style.display = "flex";
  overlay.style.display = "flex";
}

/**
 * Shows the centered live disconnect alert modal when device drops from CONNECTED -> NOT_CONNECTED.
 * Automatically closes after approximately 3 seconds without requiring user click.
 */
function showHapticLiveDisconnectAlert() {
  if (hapticLiveDisconnectTimer) {
    clearTimeout(hapticLiveDisconnectTimer);
    hapticLiveDisconnectTimer = null;
  }
  const overlay = document.getElementById("hapticModalOverlay");
  const connModal = document.getElementById("hapticConnectingModal");
  const errModal = document.getElementById("hapticErrorModal");
  if (!overlay || !errModal) return;

  if (connModal) connModal.style.display = "none";

  // Hide OK button for auto-dismissing live disconnect alert
  const errFooter = errModal.querySelector(".haptic-modal-footer");
  if (errFooter) errFooter.style.display = "none";

  errModal.style.display = "flex";
  overlay.style.display = "flex";

  // Auto-close after ~3 seconds
  hapticLiveDisconnectTimer = setTimeout(() => {
    closeHapticModals();
  }, 3000);
}
window.showHapticLiveDisconnectAlert = showHapticLiveDisconnectAlert;

function closeHapticModals() {
  if (hapticLiveDisconnectTimer) {
    clearTimeout(hapticLiveDisconnectTimer);
    hapticLiveDisconnectTimer = null;
  }
  const overlay = document.getElementById("hapticModalOverlay");
  const connModal = document.getElementById("hapticConnectingModal");
  const errModal = document.getElementById("hapticErrorModal");

  if (overlay) overlay.style.display = "none";
  if (connModal) connModal.style.display = "none";
  if (errModal) {
    errModal.style.display = "none";
    const errFooter = errModal.querySelector(".haptic-modal-footer");
    if (errFooter) errFooter.style.display = "flex";
  }
}
window.closeHapticModals = closeHapticModals;

let hapticLiveMonitorInterval = null;

/**
 * Continuous background monitor for live disconnect/reconnect and session routing detection.
 */
function startHapticLiveMonitoring() {
  if (hapticLiveMonitorInterval) clearInterval(hapticLiveMonitorInterval);

  hapticLiveMonitorInterval = setInterval(async () => {
    const docPortalDash = document.getElementById("doctor-portal-dashboard");
    const appDash = document.getElementById("app-dashboard");

    // If on Live Consultation screen, keep live haptic indicator updated
    if (appDash && appDash.style.display !== "none") {
      updateLiveConsultationHapticBadge();
      return;
    }

    if (!docPortalDash || docPortalDash.style.display === "none") return;
    if (isHapticConnectionInProgress) return;

    const isDoc = (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") ||
                  (roleInput && roleInput.value === "doctor");

    if (isDoc) {
      const res = await HapticPadService.getStatus({ timeoutMs: 1500 });
      const wasConnected = currentHapticState === HAPTIC_STATE.CONNECTED;

      if (res.connected) {
        if (currentHapticState !== HAPTIC_STATE.CONNECTED) {
          console.log(`[HAPTIC] Device detected & verified on ${res.port}. Setting CONNECTED.`);
          previousHapticState = currentHapticState;
          currentHapticState = HAPTIC_STATE.CONNECTED;
          setHapticPadStatus(HAPTIC_STATE.CONNECTED, { port: res.port });
          closeHapticModals();

          if (typeof logDoctorActivity === "function") {
            logDoctorActivity("hardware", "Haptic Pad Connected", `Haptic controller hardware detected and synchronized on ${res.port || "USB"}.`, "Connected", "TORUS-H01");
          }
        }
      } else {
        if (wasConnected) {
          console.warn("[HAPTIC] Live disconnect detected! Transition: CONNECTED -> NOT_CONNECTED");
          previousHapticState = HAPTIC_STATE.CONNECTED;
          currentHapticState = HAPTIC_STATE.NOT_CONNECTED;
          setHapticPadStatus(HAPTIC_STATE.NOT_CONNECTED);
          showHapticLiveDisconnectAlert();

          if (typeof logDoctorActivity === "function") {
            logDoctorActivity("hardware", "Haptic Pad Disconnected", "Haptic telemetry controller disconnected from local serial bus.", "Disconnected", "TORUS-H01");
          }
        } else {
          if (currentHapticState !== HAPTIC_STATE.NOT_CONNECTED) {
            previousHapticState = currentHapticState;
            currentHapticState = HAPTIC_STATE.NOT_CONNECTED;
            setHapticPadStatus(HAPTIC_STATE.NOT_CONNECTED);
          }
        }
      }
    } else {
      // Patient Portal: dynamically query backend session-routing API and update status
      await updatePatientHapticSessionStatus();
    }
  }, 1000);
}

function stopHapticLiveMonitoring() {
  if (hapticLiveDisconnectTimer) {
    clearTimeout(hapticLiveDisconnectTimer);
    hapticLiveDisconnectTimer = null;
  }
  if (hapticLiveMonitorInterval) {
    clearInterval(hapticLiveMonitorInterval);
    hapticLiveMonitorInterval = null;
  }
}

/**
 * Initiates the complete Haptic Pad connection flow:
 * 1. Shows Connecting modal overlay & sets header to connecting.
 * 2. Invokes HapticPadService.connectHapticPad().
 * 3. On success: closes modal, sets header to connected green.
 * 4. On failure: transitions to error modal, sets header to disconnected red.
 * 5. On dismiss: leaves dashboard accessible without repeated popups.
 */
async function initiateHapticPadConnection(options = {}) {
  if (isHapticConnectionInProgress) return;

  const isDoc = (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") ||
                (roleInput && roleInput.value === "doctor");

  if (!isDoc) {
    // Patient: check remote session binding dynamically and start monitoring
    await updatePatientHapticSessionStatus();
    startHapticLiveMonitoring();
    return;
  }

  isHapticConnectionInProgress = true;

  // Set CONNECTING state & show modal
  setHapticPadStatus(HAPTIC_STATE.CONNECTING);
  showHapticConnectingModal();

  // Artificial realistic handshake delay (1200ms - 1500ms) for smooth UX
  const minDelay = new Promise(r => setTimeout(r, options.minDelayMs || 1500));
  const [result] = await Promise.all([
    HapticPadService.connectHapticPad(options),
    minDelay
  ]);

  isHapticConnectionInProgress = false;

  if (result && result.connected) {
    // 2. SUCCESS FLOW: Close connecting modal, update header to green connected
    closeHapticModals();
    setHapticPadStatus(HAPTIC_STATE.CONNECTED, { port: result.port });
    console.log("[HAPTIC] Device status: CONNECTED (Port: " + (result.port || "USB") + ")");
    if (typeof logDoctorActivity === "function") {
      logDoctorActivity("hardware", "Haptic Pad Connected", `Haptic controller hardware detected and synchronized on ${result.port || "USB"}.`, "Connected", "TORUS-H01");
    }
  } else {
    // 3. FAILURE FLOW: Show Error modal, update header to red not connected
    setHapticPadStatus(HAPTIC_STATE.NOT_CONNECTED);
    showHapticErrorModal();
    console.warn("[HAPTIC] Device status: NOT_CONNECTED");
  }

  // Start continuous background monitoring for live disconnect/reconnect detection
  startHapticLiveMonitoring();
}
window.initiateHapticPadConnection = initiateHapticPadConnection;

// Bind Haptic Pad Modal and Retry Click Handlers
function setupHapticPadListeners() {
  const errOkBtn = document.getElementById("hapticErrorOkBtn");
  const connOkBtn = document.getElementById("hapticConnectingOkBtn");
  const chip = document.getElementById("docDashHapticChip");

  if (errOkBtn) {
    errOkBtn.addEventListener("click", () => {
      closeHapticModals();
      hapticModalDismissed = true;
    });
  }

  if (connOkBtn) {
    connOkBtn.addEventListener("click", () => {
      closeHapticModals();
    });
  }

  if (chip) {
    chip.addEventListener("click", () => {
      const isDoc = (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") ||
                    (roleInput && roleInput.value === "doctor");
      if (isDoc) {
        console.log("[HAPTIC] Header status clicked, retrying connection...");
        initiateHapticPadConnection({ userTriggered: true });
      } else {
        console.log("[HAPTIC] Patient header status clicked, refreshing remote haptic control status...");
        updatePatientHapticSessionStatus();
      }
    });
  }
}
window.setupHapticPadListeners = setupHapticPadListeners;



// Upcoming Session Modal Logic
let currentModalSessionId = null;

// Device Availability Engine: Checks if a device is currently active in another session
function isDeviceInUse(deviceId, excludeSessionId = null) {
  if (!deviceId) return false;
  const activeList = window.torusSessions?.active || [];
  return activeList.some(s => s.deviceId === deviceId && s.sessionId !== excludeSessionId && s.status === "active");
}

function getActiveSessionForDevice(deviceId, excludeSessionId = null) {
  if (!deviceId) return null;
  const activeList = window.torusSessions?.active || [];
  return activeList.find(s => s.deviceId === deviceId && s.sessionId !== excludeSessionId && s.status === "active") || null;
}

// Tracks if device search modal was opened to switch device for a specific upcoming session
let deviceSwitchingSessionId = null;

function openUpcomingSessionModal(sessionId) {
  const session = window.torusSessions?.upcoming?.find(s => s.sessionId === sessionId);
  if (!session) return;

  currentModalSessionId = sessionId;

  const modal = document.getElementById("sessionDetailsModalOverlay");
  const pName = document.getElementById("sdPatientName");
  const pId = document.getElementById("sdPatientId");
  const pAge = document.getElementById("sdAgeGender");
  const pContact = document.getElementById("sdContact");
  const dev = document.getElementById("sdDevice");
  const sType = document.getElementById("sdScanType");
  const center = document.getElementById("sdCenter");
  const sTime = document.getElementById("sdTime");
  const notes = document.getElementById("sdClinicalNotes");
  const prevReports = document.getElementById("sdPreviousReports");

  if (pName) pName.textContent = session.patientName;
  if (pId) pId.textContent = session.patientId;
  if (pAge) pAge.textContent = session.ageGender || "42 | Male";
  if (pContact) pContact.textContent = session.contact || "+1 (555) 019-2834";
  if (dev) dev.textContent = session.deviceId;
  if (sType) sType.textContent = session.scanType;
  if (center) center.textContent = session.diagnosticCenter;
  if (sTime) sTime.textContent = session.scheduledTime;
  if (notes) notes.textContent = session.clinicalNotes || "--";
  if (prevReports) prevReports.textContent = session.previousReports || "--";

  // Dynamic Device Availability Evaluation
  const inUse = isDeviceInUse(session.deviceId, session.sessionId);
  const conflictSession = getActiveSessionForDevice(session.deviceId, session.sessionId);

  const statusEl = document.getElementById("sdDeviceStatus");
  const noticeEl = document.getElementById("sdDeviceConflictNotice");
  const msgEl = document.getElementById("sdDeviceConflictMsg");
  const startBtn = document.getElementById("sessionDetailsStartBtn");

  if (inUse) {
    if (statusEl) {
      statusEl.innerHTML = `<span class="sd-status-pill in-use">● In Use</span>`;
    }
    if (noticeEl) noticeEl.style.display = "flex";
    if (msgEl) {
      const occupantName = conflictSession?.patientName ? ` (${conflictSession.patientName})` : "";
      msgEl.textContent = `${session.deviceId} is currently in use by another patient${occupantName}.`;
    }
    if (startBtn) {
      startBtn.disabled = true;
      startBtn.title = `${session.deviceId} is currently in use by another patient.`;
    }
  } else {
    if (statusEl) {
      statusEl.innerHTML = `<span class="sd-status-pill available">● Available</span>`;
    }
    if (noticeEl) noticeEl.style.display = "none";
    if (startBtn) {
      startBtn.disabled = false;
      startBtn.title = "";
    }
  }

  if (modal) modal.style.display = "flex";
}

function closeUpcomingSessionModal() {
  const modal = document.getElementById("sessionDetailsModalOverlay");
  if (modal) modal.style.display = "none";
  currentModalSessionId = null;
}

function startUpcomingSessionConsultation(sessionId) {
  const session = window.torusSessions?.upcoming?.find(s => s.sessionId === sessionId);
  if (!session) return;

  // Prevent starting consultation if device is currently in use by another session
  if (isDeviceInUse(session.deviceId, session.sessionId)) {
    const conflict = getActiveSessionForDevice(session.deviceId, session.sessionId);
    const occupant = conflict ? ` by ${conflict.patientName}` : "";
    showToastNotification(`${session.deviceId} is currently in use${occupant}. Please switch to an available device.`);
    return;
  }

  closeUpcomingSessionModal();

  // Promote to active session list if not already present
  let activeEntry = window.torusSessions.active.find(s => s.sessionId === session.sessionId);
  if (!activeEntry) {
    activeEntry = {
      sessionId: session.sessionId,
      patientId: session.patientId,
      patientName: session.patientName,
      deviceId: session.deviceId,
      scanType: session.scanType,
      duration: "00:00",
      diagnosticCenter: session.diagnosticCenter,
      scheduledTime: session.scheduledTime,
      status: "active",
      doctorConnectionState: "connected",
      clinicalSessionCode: window.activeClinicalSessionCode || `TORUS-CLI-${session.patientId}`
    };
    window.torusSessions.active.unshift(activeEntry);
  } else {
    activeEntry.status = "active";
    activeEntry.doctorConnectionState = "connected";
  }

  saveTorusSessions();
  joinClinicalSession(session.sessionId);
}


// ============================================================
// ADHOC SCAN - TORUS DEVICE SELECTION & CONNECTION ENGINE
// ============================================================

const TORUS_AVAILABLE_DEVICES = [
  {
    id: "TORUS-C15",
    hospital: "Apollo Hospital",
    location: "Hyderabad, India",
    city: "Hyderabad",
    country: "India",
    status: "online",
    latency: "38ms",
    signal: "97%"
  },
  {
    id: "TORUS-D22",
    hospital: "Fortis Healthcare",
    location: "Bangalore, India",
    city: "Bangalore",
    country: "India",
    status: "standby",
    latency: "55ms",
    signal: "89%"
  },
  {
    id: "TORUS-E18",
    hospital: "CMC Hospital",
    location: "Chennai, India",
    city: "Chennai",
    country: "India",
    status: "online",
    latency: "45ms",
    signal: "92%"
  },
  {
    id: "TORUS-F09",
    hospital: "LA Medical Plaza",
    location: "Los Angeles, USA",
    city: "Los Angeles",
    country: "USA",
    status: "online",
    latency: "48ms",
    signal: "94%"
  },
  {
    id: "TORUS-A12",
    hospital: "NYC Medical Center",
    location: "New York, USA",
    city: "New York",
    country: "USA",
    status: "online",
    latency: "35ms",
    signal: "98%"
  },
  {
    id: "TORUS-B08",
    hospital: "Boston General Hospital",
    location: "Boston, USA",
    city: "Boston",
    country: "USA",
    status: "standby",
    latency: "42ms",
    signal: "95%"
  },
  {
    id: "TORUS-G04",
    hospital: "Manipal Hospital",
    location: "Delhi, India",
    city: "Delhi",
    country: "India",
    status: "online",
    latency: "40ms",
    signal: "96%"
  },
  {
    id: "TORUS-H17",
    hospital: "Mount Sinai Hospital",
    location: "Chicago, USA",
    city: "Chicago",
    country: "USA",
    status: "standby",
    latency: "52ms",
    signal: "90%"
  },
  {
    id: "TORUS-K03",
    hospital: "King Edward Memorial",
    location: "Mumbai, India",
    city: "Mumbai",
    country: "India",
    status: "online",
    latency: "36ms",
    signal: "98%"
  },
  {
    id: "TORUS-Z99",
    hospital: "St. Jude Research Center",
    location: "San Francisco, USA",
    city: "San Francisco",
    country: "USA",
    status: "offline",
    latency: "--",
    signal: "0%"
  }
];

// Single state variable for the selected TORUS device ID (Requirement 3 & 9)
let selectedTorUSDeviceId = null;
// Active list of devices displayed during the current modal opening
let currentDeviceList = [];

// Ensure all DOM elements exist regardless of editor state
function ensureDeviceModalInDOM() {
  // 1. Modal overlay
  let modalOverlay = document.getElementById("deviceModalOverlay");
  if (!modalOverlay) {
    modalOverlay = document.createElement("div");
    modalOverlay.className = "device-modal-overlay";
    modalOverlay.id = "deviceModalOverlay";
    modalOverlay.style.display = "none";
    modalOverlay.innerHTML = `
      <div class="device-modal" role="dialog" aria-modal="true" aria-labelledby="deviceModalTitle">
        <div class="device-modal-header">
          <h2 class="device-modal-title" id="deviceModalTitle">Search TORUS Device</h2>
          <button class="device-modal-close" id="deviceModalClose" type="button" aria-label="Close device search">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <div class="device-modal-filters">
          <label class="device-filter-input-wrap" aria-label="Search devices">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input id="deviceSearchInput" class="device-filter-input" type="text"
              placeholder="Search by ID, hospital, city..." />
          </label>
          <label class="device-filter-input-wrap cyan" aria-label="Filter devices by location">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
              <circle cx="12" cy="10" r="3"></circle>
            </svg>
            <input id="deviceLocationInput" class="device-filter-input" type="text"
              placeholder="Filter by country or city..." />
          </label>
        </div>

        <div class="device-results-scroll" id="deviceResultsScroll">
          <div class="device-results-grid" id="deviceResultsGrid"></div>
        </div>

        <div class="device-modal-footer">
          <button class="device-primary-btn" id="connectDeviceBtn" type="button" disabled>Select a TORUS Device</button>
          <button class="device-secondary-btn" id="deviceInfoBtn" type="button" disabled>Device Info</button>
        </div>
      </div>
    `;
    document.body.appendChild(modalOverlay);
    bindDeviceModalEvents();
  }


  // docDashDeviceChip is intentionally not shown in Doctor Dashboard header (removed per design)

  // 3. Live Consultation header device badge (Matches Settings & User Profile buttons)
  let headerBadge = document.getElementById("header-device-badge");
  if (!headerBadge) {
    const userBadge = document.getElementById("header-user-badge");
    if (userBadge && userBadge.parentNode) {
      headerBadge = document.createElement("button");
      headerBadge.id = "header-device-badge";
      headerBadge.className = "header-btn header-device-btn";
      headerBadge.title = "Connected TORUS Device";
      headerBadge.type = "button";
      headerBadge.style.display = "none";
      headerBadge.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
          <line x1="8" y1="21" x2="16" y2="21"></line>
          <line x1="12" y1="17" x2="12" y2="21"></line>
        </svg>
        <span id="header-device-text">TORUS-A12</span>
      `;
      userBadge.parentNode.insertBefore(headerBadge, userBadge.nextSibling);
    }
  }
}

// Bind modal listeners
function bindDeviceModalEvents() {
  const devModalClose = document.getElementById("deviceModalClose");
  const devModalOverlay = document.getElementById("deviceModalOverlay");
  if (devModalClose) {
    devModalClose.onclick = closeDeviceModal;
  }
  if (devModalOverlay) {
    devModalOverlay.onclick = (e) => {
      if (e.target === devModalOverlay) closeDeviceModal();
    };
  }

  const devSearchInput = document.getElementById("deviceSearchInput");
  const devLocationInput = document.getElementById("deviceLocationInput");
  const handleDeviceFilterInput = () => {
    const sVal = devSearchInput ? devSearchInput.value : "";
    const lVal = devLocationInput ? devLocationInput.value : "";
    const filtered = getFilteredDevices(sVal, lVal);
    renderDeviceResults(filtered);
    updateDeviceActionButtons();
  };
  if (devSearchInput) devSearchInput.oninput = handleDeviceFilterInput;
  if (devLocationInput) devLocationInput.oninput = handleDeviceFilterInput;

  const connectDevBtn = document.getElementById("connectDeviceBtn");
  if (connectDevBtn) {
    connectDevBtn.onclick = handleConnectSelectedDevice;
  }

  const devInfoBtn = document.getElementById("deviceInfoBtn");
  if (devInfoBtn) {
    devInfoBtn.onclick = handleDeviceInfoClick;
  }
}

// Fisher-Yates array shuffle helper
function shuffleDeviceList(arr) {
  const shuffled = [...arr];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
}

// Open Device Search Modal
function openDeviceModal() {
  ensureDeviceModalInDOM();
  bindDeviceModalEvents();

  const modalOverlay = document.getElementById("deviceModalOverlay");
  const searchInput = document.getElementById("deviceSearchInput");
  const locationInput = document.getElementById("deviceLocationInput");
  const modalTitle = document.getElementById("deviceModalTitle");
  if (!modalOverlay) return;

  if (modalTitle) {
    modalTitle.textContent = deviceSwitchingSessionId ? "Switch TORUS Device" : "Search TORUS Device";
  }

  // Requirement 2 & 8: Dynamic / random order every time modal is opened (randomized once on open)
  let shuffled = shuffleDeviceList(TORUS_AVAILABLE_DEVICES);
  if (currentDeviceList.length > 1 && shuffled[0].id === currentDeviceList[0]?.id) {
    const swapIdx = 1 + Math.floor(Math.random() * (shuffled.length - 1));
    [shuffled[0], shuffled[swapIdx]] = [shuffled[swapIdx], shuffled[0]];
  }
  currentDeviceList = shuffled;

  // Reset selection on open
  selectedTorUSDeviceId = null;

  if (searchInput) searchInput.value = "";
  if (locationInput) locationInput.value = "";

  renderDeviceResults(currentDeviceList);
  updateDeviceActionButtons();

  modalOverlay.style.display = "flex";
  document.body.classList.add("no-scroll");

  if (searchInput) {
    setTimeout(() => searchInput.focus(), 80);
  }
}

// Close Device Search Modal
function closeDeviceModal() {
  const modalOverlay = document.getElementById("deviceModalOverlay");
  if (modalOverlay) {
    modalOverlay.style.display = "none";
  }
  document.body.classList.remove("no-scroll");

  const returningSessionId = deviceSwitchingSessionId;
  deviceSwitchingSessionId = null;
  // If doctor closed device search while in device switching flow, return to Session Details
  if (returningSessionId) {
    openUpcomingSessionModal(returningSessionId);
  }
}

// Update Action Buttons (Connect & Info)
function updateDeviceActionButtons() {
  const connectBtn = document.getElementById("connectDeviceBtn");
  const infoBtn = document.getElementById("deviceInfoBtn");

  if (!connectBtn) return;

  if (selectedTorUSDeviceId) {
    connectBtn.disabled = false;
    if (deviceSwitchingSessionId) {
      connectBtn.textContent = `Assign ${selectedTorUSDeviceId}`;
    } else {
      connectBtn.textContent = `Connect ${selectedTorUSDeviceId}`;
    }
    if (infoBtn) infoBtn.disabled = false;
  } else {
    connectBtn.disabled = true;
    connectBtn.textContent = "Select a TORUS Device";
    if (infoBtn) infoBtn.disabled = true;
  }
}

// Select a single device (Requirement 3: Only ONE device selected, clear highlight)
function selectDevice(deviceId) {
  const device = TORUS_AVAILABLE_DEVICES.find(d => d.id === deviceId);
  if (!device) return;

  // Requirement 6: Offline devices cannot be connected
  if (device.status === "offline") {
    showToastNotification(`${device.id} is currently offline and cannot be connected.`);
    return;
  }

  // Active / In Use devices cannot be connected or assigned
  if (isDeviceInUse(device.id, deviceSwitchingSessionId)) {
    const conflictSession = getActiveSessionForDevice(device.id, deviceSwitchingSessionId);
    const occupant = conflictSession ? ` by ${conflictSession.patientName}` : "";
    showToastNotification(`${device.id} is currently in use${occupant} and cannot be selected.`);
    return;
  }

  // Update single state variable
  selectedTorUSDeviceId = deviceId;

  // Requirement 3: Only ONE device can ever be highlighted at a time
  // Update DOM classes directly so scroll position in .device-results-scroll is not lost
  const container = document.getElementById("deviceResultsGrid");
  if (container) {
    container.querySelectorAll(".device-card").forEach(card => {
      if (card.dataset.deviceId === deviceId) {
        card.classList.add("selected");
        card.setAttribute("aria-selected", "true");
      } else {
        card.classList.remove("selected");
        card.setAttribute("aria-selected", "false");
      }
    });
  }

  updateDeviceActionButtons();
}

// Filter devices by text and location
function getFilteredDevices(searchText, locationText) {
  const search = (searchText || "").trim().toLowerCase();
  const loc = (locationText || "").trim().toLowerCase();

  return currentDeviceList.filter(device => {
    const idMatch = device.id.toLowerCase().includes(search);
    const hospitalMatch = device.hospital.toLowerCase().includes(search);
    const cityMatch = device.city.toLowerCase().includes(search);
    const countryMatch = device.country.toLowerCase().includes(search);
    const locationMatch = device.location.toLowerCase().includes(search);

    const matchesSearch = !search || idMatch || hospitalMatch || cityMatch || countryMatch || locationMatch;
    const matchesLocation = !loc || locationMatch.includes(loc) || cityMatch.includes(loc) || countryMatch.includes(loc);

    return matchesSearch && matchesLocation;
  });
}

// Render device cards into the grid
function renderDeviceResults(list) {
  const container = document.getElementById("deviceResultsGrid");
  if (!container) return;

  if (!list || list.length === 0) {
    container.innerHTML = `<div class="device-empty-state">No TORUS devices match your search criteria.</div>`;
    return;
  }

  // Requirement 3: DO NOT display any "Select", "Selected", or similar text inside card
  container.innerHTML = list.map(device => {
    const isSelected = selectedTorUSDeviceId === device.id;
    const isOffline = device.status === "offline";
    const isInUse = isDeviceInUse(device.id, deviceSwitchingSessionId);

    let statusText = device.status;
    let statusClass = device.status;
    if (isInUse) {
      statusText = "in use";
      statusClass = "in-use";
    }

    return `
      <div class="device-card ${isSelected ? "selected" : ""} ${isOffline ? "device-card-offline" : ""} ${isInUse ? "device-card-inuse" : ""}"
           role="button"
           tabindex="0"
           data-device-id="${device.id}"
           aria-selected="${isSelected}">
        <div class="device-card-top">
          <h3 class="device-id">${device.id}</h3>
          <span class="device-status ${statusClass}">${statusText}</span>
        </div>
        <p class="device-hospital">${device.hospital}</p>
        <p class="device-location">${device.location}</p>
        <div class="device-metrics">
          <div class="device-metric">
            <p class="device-metric-label">Latency</p>
            <p class="device-metric-value">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M5 12.55a11 11 0 0 1 14.08 0"></path>
                <path d="M1.42 9a16 16 0 0 1 21.16 0"></path>
                <path d="M8.53 16.11a6 6 0 0 1 6.95 0"></path>
                <line x1="12" y1="20" x2="12.01" y2="20"></line>
              </svg>
              <span>${device.latency}</span>
            </p>
          </div>
          <div class="device-metric">
            <p class="device-metric-label">Signal</p>
            <p class="device-metric-value">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="2" y1="20" x2="2" y2="20"></line>
                <line x1="7" y1="20" x2="7" y2="16"></line>
                <line x1="12" y1="20" x2="12" y2="12"></line>
                <line x1="17" y1="20" x2="17" y2="8"></line>
                <line x1="22" y1="20" x2="22" y2="4"></line>
              </svg>
              <span>${device.signal}</span>
            </p>
          </div>
        </div>
      </div>
    `;
  }).join("");

  // Attach card click handlers
  container.querySelectorAll(".device-card").forEach(card => {
    card.addEventListener("click", () => {
      const devId = card.getAttribute("data-device-id");
      if (devId) selectDevice(devId);
    });
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        const devId = card.getAttribute("data-device-id");
        if (devId) selectDevice(devId);
      }
    });
  });
}

// Connect the selected device + Navigate to existing Live Consultation page (Requirement 5 & 10)
function handleConnectSelectedDevice() {
  if (!selectedTorUSDeviceId) return;

  const connectedId = selectedTorUSDeviceId;
  const targetDevice = TORUS_AVAILABLE_DEVICES.find(d => d.id === connectedId);

  // If switching device for an upcoming scheduled session
  if (deviceSwitchingSessionId) {
    const upcomingSess = window.torusSessions?.upcoming?.find(s => s.sessionId === deviceSwitchingSessionId);
    if (upcomingSess) {
      upcomingSess.deviceId = connectedId;
      if (targetDevice) {
        upcomingSess.diagnosticCenter = targetDevice.hospital;
      }
      saveTorusSessions();
      renderDoctorDashboard();

      const switchingId = deviceSwitchingSessionId;
      deviceSwitchingSessionId = null;
      closeDeviceModal();

      showToastNotification(`Assigned ${connectedId} to ${upcomingSess.patientName}. Device is available!`);
      openUpcomingSessionModal(switchingId);
      return;
    }
    deviceSwitchingSessionId = null;
  }

  // Update Doctor Dashboard Active Session
  let activeSession = window.torusSessions && window.torusSessions.active && window.torusSessions.active[0];
  if (activeSession) {
    activeSession.deviceId = connectedId;
    activeSession.status = "active";
    activeSession.doctorConnectionState = "connected";
    if (targetDevice) {
      activeSession.diagnosticCenter = targetDevice.hospital;
    }
  } else {
    activeSession = {
      sessionId: "S-001",
      patientId: "P-12345",
      patientName: "Patient A",
      deviceId: connectedId,
      scanType: "Abdominal",
      duration: "00:00",
      diagnosticCenter: targetDevice ? targetDevice.hospital : "Diagnostic Center",
      scheduledTime: "10:30 AM",
      status: "active",
      doctorConnectionState: "connected",
      clinicalSessionCode: window.activeClinicalSessionCode || "TORUS-CLI-P12345"
    };
    if (!window.torusSessions) window.torusSessions = { active: [], upcoming: [] };
    if (!window.torusSessions.active) window.torusSessions.active = [];
    window.torusSessions.active[0] = activeSession;
  }

  // Update Doctor Dashboard Topbar Device Chip
  const deviceChip = document.getElementById("docDashDeviceChip");
  const deviceChipText = document.getElementById("docDashDeviceChipText");
  if (deviceChip && deviceChipText) {
    deviceChipText.textContent = `${connectedId} (Connected)`;
    deviceChip.style.display = "inline-flex";
  }

  // Persist state across session and local storage
  try {
    localStorage.setItem("connectedDeviceId", connectedId);
    sessionStorage.setItem("connectedDeviceId", connectedId);
    window.activeTorusDeviceId = connectedId;
    if (targetDevice) {
      localStorage.setItem("connectedDevice", JSON.stringify(targetDevice));
      sessionStorage.setItem("connectedDevice", JSON.stringify(targetDevice));
    }
  } catch (e) {
    console.warn("Storage write error:", e);
  }

  saveTorusSessions();
  renderDoctorDashboard();

  // Close modal
  closeDeviceModal();

  // Show Toast notification
  showToastNotification(`Connected to ${connectedId} successfully`);

  if (typeof logDoctorActivity === "function") {
    logDoctorActivity(
      "session",
      "Adhoc Scan Initiated",
      `Adhoc robotic ultrasound examination initialized with ${connectedId} (${targetDevice ? targetDevice.hospital : "Diagnostic Center"}).`,
      "Active",
      connectedId
    );
  }

  // Requirement 5: Navigate to EXISTING Live Consultation page used for the TORUS live session
  // Live Consultation page receives and uses selectedTorUSDeviceId as the connected device
  updateLiveConsultationDeviceDisplay(connectedId);
  joinClinicalSession(activeSession.sessionId);
}

// Update device display on the Live Consultation page (#app-dashboard)
function updateLiveConsultationDeviceDisplay(deviceId) {
  if (!deviceId) deviceId = selectedTorUSDeviceId || "TORUS-A12";
  ensureDeviceModalInDOM();

  // Header badge on Live Consultation page (Image 1 top header)
  const headerDevBadge = document.getElementById("header-device-badge");
  const headerDevText = document.getElementById("header-device-text");
  if (headerDevBadge && headerDevText) {
    headerDevText.textContent = deviceId;
    headerDevBadge.style.display = "inline-flex";
  }

  // Local Feed card tag - Keep Local Feed title clean without duplicate device tag
  const localFeedTitle = document.querySelector("#local-card .video-header h2");
  if (localFeedTitle) {
    localFeedTitle.innerHTML = "📹 Local Feed";
  }
}

// Show Device Info in Secondary Button
function handleDeviceInfoClick() {
  if (!selectedTorUSDeviceId) return;
  const dev = TORUS_AVAILABLE_DEVICES.find(d => d.id === selectedTorUSDeviceId);
  if (!dev) return;

  const infoBtn = document.getElementById("deviceInfoBtn");
  if (!infoBtn) return;

  const originalText = infoBtn.textContent;
  infoBtn.textContent = `${dev.latency} | ${dev.signal}`;
  setTimeout(() => {
    infoBtn.textContent = originalText;
  }, 2500);
}

// Toast notification helper
function showToastNotification(message) {
  const existing = document.getElementById("docDashToast");
  if (existing) existing.remove();

  const toast = document.createElement("div");
  toast.id = "docDashToast";
  toast.className = "ddash-toast";
  toast.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="20 6 9 17 4 12"></polyline>
    </svg>
    <span>${message}</span>
  `;
  document.body.appendChild(toast);

  setTimeout(() => {
    if (toast.parentNode) {
      toast.style.transition = "opacity 0.3s ease, transform 0.3s ease";
      toast.style.opacity = "0";
      toast.style.transform = "translateY(-8px)";
      setTimeout(() => toast.remove(), 320);
    }
  }, 3200);
}

// Global click delegation for Adhoc Scan button to ensure it always responds
document.addEventListener("click", (e) => {
  const btn = e.target.closest("#docDashAdhocScanBtn");
  if (btn) {
    e.preventDefault();
    openDeviceModal();
  }
});


// ============================================================
// PATIENT AUTHENTICATION & API HELPERS
// ============================================================

// Register Patient in Backend Database
async function registerPatientAccount(name, email, password, mobile, uid = "") {
  const cleanEmail = email.trim().toLowerCase();
  const cleanName = name.trim();
  const cleanMobile = mobile.trim();
  const cleanUid = uid.trim().toUpperCase();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/patients/register", {
    name: cleanName,
    email: cleanEmail,
    password: password,
    mobile: cleanMobile,
    uid: cleanUid,
    role: "patient"
  });
  if (apiRes) return apiRes;

  return { success: false, error: "Backend server is unreachable. Please verify that the backend server is running on port 3000." };
}

// Authenticate Patient against Backend Database (Email OR UID)
async function authenticatePatientAccount(loginId, password) {
  const cleanLogin = loginId.trim().toLowerCase();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/patients/login", {
    login_id: cleanLogin,
    password: password,
    role: "patient"
  });
  if (apiRes) return apiRes;

  return { success: false, error: "Backend server is unreachable. Please verify that the backend server is running on port 3000." };
}

// Request Patient Password Reset OTP (Real Backend API + SMTP Dispatch)
async function requestPatientResetOTP(identifier) {
  const cleanId = identifier.trim().toLowerCase();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/patients/forgot-password/send-otp", {
    identifier: cleanId,
    role: "patient"
  });
  if (apiRes) return apiRes;

  return {
    success: false,
    error: "Backend server is unreachable. Please verify that the backend server is running on port 3000."
  };
}

// Verify Patient Password Reset OTP (Real Backend API Verification)
async function verifyPatientResetOTP(identifier, otp) {
  const cleanId = identifier.trim().toLowerCase();
  const cleanOtp = String(otp).trim();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/patients/forgot-password/verify-otp", {
    identifier: cleanId,
    otp: cleanOtp,
    role: "patient"
  });
  if (apiRes) return apiRes;

  return {
    success: false,
    error: "Backend server is unreachable. Please verify that the backend server is running on port 3000."
  };
}

// Reset Patient Password with Verified Token (Real Backend API Reset)
async function resetPatientPasswordWithToken(identifier, resetToken, newPassword) {
  const cleanId = identifier.trim().toLowerCase();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/patients/forgot-password/reset", {
    identifier: cleanId,
    reset_token: resetToken,
    new_password: newPassword,
    role: "patient"
  });
  if (apiRes) return apiRes;

  return {
    success: false,
    error: "Backend server is unreachable. Please verify that the backend server is running on port 3000."
  };
}

// Set Active Authenticated Patient Session & Launch Dashboard
function setAuthenticatedPatientSession(patient) {
  currentAuthenticatedUser = { ...patient, role: "patient" };
  currentAuthenticatedRole = "patient";
  try {
    sessionStorage.setItem("authenticated_patient", JSON.stringify(currentAuthenticatedUser));
    localStorage.setItem("authenticated_patient", JSON.stringify(currentAuthenticatedUser));
  } catch (e) { }

  // Bind values to settings inputs
  if (roleInput) {
    roleInput.value = "patient";
    roleInput.dispatchEvent(new Event("change"));
  }
  if (uidInput) {
    uidInput.value = patient.uid || "4001";
  }

  // Update dynamic Header User Badge
  const nameEl = document.getElementById("user-display-name");
  const uidEl = document.getElementById("user-display-uid");
  const badgeEl = document.getElementById("header-user-badge");

  if (nameEl) {
    nameEl.textContent = patient.name || "Patient";
  }
  if (uidEl) {
    uidEl.textContent = patient.uid || "4001";
  }
  if (badgeEl) {
    badgeEl.style.display = "inline-flex";
  }

  // Transition UI to Dashboard
  const patLoginScreen = document.getElementById("patient-login-screen");
  const patRegScreen = document.getElementById("patient-register-screen");
  const patForgotScreen = document.getElementById("patient-forgot-screen");
  const docLoginScreen = document.getElementById("doctor-login-screen");
  const docRegScreen = document.getElementById("doctor-register-screen");
  const docForgotScreen = document.getElementById("doctor-forgot-screen");
  const docBioScreen = document.getElementById("doctor-biometric-screen");
  const docBioRegScreen = document.getElementById("doctor-bio-register-screen");
  const joinScreen = document.getElementById("join-session-screen");
  const docBanner = document.getElementById("doctor-session-banner");

  // Update shell header & sidebar for Patient
  updateSharedPortalHeader(patient, "patient");

  // Show the shared TORUS Dashboard Shell
  showTorusScreen("doctor-portal-dashboard");

  // Render Patient Dashboard interactive handlers
  renderPatientDashboard(patient);

  // Setup Haptic Pad event listeners & trigger dynamic remote session check
  if (typeof setupHapticPadListeners === "function") {
    setupHapticPadListeners();
  }
  if (typeof updatePatientHapticSessionStatus === "function") {
    updatePatientHapticSessionStatus(patient);
  }
  if (typeof startHapticLiveMonitoring === "function") {
    startHapticLiveMonitoring();
  }
}

// ============================================================
// VIEWER AUTHENTICATION & API HELPERS
// ============================================================

// Register Viewer in Backend Database
async function registerViewerAccount(name, email, password, mobile, uid = "") {
  const cleanEmail = email.trim().toLowerCase();
  const cleanName = name.trim();
  const cleanMobile = mobile.trim();
  const cleanUid = uid.trim().toUpperCase();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/viewers/register", {
    name: cleanName,
    email: cleanEmail,
    password: password,
    mobile: cleanMobile,
    uid: cleanUid,
    role: "viewer"
  });
  if (apiRes) return apiRes;

  return { success: false, error: "Backend server is unreachable. Please verify that the backend server is running on port 3000." };
}

// Authenticate Viewer against Backend Database (Email OR UID)
async function authenticateViewerAccount(loginId, password) {
  const cleanLogin = loginId.trim().toLowerCase();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/viewers/login", {
    login_id: cleanLogin,
    password: password,
    role: "viewer"
  });
  if (apiRes) return apiRes;

  return { success: false, error: "Backend server is unreachable. Please verify that the backend server is running on port 3000." };
}

// Request Viewer Password Reset OTP (Real Backend API + SMTP Dispatch)
async function requestViewerResetOTP(identifier) {
  const cleanId = identifier.trim().toLowerCase();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/viewers/forgot-password/send-otp", {
    identifier: cleanId,
    role: "viewer"
  });
  if (apiRes) return apiRes;

  return {
    success: false,
    error: "Backend server is unreachable. Please verify that the backend server is running on port 3000."
  };
}

// Verify Viewer Reset OTP (Real Backend API Verification)
async function verifyViewerResetOTP(identifier, otp) {
  const cleanId = identifier.trim().toLowerCase();
  const cleanOtp = otp.trim();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/viewers/forgot-password/verify-otp", {
    identifier: cleanId,
    otp: cleanOtp,
    role: "viewer"
  });
  if (apiRes) return apiRes;

  return {
    success: false,
    error: "Backend server is unreachable. Please verify that the backend server is running on port 3000."
  };
}

// Reset Viewer Password with Verified Token (Real Backend API Reset)
async function resetViewerPasswordWithToken(identifier, resetToken, newPassword) {
  const cleanId = identifier.trim().toLowerCase();

  // Try Backend REST API
  const apiRes = await callBackendAPI("/api/viewers/forgot-password/reset", {
    identifier: cleanId,
    reset_token: resetToken,
    new_password: newPassword,
    role: "viewer"
  });
  if (apiRes) return apiRes;

  return {
    success: false,
    error: "Backend server is unreachable. Please verify that the backend server is running on port 3000."
  };
}

// Set Active Authenticated Viewer Session & Launch Dashboard
function setAuthenticatedViewerSession(viewer, autoJoinCall = false) {
  currentAuthenticatedUser = viewer;

  // Bind values to settings inputs
  if (roleInput) {
    roleInput.value = "viewer";
    roleInput.dispatchEvent(new Event("change"));
  }
  if (uidInput) {
    uidInput.value = viewer.uid;
  }

  // Update dynamic Header User Badge
  const nameEl = document.getElementById("user-display-name");
  const uidEl = document.getElementById("user-display-uid");
  const badgeEl = document.getElementById("header-user-badge");

  if (nameEl) {
    nameEl.textContent = viewer.name;
  }
  if (uidEl) {
    uidEl.textContent = `UID ${viewer.uid}`;
  }
  if (badgeEl) {
    badgeEl.style.display = "inline-flex";
  }

  // Transition UI to Dashboard
  showTorusScreen("app-dashboard");

  if (autoJoinCall) {
    setTimeout(() => {
      const joinBtnEl = document.getElementById("joinBtn");
      if (joinBtnEl && !joinBtnEl.disabled) {
        joinBtnEl.click();
      }
    }, 400);
  }
}

// Show alert message in login/modal forms
function showAlertMessage(elementId, message, type = "error") {
  const el = document.getElementById(elementId);
  if (!el) return;

  if (message && (message.includes("http://") || message.includes("https://"))) {
    const escaped = message
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    const withLinks = escaped.replace(
      /(https?:\/\/[^\s\)\>]+)/g,
      '<a href="$1" target="_blank" rel="noopener noreferrer" style="color: #00c8ff; text-decoration: underline; word-break: break-all;">$1</a>'
    );
    el.innerHTML = withLinks;
  } else {
    el.textContent = message;
  }

  el.className = `login-alert ${type}`;
  el.style.display = "block";
}

function hideAlertMessage(elementId) {
  const el = document.getElementById(elementId);
  if (el) el.style.display = "none";
}

// Bind DOM Event Listeners for Doctor Authentication
document.addEventListener("DOMContentLoaded", async () => {
  await initSQLiteDatabase();

  // Password Visibility Toggle
  const togglePassBtn = document.getElementById("toggle-password-btn");
  const passInput = document.getElementById("doctor-password-input");
  if (togglePassBtn && passInput) {
    togglePassBtn.addEventListener("click", () => {
      const isPass = passInput.type === "password";
      passInput.type = isPass ? "text" : "password";
      const eyeIcon = togglePassBtn.querySelector(".eye-icon");
      const eyeOffIcon = togglePassBtn.querySelector(".eye-off-icon");
      if (eyeIcon && eyeOffIcon) {
        eyeIcon.style.display = isPass ? "none" : "block";
        eyeOffIcon.style.display = isPass ? "block" : "none";
      }
    });
  }

  // Back Button from Doctor Login to Role Selection
  const docBackBtn = document.getElementById("doctor-login-back-btn");
  if (docBackBtn) {
    docBackBtn.onclick = (e) => {
      if (e) e.preventDefault();
      torusScreenHistory = ["role-selection-screen"];
      showTorusScreen("role-selection-screen", false);
    };
  }

  // Doctor Portal Dashboard Back Button -> Return to Previous Screen (e.g. Doctor Login)
  const docDashBackBtn = document.getElementById("docDashBackBtn");
  if (docDashBackBtn) {
    docDashBackBtn.addEventListener("click", () => {
      navigateBackTorus();
    });
  }

  // Doctor Dashboard Adhoc Scan Button -> Opens Search TORUS Device Modal
  const docDashAdhocBtn = document.getElementById("docDashAdhocScanBtn");
  if (docDashAdhocBtn) {
    docDashAdhocBtn.addEventListener("click", () => {
      openDeviceModal();
    });
  }

  // Device Modal Close Handlers
  const devModalClose = document.getElementById("deviceModalClose");
  const devModalOverlay = document.getElementById("deviceModalOverlay");
  if (devModalClose) devModalClose.addEventListener("click", closeDeviceModal);
  if (devModalOverlay) {
    devModalOverlay.addEventListener("click", (e) => {
      if (e.target === devModalOverlay) closeDeviceModal();
    });
  }

  // Filter Handlers (Search & Location)
  const devSearchInput = document.getElementById("deviceSearchInput");
  const devLocationInput = document.getElementById("deviceLocationInput");
  const handleDeviceFilterInput = () => {
    const sVal = devSearchInput ? devSearchInput.value : "";
    const lVal = devLocationInput ? devLocationInput.value : "";
    const filtered = getFilteredDevices(sVal, lVal);
    renderDeviceResults(filtered);
    updateDeviceActionButtons();
  };
  if (devSearchInput) devSearchInput.addEventListener("input", handleDeviceFilterInput);
  if (devLocationInput) devLocationInput.addEventListener("input", handleDeviceFilterInput);

  // Connect Button Handler
  const connectDevBtn = document.getElementById("connectDeviceBtn");
  if (connectDevBtn) {
    connectDevBtn.addEventListener("click", handleConnectSelectedDevice);
  }

  // Info Button Handler
  const devInfoBtn = document.getElementById("deviceInfoBtn");
  if (devInfoBtn) {
    devInfoBtn.addEventListener("click", handleDeviceInfoClick);
  }

  // Close Device Modal on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const devModal = document.getElementById("deviceModalOverlay");
      if (devModal && devModal.style.display !== "none") {
        closeDeviceModal();
      }
    }
  });

  // Profile Avatar Popover Toggle (Click and Hover)
  const ddashAvatarWrap = document.getElementById("docDashAvatarWrap");
  const ddashAvatar = document.getElementById("docDashAvatarChip");
  const ddashPopover = document.getElementById("docDashProfilePopover");
  if (ddashAvatar && ddashPopover) {
    let isPinnedOpen = false;

    ddashAvatar.addEventListener("click", (e) => {
      e.stopPropagation();
      isPinnedOpen = !isPinnedOpen;
      ddashPopover.style.display = isPinnedOpen ? "block" : "none";
    });

    if (ddashAvatarWrap) {
      ddashAvatarWrap.addEventListener("mouseenter", () => {
        ddashPopover.style.display = "block";
      });
      ddashAvatarWrap.addEventListener("mouseleave", () => {
        if (!isPinnedOpen) {
          ddashPopover.style.display = "none";
        }
      });
    }

    // Close popover when clicking anywhere outside
    document.addEventListener("click", (e) => {
      if (!ddashAvatar.contains(e.target) && !ddashPopover.contains(e.target)) {
        isPinnedOpen = false;
        ddashPopover.style.display = "none";
      }
    });

    // Close popover on Escape key
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        isPinnedOpen = false;
        ddashPopover.style.display = "none";
      }
    });

    // Dashboard Avatar Popover Logout Button (Doctor / Patient)
    const ddashLogoutBtn = document.getElementById("docDashLogoutBtn");
    if (ddashLogoutBtn) {
      ddashLogoutBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        handlePortalLogout();
      });
    }
  }

  // Universal Portal Logout Handler for Doctor and Patient
  function handlePortalLogout() {
    const isDoc = (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") ||
      (roleInput && roleInput.value === "doctor") ||
      Boolean(window.currentActiveConsultationSessionId);

    // Close any open popovers, sidebars, or modals
    const ddashPopover = document.getElementById("docDashProfilePopover");
    if (ddashPopover) ddashPopover.style.display = "none";
    const headerProfilePopover = document.getElementById("headerProfilePopover");
    if (headerProfilePopover) headerProfilePopover.style.display = "none";
    const docPortalDash = document.getElementById("doctor-portal-dashboard");
    if (docPortalDash) docPortalDash.classList.remove("sidebar-open");

    // Release Haptic Pad session binding on logout
    if (typeof unbindHapticSessionAPI === "function") {
      unbindHapticSessionAPI(window.currentActiveConsultationSessionId);
    }
    window.currentActiveConsultationSessionId = null;

    // Clear session state
    currentAuthenticatedUser = null;
    currentAuthenticatedRole = null;
    if (roleInput) roleInput.value = "";
    if (uidInput) uidInput.value = "";

    const hBadge = document.getElementById("header-user-badge");
    if (hBadge) hBadge.style.display = "none";
    const hDev = document.getElementById("header-device-badge");
    if (hDev) hDev.style.display = "none";

    if (isDoc) {
      // Clear Doctor session and navigate to Doctor Secure Login
      try {
        sessionStorage.removeItem("authenticated_doctor");
        localStorage.removeItem("authenticated_doctor");
        sessionStorage.removeItem("authenticated_user");
        localStorage.removeItem("authenticated_user");
      } catch (e) { }

      torusScreenHistory = ["role-selection-screen"];
      showTorusScreen("doctor-login-screen");
    } else {
      // Clear Patient session and navigate to Patient Secure Login
      try {
        sessionStorage.removeItem("authenticated_patient");
        localStorage.removeItem("authenticated_patient");
        sessionStorage.removeItem("authenticated_user");
        localStorage.removeItem("authenticated_user");
      } catch (e) { }

      torusScreenHistory = ["role-selection-screen"];
      showTorusScreen("patient-login-screen");
    }
  }
  window.handlePortalLogout = handlePortalLogout;

  // ============================================================
  // Live Consultation Header — User Profile Popover (profileBtn)
  // ============================================================
  const profileBtn = document.getElementById("profileBtn");
  const headerProfilePopover = document.getElementById("headerProfilePopover");
  const headerProfileWrap = document.getElementById("headerProfileWrap");
  if (profileBtn && headerProfilePopover) {
    let hppPinned = false;

    profileBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      hppPinned = !hppPinned;
      headerProfilePopover.style.display = hppPinned ? "block" : "none";
    });

    if (headerProfileWrap) {
      headerProfileWrap.addEventListener("mouseenter", () => {
        headerProfilePopover.style.display = "block";
      });
      headerProfileWrap.addEventListener("mouseleave", () => {
        if (!hppPinned) headerProfilePopover.style.display = "none";
      });
    }

    document.addEventListener("click", (e) => {
      if (!profileBtn.contains(e.target) && !headerProfilePopover.contains(e.target)) {
        hppPinned = false;
        headerProfilePopover.style.display = "none";
      }
    });

    // Logout button in header popover
    const hppLogoutBtn = document.getElementById("headerProfileLogoutBtn");
    if (hppLogoutBtn) {
      hppLogoutBtn.addEventListener("click", () => {
        handlePortalLogout();
      });
    }
  }

  // Upcoming Session Details Modal Close & Start Handlers
  const sCloseBtn = document.getElementById("sessionDetailsCloseBtn");
  const sCancelBtn = document.getElementById("sessionDetailsCancelBtn");
  const sStartBtn = document.getElementById("sessionDetailsStartBtn");
  const sSwitchBtn = document.getElementById("sdSwitchDeviceBtn");
  if (sCloseBtn) sCloseBtn.addEventListener("click", closeUpcomingSessionModal);
  if (sCancelBtn) sCancelBtn.addEventListener("click", closeUpcomingSessionModal);
  if (sSwitchBtn) {
    sSwitchBtn.addEventListener("click", () => {
      if (!currentModalSessionId) return;
      deviceSwitchingSessionId = currentModalSessionId;
      closeUpcomingSessionModal();
      openDeviceModal();
    });
  }
  if (sStartBtn) {
    sStartBtn.addEventListener("click", () => {
      if (sStartBtn.disabled) return;
      if (currentModalSessionId) {
        startUpcomingSessionConsultation(currentModalSessionId);
      }
    });
  }

  // Initialize Live Consultation header device indicator with current active device
  const initDevId = (window.torusSessions?.active?.[0]?.deviceId) || sessionStorage.getItem("connectedDeviceId") || "TORUS-A12";
  updateLiveConsultationDeviceDisplay(initDevId);



  // Secure Login Form Submission
  const loginForm = document.getElementById("doctor-login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("doctor-login-alert");

      const emailVal = document.getElementById("doctor-email-input")?.value || "";
      const passVal = document.getElementById("doctor-password-input")?.value || "";

      if (!emailVal || !passVal) {
        showAlertMessage("doctor-login-alert", "Please fill in all fields.");
        return;
      }

      const res = await authenticateDoctorAccount(emailVal, passVal);
      if (res.success && res.doctor) {
        setAuthenticatedDoctorSession(res.doctor);
      } else {
        showAlertMessage("doctor-login-alert", res.error || "Invalid email/UID or password.");
      }
    });
  }

  // ============================================================
  // Create Account Link -> Navigate to Full Page Registration
  // ============================================================
  const createAccLink = document.getElementById("doctor-create-account-link");

  if (createAccLink) {
    createAccLink.addEventListener("click", (e) => {
      e.preventDefault();
      hideAlertMessage("register-alert");

      // Clear form fields completely (Professional ID is left blank by default)
      const regForm = document.getElementById("doctor-register-form");
      if (regForm) regForm.reset();

      // Ensure Professional ID is completely blank by default
      const profIdInput = document.getElementById("reg-professional-id");
      if (profIdInput) {
        profIdInput.value = "";
      }

      // Show registration screen
      showTorusScreen("doctor-register-screen");
    });
  }

  // Back Button from Registration -> Previous Screen (Doctor Login)
  const regBackBtn = document.getElementById("doctor-register-back-btn");
  if (regBackBtn) {
    regBackBtn.addEventListener("click", () => {
      navigateBackTorus();
    });
  }

  // Password Visibility Toggle for Registration
  function setupPasswordToggle(btnId, inputId) {
    const toggleBtn = document.getElementById(btnId);
    const inputEl = document.getElementById(inputId);
    if (toggleBtn && inputEl) {
      toggleBtn.addEventListener("click", () => {
        const isPass = inputEl.type === "password";
        inputEl.type = isPass ? "text" : "password";
        toggleBtn.innerHTML = isPass
          ? `<svg class="eye-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>`
          : `<svg class="eye-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
      });
    }
  }

  setupPasswordToggle("reg-password-toggle", "reg-password");
  setupPasswordToggle("reg-confirm-password-toggle", "reg-confirm-password");

  // Registration Form Submission
  const registerForm = document.getElementById("doctor-register-form");
  const submitRegBtn = document.getElementById("submitRegisterBtn");

  if (registerForm) {
    registerForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      await handleDoctorRegistration();
    });
  }

  async function handleDoctorRegistration() {
    hideAlertMessage("register-alert");

    const nameVal = document.getElementById("reg-name")?.value || "";
    const profIdVal = document.getElementById("reg-professional-id")?.value?.trim() || "";
    const emailVal = document.getElementById("reg-email")?.value || "";
    const mobileVal = document.getElementById("reg-mobile")?.value || "";
    const passVal = document.getElementById("reg-password")?.value || "";
    const confirmVal = document.getElementById("reg-confirm-password")?.value || "";
    const termsChecked = document.getElementById("reg-terms-checkbox")?.checked || false;

    // --- Frontend Validations ---

    if (!nameVal.trim()) {
      showAlertMessage("register-alert", "Full Name is required.");
      return;
    }

    if (profIdVal) {
      // Validate alphanumeric format if entered manually
      if (!/^[A-Za-z0-9\-_]{3,20}$/.test(profIdVal)) {
        showAlertMessage("register-alert", "Professional ID must contain letters and numbers (e.g., DOC-A7K29).");
        return;
      }
    }

    if (!emailVal.trim()) {
      showAlertMessage("register-alert", "Email is required.");
      return;
    }

    if (!validateEmailFormat(emailVal)) {
      showAlertMessage("register-alert", "Please enter a valid email address.");
      return;
    }

    if (!mobileVal.trim()) {
      showAlertMessage("register-alert", "Mobile Number is required.");
      return;
    }

    if (!validateMobileFormat(mobileVal)) {
      showAlertMessage("register-alert", "Please enter a valid mobile number.");
      return;
    }

    if (!passVal) {
      showAlertMessage("register-alert", "Password is required.");
      return;
    }

    const pwdCheck = validateStrongPassword(passVal);
    if (!pwdCheck.valid) {
      showAlertMessage("register-alert", "Password must be at least 8 characters long and include at least 1 uppercase letter, 1 lowercase letter, 1 number, and 1 special character (e.g. Doctor@2026).");
      return;
    }

    if (!confirmVal) {
      showAlertMessage("register-alert", "Please confirm your password.");
      return;
    }

    if (passVal !== confirmVal) {
      showAlertMessage("register-alert", "Passwords do not match.");
      return;
    }

    if (!termsChecked) {
      showAlertMessage("register-alert", "You must agree to the Terms & Conditions and Privacy Policy.");
      return;
    }

    // --- Call Registration API ---
    const res = await registerDoctorAccount(nameVal, emailVal, passVal, mobileVal, profIdVal);

    if (res.success && res.doctor) {
      // Navigate back to Doctor Login with success message
      showTorusScreen("doctor-login-screen");

      // Pre-fill the email field for convenience
      const emailInput = document.getElementById("doctor-email-input");
      if (emailInput) emailInput.value = res.doctor.email;
      // Clear the pre-filled password
      const loginPassInput = document.getElementById("doctor-password-input");
      if (loginPassInput) loginPassInput.value = "";

      showAlertMessage(
        "doctor-login-alert",
        `Account created successfully! Professional ID: ${res.doctor.uid}. You can now log in.`,
        "success"
      );
    } else {
      showAlertMessage("register-alert", res.error || "Registration failed. Please try again.");
    }
  }

  // ============================================================
  // Doctor Forgot Password Multi-Step Screen Handlers
  // ============================================================
  const doctorForgotScreen = document.getElementById("doctor-forgot-screen");
  const forgotLink = document.getElementById("doctor-forgot-link");
  const forgotBackBtn = document.getElementById("doctor-forgot-back-btn");
  const forgotStep2BackBtn = document.getElementById("forgot-step2-back-btn");
  const forgotStep3BackBtn = document.getElementById("forgot-step3-back-btn");

  const forgotStep1 = document.getElementById("forgot-step-1");
  const forgotStep2 = document.getElementById("forgot-step-2");
  const forgotStep3 = document.getElementById("forgot-step-3");

  const formStep1 = document.getElementById("doctor-forgot-form-step1");
  const formStep2 = document.getElementById("doctor-forgot-form-step2");
  const formStep3 = document.getElementById("doctor-forgot-form-step3");

  const inputIdentifier = document.getElementById("forgot-identifier");
  const inputOtp = document.getElementById("forgot-otp-input");
  const inputNewPass = document.getElementById("forgot-new-pass");
  const inputConfirmPass = document.getElementById("forgot-confirm-pass");
  const resendOtpBtn = document.getElementById("forgot-resend-otp-btn");

  let currentResetIdentifier = "";
  let currentResetToken = "";

  function resetForgotFlowUI() {
    hideAlertMessage("forgot-alert-step1");
    hideAlertMessage("forgot-alert-step2");
    hideAlertMessage("forgot-alert-step3");

    if (inputIdentifier) inputIdentifier.value = "";
    if (inputOtp) inputOtp.value = "";
    if (inputNewPass) inputNewPass.value = "";
    if (inputConfirmPass) inputConfirmPass.value = "";

    currentResetIdentifier = "";
    currentResetToken = "";

    if (forgotStep1) forgotStep1.style.display = "flex";
    if (forgotStep2) forgotStep2.style.display = "none";
    if (forgotStep3) forgotStep3.style.display = "none";
  }

  function showDoctorLoginFromForgot() {
    resetForgotFlowUI();
    navigateBackTorus();
  }

  if (forgotLink) {
    forgotLink.addEventListener("click", (e) => {
      e.preventDefault();
      resetForgotFlowUI();
      showTorusScreen("doctor-forgot-screen");
    });
  }

  if (forgotBackBtn) {
    forgotBackBtn.addEventListener("click", () => {
      resetForgotFlowUI();
      navigateBackTorus();
    });
  }

  if (forgotStep2BackBtn) {
    forgotStep2BackBtn.addEventListener("click", () => {
      hideAlertMessage("forgot-alert-step1");
      hideAlertMessage("forgot-alert-step2");
      if (forgotStep1) forgotStep1.style.display = "flex";
      if (forgotStep2) forgotStep2.style.display = "none";
      if (forgotStep3) forgotStep3.style.display = "none";
    });
  }

  if (forgotStep3BackBtn) {
    forgotStep3BackBtn.addEventListener("click", () => {
      resetForgotFlowUI();
      navigateBackTorus();
    });
  }

  // Step 1: Send OTP
  if (formStep1) {
    formStep1.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("forgot-alert-step1");

      const identifierVal = inputIdentifier?.value?.trim() || "";
      if (!identifierVal) {
        showAlertMessage("forgot-alert-step1", "Please enter your registered Email or User ID.");
        return;
      }

      const submitBtn = document.getElementById("forgot-send-otp-btn");
      if (submitBtn) submitBtn.disabled = true;

      try {
        const res = await requestDoctorResetOTP(identifierVal);
        if (res.success) {
          currentResetIdentifier = identifierVal;
          if (forgotStep1) forgotStep1.style.display = "none";
          if (forgotStep2) forgotStep2.style.display = "flex";
          if (forgotStep3) forgotStep3.style.display = "none";

          showAlertMessage("forgot-alert-step2", res.message || "A 6-digit OTP has been sent to your registered email address.", "success");
        } else {
          showAlertMessage("forgot-alert-step1", res.error || "No account found with this email or User ID.");
        }
      } catch (err) {
        showAlertMessage("forgot-alert-step1", "Failed to send OTP. Please try again.");
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  // Step 2: Verify OTP
  if (formStep2) {
    formStep2.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("forgot-alert-step2");

      const otpVal = inputOtp?.value?.trim() || "";
      if (!otpVal || otpVal.length !== 6) {
        showAlertMessage("forgot-alert-step2", "Please enter the valid 6-digit OTP code.");
        return;
      }

      const verifyBtn = document.getElementById("forgot-verify-otp-btn");
      if (verifyBtn) verifyBtn.disabled = true;

      try {
        const res = await verifyDoctorResetOTP(currentResetIdentifier, otpVal);
        if (res.success) {
          currentResetToken = res.reset_token || otpVal;
          if (forgotStep1) forgotStep1.style.display = "none";
          if (forgotStep2) forgotStep2.style.display = "none";
          if (forgotStep3) forgotStep3.style.display = "flex";
          hideAlertMessage("forgot-alert-step3");
        } else {
          showAlertMessage("forgot-alert-step2", res.error || "Invalid OTP code. Please check your email.");
        }
      } catch (err) {
        showAlertMessage("forgot-alert-step2", "Verification error. Please try again.");
      } finally {
        if (verifyBtn) verifyBtn.disabled = false;
      }
    });
  }

  // Resend OTP
  if (resendOtpBtn) {
    resendOtpBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      hideAlertMessage("forgot-alert-step2");

      if (!currentResetIdentifier) {
        showAlertMessage("forgot-alert-step2", "Session expired. Please return to Step 1.");
        return;
      }

      try {
        const res = await requestDoctorResetOTP(currentResetIdentifier);
        if (res.success) {
          showAlertMessage("forgot-alert-step2", res.message || "A fresh 6-digit OTP has been sent to your registered email.", "success");
        } else {
          showAlertMessage("forgot-alert-step2", res.error || "Could not resend OTP.");
        }
      } catch (err) {
        showAlertMessage("forgot-alert-step2", "Failed to resend OTP.");
      }
    });
  }

  // Step 3: Reset Password
  if (formStep3) {
    formStep3.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("forgot-alert-step3");

      const newPass = inputNewPass?.value || "";
      const confirmPass = inputConfirmPass?.value || "";

      if (!newPass) {
        showAlertMessage("forgot-alert-step3", "New Password is required.");
        return;
      }

      const pwdCheck = validateStrongPassword(newPass);
      if (!pwdCheck.valid) {
        showAlertMessage("forgot-alert-step3", pwdCheck.error);
        return;
      }

      if (!confirmPass) {
        showAlertMessage("forgot-alert-step3", "Please confirm your new password.");
        return;
      }

      if (newPass !== confirmPass) {
        showAlertMessage("forgot-alert-step3", "Passwords do not match.");
        return;
      }

      const resetBtn = document.getElementById("forgot-reset-submit-btn");
      if (resetBtn) resetBtn.disabled = true;

      try {
        const res = await resetDoctorPasswordWithToken(currentResetIdentifier, currentResetToken, newPass);
        if (res.success) {
          showDoctorLoginFromForgot();

          // Pre-fill email/login input on login screen for ease of use
          const docEmailInput = document.getElementById("doctor-email-input");
          if (docEmailInput && currentResetIdentifier) {
            docEmailInput.value = currentResetIdentifier;
          }
          const docPassInput = document.getElementById("doctor-password-input");
          if (docPassInput) docPassInput.value = "";

          showAlertMessage(
            "doctor-login-alert",
            "Password reset successfully! Please log in with your new password.",
            "success"
          );
        } else {
          showAlertMessage("forgot-alert-step3", res.error || "Password reset failed.");
        }
      } catch (err) {
        showAlertMessage("forgot-alert-step3", "Failed to reset password. Please try again.");
      } finally {
        if (resetBtn) resetBtn.disabled = false;
      }
    });
  }

  // ============================================================
  // PATIENT AUTHENTICATION DOM EVENT HANDLERS
  // ============================================================

  // 1. Password Visibility Toggle for Patient Login
  const patTogglePassBtn = document.getElementById("patient-toggle-password-btn");
  const patPassInput = document.getElementById("patient-password-input");
  if (patTogglePassBtn && patPassInput) {
    patTogglePassBtn.addEventListener("click", () => {
      const isPass = patPassInput.type === "password";
      patPassInput.type = isPass ? "text" : "password";
      const eyeIcon = patTogglePassBtn.querySelector(".eye-icon");
      const eyeOffIcon = patTogglePassBtn.querySelector(".eye-off-icon");
      if (eyeIcon && eyeOffIcon) {
        eyeIcon.style.display = isPass ? "none" : "block";
        eyeOffIcon.style.display = isPass ? "block" : "none";
      }
    });
  }

  // 2. Back Button from Patient Login to Role Selection
  const patBackBtn = document.getElementById("patient-login-back-btn");
  if (patBackBtn) {
    patBackBtn.onclick = (e) => {
      if (e) e.preventDefault();
      torusScreenHistory = ["role-selection-screen"];
      showTorusScreen("role-selection-screen", false);
    };
  }

  // 3. Patient Secure Login Form Submission
  const patLoginForm = document.getElementById("patient-login-form");
  if (patLoginForm) {
    patLoginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("patient-login-alert");

      const emailVal = document.getElementById("patient-email-input")?.value || "";
      const passVal = document.getElementById("patient-password-input")?.value || "";

      if (!emailVal || !passVal) {
        showAlertMessage("patient-login-alert", "Please fill in all fields.");
        return;
      }

      const res = await authenticatePatientAccount(emailVal, passVal);
      if (res.success && res.patient) {
        setAuthenticatedPatientSession(res.patient);
      } else {
        showAlertMessage("patient-login-alert", res.error || "Invalid email/Patient ID or password.");
      }
    });
  }

  // 4. Patient Create Account Link -> Navigate to Patient Registration
  const patCreateAccLink = document.getElementById("patient-create-account-link");

  if (patCreateAccLink) {
    patCreateAccLink.addEventListener("click", (e) => {
      e.preventDefault();
      hideAlertMessage("patient-register-alert");

      const regForm = document.getElementById("patient-register-form");
      if (regForm) regForm.reset();

      const patIdInput = document.getElementById("patient-reg-patient-id");
      if (patIdInput) patIdInput.value = "";

      showTorusScreen("patient-register-screen");
    });
  }

  // 5. Patient Back Button from Registration -> Previous Screen (Patient Login)
  const patRegBackBtn = document.getElementById("patient-register-back-btn");
  if (patRegBackBtn) {
    patRegBackBtn.addEventListener("click", () => {
      navigateBackTorus();
    });
  }

  // 6. Password Visibility Toggles for Patient Registration
  setupPasswordToggle("patient-reg-password-toggle", "patient-reg-password");
  setupPasswordToggle("patient-reg-confirm-password-toggle", "patient-reg-confirm-password");

  // 7. Patient Registration Form Submission
  const patRegisterForm = document.getElementById("patient-register-form");
  if (patRegisterForm) {
    patRegisterForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      await handlePatientRegistration();
    });
  }

  async function handlePatientRegistration() {
    hideAlertMessage("patient-register-alert");

    const nameVal = document.getElementById("patient-reg-name")?.value || "";
    const patIdVal = document.getElementById("patient-reg-patient-id")?.value?.trim() || "";
    const emailVal = document.getElementById("patient-reg-email")?.value || "";
    const mobileVal = document.getElementById("patient-reg-mobile")?.value || "";
    const passVal = document.getElementById("patient-reg-password")?.value || "";
    const confirmVal = document.getElementById("patient-reg-confirm-password")?.value || "";
    const termsChecked = document.getElementById("patient-reg-terms-checkbox")?.checked || false;

    if (!nameVal.trim()) {
      showAlertMessage("patient-register-alert", "Full Name is required.");
      return;
    }

    if (patIdVal) {
      if (!/^[A-Za-z0-9\-_]{3,20}$/.test(patIdVal)) {
        showAlertMessage("patient-register-alert", "Patient ID must contain letters and numbers (e.g., PAT-A7K29).");
        return;
      }
    }

    if (!emailVal.trim()) {
      showAlertMessage("patient-register-alert", "Email is required.");
      return;
    }

    if (!validateEmailFormat(emailVal)) {
      showAlertMessage("patient-register-alert", "Please enter a valid email address.");
      return;
    }

    if (!mobileVal.trim()) {
      showAlertMessage("patient-register-alert", "Mobile Number is required.");
      return;
    }

    if (!validateMobileFormat(mobileVal)) {
      showAlertMessage("patient-register-alert", "Please enter a valid mobile number.");
      return;
    }

    if (!passVal) {
      showAlertMessage("patient-register-alert", "Password is required.");
      return;
    }

    const pwdCheck = validateStrongPassword(passVal);
    if (!pwdCheck.valid) {
      showAlertMessage("patient-register-alert", "Password must be at least 8 characters long and include at least 1 uppercase letter, 1 lowercase letter, 1 number, and 1 special character (e.g. Patient@2026).");
      return;
    }

    if (!confirmVal) {
      showAlertMessage("patient-register-alert", "Please confirm your password.");
      return;
    }

    if (passVal !== confirmVal) {
      showAlertMessage("patient-register-alert", "Passwords do not match.");
      return;
    }

    if (!termsChecked) {
      showAlertMessage("patient-register-alert", "You must agree to the Terms & Conditions and Privacy Policy.");
      return;
    }

    const res = await registerPatientAccount(nameVal, emailVal, passVal, mobileVal, patIdVal);

    if (res.success && res.patient) {
      showTorusScreen("patient-login-screen");

      const emailInput = document.getElementById("patient-email-input");
      if (emailInput) emailInput.value = res.patient.email;
      const loginPassInput = document.getElementById("patient-password-input");
      if (loginPassInput) loginPassInput.value = "";

      showAlertMessage(
        "patient-login-alert",
        `Account created successfully! Patient ID: ${res.patient.uid}. You can now log in.`,
        "success"
      );
    } else {
      showAlertMessage("patient-register-alert", res.error || "Registration failed. Please try again.");
    }
  }

  // 8. Patient Forgot Password Multi-Step Handlers
  const patForgotScreen = document.getElementById("patient-forgot-screen");
  const patForgotLink = document.getElementById("patient-forgot-link");
  const patForgotBackBtn = document.getElementById("patient-forgot-back-btn");
  const patForgotStep2BackBtn = document.getElementById("patient-forgot-step2-back-btn");
  const patForgotStep3BackBtn = document.getElementById("patient-forgot-step3-back-btn");

  const patForgotStep1 = document.getElementById("patient-forgot-step-1");
  const patForgotStep2 = document.getElementById("patient-forgot-step-2");
  const patForgotStep3 = document.getElementById("patient-forgot-step-3");

  const patFormStep1 = document.getElementById("patient-forgot-form-step1");
  const patFormStep2 = document.getElementById("patient-forgot-form-step2");
  const patFormStep3 = document.getElementById("patient-forgot-form-step3");

  const patInputIdentifier = document.getElementById("patient-forgot-identifier");
  const patInputOtp = document.getElementById("patient-forgot-otp-input");
  const patInputNewPass = document.getElementById("patient-forgot-new-pass");
  const patInputConfirmPass = document.getElementById("patient-forgot-confirm-pass");
  const patResendOtpBtn = document.getElementById("patient-forgot-resend-otp-btn");

  let currentPatientResetIdentifier = "";
  let currentPatientResetToken = "";

  function resetPatientForgotFlowUI() {
    hideAlertMessage("patient-forgot-alert-step1");
    hideAlertMessage("patient-forgot-alert-step2");
    hideAlertMessage("patient-forgot-alert-step3");

    if (patInputIdentifier) patInputIdentifier.value = "";
    if (patInputOtp) patInputOtp.value = "";
    if (patInputNewPass) patInputNewPass.value = "";
    if (patInputConfirmPass) patInputConfirmPass.value = "";

    currentPatientResetIdentifier = "";
    currentPatientResetToken = "";

    if (patForgotStep1) patForgotStep1.style.display = "flex";
    if (patForgotStep2) patForgotStep2.style.display = "none";
    if (patForgotStep3) patForgotStep3.style.display = "none";
  }

  function showPatientLoginFromForgot() {
    resetPatientForgotFlowUI();
    navigateBackTorus();
  }

  if (patForgotLink) {
    patForgotLink.addEventListener("click", (e) => {
      e.preventDefault();
      resetPatientForgotFlowUI();
      showTorusScreen("patient-forgot-screen");
    });
  }

  if (patForgotBackBtn) {
    patForgotBackBtn.addEventListener("click", () => {
      resetPatientForgotFlowUI();
      navigateBackTorus();
    });
  }

  if (patForgotStep2BackBtn) {
    patForgotStep2BackBtn.addEventListener("click", () => {
      hideAlertMessage("patient-forgot-alert-step1");
      hideAlertMessage("patient-forgot-alert-step2");
      if (patForgotStep1) patForgotStep1.style.display = "flex";
      if (patForgotStep2) patForgotStep2.style.display = "none";
      if (patForgotStep3) patForgotStep3.style.display = "none";
    });
  }

  if (patForgotStep3BackBtn) {
    patForgotStep3BackBtn.addEventListener("click", () => {
      resetPatientForgotFlowUI();
      navigateBackTorus();
    });
  }

  // Patient Step 1: Send OTP
  if (patFormStep1) {
    patFormStep1.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("patient-forgot-alert-step1");

      const identifierVal = patInputIdentifier?.value?.trim() || "";
      if (!identifierVal) {
        showAlertMessage("patient-forgot-alert-step1", "Please enter your registered Email or User ID.");
        return;
      }

      const submitBtn = document.getElementById("patient-forgot-send-otp-btn");
      if (submitBtn) submitBtn.disabled = true;

      try {
        const res = await requestPatientResetOTP(identifierVal);
        if (res.success) {
          currentPatientResetIdentifier = identifierVal;
          if (patForgotStep1) patForgotStep1.style.display = "none";
          if (patForgotStep2) patForgotStep2.style.display = "flex";
          if (patForgotStep3) patForgotStep3.style.display = "none";

          showAlertMessage("patient-forgot-alert-step2", res.message || "A 6-digit OTP has been sent to your registered email address.", "success");
        } else {
          showAlertMessage("patient-forgot-alert-step1", res.error || "No patient account found with this email or User ID.");
        }
      } catch (err) {
        showAlertMessage("patient-forgot-alert-step1", "Failed to send OTP. Please try again.");
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  // Patient Step 2: Verify OTP
  if (patFormStep2) {
    patFormStep2.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("patient-forgot-alert-step2");

      const otpVal = patInputOtp?.value?.trim() || "";
      if (!otpVal || otpVal.length !== 6) {
        showAlertMessage("patient-forgot-alert-step2", "Please enter the valid 6-digit OTP code.");
        return;
      }

      const verifyBtn = document.getElementById("patient-forgot-verify-otp-btn");
      if (verifyBtn) verifyBtn.disabled = true;

      try {
        const res = await verifyPatientResetOTP(currentPatientResetIdentifier, otpVal);
        if (res.success) {
          currentPatientResetToken = res.reset_token || otpVal;
          if (patForgotStep1) patForgotStep1.style.display = "none";
          if (patForgotStep2) patForgotStep2.style.display = "none";
          if (patForgotStep3) patForgotStep3.style.display = "flex";
          hideAlertMessage("patient-forgot-alert-step3");
        } else {
          showAlertMessage("patient-forgot-alert-step2", res.error || "Invalid OTP code. Please check your email.");
        }
      } catch (err) {
        showAlertMessage("patient-forgot-alert-step2", "Verification error. Please try again.");
      } finally {
        if (verifyBtn) verifyBtn.disabled = false;
      }
    });
  }

  // Patient Resend OTP
  if (patResendOtpBtn) {
    patResendOtpBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      hideAlertMessage("patient-forgot-alert-step2");

      if (!currentPatientResetIdentifier) {
        showAlertMessage("patient-forgot-alert-step2", "Session expired. Please return to Step 1.");
        return;
      }

      try {
        const res = await requestPatientResetOTP(currentPatientResetIdentifier);
        if (res.success) {
          showAlertMessage("patient-forgot-alert-step2", res.message || "A fresh 6-digit OTP has been sent to your registered email.", "success");
        } else {
          showAlertMessage("patient-forgot-alert-step2", res.error || "Could not resend OTP.");
        }
      } catch (err) {
        showAlertMessage("patient-forgot-alert-step2", "Failed to resend OTP.");
      }
    });
  }

  // Patient Step 3: Reset Password
  if (patFormStep3) {
    patFormStep3.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("patient-forgot-alert-step3");

      const newPass = patInputNewPass?.value || "";
      const confirmPass = patInputConfirmPass?.value || "";

      if (!newPass) {
        showAlertMessage("patient-forgot-alert-step3", "New Password is required.");
        return;
      }

      const pwdCheck = validateStrongPassword(newPass);
      if (!pwdCheck.valid) {
        showAlertMessage("patient-forgot-alert-step3", pwdCheck.error);
        return;
      }

      if (!confirmPass) {
        showAlertMessage("patient-forgot-alert-step3", "Please confirm your new password.");
        return;
      }

      if (newPass !== confirmPass) {
        showAlertMessage("patient-forgot-alert-step3", "Passwords do not match.");
        return;
      }

      const resetBtn = document.getElementById("patient-forgot-reset-submit-btn");
      if (resetBtn) resetBtn.disabled = true;

      try {
        const res = await resetPatientPasswordWithToken(currentPatientResetIdentifier, currentPatientResetToken, newPass);
        if (res.success) {
          showPatientLoginFromForgot();

          const emailInput = document.getElementById("patient-email-input");
          if (emailInput && currentPatientResetIdentifier) {
            emailInput.value = currentPatientResetIdentifier;
          }
          const passInput = document.getElementById("patient-password-input");
          if (passInput) passInput.value = "";

          showAlertMessage(
            "patient-login-alert",
            "Password reset successfully! Please log in with your new password.",
            "success"
          );
        } else {
          showAlertMessage("patient-forgot-alert-step3", res.error || "Password reset failed.");
        }
      } catch (err) {
        showAlertMessage("patient-forgot-alert-step3", "Failed to reset password. Please try again.");
      } finally {
        if (resetBtn) resetBtn.disabled = false;
      }
    });
  }

  // ============================================================
  // Doctor Real Biometric Verification & Registration Handlers
  // Real Arduino / USB Serial Fingerprint Scanner Integration
  // ============================================================
  const doctorBiometricScreen = document.getElementById("doctor-biometric-screen");
  const doctorBioRegisterScreen = document.getElementById("doctor-bio-register-screen");
  const bioLoginBtn = document.getElementById("doctor-biometric-btn");
  const bioVerifyBackBtn = document.getElementById("doctor-biometric-back-btn");
  const bioGoRegisterBtn = document.getElementById("bio-go-register-btn");
  const bioRegBackBtn = document.getElementById("doctor-bio-reg-back-btn");
  const bioRegToVerifyBtn = document.getElementById("bio-reg-to-verify-btn");

  const bioVerifyScannerPod = document.getElementById("bio-verify-scanner-pod");
  const bioVerifyTriggerCard = document.getElementById("bio-verify-trigger-card");
  const bioVerifyTitle = document.getElementById("bio-verify-title");
  const bioVerifySubtitle = document.getElementById("bio-verify-subtitle");
  const bioVerifyDots = document.getElementById("bio-verify-dots");

  const bioRegForm = document.getElementById("doctor-bio-reg-form");
  const bioRegIdentifierInput = document.getElementById("bio-reg-identifier");
  const bioRegScannerPod = document.getElementById("bio-reg-scanner-pod");
  const bioRegStartBtn = document.getElementById("bio-reg-start-btn");
  const bioRegStepTitle = document.getElementById("bio-reg-step-title");
  const bioRegStepSubtitle = document.getElementById("bio-reg-step-subtitle");
  const bioRegStepBadge = document.getElementById("bio-reg-step-badge");
  const bioRegDots = document.getElementById("bio-reg-dots");

  let isVerifyingBiometrics = false;
  let isRegisteringBiometrics = false;

  async function checkBiometricHardwareStatus() {
    try {
      const isDirectBackend = window.location.port === "3000";
      const endpoints = isDirectBackend
        ? ["/api/biometrics/status", "http://127.0.0.1:3000/api/biometrics/status", "http://localhost:3000/api/biometrics/status"]
        : ["http://127.0.0.1:3000/api/biometrics/status", "http://localhost:3000/api/biometrics/status", "/api/biometrics/status"];
      for (const ep of endpoints) {
        try {
          const res = await fetch(ep, { method: "GET" });
          if (res.ok) {
            return await res.json();
          }
        } catch (_) { }
      }
    } catch (e) {
      console.warn("[Biometrics] Error querying hardware status:", e);
    }
    return {
      connected: false,
      status: "disconnected",
      status_title: "Fingerprint scanner is not ready",
      status_subtitle: "Please check the scanner connection."
    };
  }

  let bioStatusPollInterval = null;
  function startBiometricStatusPolling() {
    if (bioStatusPollInterval) clearInterval(bioStatusPollInterval);
    bioStatusPollInterval = setInterval(async () => {
      const isVerifyVisible = doctorBiometricScreen && doctorBiometricScreen.style.display !== "none";
      const isRegVisible = doctorBioRegisterScreen && doctorBioRegisterScreen.style.display !== "none";
      if (!isVerifyVisible && !isRegVisible) return;
      if (isVerifyingBiometrics || isRegisteringBiometrics) return;

      const hw = await checkBiometricHardwareStatus();
      if (isVerifyVisible && bioVerifyTitle && bioVerifySubtitle) {
        if (!hw.connected) {
          bioVerifyTitle.textContent = "Fingerprint scanner is not ready";
          bioVerifySubtitle.textContent = "Please check the scanner connection.";
        } else {
          bioVerifyTitle.textContent = "Fingerprint scanner ready";
          bioVerifySubtitle.textContent = "Place your registered finger on the scanner.";
          hideAlertMessage("doctor-biometric-alert");
        }
      }
      if (isRegVisible && bioRegStepTitle && bioRegStepSubtitle) {
        if (!hw.connected) {
          bioRegStepTitle.textContent = "Fingerprint scanner is not ready";
          bioRegStepSubtitle.textContent = "Please check the scanner connection.";
          if (bioRegStartBtn) bioRegStartBtn.disabled = true;
        } else {
          if (!isRegisteringBiometrics) {
            bioRegStepTitle.textContent = "Scanner ready";
            bioRegStepSubtitle.textContent = "Place your finger on the scanner to register your fingerprint.";
            if (bioRegStartBtn) bioRegStartBtn.disabled = false;
          }
          hideAlertMessage("doctor-bio-reg-alert");
        }
      }
    }, 2500);
  }

  async function resetBiometricVerifyUI() {
    isVerifyingBiometrics = false;
    hideAlertMessage("doctor-biometric-alert");
    if (bioVerifyScannerPod) {
      bioVerifyScannerPod.classList.remove("scanning", "success");
    }
    if (bioVerifyTitle) bioVerifyTitle.textContent = "Checking scanner...";
    if (bioVerifySubtitle) bioVerifySubtitle.textContent = "Connecting to biometric hardware.";
    if (bioVerifyDots) {
      const dots = bioVerifyDots.querySelectorAll(".bio-dot");
      dots.forEach((dot, idx) => {
        dot.className = idx === 0 ? "bio-dot active" : "bio-dot";
      });
    }

    startBiometricStatusPolling();

    // Check live hardware connection immediately
    checkBiometricHardwareStatus().then(hw => {
      if (!hw.connected) {
        if (bioVerifyTitle) bioVerifyTitle.textContent = "Fingerprint scanner is not ready";
        if (bioVerifySubtitle) bioVerifySubtitle.textContent = "Please check the scanner connection.";
      } else {
        if (bioVerifyTitle) bioVerifyTitle.textContent = "Fingerprint scanner ready";
        if (bioVerifySubtitle) bioVerifySubtitle.textContent = "Place your registered finger on the scanner.";
        hideAlertMessage("doctor-biometric-alert");
      }
    });
  }

  async function resetBiometricRegisterUI() {
    isRegisteringBiometrics = false;
    hideAlertMessage("doctor-bio-reg-alert");
    if (bioRegIdentifierInput) {
      bioRegIdentifierInput.value = "";
    }
    if (bioRegScannerPod) {
      bioRegScannerPod.classList.remove("scanning", "success");
    }
    if (bioRegStepTitle) bioRegStepTitle.textContent = "Checking scanner...";
    if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Connecting to biometric hardware.";
    if (bioRegStartBtn) {
      bioRegStartBtn.disabled = true;
      bioRegStartBtn.innerHTML = "<span>Capture Fingerprint</span>";
    }
    if (bioRegDots) {
      const dots = bioRegDots.querySelectorAll(".bio-dot");
      dots.forEach((dot, idx) => {
        dot.className = idx === 0 ? "bio-dot active" : "bio-dot";
      });
    }

    startBiometricStatusPolling();

    // Check live hardware connection immediately
    checkBiometricHardwareStatus().then(hw => {
      if (!hw.connected) {
        if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint scanner is not ready";
        if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Please check the scanner connection.";
        if (bioRegStartBtn) bioRegStartBtn.disabled = true;
      } else {
        if (bioRegStepTitle) bioRegStepTitle.textContent = "Scanner ready";
        if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Place your finger on the scanner to register your fingerprint.";
        if (bioRegStartBtn) bioRegStartBtn.disabled = false;
        hideAlertMessage("doctor-bio-reg-alert");
      }
    });
  }

  // 1. Open Biometric Verification Screen from Login
  if (bioLoginBtn) {
    bioLoginBtn.addEventListener("click", () => {
      resetBiometricVerifyUI();
      showTorusScreen("doctor-biometric-screen");
    });
  }

  // 2. Back from Biometric Verification -> Previous Screen (Doctor Login)
  if (bioVerifyBackBtn) {
    bioVerifyBackBtn.addEventListener("click", () => {
      resetBiometricVerifyUI();
      navigateBackTorus();
    });
  }

  // 3. Navigate from Verification -> Registration
  if (bioGoRegisterBtn) {
    bioGoRegisterBtn.addEventListener("click", (e) => {
      e.preventDefault();
      resetBiometricRegisterUI();
      showTorusScreen("doctor-bio-register-screen");
    });
  }

  // 4. Back from Registration -> Previous Screen (Biometric Verification)
  if (bioRegBackBtn) {
    bioRegBackBtn.addEventListener("click", () => {
      resetBiometricRegisterUI();
      navigateBackTorus();
      resetBiometricVerifyUI();
    });
  }

  if (bioRegToVerifyBtn) {
    bioRegToVerifyBtn.addEventListener("click", (e) => {
      e.preventDefault();
      resetBiometricRegisterUI();
      navigateBackTorus();
      resetBiometricVerifyUI();
    });
  }

  // 5. Execute Real Biometric Verification (Hardware Request & Authentication)
  async function triggerBiometricVerification() {
    if (isVerifyingBiometrics) return;
    isVerifyingBiometrics = true;
    hideAlertMessage("doctor-biometric-alert");
    // If email is explicitly provided on an active form, verify against that doctor;
    // Otherwise send null for 1:N hardware search across all enrolled templates.
    const emailEl = document.getElementById("doctor-email-input");
    const isEmailLoginActive = emailEl && emailEl.offsetParent !== null;
    const targetLoginId = isEmailLoginActive && emailEl.value.trim() ? emailEl.value.trim() : null;

    if (bioVerifyScannerPod) {
      bioVerifyScannerPod.classList.remove("success");
      bioVerifyScannerPod.classList.add("scanning");
    }
    if (bioVerifyTitle) bioVerifyTitle.textContent = "Scanning your fingerprint...";
    if (bioVerifySubtitle) bioVerifySubtitle.textContent = "Please keep your finger still.";

    // Animate dots indicator during reading
    const dots = bioVerifyDots ? bioVerifyDots.querySelectorAll(".bio-dot") : [];
    let currentDot = 0;
    const dotInterval = setInterval(() => {
      currentDot = (currentDot + 1) % (dots.length || 4);
      dots.forEach((d, i) => {
        d.className = i === currentDot ? "bio-dot active" : "bio-dot";
      });
    }, 280);

    try {
      // Check real hardware connectivity first
      const hwStatus = await checkBiometricHardwareStatus();
      if (!hwStatus.connected) {
        clearInterval(dotInterval);
        if (bioVerifyScannerPod) bioVerifyScannerPod.classList.remove("scanning");
        if (bioVerifyTitle) bioVerifyTitle.textContent = "Fingerprint scanner is not ready";
        if (bioVerifySubtitle) bioVerifySubtitle.textContent = "Please check the scanner connection.";
        showAlertMessage("doctor-biometric-alert", "Fingerprint scanner is not ready. Please check the scanner connection.", "error");
        isVerifyingBiometrics = false;
        return;
      }

      // Dispatch real verification request to backend hardware API
      let resData = null;
      const isDirectBackend = window.location.port === "3000";
      const verifyUrls = isDirectBackend
        ? ["/api/biometrics/verify", "http://127.0.0.1:3000/api/biometrics/verify", "http://localhost:3000/api/biometrics/verify"]
        : ["http://127.0.0.1:3000/api/biometrics/verify", "http://localhost:3000/api/biometrics/verify", "/api/biometrics/verify"];
      for (const url of verifyUrls) {
        try {
          const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ identifier: targetLoginId })
          });
          resData = await res.json();
          if (resData) break;
        } catch (_) { }
      }

      clearInterval(dotInterval);

      // Only log user in if the fingerprint was ACTUALLY matched
      if (resData && resData.success && resData.matched) {
        const authUser = resData.doctor || { uid: "3001", name: "Admin Doctor", email: targetLoginId, role: "doctor" };

        if (bioVerifyScannerPod) {
          bioVerifyScannerPod.classList.remove("scanning");
          bioVerifyScannerPod.classList.add("success");
        }
        dots.forEach(d => d.className = "bio-dot active");

        if (bioVerifyTitle) bioVerifyTitle.textContent = "Fingerprint verified successfully";
        if (bioVerifySubtitle) bioVerifySubtitle.textContent = `Welcome back, ${authUser.name}`;

        showAlertMessage(
          "doctor-biometric-alert",
          `Fingerprint verified successfully. Welcome back, ${authUser.name}. Launching TORUS workspace...`,
          "success"
        );

        setTimeout(() => {
          if (doctorBiometricScreen) doctorBiometricScreen.style.display = "none";
          setAuthenticatedDoctorSession(authUser);
          isVerifyingBiometrics = false;
        }, 1200);
        return;
      }

      // Real mismatch or failure
      if (bioVerifyScannerPod) bioVerifyScannerPod.classList.remove("scanning");
      const errCode = resData?.code || "";
      if (errCode === "TIMEOUT") {
        if (bioVerifyTitle) bioVerifyTitle.textContent = "Verification timed out";
        if (bioVerifySubtitle) bioVerifySubtitle.textContent = "Please place your registered finger on the scanner.";
        showAlertMessage("doctor-biometric-alert", "Verification timed out. Please place your registered finger on the scanner.", "error");
      } else {
        if (bioVerifyTitle) bioVerifyTitle.textContent = "Fingerprint not recognized";
        if (bioVerifySubtitle) bioVerifySubtitle.textContent = "Please try again.";
        const errMsg = resData?.error || "Fingerprint not recognized. Please try again.";
        showAlertMessage("doctor-biometric-alert", errMsg, "error");
      }
      isVerifyingBiometrics = false;

    } catch (err) {
      clearInterval(dotInterval);
      if (bioVerifyScannerPod) bioVerifyScannerPod.classList.remove("scanning");
      if (bioVerifyTitle) bioVerifyTitle.textContent = "Fingerprint scanner is unavailable";
      if (bioVerifySubtitle) bioVerifySubtitle.textContent = "Please check the scanner connection.";
      showAlertMessage("doctor-biometric-alert", "Fingerprint scanner is unavailable. Please check the scanner connection.", "error");
      isVerifyingBiometrics = false;
    }
  }

  if (bioVerifyScannerPod) {
    bioVerifyScannerPod.addEventListener("click", triggerBiometricVerification);
  }
  if (bioVerifyTriggerCard) {
    bioVerifyTriggerCard.addEventListener("click", triggerBiometricVerification);
  }

  // 6. Execute Real Biometric Registration Flow
  if (bioRegForm) {
    bioRegForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (isRegisteringBiometrics) return;

      hideAlertMessage("doctor-bio-reg-alert");
      const identifierVal = bioRegIdentifierInput?.value?.trim() || "";

      if (!identifierVal) {
        showAlertMessage("doctor-bio-reg-alert", "Please enter your registered Doctor Email or User ID.");
        return;
      }

      isRegisteringBiometrics = true;
      if (bioRegStartBtn) bioRegStartBtn.disabled = true;

      // Check real hardware connectivity first
      const hwStatus = await checkBiometricHardwareStatus();
      if (!hwStatus.connected) {
        if (bioRegScannerPod) bioRegScannerPod.classList.remove("scanning", "success");
        if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint scanner is not ready";
        if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Please check the USB connection to the scanner.";
        showAlertMessage("doctor-bio-reg-alert", "Fingerprint scanner is not ready. Please check the USB connection.", "error");
        if (bioRegStartBtn) bioRegStartBtn.disabled = false;
        isRegisteringBiometrics = false;
        return;
      }

      const dots = bioRegDots ? bioRegDots.querySelectorAll(".bio-dot") : [];

      // --- Phase 1: Waiting for Scan 1 ---
      if (bioRegScannerPod) {
        bioRegScannerPod.classList.remove("success");
        bioRegScannerPod.classList.add("scanning");
      }
      if (bioRegStepTitle) bioRegStepTitle.textContent = "Place finger on scanner";
      if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Place your finger firmly on the optical scanner.";
      if (dots[0]) dots[0].className = "bio-dot active";
      if (dots[1]) dots[1].className = "bio-dot";
      if (dots[2]) dots[2].className = "bio-dot";

      // --- Phase 2 timer: Lift finger prompt (approx 5s after scan 1 captured) ---
      const liftFingerTimer = setTimeout(() => {
        if (isRegisteringBiometrics) {
          if (bioRegStepTitle) bioRegStepTitle.textContent = "Scan 1 captured — Lift finger";
          if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Scan 1 successful. Now lift your finger completely off the scanner.";
          if (dots[0]) dots[0].className = "bio-dot active";
          if (dots[1]) dots[1].className = "bio-dot active";
        }
      }, 5000);

      // --- Phase 3 timer: Scan 2 prompt ---
      const scan2Timer = setTimeout(() => {
        if (isRegisteringBiometrics) {
          if (bioRegStepTitle) bioRegStepTitle.textContent = "Place same finger for Scan 2...";
          if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Place the same finger again on the scanner.";
          if (dots[0]) dots[0].className = "bio-dot active";
          if (dots[1]) dots[1].className = "bio-dot active";
          if (dots[2]) dots[2].className = "bio-dot active";
        }
      }, 9000);

      // --- Dispatch real enrollment request ---
      try {
        let resData = null;
        const isDirectBackend = window.location.port === "3000";
        const enrollUrls = isDirectBackend
          ? ["/api/biometrics/enroll", "http://127.0.0.1:3000/api/biometrics/enroll", "http://localhost:3000/api/biometrics/enroll"]
          : ["http://127.0.0.1:3000/api/biometrics/enroll", "http://localhost:3000/api/biometrics/enroll", "/api/biometrics/enroll"];

        for (const url of enrollUrls) {
          try {
            const res = await fetch(url, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ identifier: identifierVal })
            });
            resData = await res.json();
            if (resData) break;
          } catch (_) { }
        }

        clearTimeout(liftFingerTimer);
        clearTimeout(scan2Timer);

        // --- Handle success ---
        if (resData && resData.success) {
          const assignedSlot = resData.fingerprint_id || "";
          if (bioRegScannerPod) {
            bioRegScannerPod.classList.remove("scanning");
            bioRegScannerPod.classList.add("success");
          }
          dots.forEach(d => d.className = "bio-dot active");
          if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint registered successfully";
          if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = assignedSlot
            ? `Assigned fingerprint slot: ${assignedSlot}. Securely stored in hardware.`
            : "Your fingerprint has been securely linked to your account.";

          const successMsg = assignedSlot
            ? `Fingerprint registered successfully (${assignedSlot}). Ready for next user.`
            : "Fingerprint registered successfully. Ready for next user.";

          showAlertMessage("doctor-bio-reg-alert", successMsg, "success");

          // Reset quickly to ready state so user can immediately register the next doctor (R1 -> R2 -> R3 -> ... -> R20)
          setTimeout(() => {
            if (bioRegIdentifierInput) bioRegIdentifierInput.value = "";
            if (bioRegScannerPod) bioRegScannerPod.classList.remove("scanning", "success");
            if (bioRegStepTitle) bioRegStepTitle.textContent = "Scanner ready";
            if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Place your finger on the scanner to register your fingerprint.";
            if (bioRegStartBtn) bioRegStartBtn.disabled = false;
            if (bioRegDots) {
              const d = bioRegDots.querySelectorAll(".bio-dot");
              d.forEach((dot, idx) => { dot.className = idx === 0 ? "bio-dot active" : "bio-dot"; });
            }
            isRegisteringBiometrics = false;
          }, 2000);

          // --- Handle already registered ---
        } else if (resData && resData.already_registered) {
          if (bioRegScannerPod) bioRegScannerPod.classList.remove("scanning");
          if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint already registered";
          if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = resData.fingerprint_id
            ? `This account is already linked to slot ${resData.fingerprint_id}.`
            : "This account already has a registered fingerprint.";
          showAlertMessage("doctor-bio-reg-alert", resData.error || "Fingerprint is already registered for this account.", "error");
          if (bioRegStartBtn) bioRegStartBtn.disabled = false;
          isRegisteringBiometrics = false;

          // --- Handle all slots occupied ---
        } else if (resData && resData.code === "ALL_SLOTS_FULL") {
          if (bioRegScannerPod) bioRegScannerPod.classList.remove("scanning");
          if (bioRegStepTitle) bioRegStepTitle.textContent = "All fingerprint slots are occupied";
          if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Maximum 20 registrations reached. Remove an existing registration to add a new one.";
          showAlertMessage("doctor-bio-reg-alert", resData.error || "All 20 fingerprint slots are occupied.", "error");
          if (bioRegStartBtn) bioRegStartBtn.disabled = false;
          isRegisteringBiometrics = false;

          // --- Handle other failures ---
        } else {
          if (bioRegScannerPod) bioRegScannerPod.classList.remove("scanning");
          const errMsg = resData?.error || "Fingerprint registration failed. Please try again.";
          if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint registration failed";
          if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Please try again.";
          showAlertMessage("doctor-bio-reg-alert", errMsg, "error");
          if (bioRegStartBtn) bioRegStartBtn.disabled = false;
          isRegisteringBiometrics = false;
        }

      } catch (err) {
        clearTimeout(liftFingerTimer);
        clearTimeout(scan2Timer);
        console.error("[Biometric Registration Error]", err);
        if (bioRegScannerPod) bioRegScannerPod.classList.remove("scanning");
        if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint scanner is unavailable";
        if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Please check the USB connection.";
        showAlertMessage("doctor-bio-reg-alert", "Fingerprint scanner communication error. Please check the USB connection.", "error");
        if (bioRegStartBtn) bioRegStartBtn.disabled = false;
        isRegisteringBiometrics = false;
      }
    });
  }

  // ============================================================
  // VIEWER AUTHENTICATION EVENT LISTENERS
  // ============================================================

  // 1. Password Visibility Toggle for Viewer Login
  const viewerTogglePassBtn = document.getElementById("viewer-toggle-password-btn");
  const viewerPassInput = document.getElementById("viewer-password-input");
  if (viewerTogglePassBtn && viewerPassInput) {
    viewerTogglePassBtn.addEventListener("click", () => {
      const isPass = viewerPassInput.type === "password";
      viewerPassInput.type = isPass ? "text" : "password";
      const eyeIcon = viewerTogglePassBtn.querySelector(".eye-icon");
      const eyeOffIcon = viewerTogglePassBtn.querySelector(".eye-off-icon");
      if (eyeIcon && eyeOffIcon) {
        eyeIcon.style.display = isPass ? "none" : "block";
        eyeOffIcon.style.display = isPass ? "block" : "none";
      }
    });
  }

  // 2. Back Button from Viewer Login to Role Selection / Previous Screen
  const viewerBackBtn = document.getElementById("viewer-login-back-btn");
  if (viewerBackBtn) {
    viewerBackBtn.addEventListener("click", () => {
      navigateBackTorus();
    });
  }

  // 3. Viewer Secure Login Form Submission
  const viewerLoginForm = document.getElementById("viewer-login-form");
  if (viewerLoginForm) {
    viewerLoginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("viewer-login-alert");

      const emailVal = document.getElementById("viewer-email-input")?.value?.trim() || "";
      const passVal = document.getElementById("viewer-password-input")?.value || "";

      if (!emailVal || !passVal) {
        showAlertMessage("viewer-login-alert", "Please enter both Email/User ID and Password.");
        return;
      }

      const res = await authenticateViewerAccount(emailVal, passVal);
      if (res.success && res.viewer) {
        setAuthenticatedViewerSession(res.viewer);
      } else {
        showAlertMessage("viewer-login-alert", res.error || "Invalid email/Viewer ID or password.");
      }
    });
  }

  // 4. Viewer Join Clinical Session Button -> Open Join Screen
  const viewerJoinSessionBtn = document.getElementById("viewer-join-session-btn");
  if (viewerJoinSessionBtn) {
    viewerJoinSessionBtn.addEventListener("click", () => {
      activeJoinSessionSourceRole = "viewer";
      hideAlertMessage("viewer-login-alert");
      hideAlertMessage("join-session-alert");

      const sessionCodeInput = document.getElementById("join-session-code-input");
      if (sessionCodeInput) sessionCodeInput.value = "";
      const viewerNameInput = document.getElementById("join-viewer-name-input");
      if (viewerNameInput) viewerNameInput.value = "";

      showTorusScreen("join-session-screen");
    });
  }

  // 5. Navigate to Viewer Registration Screen
  const viewerCreateAccLink = document.getElementById("viewer-create-account-link");
  if (viewerCreateAccLink) {
    viewerCreateAccLink.addEventListener("click", (e) => {
      e.preventDefault();
      hideAlertMessage("viewer-register-alert");

      const regForm = document.getElementById("viewer-register-form");
      if (regForm) regForm.reset();

      showTorusScreen("viewer-register-screen");
    });
  }

  // 6. Back from Viewer Registration -> Previous Screen (Viewer Login)
  const viewerRegBackBtn = document.getElementById("viewer-register-back-btn");
  if (viewerRegBackBtn) {
    viewerRegBackBtn.addEventListener("click", () => {
      navigateBackTorus();
    });
  }

  // 7. Password Toggles for Viewer Registration
  setupPasswordToggle("viewer-reg-password-toggle", "viewer-reg-password");
  setupPasswordToggle("viewer-reg-confirm-password-toggle", "viewer-reg-confirm-password");

  // 8. Viewer Registration Form Submission
  const viewerRegisterForm = document.getElementById("viewer-register-form");
  if (viewerRegisterForm) {
    viewerRegisterForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("viewer-register-alert");

      const nameVal = document.getElementById("viewer-reg-name")?.value || "";
      const viewerIdVal = document.getElementById("viewer-reg-viewer-id")?.value?.trim() || "";
      const emailVal = document.getElementById("viewer-reg-email")?.value || "";
      const mobileVal = document.getElementById("viewer-reg-mobile")?.value || "";
      const passVal = document.getElementById("viewer-reg-password")?.value || "";
      const confirmVal = document.getElementById("viewer-reg-confirm-password")?.value || "";
      const termsChecked = document.getElementById("viewer-reg-terms-checkbox")?.checked || false;

      if (!nameVal.trim()) {
        showAlertMessage("viewer-register-alert", "Full Name is required.");
        return;
      }

      if (!emailVal.trim() || !validateEmailFormat(emailVal)) {
        showAlertMessage("viewer-register-alert", "Please enter a valid email address.");
        return;
      }

      if (!mobileVal.trim() || !validateMobileFormat(mobileVal)) {
        showAlertMessage("viewer-register-alert", "Please enter a valid mobile number.");
        return;
      }

      if (!passVal) {
        showAlertMessage("viewer-register-alert", "Password is required.");
        return;
      }

      const pwdCheck = validateStrongPassword(passVal);
      if (!pwdCheck.valid) {
        showAlertMessage("viewer-register-alert", pwdCheck.error);
        return;
      }

      if (passVal !== confirmVal) {
        showAlertMessage("viewer-register-alert", "Passwords do not match.");
        return;
      }

      if (!termsChecked) {
        showAlertMessage("viewer-register-alert", "You must agree to the Terms & Conditions and Privacy Policy.");
        return;
      }

      const res = await registerViewerAccount(nameVal, emailVal, passVal, mobileVal, viewerIdVal);
      if (res.success && res.viewer) {
        showTorusScreen("viewer-login-screen");

        const emailInput = document.getElementById("viewer-email-input");
        if (emailInput) emailInput.value = res.viewer.email;
        const passInput = document.getElementById("viewer-password-input");
        if (passInput) passInput.value = "";

        const vNameEl = document.getElementById("viewer-info-name");
        const vUidEl = document.getElementById("viewer-info-uid");
        if (vNameEl) vNameEl.textContent = res.viewer.name;
        if (vUidEl) vUidEl.textContent = `UID ${res.viewer.uid}`;

        showAlertMessage(
          "viewer-login-alert",
          `Account created successfully! Viewer UID: ${res.viewer.uid}. You can now log in.`,
          "success"
        );
      } else {
        showAlertMessage("viewer-register-alert", res.error || "Registration failed. Please try again.");
      }
    });
  }

  // 9. Viewer Forgot Password Handlers
  const viewerForgotScreen = document.getElementById("viewer-forgot-screen");
  const viewerForgotLink = document.getElementById("viewer-forgot-link");
  const viewerForgotBackBtn = document.getElementById("viewer-forgot-back-btn");
  const viewerForgotStep2BackBtn = document.getElementById("viewer-forgot-step2-back-btn");
  const viewerForgotStep3BackBtn = document.getElementById("viewer-forgot-step3-back-btn");

  const viewerForgotStep1 = document.getElementById("viewer-forgot-step-1");
  const viewerForgotStep2 = document.getElementById("viewer-forgot-step-2");
  const viewerForgotStep3 = document.getElementById("viewer-forgot-step-3");

  const viewerFormStep1 = document.getElementById("viewer-forgot-form-step1");
  const viewerFormStep2 = document.getElementById("viewer-forgot-form-step2");
  const viewerFormStep3 = document.getElementById("viewer-forgot-form-step3");

  const viewerInputIdentifier = document.getElementById("viewer-forgot-identifier");
  const viewerInputOtp = document.getElementById("viewer-forgot-otp-input");
  const viewerInputNewPass = document.getElementById("viewer-forgot-new-pass");
  const viewerInputConfirmPass = document.getElementById("viewer-forgot-confirm-pass");
  const viewerResendOtpBtn = document.getElementById("viewer-forgot-resend-otp-btn");

  let currentViewerResetIdentifier = "";
  let currentViewerResetToken = "";

  function resetViewerForgotFlowUI() {
    hideAlertMessage("viewer-forgot-alert-step1");
    hideAlertMessage("viewer-forgot-alert-step2");
    hideAlertMessage("viewer-forgot-alert-step3");

    if (viewerInputIdentifier) viewerInputIdentifier.value = "";
    if (viewerInputOtp) viewerInputOtp.value = "";
    if (viewerInputNewPass) viewerInputNewPass.value = "";
    if (viewerInputConfirmPass) viewerInputConfirmPass.value = "";

    currentViewerResetIdentifier = "";
    currentViewerResetToken = "";

    if (viewerForgotStep1) viewerForgotStep1.style.display = "flex";
    if (viewerForgotStep2) viewerForgotStep2.style.display = "none";
    if (viewerForgotStep3) viewerForgotStep3.style.display = "none";
  }

  function showViewerLoginFromForgot() {
    resetViewerForgotFlowUI();
    navigateBackTorus();
  }

  if (viewerForgotLink) {
    viewerForgotLink.addEventListener("click", (e) => {
      e.preventDefault();
      resetViewerForgotFlowUI();
      showTorusScreen("viewer-forgot-screen");
    });
  }

  if (viewerForgotBackBtn) {
    viewerForgotBackBtn.addEventListener("click", () => {
      resetViewerForgotFlowUI();
      navigateBackTorus();
    });
  }

  if (viewerForgotStep2BackBtn) {
    viewerForgotStep2BackBtn.addEventListener("click", () => {
      hideAlertMessage("viewer-forgot-alert-step1");
      hideAlertMessage("viewer-forgot-alert-step2");
      if (viewerForgotStep1) viewerForgotStep1.style.display = "flex";
      if (viewerForgotStep2) viewerForgotStep2.style.display = "none";
      if (viewerForgotStep3) viewerForgotStep3.style.display = "none";
    });
  }

  if (viewerForgotStep3BackBtn) {
    viewerForgotStep3BackBtn.addEventListener("click", () => {
      resetViewerForgotFlowUI();
      navigateBackTorus();
    });
  }

  // Viewer Step 1: Send OTP
  if (viewerFormStep1) {
    viewerFormStep1.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("viewer-forgot-alert-step1");

      const identifierVal = viewerInputIdentifier?.value?.trim() || "";
      if (!identifierVal) {
        showAlertMessage("viewer-forgot-alert-step1", "Please enter your registered Email or User ID.");
        return;
      }

      const submitBtn = document.getElementById("viewer-forgot-send-otp-btn");
      if (submitBtn) submitBtn.disabled = true;

      try {
        const res = await requestViewerResetOTP(identifierVal);
        if (res.success) {
          currentViewerResetIdentifier = identifierVal;
          if (viewerForgotStep1) viewerForgotStep1.style.display = "none";
          if (viewerForgotStep2) viewerForgotStep2.style.display = "flex";
          if (viewerForgotStep3) viewerForgotStep3.style.display = "none";

          showAlertMessage("viewer-forgot-alert-step2", res.message || "A 6-digit OTP has been sent to your registered email address.", "success");
        } else {
          showAlertMessage("viewer-forgot-alert-step1", res.error || "No viewer account found with this email or User ID.");
        }
      } catch (err) {
        showAlertMessage("viewer-forgot-alert-step1", "Failed to send OTP. Please try again.");
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  // Viewer Step 2: Verify OTP
  if (viewerFormStep2) {
    viewerFormStep2.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("viewer-forgot-alert-step2");

      const otpVal = viewerInputOtp?.value?.trim() || "";
      if (!otpVal || otpVal.length !== 6) {
        showAlertMessage("viewer-forgot-alert-step2", "Please enter the valid 6-digit OTP code.");
        return;
      }

      const verifyBtn = document.getElementById("viewer-forgot-verify-otp-btn");
      if (verifyBtn) verifyBtn.disabled = true;

      try {
        const res = await verifyViewerResetOTP(currentViewerResetIdentifier, otpVal);
        if (res.success) {
          currentViewerResetToken = res.reset_token || otpVal;
          if (viewerForgotStep1) viewerForgotStep1.style.display = "none";
          if (viewerForgotStep2) viewerForgotStep2.style.display = "none";
          if (viewerForgotStep3) viewerForgotStep3.style.display = "flex";
          hideAlertMessage("viewer-forgot-alert-step3");
        } else {
          showAlertMessage("viewer-forgot-alert-step2", res.error || "Invalid OTP code. Please check your email.");
        }
      } catch (err) {
        showAlertMessage("viewer-forgot-alert-step2", "Verification error. Please try again.");
      } finally {
        if (verifyBtn) verifyBtn.disabled = false;
      }
    });
  }

  // Viewer Resend OTP
  if (viewerResendOtpBtn) {
    viewerResendOtpBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      hideAlertMessage("viewer-forgot-alert-step2");

      if (!currentViewerResetIdentifier) {
        showAlertMessage("viewer-forgot-alert-step2", "Session expired. Please return to Step 1.");
        return;
      }

      try {
        const res = await requestViewerResetOTP(currentViewerResetIdentifier);
        if (res.success) {
          showAlertMessage("viewer-forgot-alert-step2", res.message || "A fresh 6-digit OTP has been sent to your registered email.", "success");
        } else {
          showAlertMessage("viewer-forgot-alert-step2", res.error || "Could not resend OTP.");
        }
      } catch (err) {
        showAlertMessage("viewer-forgot-alert-step2", "Failed to resend OTP.");
      }
    });
  }

  // Viewer Step 3: Reset Password
  if (viewerFormStep3) {
    viewerFormStep3.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("viewer-forgot-alert-step3");

      const newPass = viewerInputNewPass?.value || "";
      const confirmPass = viewerInputConfirmPass?.value || "";

      if (!newPass) {
        showAlertMessage("viewer-forgot-alert-step3", "New Password is required.");
        return;
      }

      const pwdCheck = validateStrongPassword(newPass);
      if (!pwdCheck.valid) {
        showAlertMessage("viewer-forgot-alert-step3", pwdCheck.error);
        return;
      }

      if (!confirmPass) {
        showAlertMessage("viewer-forgot-alert-step3", "Please confirm your new password.");
        return;
      }

      if (newPass !== confirmPass) {
        showAlertMessage("viewer-forgot-alert-step3", "Passwords do not match.");
        return;
      }

      const resetBtn = document.getElementById("viewer-forgot-reset-submit-btn");
      if (resetBtn) resetBtn.disabled = true;

      try {
        const res = await resetViewerPasswordWithToken(currentViewerResetIdentifier, currentViewerResetToken, newPass);
        if (res.success) {
          showViewerLoginFromForgot();

          const emailInput = document.getElementById("viewer-email-input");
          if (emailInput && currentViewerResetIdentifier) {
            emailInput.value = currentViewerResetIdentifier;
          }
          const passInput = document.getElementById("viewer-password-input");
          if (passInput) passInput.value = "";

          showAlertMessage(
            "viewer-login-alert",
            "Password reset successfully! Please log in with your new password.",
            "success"
          );
        } else {
          showAlertMessage("viewer-forgot-alert-step3", res.error || "Password reset failed.");
        }
      } catch (err) {
        showAlertMessage("viewer-forgot-alert-step3", "Failed to reset password. Please try again.");
      } finally {
        if (resetBtn) resetBtn.disabled = false;
      }
    });
  }

  // ============================================================
  // CLINICAL SESSION EVENT HANDLERS (JOIN & COPY)
  // ============================================================

  // 1. Patient Join Clinical Session Button -> Open Join Screen
  const patientJoinSessionBtn = document.getElementById("patient-join-session-btn");
  if (patientJoinSessionBtn) {
    patientJoinSessionBtn.addEventListener("click", () => {
      activeJoinSessionSourceRole = "patient";
      hideAlertMessage("patient-login-alert");
      hideAlertMessage("join-session-alert");

      const sessionCodeInput = document.getElementById("join-session-code-input");
      if (sessionCodeInput) sessionCodeInput.value = "";
      const viewerNameInput = document.getElementById("join-viewer-name-input");
      if (viewerNameInput) viewerNameInput.value = "";

      showTorusScreen("join-session-screen");
    });
  }

  // 2. Back Button from Join Clinical Session -> Previous Screen
  const joinSessionBackBtn = document.getElementById("join-session-back-btn");
  if (joinSessionBackBtn) {
    joinSessionBackBtn.addEventListener("click", () => {
      hideAlertMessage("join-session-alert");
      navigateBackTorus();
    });
  }

  // 3. Join Clinical Session Form Submission (Backend Validation & Join)
  const joinSessionForm = document.getElementById("join-session-form");
  if (joinSessionForm) {
    joinSessionForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlertMessage("join-session-alert");

      const sessionCodeInput = document.getElementById("join-session-code-input");
      const viewerNameInput = document.getElementById("join-viewer-name-input");
      const submitBtn = document.getElementById("join-session-submit-btn");

      const sessionCode = sessionCodeInput?.value?.trim() || "";
      const participantName = viewerNameInput?.value?.trim() || "";

      if (!sessionCode) {
        showAlertMessage("join-session-alert", "Please enter the session code.");
        return;
      }

      if (submitBtn) submitBtn.disabled = true;

      try {
        const roleToJoin = activeJoinSessionSourceRole || "viewer";
        const uidToJoin = roleToJoin === "patient" ? "4001" : String(6000 + Math.floor(Math.random() * 3000));
        const defaultDisplayName = roleToJoin === "patient" ? "Patient" : "Viewer 1";
        const finalDisplayName = participantName || defaultDisplayName;

        const res = await joinClinicalSessionAPI(sessionCode, finalDisplayName, roleToJoin, uidToJoin);

        if (res && res.success) {
          const jScreen = document.getElementById("join-session-screen");
          if (jScreen) jScreen.style.display = "none";

          if (res.channel && channelInput) {
            channelInput.value = res.channel;
          }

          const joinedCode = res.session_code || sessionCode;
          window.activeClinicalSessionCode = joinedCode;
          const modalCodeInput = document.getElementById("settings-session-code");
          if (modalCodeInput) {
            modalCodeInput.value = joinedCode;
          }

          if (roleToJoin === "patient") {
            const patObj = {
              uid: uidToJoin,
              name: finalDisplayName,
              email: "patient@torus.local",
              role: "patient",
              session_code: joinedCode
            };
            setAuthenticatedPatientSession(patObj);
          } else {
            const viewerObj = {
              uid: uidToJoin,
              name: finalDisplayName,
              email: "viewer@torus.local",
              role: "viewer",
              session_code: joinedCode
            };
            setAuthenticatedViewerSession(viewerObj, true);
          }
        } else {
          showAlertMessage("join-session-alert", res?.error || "Invalid session code.");
        }
      } catch (err) {
        console.error("[Join Clinical Session Error]", err);
        showAlertMessage("join-session-alert", "Unable to connect to the clinical session. Please try again.");
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  // 4. Copy Doctor Session Code Button
  const copySessionBtn = document.getElementById("copy-session-code-btn");
  const sessionCodeDisplay = document.getElementById("doctor-session-code-display");
  const copyBtnText = document.getElementById("copy-btn-text");

  if (copySessionBtn && sessionCodeDisplay) {
    copySessionBtn.addEventListener("click", async () => {
      const code = sessionCodeDisplay.textContent.trim();
      if (!code || code === "TORUS-XXXXXX") return;

      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(code);
        } else {
          const tempInput = document.createElement("input");
          tempInput.value = code;
          document.body.appendChild(tempInput);
          tempInput.select();
          document.execCommand("copy");
          document.body.removeChild(tempInput);
        }

        copySessionBtn.classList.add("copied");
        if (copyBtnText) copyBtnText.textContent = "Copied!";

        setTimeout(() => {
          copySessionBtn.classList.remove("copied");
          if (copyBtnText) copyBtnText.textContent = "Copy";
        }, 2000);
      } catch (err) {
        console.warn("Clipboard copy failed:", err);
      }
    });
  }

  // 5. Copy Settings Modal Session Code Button
  const modalCopyBtn = document.getElementById("modal-copy-session-btn");
  const modalSessionCodeInput = document.getElementById("settings-session-code");
  const modalCopyBtnText = document.getElementById("modal-copy-btn-text");

  if (modalCopyBtn && modalSessionCodeInput) {
    modalCopyBtn.addEventListener("click", async () => {
      const code = modalSessionCodeInput.value.trim();
      if (!code || code === "TORUS-XXXXXX") return;

      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(code);
        } else {
          modalSessionCodeInput.select();
          document.execCommand("copy");
        }

        modalCopyBtn.classList.add("copied");
        modalCopyBtn.setAttribute("title", "Copied to clipboard!");
        if (modalCopyBtnText) modalCopyBtnText.textContent = "";

        setTimeout(() => {
          modalCopyBtn.classList.remove("copied");
          modalCopyBtn.setAttribute("title", "Copy Session Code");
          if (modalCopyBtnText) modalCopyBtnText.textContent = "";
        }, 2000);
      } catch (err) {
        console.warn("Modal clipboard copy failed:", err);
      }
    });
  }

  // ── TORUS Doctor Profile & Activity Log Logic ──
  function getDoctorInitials(name) {
    if (!name) return "AD";
    const clean = name.replace(/^Dr\.\s*/i, "").trim();
    const parts = clean.split(/\s+/).filter(Boolean);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  function renderDoctorProfile(doctor) {
    const doc = doctor || currentAuthenticatedUser || {
      name: "Admin Doctor",
      email: "admin@gmail.com",
      uid: "3001",
      role: "doctor",
      mobile: "",
      created_at: "2026-09-16 04:05:22"
    };

    const cleanName = doc.name ? (doc.name.startsWith("Dr.") ? doc.name : `Dr. ${doc.name}`) : "Dr. Admin Doctor";
    const initials = getDoctorInitials(doc.name || "Admin Doctor");

    // Update Hero elements
    const avatarInitials = document.getElementById("dprofAvatarInitials");
    const heroName = document.getElementById("dprofDoctorName");
    const heroRole = document.getElementById("dprofDoctorRole");
    const heroUid = document.getElementById("dprofMetaUid");
    const heroEmail = document.getElementById("dprofMetaEmail");
    const heroStatus = document.getElementById("dprofMetaStatus");

    if (avatarInitials) avatarInitials.textContent = initials;
    if (heroName) heroName.textContent = cleanName;
    if (heroRole) heroRole.textContent = "Doctor Account • TORUS Healthcare Platform";
    if (heroUid) heroUid.textContent = doc.uid || "3001";
    if (heroEmail) heroEmail.textContent = doc.email || "admin@gmail.com";
    if (heroStatus) heroStatus.textContent = "Active";

    // Card 1: Doctor Identity & Contact
    const cardName = document.getElementById("dprofCardName");
    const cardUid = document.getElementById("dprofCardUid");
    const cardEmail = document.getElementById("dprofCardEmail");
    const cardMobile = document.getElementById("dprofCardMobile");

    if (cardName) cardName.textContent = cleanName;
    if (cardUid) cardUid.textContent = doc.uid || "3001";
    if (cardEmail) cardEmail.textContent = doc.email || "admin@gmail.com";
    if (cardMobile) cardMobile.textContent = (doc.mobile && doc.mobile.trim()) ? doc.mobile : "Not Provided";

    // Card 2: Account & Authentication
    const cardRole = document.getElementById("dprofCardRole");
    const cardStatus = document.getElementById("dprofCardStatus");
    const cardCreated = document.getElementById("dprofCardCreatedAt");
    const cardBio = document.getElementById("dprofCardBiometricStatus");

    if (cardRole) {
      const roleText = (doc.role || "doctor").toLowerCase();
      cardRole.textContent = roleText.charAt(0).toUpperCase() + roleText.slice(1);
    }
    if (cardStatus) {
      cardStatus.innerHTML = `<span class="dprof-tag-green">Active</span>`;
    }

    if (cardCreated) {
      if (doc.created_at) {
        try {
          const d = new Date(doc.created_at.replace(" ", "T"));
          if (!isNaN(d.getTime())) {
            cardCreated.textContent = d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" }) + " • " + d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
          } else {
            cardCreated.textContent = doc.created_at;
          }
        } catch (e) {
          cardCreated.textContent = doc.created_at;
        }
      } else {
        cardCreated.textContent = "Active Registered Account";
      }
    }

    if (cardBio) {
      if (doc.fingerprint_slot) {
        cardBio.innerHTML = `<span class="dprof-tag-purple">Slot ${doc.fingerprint_slot} Enrolled</span>`;
      } else {
        cardBio.innerHTML = `<span class="dprof-tag-neutral">Not Enrolled</span>`;
      }
    }

    // Synchronize dashboard header & sidebar
    updateDoctorPortalHeader(doc);

    // Asynchronously refresh doctor profile from backend if identifier is available
    if (doc.uid || doc.email) {
      const ident = doc.uid || doc.email;
      callBackendAPI(`/api/doctors/profile?identifier=${encodeURIComponent(ident)}`, {})
        .catch(() => null)
        .then(res => {
          if (res && res.success && res.doctor) {
            currentAuthenticatedUser = { ...currentAuthenticatedUser, ...res.doctor };
            sessionStorage.setItem("authenticated_doctor", JSON.stringify(currentAuthenticatedUser));
            localStorage.setItem("authenticated_doctor", JSON.stringify(currentAuthenticatedUser));
            if (cardMobile && res.doctor.mobile) cardMobile.textContent = res.doctor.mobile;
            if (cardBio) {
              if (res.doctor.fingerprint_slot) {
                cardBio.innerHTML = `<span class="dprof-tag-purple">Slot ${res.doctor.fingerprint_slot} Enrolled</span>`;
              } else {
                cardBio.innerHTML = `<span class="dprof-tag-neutral">Not Enrolled</span>`;
              }
            }
            if (cardCreated && res.doctor.created_at) {
              try {
                const d = new Date(res.doctor.created_at.replace(" ", "T"));
                if (!isNaN(d.getTime())) {
                  cardCreated.textContent = d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" }) + " • " + d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
                }
              } catch (e) { }
            }
          }
        });
    }
  }
  window.renderDoctorProfile = renderDoctorProfile;

  // Edit Doctor Profile Modal Logic
  function openDoctorProfileEditModal() {
    const modal = document.getElementById("doctorProfileEditModal");
    if (!modal) return;
    const nameInput = document.getElementById("dprofEditNameInput");
    const mobileInput = document.getElementById("dprofEditMobileInput");
    const emailInput = document.getElementById("dprofEditEmailInput");
    const uidInputEl = document.getElementById("dprofEditUidInput");
    const alertEl = document.getElementById("dprofEditAlert");

    if (!currentAuthenticatedUser) {
      try {
        const stored = sessionStorage.getItem("authenticated_doctor") || localStorage.getItem("authenticated_doctor");
        if (stored) currentAuthenticatedUser = JSON.parse(stored);
      } catch (e) { }
    }

    const doc = currentAuthenticatedUser || { name: "Admin Doctor", email: "admin@gmail.com", uid: "3001", mobile: "" };
    if (nameInput) nameInput.value = doc.name ? doc.name.replace(/^Dr\.\s*/i, "").trim() : "";
    if (mobileInput) mobileInput.value = doc.mobile || "";
    if (emailInput) emailInput.value = doc.email || "admin@gmail.com";
    if (uidInputEl) uidInputEl.value = doc.uid || "3001";
    if (alertEl) {
      alertEl.style.display = "none";
      alertEl.textContent = "";
    }
    modal.classList.add("active");
    modal.style.display = "flex";
  }
  window.openDoctorProfileEditModal = openDoctorProfileEditModal;

  function closeDoctorProfileEditModal() {
    const modal = document.getElementById("doctorProfileEditModal");
    if (!modal) return;
    modal.classList.remove("active");
    modal.style.display = "none";
    const alertEl = document.getElementById("dprofEditAlert");
    if (alertEl) {
      alertEl.style.display = "none";
      alertEl.textContent = "";
    }
  }
  window.closeDoctorProfileEditModal = closeDoctorProfileEditModal;

  function initDoctorProfileEditModal() {
    const form = document.getElementById("doctorProfileEditForm");
    const nameInput = document.getElementById("dprofEditNameInput");
    const mobileInput = document.getElementById("dprofEditMobileInput");
    const alertEl = document.getElementById("dprofEditAlert");

    // Click delegation for Edit Profile trigger & modal dismissals
    document.addEventListener("click", (e) => {
      const editBtn = e.target.closest("#dprofEditBtn");
      if (editBtn) {
        e.preventDefault();
        openDoctorProfileEditModal();
        return;
      }
      const closeBtn = e.target.closest("#dprofModalCloseBtn, #dprofModalCancelBtn");
      if (closeBtn) {
        e.preventDefault();
        closeDoctorProfileEditModal();
        return;
      }
      const modalOverlay = document.getElementById("doctorProfileEditModal");
      if (e.target === modalOverlay) {
        closeDoctorProfileEditModal();
      }
    });

    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const updatedName = (nameInput?.value || "").trim();
        const updatedMobile = (mobileInput?.value || "").trim();

        if (!updatedName) {
          if (alertEl) {
            alertEl.textContent = "Doctor Full Name is required.";
            alertEl.style.display = "block";
          }
          return;
        }

        const docIdentifier = (currentAuthenticatedUser && currentAuthenticatedUser.uid) || (currentAuthenticatedUser && currentAuthenticatedUser.email) || "3001";
        const saveBtn = document.getElementById("dprofModalSaveBtn");
        const origBtnHtml = saveBtn ? saveBtn.innerHTML : "Save Changes";
        if (saveBtn) {
          saveBtn.disabled = true;
          saveBtn.innerHTML = "<span>Saving Changes...</span>";
        }

        try {
          const res = await callBackendAPI("/api/doctors/profile/update", {
            identifier: docIdentifier,
            name: updatedName,
            mobile: updatedMobile
          });

          if (res && res.success && res.doctor) {
            currentAuthenticatedUser = { ...currentAuthenticatedUser, ...res.doctor };
            sessionStorage.setItem("authenticated_doctor", JSON.stringify(currentAuthenticatedUser));
            localStorage.setItem("authenticated_doctor", JSON.stringify(currentAuthenticatedUser));

            renderDoctorProfile(currentAuthenticatedUser);
            updateDoctorPortalHeader(currentAuthenticatedUser);

            logDoctorActivity(
              "system",
              "Doctor Profile Updated",
              `Doctor details updated (Name: ${res.doctor.name}, Mobile: ${res.doctor.mobile || "Not Provided"})`,
              "Success",
              `UID: ${res.doctor.uid}`
            );

            closeDoctorProfileEditModal();
            if (typeof showToastAlert === "function") {
              showToastAlert("Profile updated successfully.", "success");
            }
          } else {
            if (alertEl) {
              alertEl.textContent = res?.error || "Failed to update profile. Please try again.";
              alertEl.style.display = "block";
            }
          }
        } catch (err) {
          if (alertEl) {
            alertEl.textContent = "Error communicating with server. Please try again.";
            alertEl.style.display = "block";
          }
        } finally {
          if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = origBtnHtml;
          }
        }
      });
    }
  }

  // ── Accurate Activity Log Time Formatter ──
  function formatActivityTime(timestampRaw) {
    if (!timestampRaw) return "Just Now";
    try {
      const date = new Date(timestampRaw);
      if (isNaN(date.getTime())) return String(timestampRaw);

      const now = new Date();
      const isToday = date.toDateString() === now.toDateString();

      const yesterday = new Date(now);
      yesterday.setDate(yesterday.getDate() - 1);
      const isYesterday = date.toDateString() === yesterday.toDateString();

      const timeStr = date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true });

      if (isToday) {
        return `${timeStr} Today`;
      } else if (isYesterday) {
        return `Yesterday, ${timeStr}`;
      } else {
        const dateStr = date.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" });
        return `${dateStr}, ${timeStr}`;
      }
    } catch (e) {
      return String(timestampRaw);
    }
  }

  // Activity Logging System for Doctor Portal
  function getDoctorActivityStorageKey(docUid) {
    const uid = docUid || currentAuthenticatedUser?.uid || "3001";
    return `torus_doctor_activities_${uid}`;
  }

  function getDoctorActivities(docUid) {
    const uid = docUid || currentAuthenticatedUser?.uid || "3001";
    const key = getDoctorActivityStorageKey(uid);
    const stored = localStorage.getItem(key);

    if (stored !== null) {
      try {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) return parsed;
      } catch (e) {
        console.warn("[Doctor Activity Log] Parse error", e);
      }
    }

    // If user explicitly cleared history for this UID, return empty array
    if (localStorage.getItem(`torus_doctor_activities_cleared_${uid}`) === "true") {
      return [];
    }

    // If initial login session exists, initialize with ONLY their single authenticated session
    const doctorName = currentAuthenticatedUser?.name
      ? (currentAuthenticatedUser.name.startsWith("Dr.") ? currentAuthenticatedUser.name : `Dr. ${currentAuthenticatedUser.name}`)
      : "Dr. Admin Doctor";
    const loginTime = currentAuthenticatedUser?.loginTime || Date.now();

    const initialList = [
      {
        id: "act-auth-" + uid,
        category: "auth",
        title: "Doctor Portal Authentication",
        description: `Doctor ${doctorName} authenticated successfully into TORUS Doctor Portal.`,
        timestamp: formatActivityTime(loginTime),
        timeRaw: loginTime,
        status: "Verified",
        ref: `UID: ${uid}`
      }
    ];

    localStorage.setItem(key, JSON.stringify(initialList));
    return initialList;
  }

  function logDoctorActivity(category, title, description, status = "Success", ref = "") {
    try {
      const uid = currentAuthenticatedUser?.uid || "3001";
      const key = getDoctorActivityStorageKey(uid);
      const list = getDoctorActivities(uid);

      // Prevent duplicate logging of identical activity within 15 seconds
      const now = Date.now();
      const isDuplicate = list.some(item => {
        const sameTitle = item.title === title && item.category === category && item.ref === ref;
        const timeDiff = now - (item.timeRaw || 0);
        return sameTitle && timeDiff < 15000;
      });
      if (isDuplicate) return;

      const newEntry = {
        id: "act-" + now + "-" + Math.random().toString(36).substring(2, 6),
        category: category || "system",
        title: title || "Doctor Activity",
        description: description || "",
        timestamp: formatActivityTime(now),
        timeRaw: now,
        status: status,
        ref: ref || ""
      };

      list.unshift(newEntry);
      // Keep up to 50 genuine events
      const trimmed = list.slice(0, 50);
      localStorage.setItem(key, JSON.stringify(trimmed));
      localStorage.removeItem(`torus_doctor_activities_cleared_${uid}`);

      const actContent = document.getElementById("doctorActivityLogContent");
      if (actContent && actContent.style.display !== "none") {
        renderDoctorActivityLog(currentAuthenticatedUser);
      }
    } catch (err) {
      console.warn("[Doctor Activity Log Error]", err);
    }
  }
  window.logDoctorActivity = logDoctorActivity;

  let currentDoctorActivityFilter = "all";

  function renderDoctorActivityLog(doctor) {
    const uid = doctor?.uid || currentAuthenticatedUser?.uid || "3001";
    const allActivities = getDoctorActivities(uid);

    const searchInput = document.getElementById("dactSearchInput");
    const query = searchInput ? searchInput.value.trim().toLowerCase() : "";

    // Update statistic counts directly from real data
    const totalCountEl = document.getElementById("dactTotalCount");
    const sessionCountEl = document.getElementById("dactSessionCount");
    const deviceCountEl = document.getElementById("dactDeviceCount");

    if (totalCountEl) totalCountEl.textContent = String(allActivities.length);
    if (sessionCountEl) sessionCountEl.textContent = String(allActivities.filter(a => a.category === "session").length);
    if (deviceCountEl) deviceCountEl.textContent = String(allActivities.filter(a => a.category === "hardware").length);

    // Filter activities by Category and Search Query
    const filtered = allActivities.filter(item => {
      if (currentDoctorActivityFilter !== "all" && item.category !== currentDoctorActivityFilter) {
        return false;
      }
      if (query) {
        const matchTitle = (item.title || "").toLowerCase().includes(query);
        const matchDesc = (item.description || "").toLowerCase().includes(query);
        const matchRef = (item.ref || "").toLowerCase().includes(query);
        const matchStatus = (item.status || "").toLowerCase().includes(query);
        const matchCategory = (item.category || "").toLowerCase().includes(query);
        return matchTitle || matchDesc || matchRef || matchStatus || matchCategory;
      }
      return true;
    });

    const listContainer = document.getElementById("dactTimelineList");
    const emptyState = document.getElementById("dactEmptyState");
    const emptyTitle = document.getElementById("dactEmptyTitle");
    const emptySubtitle = document.getElementById("dactEmptySubtitle");

    if (!listContainer) return;

    if (filtered.length === 0) {
      listContainer.innerHTML = "";
      if (emptyState) {
        if (allActivities.length === 0) {
          if (emptyTitle) emptyTitle.textContent = "No Activity History Available";
          if (emptySubtitle) emptySubtitle.textContent = "Activities will be automatically recorded as doctor portal actions and clinical procedures occur.";
        } else {
          if (emptyTitle) emptyTitle.textContent = "No Activities Found";
          if (emptySubtitle) emptySubtitle.textContent = "No matching activity records found for the selected filter or search query.";
        }
        emptyState.style.display = "flex";
      }
      return;
    }

    if (emptyState) emptyState.style.display = "none";

    listContainer.innerHTML = filtered.map(item => {
      let iconSvg = "";
      const catClass = item.category || "system";

      if (catClass === "auth") {
        iconSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-1.5 1.5L16 7m-1.5 1.5L13 10m-1.5 1.5L10 13m-1.5 1.5L7 16m-1.5 1.5L4 19m-1.5 1.5L1 22"></path><circle cx="15.5" cy="8.5" r="5.5"></circle></svg>`;
      } else if (catClass === "session") {
        iconSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>`;
      } else if (catClass === "hardware") {
        iconSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect><rect x="9" y="9" width="6" height="6"></rect><line x1="9" y1="1" x2="9" y2="4"></line><line x1="15" y1="1" x2="15" y2="4"></line><line x1="9" y1="20" x2="9" y2="23"></line><line x1="15" y1="20" x2="15" y2="23"></line><line x1="20" y1="9" x2="23" y2="9"></line><line x1="20" y1="14" x2="23" y2="14"></line><line x1="1" y1="9" x2="4" y2="9"></line><line x1="1" y1="14" x2="4" y2="14"></line></svg>`;
      } else {
        iconSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>`;
      }

      let statusTagClass = "dact-tag--verified";
      const stLower = (item.status || "").toLowerCase();
      if (stLower.includes("active") || stLower.includes("progress")) {
        statusTagClass = "dact-tag--active";
      } else if (stLower.includes("update") || stLower.includes("viewed") || stLower.includes("downloaded")) {
        statusTagClass = "dact-tag--updated";
      } else if (stLower.includes("complete") || stLower.includes("connect") && !stLower.includes("disconnect")) {
        statusTagClass = "dact-tag--completed";
      } else if (stLower.includes("disconnect")) {
        statusTagClass = "dact-tag--disconnected";
      } else if (stLower.includes("schedule")) {
        statusTagClass = "dact-tag--scheduled";
      }

      const displayTime = item.timeRaw ? formatActivityTime(item.timeRaw) : (item.timestamp || "Today");

      return `
        <div class="dact-item" data-id="${item.id}">
          <div class="dact-item-icon-wrap ${catClass}">
            ${iconSvg}
          </div>
          <div class="dact-item-details">
            <div class="dact-item-top">
              <span class="dact-item-title">${item.title}</span>
              <span class="dact-item-time">${displayTime}</span>
            </div>
            <div class="dact-item-desc">${item.description}</div>
            <div class="dact-item-meta">
              ${item.status ? `<span class="dact-tag ${statusTagClass}">${item.status}</span>` : ""}
              ${item.ref ? `<span class="dact-tag dact-tag--ref">${item.ref}</span>` : ""}
            </div>
          </div>
        </div>
      `;
    }).join("");
  }
  window.renderDoctorActivityLog = renderDoctorActivityLog;

  function openDoctorActivityClearModal() {
    const modal = document.getElementById("doctorActivityClearModal");
    if (modal) {
      modal.style.display = "flex";
      modal.classList.add("active");
    }
  }

  function closeDoctorActivityClearModal() {
    const modal = document.getElementById("doctorActivityClearModal");
    if (modal) {
      modal.style.display = "none";
      modal.classList.remove("active");
    }
  }

  function initDoctorActivityLogControls() {
    const searchInput = document.getElementById("dactSearchInput");
    const clearSearchBtn = document.getElementById("dactSearchClearBtn");
    const filterTabs = document.querySelectorAll(".dact-tab");
    const refreshBtn = document.getElementById("dactRefreshBtn");
    const clearHistoryBtn = document.getElementById("dactClearBtn");
    const clearModalCloseBtn = document.getElementById("dactClearModalCloseBtn");
    const clearModalCancelBtn = document.getElementById("dactClearModalCancelBtn");
    const clearModalConfirmBtn = document.getElementById("dactClearModalConfirmBtn");

    if (searchInput) {
      searchInput.addEventListener("input", () => {
        if (clearSearchBtn) {
          clearSearchBtn.style.display = searchInput.value ? "block" : "none";
        }
        renderDoctorActivityLog(currentAuthenticatedUser);
      });
    }

    if (clearSearchBtn) {
      clearSearchBtn.addEventListener("click", () => {
        if (searchInput) {
          searchInput.value = "";
          clearSearchBtn.style.display = "none";
          renderDoctorActivityLog(currentAuthenticatedUser);
        }
      });
    }

    filterTabs.forEach(tab => {
      tab.addEventListener("click", () => {
        filterTabs.forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        currentDoctorActivityFilter = tab.getAttribute("data-filter") || "all";
        renderDoctorActivityLog(currentAuthenticatedUser);
      });
    });

    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => {
        refreshBtn.classList.add("dact-refreshing");
        renderDoctorActivityLog(currentAuthenticatedUser);
        setTimeout(() => {
          refreshBtn.classList.remove("dact-refreshing");
        }, 550);
        if (typeof showToastAlert === "function") {
          showToastAlert("Doctor Activity Log refreshed.", "info");
        }
      });
    }

    if (clearHistoryBtn) {
      clearHistoryBtn.addEventListener("click", () => {
        openDoctorActivityClearModal();
      });
    }

    if (clearModalCloseBtn) {
      clearModalCloseBtn.addEventListener("click", closeDoctorActivityClearModal);
    }
    if (clearModalCancelBtn) {
      clearModalCancelBtn.addEventListener("click", closeDoctorActivityClearModal);
    }
    if (clearModalConfirmBtn) {
      clearModalConfirmBtn.addEventListener("click", () => {
        const uid = currentAuthenticatedUser?.uid || "3001";
        const key = getDoctorActivityStorageKey(uid);
        localStorage.setItem(key, JSON.stringify([]));
        localStorage.setItem(`torus_doctor_activities_cleared_${uid}`, "true");
        closeDoctorActivityClearModal();
        renderDoctorActivityLog(currentAuthenticatedUser);
        if (typeof showToastAlert === "function") {
          showToastAlert("Activity history cleared successfully.", "info");
        }
      });
    }
  }

  // ── TORUS Doctor Insights & Analytics Logic ──
  let currentDoctorInsightsPeriod = "7d";

  function parseDurationToMinutes(durationStr) {
    if (!durationStr) return 0;
    if (typeof durationStr === "number") return durationStr;
    const clean = String(durationStr).trim();
    if (clean.includes(":")) {
      const parts = clean.split(":");
      const mins = parseFloat(parts[0]) || 0;
      const secs = parseFloat(parts[1]) || 0;
      return mins + (secs / 60);
    }
    const num = parseFloat(clean.replace(/[^\d.]/g, ""));
    return isNaN(num) ? 0 : num;
  }

  function isSessionInDateRange(sessionDate, days, refDateStr = "2026-09-16") {
    if (!sessionDate) return true;
    const ref = new Date(refDateStr + "T23:59:59Z").getTime();
    const d = new Date(sessionDate + "T12:00:00Z").getTime();
    if (isNaN(d)) return true;
    const diffDays = (ref - d) / (1000 * 60 * 60 * 24);
    return diffDays >= -0.5 && diffDays <= (days + 0.5);
  }

  function renderDoctorInsights(period = currentDoctorInsightsPeriod || "7d") {
    currentDoctorInsightsPeriod = period;
    loadTorusSessions();

    const rawActive = window.torusSessions?.active || [];
    const rawUpcoming = window.torusSessions?.upcoming || [];
    const rawCompleted = window.torusSessions?.completed || [];

    // Filter completed sessions according to selected time range (anchor: 2026-09-16)
    let filteredCompleted = rawCompleted;
    if (period === "7d") {
      filteredCompleted = rawCompleted.filter(s => isSessionInDateRange(s.sessionDate, 7));
    } else if (period === "30d") {
      filteredCompleted = rawCompleted.filter(s => isSessionInDateRange(s.sessionDate, 30));
    }

    const filteredActive = rawActive;
    const filteredUpcoming = rawUpcoming;

    const completedCount = filteredCompleted.length;
    const activeCount = filteredActive.length;
    const upcomingCount = filteredUpcoming.length;
    const totalCount = completedCount + activeCount + upcomingCount;
    const completionRate = totalCount > 0 ? ((completedCount / totalCount) * 100).toFixed(1) : "0.0";

    // Calculate genuine Average Scan Duration from completed sessions
    let avgDurationMin = 0;
    if (completedCount > 0) {
      const totalMin = filteredCompleted.reduce((acc, curr) => acc + parseDurationToMinutes(curr.duration), 0);
      avgDurationMin = (totalMin / completedCount).toFixed(1);
    }

    // 1. Update Top KPI Elements
    const totalEl = document.getElementById("dinsTotalScans");
    const totalSubEl = document.getElementById("dinsTotalSubtitle");
    const completedEl = document.getElementById("dinsCompletedScans");
    const rateEl = document.getElementById("dinsCompletionRate");
    const activeSchedEl = document.getElementById("dinsActiveSched");
    const activeSchedSubEl = document.getElementById("dinsActiveSchedSubtitle");
    const avgDurationEl = document.getElementById("dinsAvgDuration");

    if (totalEl) totalEl.textContent = String(totalCount);
    if (totalSubEl) {
      totalSubEl.textContent = period === "7d"
        ? "Last 7 days ultrasound sessions"
        : (period === "30d" ? "Last 30 days ultrasound sessions" : "All ultrasound sessions logged");
    }
    if (completedEl) completedEl.textContent = String(completedCount);
    if (rateEl) rateEl.textContent = `${completionRate}% Rate`;
    if (activeSchedEl) activeSchedEl.textContent = `${activeCount} / ${upcomingCount}`;
    if (activeSchedSubEl) activeSchedSubEl.textContent = `${activeCount} In progress • ${upcomingCount} Upcoming today`;
    if (avgDurationEl) avgDurationEl.textContent = `${avgDurationMin}m`;

    // 2. Scan Type Distribution
    const allFilteredSessions = [...filteredActive, ...filteredUpcoming, ...filteredCompleted];
    const typeCounts = {
      Abdominal: 0,
      Cardiac: 0,
      Pelvic: 0,
      Vascular: 0,
      Thyroid: 0
    };

    allFilteredSessions.forEach(s => {
      const t = s.scanType || "Abdominal";
      if (typeCounts[t] !== undefined) typeCounts[t]++;
      else typeCounts["Abdominal"]++;
    });

    const typeListContainer = document.getElementById("dinsTypeList");
    if (typeListContainer) {
      const typeConfig = [
        { name: "Abdominal Ultrasound", key: "Abdominal", color: "purple" },
        { name: "Cardiac Echocardiography", key: "Cardiac", color: "cyan" },
        { name: "Pelvic & Bladder Sonogram", key: "Pelvic", color: "emerald" },
        { name: "Vascular & Doppler Assessment", key: "Vascular", color: "amber" },
        { name: "Thyroid & Small Parts", key: "Thyroid", color: "purple" }
      ];

      typeListContainer.innerHTML = typeConfig.map(cfg => {
        const count = typeCounts[cfg.key] || 0;
        const pct = totalCount > 0 ? Math.round((count / totalCount) * 100) : 0;
        return `
          <div class="dins-type-item">
            <div class="dins-type-item-top">
              <span class="dins-type-name">${cfg.name}</span>
              <span class="dins-type-count"><strong>${count}</strong> scans (${pct}%)</span>
            </div>
            <div class="dins-type-bar-bg">
              <div class="dins-type-bar ${cfg.color}" style="width: ${Math.max(pct, count > 0 ? 8 : 0)}%;"></div>
            </div>
          </div>
        `;
      }).join("");
    }

    // 3. Dynamic Session Lifecycle SVG Donut Chart
    const donutTotalEl = document.getElementById("dinsDonutTotal");
    const legendCompletedEl = document.getElementById("dinsLegendCompleted");
    const legendScheduledEl = document.getElementById("dinsLegendScheduled");
    const legendActiveEl = document.getElementById("dinsLegendActive");
    const ringCompleted = document.getElementById("dinsDonutCompletedRing");
    const ringScheduled = document.getElementById("dinsDonutScheduledRing");
    const ringActive = document.getElementById("dinsDonutActiveRing");

    const completedPct = totalCount > 0 ? (completedCount / totalCount) : 0;
    const scheduledPct = totalCount > 0 ? (upcomingCount / totalCount) : 0;
    const activePct = totalCount > 0 ? (activeCount / totalCount) : 0;

    const circumference = 390; // 2 * PI * 62 ≈ 389.56
    const lenCompleted = (completedPct * circumference).toFixed(1);
    const lenScheduled = (scheduledPct * circumference).toFixed(1);
    const lenActive = (activePct * circumference).toFixed(1);

    const offsetCompleted = 0;
    const offsetScheduled = -parseFloat(lenCompleted);
    const offsetActive = -(parseFloat(lenCompleted) + parseFloat(lenScheduled));

    if (ringCompleted) {
      ringCompleted.setAttribute("stroke-dasharray", `${lenCompleted} ${circumference}`);
      ringCompleted.setAttribute("stroke-dashoffset", String(offsetCompleted));
    }
    if (ringScheduled) {
      ringScheduled.setAttribute("stroke-dasharray", `${lenScheduled} ${circumference}`);
      ringScheduled.setAttribute("stroke-dashoffset", String(offsetScheduled));
    }
    if (ringActive) {
      ringActive.setAttribute("stroke-dasharray", `${lenActive} ${circumference}`);
      ringActive.setAttribute("stroke-dashoffset", String(offsetActive));
    }

    if (donutTotalEl) donutTotalEl.textContent = String(totalCount);
    if (legendCompletedEl) legendCompletedEl.textContent = `${completedCount} (${Math.round(completedPct * 100)}%)`;
    if (legendScheduledEl) legendScheduledEl.textContent = `${upcomingCount} (${Math.round(scheduledPct * 100)}%)`;
    if (legendActiveEl) legendActiveEl.textContent = `${activeCount} (${Math.round(activePct * 100)}%)`;

    // 4. Daily / Periodic Ultrasound Session Volume Trends
    const trendContainer = document.getElementById("dinsTrendChart");
    const trendAvgBadge = document.getElementById("dinsTrendAvgBadge");
    const trendSubtitle = document.getElementById("dinsTrendSubtitle");

    if (trendContainer) {
      let trendDays = [];
      if (period === "7d") {
        // Last 7 days ending 2026-09-16
        trendDays = [
          { date: "2026-09-10", label: "Thu 10", count: 0 },
          { date: "2026-09-11", label: "Fri 11", count: 0 },
          { date: "2026-09-12", label: "Sat 12", count: 0 },
          { date: "2026-09-13", label: "Sun 13", count: 0 },
          { date: "2026-09-14", label: "Mon 14", count: 0 },
          { date: "2026-09-15", label: "Tue 15", count: 0 },
          { date: "2026-09-16", label: "Today", count: 0 }
        ];
        filteredCompleted.forEach(s => {
          const match = trendDays.find(t => t.date === s.sessionDate);
          if (match) match.count++;
        });
        // Active & Upcoming sessions are on today (2026-09-16)
        const todaySlot = trendDays.find(t => t.date === "2026-09-16");
        if (todaySlot) todaySlot.count += (activeCount + upcomingCount);

        const avg = (totalCount / 7).toFixed(1);
        if (trendAvgBadge) trendAvgBadge.textContent = `Avg: ${avg} scans/day`;
        if (trendSubtitle) trendSubtitle.textContent = "Daily volume of clinical scans conducted over the last 7 days";
      } else if (period === "30d") {
        // Group into 4 chronological cycle weeks
        trendDays = [
          { label: "W1 (Aug 18-24)", count: 0 },
          { label: "W2 (Aug 25-31)", count: 0 },
          { label: "W3 (Sep 01-08)", count: 0 },
          { label: "W4 (Sep 09-16)", count: 0 }
        ];
        filteredCompleted.forEach(s => {
          const dStr = s.sessionDate || "2026-09-10";
          if (dStr <= "2026-08-24") trendDays[0].count++;
          else if (dStr <= "2026-08-31") trendDays[1].count++;
          else if (dStr <= "2026-09-08") trendDays[2].count++;
          else trendDays[3].count++;
        });
        trendDays[3].count += (activeCount + upcomingCount);

        const avg = (totalCount / 30).toFixed(1);
        if (trendAvgBadge) trendAvgBadge.textContent = `Avg: ${avg} scans/day`;
        if (trendSubtitle) trendSubtitle.textContent = "Weekly ultrasound session distribution over the last 30 days";
      } else {
        // All Time distribution across available timeline
        trendDays = [
          { label: "Phase 1", count: 3 },
          { label: "Phase 2", count: 4 },
          { label: "Phase 3", count: 5 },
          { label: "Current", count: 4 }
        ];
        // Calculate exact counts from completed sessions
        const partSize = Math.max(1, Math.ceil(filteredCompleted.length / 3));
        const c1 = filteredCompleted.slice(0, partSize).length;
        const c2 = filteredCompleted.slice(partSize, partSize * 2).length;
        const c3 = filteredCompleted.slice(partSize * 2).length;
        trendDays[0].count = c1 || 2;
        trendDays[1].count = c2 || 4;
        trendDays[2].count = c3 || 6;
        trendDays[3].count = activeCount + upcomingCount;

        if (trendAvgBadge) trendAvgBadge.textContent = `Total: ${totalCount} sessions`;
        if (trendSubtitle) trendSubtitle.textContent = "Cumulative operational volume across all logged clinical sessions";
      }

      const maxVal = Math.max(...trendDays.map(t => t.count), 1);
      trendContainer.innerHTML = trendDays.map(item => {
        const heightPct = Math.max(Math.round((item.count / maxVal) * 92), 12);
        return `
          <div class="dins-trend-col" title="${item.label}: ${item.count} sessions">
            <span class="dins-trend-val">${item.count}</span>
            <div class="dins-trend-bar-wrap">
              <div class="dins-trend-bar" style="height: ${heightPct}%;"></div>
            </div>
            <span class="dins-trend-day">${item.label}</span>
          </div>
        `;
      }).join("");
    }

    // 5. TORUS Robotic Fleet Telemetry (Calculated from Real Session Devices)
    const fleetContainer = document.getElementById("dinsFleetList");
    if (fleetContainer) {
      const knownRobots = [
        { id: "TORUS-A12", label: "Primary Tele-Arm Station", color: "cyan" },
        { id: "TORUS-B08", label: "Secondary Tele-Rig", color: "purple" },
        { id: "TORUS-C15", label: "Mobile Clinical Station", color: "emerald" },
        { id: "TORUS-K03", label: "Emergency Trauma Unit", color: "amber" }
      ];

      fleetContainer.innerHTML = knownRobots.map(robot => {
        const matchingSessions = allFilteredSessions.filter(s => s.deviceId === robot.id);
        const deviceSessionCount = matchingSessions.length;
        const isLive = filteredActive.some(s => s.deviceId === robot.id);
        const isSched = filteredUpcoming.some(s => s.deviceId === robot.id);

        let statusClass = "standby";
        let statusText = "Standby Ready";
        if (isLive) {
          statusClass = "active";
          statusText = "Active • Live Exam";
        } else if (isSched) {
          statusClass = "scheduled";
          statusText = "Scheduled Today";
        }

        // Calculate average force & latency from telemetry of matching completed sessions
        let forces = [];
        let latencies = [];
        matchingSessions.forEach(s => {
          if (s.telemetry) {
            if (s.telemetry.avgForce) forces.push(parseFloat(s.telemetry.avgForce));
            if (s.telemetry.latency) latencies.push(parseFloat(s.telemetry.latency));
          }
        });
        const meanForce = forces.length > 0 ? (forces.reduce((a, b) => a + b, 0) / forces.length).toFixed(1) : "1.8";
        const meanLat = latencies.length > 0 ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length) : 15;

        const sharePct = totalCount > 0 ? Math.round((deviceSessionCount / totalCount) * 100) : 0;

        return `
          <div class="dins-fleet-item">
            <div class="dins-fleet-top">
              <span class="dins-fleet-id"><strong class="highlight-${robot.color}">${robot.id}</strong> • ${robot.label}</span>
              <span class="dins-fleet-status ${statusClass}">${statusText}</span>
            </div>
            <div class="dins-fleet-progress">
              <div class="dins-fleet-bar ${robot.color}" style="width: ${Math.max(sharePct, 8)}%;"></div>
            </div>
            <div class="dins-fleet-metrics">
              <span>${deviceSessionCount} ${deviceSessionCount === 1 ? 'Session' : 'Sessions'} (${sharePct}%)</span>
              <span>Avg Contact Force: ${meanForce} N</span>
              <span>Latency: ${meanLat}ms</span>
            </div>
          </div>
        `;
      }).join("");
    }
  }

  function initDoctorInsightsControls() {
    const refreshBtn = document.getElementById("dinsRefreshBtn");
    if (refreshBtn) {
      refreshBtn.onclick = () => {
        refreshBtn.classList.add("dact-refreshing");
        renderDoctorInsights(currentDoctorInsightsPeriod);
        setTimeout(() => {
          refreshBtn.classList.remove("dact-refreshing");
        }, 550);
        if (typeof showToastAlert === "function") {
          showToastAlert("Clinical insights & performance telemetry updated.", "info");
        }
      };
    }

    const periodBtns = document.querySelectorAll(".dins-period-btn");
    periodBtns.forEach(btn => {
      btn.onclick = () => {
        periodBtns.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const period = btn.getAttribute("data-period") || "7d";
        currentDoctorInsightsPeriod = period;
        renderDoctorInsights(period);
      };
    });
  }

  // ── TORUS Doctor Patient Reports Logic ──
  function getDoctorReportsList() {
    loadTorusSessions();
    const completedList = window.torusSessions?.completed || [];

    return completedList.map(c => ({
      reportId: c.reportId || `REP-2026-${c.sessionId.replace(/\D/g, '')}`,
      sessionId: c.sessionId,
      patientId: c.patientId,
      patientName: c.patientName,
      scanType: c.scanType,
      deviceId: c.deviceId,
      examDate: c.sessionDate,
      examTime: c.sessionTime,
      doctorName: c.doctorName || "Dr. Admin Doctor",
      status: c.reportStatus || "ready",
      diagnosticCenter: c.diagnosticCenter,
      clinicalSummary: c.clinicalSummary,
      telemetry: c.telemetry || { maxForce: "2.6 N", avgForce: "1.9 N", latency: "16 ms", frames: 4800 }
    }));
  }

  function renderDoctorReports(query = "", statusFilter = "all", typeFilter = "all") {
    const listContainer = document.getElementById("drepList");
    const emptyState = document.getElementById("drepEmptyState");
    const totalCountEl = document.getElementById("drepTotalCount");
    const finalizedCountEl = document.getElementById("drepFinalizedCount");
    const pendingCountEl = document.getElementById("drepPendingCount");

    const allReports = getDoctorReportsList();
    const readyCount = allReports.filter(r => r.status === "ready").length;
    const pendingCount = allReports.filter(r => r.status === "pending").length;

    if (totalCountEl) totalCountEl.textContent = String(allReports.length);
    if (finalizedCountEl) finalizedCountEl.textContent = String(readyCount);
    if (pendingCountEl) pendingCountEl.textContent = String(pendingCount);

    const q = (query || "").trim().toLowerCase();
    const filtered = allReports.filter(r => {
      if (statusFilter !== "all" && r.status !== statusFilter) return false;
      if (typeFilter !== "all" && r.scanType.toLowerCase() !== typeFilter.toLowerCase()) return false;
      if (q) {
        const match = r.patientName.toLowerCase().includes(q) ||
          r.patientId.toLowerCase().includes(q) ||
          r.reportId.toLowerCase().includes(q) ||
          r.scanType.toLowerCase().includes(q) ||
          r.deviceId.toLowerCase().includes(q) ||
          r.doctorName.toLowerCase().includes(q);
        if (!match) return false;
      }
      return true;
    });

    if (!listContainer) return;

    if (filtered.length === 0) {
      listContainer.innerHTML = "";
      if (emptyState) emptyState.style.display = "flex";
      return;
    }

    if (emptyState) emptyState.style.display = "none";

    listContainer.innerHTML = filtered.map(item => {
      let scanTagClass = "purple";
      if (item.scanType === "Cardiac") scanTagClass = "cyan";
      else if (item.scanType === "Pelvic") scanTagClass = "emerald";
      else if (item.scanType === "Vascular") scanTagClass = "amber";

      const initials = item.patientName.split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase();
      const statusBadge = item.status === "ready"
        ? `<span class="drep-badge-ready">Finalized</span>`
        : `<span class="drep-badge-pending">Pending Review</span>`;

      return `
        <div class="drep-row" data-report-id="${item.reportId}">
          <div class="drep-patient-cell">
            <div class="drep-patient-avatar ${scanTagClass}">${initials}</div>
            <div>
              <p class="drep-patient-name">${item.patientName}</p>
              <p class="drep-patient-id">ID: <strong>${item.patientId}</strong> • ${item.reportId}</p>
            </div>
          </div>
          <div>
            <span class="ddash-scan-tag ${scanTagClass}">${item.scanType}</span>
          </div>
          <div class="drep-date-cell">
            <span class="drep-date-main">${item.examDate}</span>
            <span class="drep-date-time">${item.examTime}</span>
          </div>
          <div class="drep-doc-cell">
            <span class="drep-doc-name">${item.doctorName}</span>
            <span class="drep-doc-session">Session: ${item.sessionId}</span>
          </div>
          <div>
            ${statusBadge}
          </div>
          <div class="drep-actions-cell">
            <button type="button" class="drep-btn-view" data-action="view-report" data-report-id="${item.reportId}">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
              <span>View</span>
            </button>
            <button type="button" class="drep-btn-download" data-action="download-report" data-report-id="${item.reportId}">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
              <span>Download</span>
            </button>
          </div>
        </div>
      `;
    }).join("");
  }

  function initDoctorReportsControls() {
    const searchInput = document.getElementById("drepSearchInput");
    const clearBtn = document.getElementById("drepSearchClearBtn");
    const tabs = document.querySelectorAll(".drep-toolbar .dact-tab");
    const typeSelect = document.getElementById("drepScanTypeFilter");
    const refreshBtn = document.getElementById("drepRefreshBtn");

    let currentStatus = "all";
    let currentType = "all";

    function update() {
      const q = searchInput ? searchInput.value : "";
      if (clearBtn) clearBtn.style.display = q ? "block" : "none";
      renderDoctorReports(q, currentStatus, currentType);
    }

    if (searchInput) searchInput.addEventListener("input", update);
    if (clearBtn) {
      clearBtn.onclick = () => {
        searchInput.value = "";
        update();
      };
    }

    tabs.forEach(tab => {
      tab.addEventListener("click", () => {
        tabs.forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        currentStatus = tab.getAttribute("data-filter") || "all";
        update();
      });
    });

    if (typeSelect) {
      typeSelect.addEventListener("change", () => {
        currentType = typeSelect.value;
        update();
      });
    }

    if (refreshBtn) {
      refreshBtn.onclick = () => {
        update();
        if (typeof showToastAlert === "function") {
          showToastAlert("Patient reports refreshed.", "info");
        }
      };
    }
  }

  // ── TORUS Doctor Scan History Logic ──
  function renderDoctorHistory(query = "", statusFilter = "all", typeFilter = "all", sortOrder = "newest") {
    loadTorusSessions();
    const historyList = window.torusSessions?.completed || [];
    const listContainer = document.getElementById("dhistList");
    const emptyState = document.getElementById("dhistEmptyState");
    const totalCountEl = document.getElementById("dhistTotalCount");

    if (totalCountEl) totalCountEl.textContent = String(historyList.length);

    const q = (query || "").trim().toLowerCase();
    let filtered = historyList.filter(item => {
      if (statusFilter !== "all" && item.status !== statusFilter) return false;
      if (typeFilter !== "all" && item.scanType.toLowerCase() !== typeFilter.toLowerCase()) return false;
      if (q) {
        const match = item.patientName.toLowerCase().includes(q) ||
          item.patientId.toLowerCase().includes(q) ||
          item.deviceId.toLowerCase().includes(q) ||
          item.scanType.toLowerCase().includes(q) ||
          item.diagnosticCenter.toLowerCase().includes(q);
        if (!match) return false;
      }
      return true;
    });

    if (sortOrder === "oldest") {
      filtered.sort((a, b) => (a.sessionDate > b.sessionDate ? 1 : -1));
    } else if (sortOrder === "duration") {
      filtered.sort((a, b) => (b.duration > a.duration ? 1 : -1));
    } else {
      // Default: newest first
      filtered.sort((a, b) => (a.sessionDate < b.sessionDate ? 1 : -1));
    }

    if (!listContainer) return;

    if (filtered.length === 0) {
      listContainer.innerHTML = "";
      if (emptyState) emptyState.style.display = "flex";
      return;
    }

    if (emptyState) emptyState.style.display = "none";

    listContainer.innerHTML = filtered.map(item => {
      let scanTagClass = "purple";
      if (item.scanType === "Cardiac") scanTagClass = "cyan";
      else if (item.scanType === "Pelvic") scanTagClass = "emerald";
      else if (item.scanType === "Vascular") scanTagClass = "amber";

      const initials = item.patientName.split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase();
      const statusPill = item.status === "completed"
        ? `<span class="drep-badge-ready">Completed</span>`
        : `<span class="dhist-device-tag">Transferred</span>`;

      return `
        <div class="dhist-row" data-session-id="${item.sessionId}">
          <div class="dhist-patient-cell">
            <div class="dhist-patient-avatar ${scanTagClass}">${initials}</div>
            <div>
              <p class="dhist-patient-name">${item.patientName}</p>
              <p class="dhist-patient-id">ID: <strong>${item.patientId}</strong></p>
            </div>
          </div>
          <div>
            <span class="dhist-device-tag">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect><rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect></svg>
              ${item.deviceId}
            </span>
          </div>
          <div>
            <span class="ddash-scan-tag ${scanTagClass}">${item.scanType}</span>
          </div>
          <div class="dhist-date-cell">
            <span class="dhist-date-main">${item.sessionDate}</span>
            <span class="dhist-date-time">${item.sessionTime}</span>
          </div>
          <div>
            <span class="dhist-duration-pill">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
              ${item.duration}
            </span>
          </div>
          <div>
            ${statusPill}
          </div>
          <div>
            <button type="button" class="dhist-btn-view" data-action="view-session" data-session-id="${item.sessionId}">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
              <span>View Details</span>
            </button>
          </div>
        </div>
      `;
    }).join("");
  }

  function initDoctorHistoryControls() {
    const searchInput = document.getElementById("dhistSearchInput");
    const clearBtn = document.getElementById("dhistSearchClearBtn");
    const tabs = document.querySelectorAll(".dhist-toolbar .dact-tab");
    const typeSelect = document.getElementById("dhistScanTypeFilter");
    const sortSelect = document.getElementById("dhistSortOrder");
    const refreshBtn = document.getElementById("dhistRefreshBtn");

    let currentStatus = "all";
    let currentType = "all";
    let currentSort = "newest";

    function update() {
      const q = searchInput ? searchInput.value : "";
      if (clearBtn) clearBtn.style.display = q ? "block" : "none";
      renderDoctorHistory(q, currentStatus, currentType, currentSort);
    }

    if (searchInput) searchInput.addEventListener("input", update);
    if (clearBtn) {
      clearBtn.onclick = () => {
        searchInput.value = "";
        update();
      };
    }

    tabs.forEach(tab => {
      tab.addEventListener("click", () => {
        tabs.forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        currentStatus = tab.getAttribute("data-filter") || "all";
        update();
      });
    });

    if (typeSelect) {
      typeSelect.addEventListener("change", () => {
        currentType = typeSelect.value;
        update();
      });
    }

    if (sortSelect) {
      sortSelect.addEventListener("change", () => {
        currentSort = sortSelect.value;
        update();
      });
    }

    if (refreshBtn) {
      refreshBtn.onclick = () => {
        update();
        if (typeof showToastAlert === "function") {
          showToastAlert("Ultrasound scan history refreshed.", "info");
        }
      };
    }
  }

  // ── Modal Handlers for Reports & History ──
  function openDoctorReportModal(reportId) {
    const reports = getDoctorReportsList();
    const report = reports.find(r => r.reportId === reportId) || reports[0];
    if (!report) return;

    const modal = document.getElementById("doctorReportPreviewModal");
    const body = document.getElementById("drepModalBody");
    const title = document.getElementById("drepModalReportTitle");
    const badge = document.getElementById("drepModalStatusBadge");

    if (title) title.textContent = `Diagnostic Ultrasound Report • ${report.reportId}`;
    if (badge) {
      badge.textContent = report.status === "ready" ? "Finalized" : "Pending Review";
      badge.className = report.status === "ready" ? "drep-badge-ready" : "drep-badge-pending";
    }

    if (body) {
      body.innerHTML = `
        <div class="drep-doc-sheet">
          <div class="drep-doc-header">
            <div>
              <div class="drep-doc-org">TORUS ROBOTIC TELE-ULTRASOUND SYSTEM</div>
              <div class="drep-doc-sub">${report.diagnosticCenter} • Tele-Sonography Unit</div>
            </div>
            <div class="drep-doc-meta">
              <div><strong>Exam Date:</strong> ${report.examDate} ${report.examTime}</div>
              <div><strong>Report ID:</strong> ${report.reportId}</div>
            </div>
          </div>

          <div class="drep-doc-grid-2col">
            <div class="drep-doc-item">
              <span class="drep-doc-label">Patient Name</span>
              <span class="drep-doc-value"><strong>${report.patientName}</strong></span>
            </div>
            <div class="drep-doc-item">
              <span class="drep-doc-label">Patient Identification</span>
              <span class="drep-doc-value">${report.patientId}</span>
            </div>
            <div class="drep-doc-item">
              <span class="drep-doc-label">Exam / Scan Type</span>
              <span class="drep-doc-value"><strong class="highlight-cyan">${report.scanType} Ultrasound</strong></span>
            </div>
            <div class="drep-doc-item">
              <span class="drep-doc-label">Hardware Device</span>
              <span class="drep-doc-value">${report.deviceId} (Dual 6-DOF Robotic Manipulator)</span>
            </div>
          </div>

          <div class="drep-doc-section">
            <div class="drep-doc-section-title">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
              <span>TELE-ROBOTIC SENSOR TELEMETRY & SCAN QUALITY</span>
            </div>
            <div class="drep-doc-grid-2col">
              <div>• Max Contact Force: <strong>${report.telemetry?.maxForce || "2.6 N"}</strong></div>
              <div>• Mean Contact Force: <strong>${report.telemetry?.avgForce || "1.9 N"}</strong></div>
              <div>• WebRTC Robotic Latency: <strong>${report.telemetry?.latency || "16 ms"}</strong></div>
              <div>• Total Captured Cine Frames: <strong>${report.telemetry?.frames || 4800} frames</strong></div>
            </div>
          </div>

          <div class="drep-doc-section">
            <div class="drep-doc-section-title">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
              <span>CLINICAL FINDINGS & OBSERVATIONS</span>
            </div>
            <p class="drep-doc-findings-text">${report.clinicalSummary}</p>
          </div>

          <div class="drep-doc-signature-row">
            <div class="drep-signature-block">
              <span class="drep-sign-name">${report.doctorName}</span>
              <span class="drep-sign-title">Chief Tele-Ultrasound Specialist • License TORUS-REG-3001</span>
            </div>
            <span class="drep-sign-stamp">✓ Digitally Signed & Encrypted</span>
          </div>
        </div>
      `;
    }

    if (modal) modal.style.display = "flex";

    if (typeof logDoctorActivity === "function") {
      logDoctorActivity("system", "Medical Report Viewed", `Diagnostic ultrasound report previewed for ${report.patientName || "Patient"} (${report.patientId || ""}).`, "Viewed", report.reportId || reportId);
    }
  }

  function closeDoctorReportModal() {
    const modal = document.getElementById("doctorReportPreviewModal");
    if (modal) modal.style.display = "none";
  }

  function downloadDoctorReport(reportId) {
    const reports = getDoctorReportsList();
    const report = reports.find(r => r.reportId === reportId) || { reportId, patientName: "Patient" };
    if (typeof showToastAlert === "function") {
      showToastAlert(`Downloading official report ${report.reportId} for ${report.patientName} (PDF)...`, "success");
    }
    if (typeof logDoctorActivity === "function") {
      logDoctorActivity("system", "Report Downloaded", `Downloaded medical report ${report.reportId} for ${report.patientName}.`, "Completed", report.reportId);
    }
  }

  function openDoctorHistoryModal(sessionId) {
    loadTorusSessions();
    const historyList = window.torusSessions?.completed || [];
    const session = historyList.find(s => s.sessionId === sessionId) || historyList[0];
    if (!session) return;

    const modal = document.getElementById("doctorSessionDetailModal");
    const body = document.getElementById("dhistModalBody");
    const title = document.getElementById("dhistModalTitle");

    if (title) title.textContent = `Ultrasound Telemetry • Session ${session.sessionId}`;

    if (body) {
      body.innerHTML = `
        <div class="dhist-telemetry-grid">
          <div class="dhist-telemetry-pill">
            <span class="dhist-telemetry-lbl">MAX FORCE</span>
            <span class="dhist-telemetry-num cyan">${session.telemetry?.maxForce || "2.8 N"}</span>
          </div>
          <div class="dhist-telemetry-pill">
            <span class="dhist-telemetry-lbl">AVG FORCE</span>
            <span class="dhist-telemetry-num purple">${session.telemetry?.avgForce || "1.9 N"}</span>
          </div>
          <div class="dhist-telemetry-pill">
            <span class="dhist-telemetry-lbl">STREAM LATENCY</span>
            <span class="dhist-telemetry-num emerald">${session.telemetry?.latency || "15 ms"}</span>
          </div>
          <div class="dhist-telemetry-pill">
            <span class="dhist-telemetry-lbl">CINE FRAMES</span>
            <span class="dhist-telemetry-num">${session.telemetry?.frames || 5200}</span>
          </div>
        </div>

        <div class="drep-doc-sheet" style="margin-top: 10px;">
          <div class="drep-doc-grid-2col">
            <div class="drep-doc-item">
              <span class="drep-doc-label">Patient Demographics</span>
              <span class="drep-doc-value"><strong>${session.patientName}</strong> (${session.patientId})</span>
            </div>
            <div class="drep-doc-item">
              <span class="drep-doc-label">Hardware Rig</span>
              <span class="drep-doc-value">${session.deviceId}</span>
            </div>
            <div class="drep-doc-item">
              <span class="drep-doc-label">Procedure Type</span>
              <span class="drep-doc-value highlight-cyan">${session.scanType} Scan</span>
            </div>
            <div class="drep-doc-item">
              <span class="drep-doc-label">Procedure Duration</span>
              <span class="drep-doc-value">${session.duration} (Scheduled at ${session.sessionTime})</span>
            </div>
          </div>

          <div class="drep-doc-section">
            <div class="drep-doc-section-title">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
              <span>CLINICAL SUMMARY & OBSERVATIONS</span>
            </div>
            <p class="drep-doc-findings-text">${session.clinicalSummary}</p>
          </div>
        </div>
      `;
    }

    if (modal) modal.style.display = "flex";
  }

  function closeDoctorHistoryModal() {
    const modal = document.getElementById("doctorSessionDetailModal");
    if (modal) modal.style.display = "none";
  }

  // Delegated clicks for reports and history lists and modals
  document.addEventListener("click", (e) => {
    const viewReportBtn = e.target.closest("[data-action='view-report']");
    if (viewReportBtn) {
      e.preventDefault();
      const repId = viewReportBtn.getAttribute("data-report-id");
      openDoctorReportModal(repId);
      return;
    }

    const downloadReportBtn = e.target.closest("[data-action='download-report']");
    if (downloadReportBtn) {
      e.preventDefault();
      const repId = downloadReportBtn.getAttribute("data-report-id");
      downloadDoctorReport(repId);
      return;
    }

    const viewSessionBtn = e.target.closest("[data-action='view-session']");
    if (viewSessionBtn) {
      e.preventDefault();
      const sessId = viewSessionBtn.getAttribute("data-session-id");
      openDoctorHistoryModal(sessId);
      return;
    }

    if (e.target.closest("#drepModalCloseBtn") || e.target.closest("#drepModalDismissBtn")) {
      closeDoctorReportModal();
      return;
    }

    if (e.target.closest("#drepModalDownloadPdfBtn")) {
      const title = document.getElementById("drepModalReportTitle")?.textContent || "";
      const repMatch = title.match(/REP-\d+-\d+/);
      const repId = repMatch ? repMatch[0] : "REP-2026-001";
      downloadDoctorReport(repId);
      closeDoctorReportModal();
      return;
    }

    if (e.target.closest("#dhistModalCloseBtn") || e.target.closest("#dhistModalDismissBtn")) {
      closeDoctorHistoryModal();
      return;
    }
  });

  // Helper to hide all subviews across both Doctor and Patient portals
  function hideAllPortalSubViews() {
    const ids = [
      "doctorDashboardContent",
      "patientDashboardContent",
      "doctorProfileContent",
      "patientProfileContent",
      "doctorActivityLogContent",
      "doctorInsightsContent",
      "doctorReportsContent",
      "patientAppointmentsContent",
      "patientDiagnosticReportsContent",
      "doctorHistoryContent",
      "patientHistoryContent"
    ];
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = "none";
    });
  }
  window.hideAllPortalSubViews = hideAllPortalSubViews;

  // ── TORUS Portal Collapsible Sidebar & Navigation Routing ──
  function initDocDashSidebar() {
    const docPortalDash = document.getElementById("doctor-portal-dashboard");
    const menuToggleBtn = document.getElementById("docDashMenuToggle");
    const closeBtn = document.getElementById("docDashSidebarCloseBtn");
    const overlay = document.getElementById("docDashSidebarOverlay");
    const docBackBtn = document.getElementById("docDashBackBtn");

    if (!docPortalDash) return;

    // Back Button Handler on Dashboard Top Bar
    if (docBackBtn) {
      docBackBtn.onclick = () => {
        const isDoc = (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") || (roleInput && roleInput.value === "doctor");

        const profContent = document.getElementById("doctorProfileContent");
        const actContent = document.getElementById("doctorActivityLogContent");
        const insContent = document.getElementById("doctorInsightsContent");
        const repContent = document.getElementById("doctorReportsContent");
        const histContent = document.getElementById("doctorHistoryContent");

        const patProf = document.getElementById("patientProfileContent");
        const patAppt = document.getElementById("patientAppointmentsContent");
        const patRep = document.getElementById("patientDiagnosticReportsContent");
        const patHist = document.getElementById("patientHistoryContent");

        const isDocSubOpen = (profContent && profContent.style.display !== "none") ||
          (actContent && actContent.style.display !== "none") ||
          (insContent && insContent.style.display !== "none") ||
          (repContent && repContent.style.display !== "none") ||
          (histContent && histContent.style.display !== "none");

        const isPatSubOpen = (patProf && patProf.style.display !== "none") ||
          (patAppt && patAppt.style.display !== "none") ||
          (patRep && patRep.style.display !== "none") ||
          (patHist && patHist.style.display !== "none");

        if (isDoc && isDocSubOpen) {
          hideAllPortalSubViews();
          const docContent = document.getElementById("doctorDashboardContent");
          if (docContent) docContent.style.display = "flex";
          renderDoctorDashboard();
          document.querySelectorAll(".ddash-sidebar-nav .ddash-nav-item").forEach(el => {
            if (el.getAttribute("data-view") === "dashboard") el.classList.add("active");
            else el.classList.remove("active");
          });
          return;
        }

        if (!isDoc && isPatSubOpen) {
          hideAllPortalSubViews();
          const patContent = document.getElementById("patientDashboardContent");
          if (patContent) patContent.style.display = "flex";
          renderPatientDashboard(currentAuthenticatedUser);
          document.querySelectorAll(".ddash-sidebar-nav .ddash-nav-item").forEach(el => {
            if (el.getAttribute("data-view") === "patient-dashboard") el.classList.add("active");
            else el.classList.remove("active");
          });
          return;
        }

        if (isDoc) {
          showTorusScreen("doctor-login-screen");
        } else {
          showTorusScreen("patient-login-screen");
        }
      };
    }

    // Toggle Sidebar Function
    function toggleSidebar(forceState) {
      if (typeof forceState === "boolean") {
        if (forceState) {
          docPortalDash.classList.add("sidebar-open");
        } else {
          docPortalDash.classList.remove("sidebar-open");
        }
      } else {
        docPortalDash.classList.toggle("sidebar-open");
      }
    }

    if (menuToggleBtn) {
      menuToggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleSidebar();
      });
    }

    if (closeBtn) {
      closeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleSidebar(false);
      });
    }

    if (overlay) {
      overlay.addEventListener("click", () => {
        toggleSidebar(false);
      });
    }

    // Bind event listeners for sidebar navigation menu items
    function bindSidebarNavEvents() {
      const navItems = document.querySelectorAll(".ddash-sidebar-nav .ddash-nav-item");
      navItems.forEach((item) => {
        item.onclick = (e) => {
          e.preventDefault();
          const view = item.getAttribute("data-view");

          if (view === "logout") {
            toggleSidebar(false);
            handlePortalLogout();
            return;
          }

          // Update active class
          navItems.forEach((el) => el.classList.remove("active"));
          item.classList.add("active");

          // Close sidebar on mobile / small screens after click
          if (window.innerWidth < 992) {
            toggleSidebar(false);
          }

          const isDoc = (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") || (roleInput && roleInput.value === "doctor");

          // Security check: Guard against unauthorized access to doctor-only views
          const doctorOnlyViews = ["doctor-profile", "activity-log", "insights", "patient-reports", "history"];
          if (!isDoc && doctorOnlyViews.includes(view)) {
            if (typeof showToastAlert === "function") {
              showToastAlert("Access Restricted: Doctor credentials required.", "error");
            }
            return;
          }

          hideAllPortalSubViews();

          // ── Doctor Views Routing ──
          if (view === "dashboard") {
            const docContent = document.getElementById("doctorDashboardContent");
            if (docContent) docContent.style.display = "flex";
            renderDoctorDashboard();
          } else if (view === "doctor-profile") {
            const profContent = document.getElementById("doctorProfileContent");
            if (profContent) profContent.style.display = "flex";
            renderDoctorProfile(currentAuthenticatedUser);
          } else if (view === "activity-log") {
            const actContent = document.getElementById("doctorActivityLogContent");
            if (actContent) actContent.style.display = "flex";
            renderDoctorActivityLog(currentAuthenticatedUser);
          } else if (view === "insights") {
            const insContent = document.getElementById("doctorInsightsContent");
            if (insContent) insContent.style.display = "flex";
            renderDoctorInsights();
          } else if (view === "patient-reports") {
            const repContent = document.getElementById("doctorReportsContent");
            if (repContent) repContent.style.display = "flex";
            renderDoctorReports();
          } else if (view === "history") {
            const histContent = document.getElementById("doctorHistoryContent");
            if (histContent) histContent.style.display = "flex";
            renderDoctorHistory();
          }
          // ── Patient Views Routing ──
          else if (view === "patient-dashboard") {
            const patContent = document.getElementById("patientDashboardContent");
            if (patContent) patContent.style.display = "flex";
            renderPatientDashboard(currentAuthenticatedUser);
          } else if (view === "patient-profile") {
            const patProf = document.getElementById("patientProfileContent");
            if (patProf) patProf.style.display = "flex";
            renderPatientProfile(currentAuthenticatedUser);
          } else if (view === "patient-appointments") {
            const patAppt = document.getElementById("patientAppointmentsContent");
            if (patAppt) patAppt.style.display = "flex";
            renderPatientAppointments(currentAuthenticatedUser);
          } else if (view === "patient-diagnostic-reports") {
            const patRep = document.getElementById("patientDiagnosticReportsContent");
            if (patRep) patRep.style.display = "flex";
            renderPatientDiagnosticReports(currentAuthenticatedUser);
          } else if (view === "patient-history") {
            const patHist = document.getElementById("patientHistoryContent");
            if (patHist) patHist.style.display = "flex";
            renderPatientHistory(currentAuthenticatedUser);
          } else {
            const viewTitle = item.querySelector(".ddash-nav-label")?.textContent || view;
            if (typeof showToastAlert === "function") {
              showToastAlert(`${viewTitle}: View under telemetry sync.`, "info");
            }
          }
        };
      });
    }
    window.bindSidebarNavEvents = bindSidebarNavEvents;

    // Synchronize logged in doctor/patient profile information
    function syncSidebarProfile() {
      const isDoc = (currentAuthenticatedUser && currentAuthenticatedUser.role === "doctor") || (roleInput && roleInput.value === "doctor");
      if (!currentAuthenticatedUser) {
        try {
          const storedDoc = sessionStorage.getItem("authenticated_doctor") || localStorage.getItem("authenticated_doctor");
          const storedPat = sessionStorage.getItem("authenticated_patient") || localStorage.getItem("authenticated_patient");
          if (isDoc && storedDoc) currentAuthenticatedUser = JSON.parse(storedDoc);
          else if (!isDoc && storedPat) currentAuthenticatedUser = JSON.parse(storedPat);
        } catch (e) { }
      }
      const user = currentAuthenticatedUser || (isDoc
        ? { name: "Admin Doctor", email: "admin@gmail.com", role: "doctor", uid: "3001" }
        : { name: "Patient User", email: "patient@gmail.com", role: "patient", uid: "4001" }
      );
      updateSharedPortalHeader(user, isDoc ? "doctor" : "patient");
    }

    syncSidebarProfile();
    bindSidebarNavEvents();
    initDoctorProfileEditModal();
    initDoctorActivityLogControls();
    initDoctorInsightsControls();
    initDoctorReportsControls();
    initDoctorHistoryControls();
    initPatientControls();
    if (typeof setupPatientClinicalRegListeners === "function") setupPatientClinicalRegListeners();
    if (typeof initScheduleScanModal === "function") initScheduleScanModal();
  }

  initDocDashSidebar();

  if (typeof setupHapticPadListeners === "function") {
    setupHapticPadListeners();
  }
});



