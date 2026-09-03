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
  feedTypeContainer.style.display = selectedRole === "patient" ? "" : "none";
  updateControlsButtonVisibility();
});

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
  const statusText = statusEl.querySelector(".status-text");
  if (statusText) {
    statusText.textContent = message;
  } else {
    statusEl.textContent = message;
  }

  statusEl.className = "status-pill";
  const msgLower = message.toLowerCase();
  if (msgLower.includes("connected to")) {
    statusEl.classList.add("connected");
  } else if (msgLower.includes("connecting") || msgLower.includes("joining")) {
    statusEl.classList.add("connecting");
  } else if (msgLower.includes("failed") || msgLower.includes("error") || msgLower.includes("enter")) {
    statusEl.classList.add("error");
  } else {
    statusEl.classList.add("disconnected");
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
  const appId = appIdInput.value.trim();
  const channel = channelInput.value.trim();
  const tokenText = tokenInput.value.trim();
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
    appId: appIdInput.value,
    channel: channelInput.value,
    role: roleInput.value,
    feedType: feedTypeInput.value,
    token: tokenInput.value,
    uid: uidInput.value
  };
  settingsModal.classList.add("active");
}

function closeSettings(save = false) {
  if (!save) {
    appIdInput.value = originalSettings.appId;
    channelInput.value = originalSettings.channel;
    roleInput.value = originalSettings.role;
    feedTypeInput.value = originalSettings.feedType;
    tokenInput.value = originalSettings.token;
    uidInput.value = originalSettings.uid;
    roleInput.dispatchEvent(new Event("change"));
  }
  settingsModal.classList.remove("active");
}

settingsBtn.addEventListener("click", openSettings);
closeModalBtn.addEventListener("click", () => closeSettings(false));
cancelSettingsBtn.addEventListener("click", () => closeSettings(false));
saveSettingsBtn.addEventListener("click", () => closeSettings(true));

settingsModal.addEventListener("click", (e) => {
  if (e.target === settingsModal) {
    closeSettings(false);
  }
});

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

// Fetch initial parameters directly from curv_proper_code.py to sync Doctor controls
async function syncDoctorControlsFromPatientState() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();
    console.log("[Doctor UI] Synced state from curv_proper_code.py:", data);

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

// Role Selection screen card click handlers
const roleCards = document.querySelectorAll(".role-card-item");
const roleSelectionScreen = document.getElementById("role-selection-screen");
const doctorLoginScreen = document.getElementById("doctor-login-screen");
const doctorRegisterScreen = document.getElementById("doctor-register-screen");
const appDashboard = document.getElementById("app-dashboard");

roleCards.forEach(card => {
  card.addEventListener("click", () => {
    const selectedRole = card.getAttribute("data-role");
    const selectedUid = card.getAttribute("data-uid");

    if (selectedRole === "doctor") {
      // Show Doctor Secure Login screen instead of jumping directly to dashboard
      roleSelectionScreen.style.display = "none";
      if (doctorLoginScreen) doctorLoginScreen.style.display = "flex";
      return;
    }

    roleInput.value = selectedRole;
    uidInput.value = selectedUid;

    // Trigger settings updates (like feedType container visibility)
    roleInput.dispatchEvent(new Event("change"));

    // Navigate from selection page to dashboard
    roleSelectionScreen.style.display = "none";
    appDashboard.style.display = "flex";

    // Trigger header logo card boot sequence animation
    if (typeof triggerHeaderBootSequence === "function") {
      triggerHeaderBootSequence();
    }

    // Push history state to enable back button navigation integration
    if (window.history && window.history.pushState) {
      window.history.pushState({ page: "dashboard" }, "");
    }
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
  backBtn.addEventListener("click", async () => {
    // If currently in a call, trigger leaveCall to disconnect and clean up safely
    if (leaveBtn && !leaveBtn.disabled) {
      try {
        await leaveCall();
      } catch (err) {
        console.warn("Error leaving call on back navigation:", err);
      }
    }

    // Attempt history navigation if history exists, with a fallback to direct SPA navigation
    if (window.history && window.history.length > 1) {
      window.history.back();
      // Safety fallback in case browser history does not transition state
      setTimeout(() => {
        if (appDashboard && appDashboard.style.display !== "none") {
          appDashboard.style.display = "none";
          roleSelectionScreen.style.display = "flex";
        }
      }, 100);
    } else {
      if (appDashboard && roleSelectionScreen) {
        appDashboard.style.display = "none";
        roleSelectionScreen.style.display = "flex";
      }
    }
  });
}

// Listen for browser back/forward navigation to update SPA UI states and safely leave active calls
window.addEventListener("popstate", async (event) => {
  const isDashboard = event.state && event.state.page === "dashboard";
  if (isDashboard) {
    if (roleSelectionScreen && appDashboard) {
      roleSelectionScreen.style.display = "none";
      appDashboard.style.display = "flex";
      if (typeof triggerHeaderBootSequence === "function") {
        triggerHeaderBootSequence();
      }
    }
  } else {
    // If currently in a call, trigger leaveCall to disconnect and clean up safely
    if (leaveBtn && !leaveBtn.disabled) {
      try {
        await leaveCall();
      } catch (err) {
        console.warn("Error leaving call on back navigation:", err);
      }
    }
    if (roleSelectionScreen && appDashboard) {
      appDashboard.style.display = "none";
      roleSelectionScreen.style.display = "flex";
    }
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
  card.addEventListener("click", function(e) {
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

      // Safely add mobile column if missing (for pre-existing databases)
      try {
        dbInstance.run("SELECT mobile FROM doctors LIMIT 1");
      } catch (e) {
        try {
          dbInstance.run("ALTER TABLE doctors ADD COLUMN mobile TEXT DEFAULT ''");
          saveSQLiteState();
          console.log("[SQLite] Migrated: added 'mobile' column.");
        } catch (e2) {}
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
    }
  } catch (err) {
    console.warn("[SQLite] sql.js initialization warning (falling back to REST API):", err);
  }
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
async function callBackendAPI(endpoint, payload) {
  const isPort8000 = window.location.port === "8000";
  const candidateUrls = isPort8000
    ? [
        endpoint,
        `http://127.0.0.1:8000${endpoint}`,
        `http://localhost:8000${endpoint}`
      ]
    : [
        `http://127.0.0.1:8000${endpoint}`,
        `http://localhost:8000${endpoint}`,
        endpoint,
        `http://127.0.0.1:8080${endpoint}`,
        `http://localhost:8080${endpoint}`,
        `http://127.0.0.1:5000${endpoint}`,
        `http://localhost:5000${endpoint}`
      ];

  const uniqueUrls = Array.from(new Set(candidateUrls));

  for (const url of uniqueUrls) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 6000);

      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal
      });
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

// Register Doctor in SQLite
async function registerDoctorAccount(name, email, password, mobile, uid = "") {
  const cleanEmail = email.trim().toLowerCase();
  const cleanName = name.trim();
  const cleanMobile = mobile.trim();
  const cleanUid = uid.trim().toUpperCase();
  const pwdHash = await hashPasswordSHA256(password);

  // 1. Try Backend REST API first
  const apiRes = await callBackendAPI("/api/doctors/register", {
    name: cleanName,
    email: cleanEmail,
    password: password,
    mobile: cleanMobile,
    uid: cleanUid
  });
  if (apiRes) return apiRes;

  // 2. Client SQLite fallback
  if (dbInstance) {
    // Check duplicate email
    const checkRes = dbInstance.exec(`SELECT id FROM doctors WHERE LOWER(email) = '${cleanEmail}'`);
    if (checkRes && checkRes.length > 0 && checkRes[0].values.length > 0) {
      return { success: false, error: "An account with this email already exists." };
    }

    // Process UID
    let finalUid = cleanUid;
    if (finalUid) {
      const uidCheck = dbInstance.exec(`SELECT id FROM doctors WHERE UPPER(uid) = '${finalUid}'`);
      if (uidCheck && uidCheck.length > 0 && uidCheck[0].values.length > 0) {
        return { success: false, error: `Professional ID '${finalUid}' is already in use.` };
      }
    } else {
      finalUid = generateProfessionalId();
    }

    dbInstance.run(
      "INSERT INTO doctors (uid, name, email, password_hash, role, mobile) VALUES (?, ?, ?, ?, 'doctor', ?)",
      [finalUid, cleanName, cleanEmail, pwdHash, cleanMobile]
    );
    saveSQLiteState();

    return {
      success: true,
      doctor: { uid: finalUid, name: cleanName, email: cleanEmail, mobile: cleanMobile, role: "doctor" }
    };
  }

  return { success: false, error: "Database engine unavailable. Please try again." };
}

// Authenticate Doctor against SQLite (Email OR UID)
async function authenticateDoctorAccount(loginId, password) {
  const cleanLogin = loginId.trim().toLowerCase();
  const pwdHash = await hashPasswordSHA256(password);

  // 1. Try Backend REST API first
  const apiRes = await callBackendAPI("/api/doctors/login", {
    login_id: cleanLogin,
    password: password
  });
  if (apiRes) return apiRes;

  // 2. Client SQLite fallback
  if (dbInstance) {
    const stmt = `SELECT id, uid, name, email, role FROM doctors WHERE (LOWER(email) = '${cleanLogin}' OR LOWER(uid) = '${cleanLogin}') AND password_hash = '${pwdHash}'`;
    const res = dbInstance.exec(stmt);
    if (res && res.length > 0 && res[0].values.length > 0) {
      const row = res[0].values[0];
      return {
        success: true,
        doctor: { id: row[0], uid: String(row[1]), name: row[2], email: row[3], role: row[4] }
      };
    }
    return { success: false, error: "Invalid email/UID or password." };
  }

  return { success: false, error: "Invalid credentials." };
}

// Request Doctor Password Reset OTP (Real Backend API + Client SQLite Fallback)
async function requestDoctorResetOTP(identifier) {
  const cleanId = identifier.trim().toLowerCase();

  // 1. Try Backend REST API first (sends real email via SMTP)
  const apiRes = await callBackendAPI("/api/doctors/forgot-password/send-otp", {
    identifier: cleanId
  });
  if (apiRes) return apiRes;

  // 2. Client SQLite fallback
  if (dbInstance) {
    const stmt = `SELECT id, uid, name, email FROM doctors WHERE LOWER(email) = '${cleanId}' OR LOWER(uid) = '${cleanId}'`;
    const res = dbInstance.exec(stmt);
    if (res && res.length > 0 && res[0].values.length > 0) {
      const row = res[0].values[0];
      const docEmail = String(row[3]);
      const docUid = String(row[1]);

      // Generate a 6-digit OTP for offline/demo recovery
      const offlineOtp = String(Math.floor(100000 + Math.random() * 900000));
      const expiry = Date.now() + 10 * 60 * 1000;
      sessionStorage.setItem("torus_offline_reset", JSON.stringify({
        email: docEmail,
        uid: docUid,
        otp: offlineOtp,
        expires: expiry
      }));

      return {
        success: true,
        message: `A 6-digit OTP code has been generated: ${offlineOtp} (Offline Fallback)`,
        masked_email: maskEmailAddress(docEmail),
        email: docEmail,
        offline: true
      };
    }
    return {
      success: false,
      error: "No account found with this email or User ID."
    };
  }

  return {
    success: false,
    error: "Backend API is unreachable. Please verify that the Python backend server is running."
  };
}

// Verify Doctor Password Reset OTP (Real Backend API + Client SQLite Fallback)
async function verifyDoctorResetOTP(identifier, otp) {
  const cleanId = identifier.trim().toLowerCase();
  const cleanOtp = String(otp).trim();

  // 1. Try Backend REST API first
  const apiRes = await callBackendAPI("/api/doctors/forgot-password/verify-otp", {
    identifier: cleanId,
    otp: cleanOtp
  });
  if (apiRes) return apiRes;

  // 2. Client SQLite fallback
  const offlineDataStr = sessionStorage.getItem("torus_offline_reset");
  if (offlineDataStr) {
    try {
      const offlineData = JSON.parse(offlineDataStr);
      if (Date.now() > offlineData.expires) {
        return { success: false, error: "OTP has expired. Please request a new OTP." };
      }
      if (offlineData.otp !== cleanOtp) {
        return { success: false, error: "Invalid OTP code. Please enter the valid 6-digit code." };
      }
      const resetToken = "offline_token_" + Date.now();
      offlineData.reset_token = resetToken;
      sessionStorage.setItem("torus_offline_reset", JSON.stringify(offlineData));
      return {
        success: true,
        message: "OTP verified successfully.",
        reset_token: resetToken,
        email: offlineData.email
      };
    } catch (e) {
      console.warn("Offline OTP parse warning:", e);
    }
  }

  return {
    success: false,
    error: "Backend API is unreachable. Please verify that the Python backend server is running."
  };
}

// Reset Doctor Password with Verified Token (Real Backend API + Client SQLite Fallback)
async function resetDoctorPasswordWithToken(identifier, resetToken, newPassword) {
  const cleanId = identifier.trim().toLowerCase();
  const pwdHash = await hashPasswordSHA256(newPassword);

  // 1. Try Backend REST API first
  const apiRes = await callBackendAPI("/api/doctors/forgot-password/reset", {
    identifier: cleanId,
    reset_token: resetToken,
    new_password: newPassword
  });
  if (apiRes) {
    if (apiRes.success && dbInstance) {
      dbInstance.run(`UPDATE doctors SET password_hash = '${pwdHash}' WHERE LOWER(email) = '${cleanId}' OR LOWER(uid) = '${cleanId}'`);
      saveSQLiteState();
    }
    return apiRes;
  }

  // 2. Client SQLite fallback
  if (dbInstance) {
    const offlineDataStr = sessionStorage.getItem("torus_offline_reset");
    let isValidOfflineSession = false;
    if (offlineDataStr) {
      try {
        const offlineData = JSON.parse(offlineDataStr);
        if (offlineData.reset_token === resetToken || resetToken === "legacy_direct") {
          isValidOfflineSession = true;
        }
      } catch (e) {}
    }

    if (isValidOfflineSession || resetToken === "legacy_direct") {
      dbInstance.run(`UPDATE doctors SET password_hash = '${pwdHash}' WHERE LOWER(email) = '${cleanId}' OR LOWER(uid) = '${cleanId}'`);
      saveSQLiteState();
      sessionStorage.removeItem("torus_offline_reset");
      return {
        success: true,
        message: "Password updated successfully in local database. You can now log in."
      };
    }
  }

  return {
    success: false,
    error: "Backend API is unreachable. Please verify that the Python backend server is running."
  };
}

// Legacy wrapper
async function resetDoctorPasswordAccount(email, newPassword) {
  return resetDoctorPasswordWithToken(email, "legacy_direct", newPassword);
}

// Set Active Authenticated Doctor Session & Launch Dashboard
function setAuthenticatedDoctorSession(doctor) {
  currentAuthenticatedUser = doctor;

  // Bind values to settings inputs
  if (roleInput) {
    roleInput.value = "doctor";
    roleInput.dispatchEvent(new Event("change"));
  }
  if (uidInput) {
    uidInput.value = doctor.uid;
  }

  // Update dynamic Header User Badge
  const nameEl = document.getElementById("user-display-name");
  const uidEl = document.getElementById("user-display-uid");
  const badgeEl = document.getElementById("header-user-badge");

  if (nameEl) {
    nameEl.textContent = doctor.name.startsWith("Dr.") ? doctor.name : `Dr. ${doctor.name}`;
  }
  if (uidEl) {
    // Display Professional ID (DOC-XXXXX) or fallback to UID format
    uidEl.textContent = doctor.uid;
  }
  if (badgeEl) {
    badgeEl.style.display = "inline-flex";
  }

  // Connect Doctor MQTT
  connectDoctorMQTT(appIdInput ? appIdInput.value : "f320d3475b6d4b70ba512b06d09849d7", channelInput ? channelInput.value : "torus");

  // Transition UI to Dashboard
  const doctorRegisterScreen = document.getElementById("doctor-register-screen");
  const doctorForgotScreen = document.getElementById("doctor-forgot-screen");
  if (doctorLoginScreen) doctorLoginScreen.style.display = "none";
  if (doctorRegisterScreen) doctorRegisterScreen.style.display = "none";
  if (doctorForgotScreen) doctorForgotScreen.style.display = "none";
  if (roleSelectionScreen) roleSelectionScreen.style.display = "none";
  if (appDashboard) appDashboard.style.display = "flex";

  if (typeof triggerHeaderBootSequence === "function") {
    triggerHeaderBootSequence();
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
    docBackBtn.addEventListener("click", () => {
      if (doctorLoginScreen) doctorLoginScreen.style.display = "none";
      if (roleSelectionScreen) roleSelectionScreen.style.display = "flex";
    });
  }

  // Main Dashboard Back Button -> Return to Role Selection
  const mainBackBtn = document.getElementById("backBtn");
  if (mainBackBtn) {
    mainBackBtn.addEventListener("click", () => {
      if (appDashboard) appDashboard.style.display = "none";
      if (roleSelectionScreen) roleSelectionScreen.style.display = "flex";
      // Hide header user badge when returning to role selection
      const badgeEl = document.getElementById("header-user-badge");
      if (badgeEl) badgeEl.style.display = "none";
    });
  }

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

      // Hide login screen, show registration screen
      const loginScreen = document.getElementById("doctor-login-screen");
      const regScreen = document.getElementById("doctor-register-screen");
      if (loginScreen) loginScreen.style.display = "none";
      if (regScreen) regScreen.style.display = "flex";
    });
  }

  // Back Button from Registration -> Doctor Login
  const regBackBtn = document.getElementById("doctor-register-back-btn");
  if (regBackBtn) {
    regBackBtn.addEventListener("click", () => {
      const loginScreen = document.getElementById("doctor-login-screen");
      const regScreen = document.getElementById("doctor-register-screen");
      if (regScreen) regScreen.style.display = "none";
      if (loginScreen) loginScreen.style.display = "flex";
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
      if (doctorRegisterScreen) doctorRegisterScreen.style.display = "none";
      if (doctorLoginScreen) doctorLoginScreen.style.display = "flex";

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
    if (doctorForgotScreen) doctorForgotScreen.style.display = "none";
    if (doctorLoginScreen) doctorLoginScreen.style.display = "flex";
    resetForgotFlowUI();
  }

  if (forgotLink) {
    forgotLink.addEventListener("click", (e) => {
      e.preventDefault();
      resetForgotFlowUI();

      if (doctorLoginScreen) doctorLoginScreen.style.display = "none";
      if (doctorRegisterScreen) doctorRegisterScreen.style.display = "none";
      if (doctorForgotScreen) doctorForgotScreen.style.display = "flex";
    });
  }

  if (forgotBackBtn) {
    forgotBackBtn.addEventListener("click", showDoctorLoginFromForgot);
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
    forgotStep3BackBtn.addEventListener("click", showDoctorLoginFromForgot);
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
      const endpoints = ["/api/biometrics/status", "http://127.0.0.1:8000/api/biometrics/status"];
      for (const ep of endpoints) {
        try {
          const res = await fetch(ep, { method: "GET" });
          if (res.ok) {
            return await res.json();
          }
        } catch (_) {}
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

  async function resetBiometricVerifyUI() {
    isVerifyingBiometrics = false;
    hideAlertMessage("doctor-biometric-alert");
    if (bioVerifyScannerPod) {
      bioVerifyScannerPod.classList.remove("scanning", "success");
    }
    if (bioVerifyTitle) bioVerifyTitle.textContent = "Fingerprint scanner ready";
    if (bioVerifySubtitle) bioVerifySubtitle.textContent = "Place your registered finger on the scanner.";
    if (bioVerifyDots) {
      const dots = bioVerifyDots.querySelectorAll(".bio-dot");
      dots.forEach((dot, idx) => {
        dot.className = idx === 0 ? "bio-dot active" : "bio-dot";
      });
    }

    // Check live hardware connection in background
    checkBiometricHardwareStatus().then(hw => {
      if (!hw.connected) {
        if (bioVerifyTitle) bioVerifyTitle.textContent = "Fingerprint scanner is not ready";
        if (bioVerifySubtitle) bioVerifySubtitle.textContent = "Please check the scanner connection.";
      } else {
        if (bioVerifyTitle) bioVerifyTitle.textContent = "Fingerprint scanner ready";
        if (bioVerifySubtitle) bioVerifySubtitle.textContent = "Place your registered finger on the scanner.";
      }
    });
  }

  async function resetBiometricRegisterUI() {
    isRegisteringBiometrics = false;
    hideAlertMessage("doctor-bio-reg-alert");
    if (bioRegScannerPod) {
      bioRegScannerPod.classList.remove("scanning", "success");
    }
    if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint scanner ready";
    if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Place your finger on the scanner to register your fingerprint.";
    if (bioRegStartBtn) {
      bioRegStartBtn.disabled = false;
      bioRegStartBtn.innerHTML = "<span>Capture Fingerprint</span>";
    }
    if (bioRegDots) {
      const dots = bioRegDots.querySelectorAll(".bio-dot");
      dots.forEach((dot, idx) => {
        dot.className = idx === 0 ? "bio-dot active" : "bio-dot";
      });
    }

    // Check live hardware connection in background
    checkBiometricHardwareStatus().then(hw => {
      if (!hw.connected) {
        if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint scanner is not ready";
        if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Please check the scanner connection.";
      } else {
        if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint scanner ready";
        if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Place your finger on the scanner to register your fingerprint.";
      }
    });
  }

  // 1. Open Biometric Verification Screen from Login
  if (bioLoginBtn) {
    bioLoginBtn.addEventListener("click", () => {
      resetBiometricVerifyUI();
      if (doctorLoginScreen) doctorLoginScreen.style.display = "none";
      if (doctorRegisterScreen) doctorRegisterScreen.style.display = "none";
      if (doctorForgotScreen) doctorForgotScreen.style.display = "none";
      if (doctorBioRegisterScreen) doctorBioRegisterScreen.style.display = "none";
      if (doctorBiometricScreen) doctorBiometricScreen.style.display = "flex";

      const docEmailVal = document.getElementById("doctor-email-input")?.value?.trim();
      if (docEmailVal && bioRegIdentifierInput) {
        bioRegIdentifierInput.value = docEmailVal;
      }
    });
  }

  // 2. Back from Biometric Verification -> Doctor Login
  if (bioVerifyBackBtn) {
    bioVerifyBackBtn.addEventListener("click", () => {
      resetBiometricVerifyUI();
      if (doctorBiometricScreen) doctorBiometricScreen.style.display = "none";
      if (doctorLoginScreen) doctorLoginScreen.style.display = "flex";
    });
  }

  // 3. Navigate from Verification -> Registration
  if (bioGoRegisterBtn) {
    bioGoRegisterBtn.addEventListener("click", (e) => {
      e.preventDefault();
      resetBiometricRegisterUI();
      if (doctorBiometricScreen) doctorBiometricScreen.style.display = "none";
      if (doctorBioRegisterScreen) doctorBioRegisterScreen.style.display = "flex";
    });
  }

  // 4. Back from Registration -> Verification
  if (bioRegBackBtn) {
    bioRegBackBtn.addEventListener("click", () => {
      resetBiometricRegisterUI();
      if (doctorBioRegisterScreen) doctorBioRegisterScreen.style.display = "none";
      if (doctorBiometricScreen) doctorBiometricScreen.style.display = "flex";
      resetBiometricVerifyUI();
    });
  }

  if (bioRegToVerifyBtn) {
    bioRegToVerifyBtn.addEventListener("click", (e) => {
      e.preventDefault();
      resetBiometricRegisterUI();
      if (doctorBioRegisterScreen) doctorBioRegisterScreen.style.display = "none";
      if (doctorBiometricScreen) doctorBiometricScreen.style.display = "flex";
      resetBiometricVerifyUI();
    });
  }

  // 5. Execute Real Biometric Verification (Hardware Request & Authentication)
  async function triggerBiometricVerification() {
    if (isVerifyingBiometrics) return;
    isVerifyingBiometrics = true;
    hideAlertMessage("doctor-biometric-alert");

    const targetLoginId = document.getElementById("doctor-email-input")?.value?.trim() || bioRegIdentifierInput?.value?.trim() || "admin@gmail.com";

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
      const verifyUrls = ["/api/biometrics/verify", "http://127.0.0.1:8000/api/biometrics/verify"];
      for (const url of verifyUrls) {
        try {
          const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ identifier: targetLoginId })
          });
          resData = await res.json();
          if (resData) break;
        } catch (_) {}
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
      if (bioVerifyTitle) bioVerifyTitle.textContent = "Fingerprint does not match";
      if (bioVerifySubtitle) bioVerifySubtitle.textContent = "Please try again.";

      const errMsg = resData?.error || "Fingerprint does not match. Please try again.";
      showAlertMessage("doctor-biometric-alert", errMsg, "error");
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

      // Check real hardware connectivity
      const hwStatus = await checkBiometricHardwareStatus();
      if (!hwStatus.connected) {
        if (bioRegScannerPod) bioRegScannerPod.classList.remove("scanning", "success");
        if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint scanner is not ready";
        if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Please check the scanner connection.";
        showAlertMessage("doctor-bio-reg-alert", "Fingerprint scanner is not ready. Please check the scanner connection.", "error");
        if (bioRegStartBtn) bioRegStartBtn.disabled = false;
        isRegisteringBiometrics = false;
        return;
      }

      const dots = bioRegDots ? bioRegDots.querySelectorAll(".bio-dot") : [];

      // Step 1: Scanning fingerprint
      if (bioRegScannerPod) {
        bioRegScannerPod.classList.remove("success");
        bioRegScannerPod.classList.add("scanning");
      }
      if (bioRegStepTitle) bioRegStepTitle.textContent = "Scanning your fingerprint...";
      if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Please keep your finger still.";
      if (dots[0]) dots[0].className = "bio-dot active";
      if (dots[1]) dots[1].className = "bio-dot";

      setTimeout(async () => {
        // Step 2: Prompt lift & second touch if hardware requires multi-pass
        if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint captured";
        if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Please lift your finger and place it again when prompted.";
        if (dots[0]) dots[0].className = "bio-dot active";
        if (dots[1]) dots[1].className = "bio-dot active";

        setTimeout(async () => {
          // Step 3: Processing template
          if (bioRegStepTitle) bioRegStepTitle.textContent = "Scanning your fingerprint...";
          if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Please keep your finger still.";

          // Dispatch real enrollment request to backend API
          try {
            let resData = null;
            const enrollUrls = ["/api/biometrics/enroll", "http://127.0.0.1:8000/api/biometrics/enroll"];
            for (const url of enrollUrls) {
              try {
                const res = await fetch(url, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ identifier: identifierVal })
                });
                resData = await res.json();
                if (resData) break;
              } catch (_) {}
            }

            // Only mark complete if real scanner and backend report success
            if (resData && resData.success) {
              if (bioRegScannerPod) {
                bioRegScannerPod.classList.remove("scanning");
                bioRegScannerPod.classList.add("success");
              }
              if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint registered successfully.";
              if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Your fingerprint has been securely linked to your account.";

              showAlertMessage(
                "doctor-bio-reg-alert",
                "Fingerprint registered successfully. Your fingerprint has been securely linked to your account. Redirecting to Biometric Login...",
                "success"
              );

              setTimeout(() => {
                if (doctorBioRegisterScreen) doctorBioRegisterScreen.style.display = "none";
                if (doctorBiometricScreen) doctorBiometricScreen.style.display = "flex";
                resetBiometricVerifyUI();
                showAlertMessage(
                  "doctor-biometric-alert",
                  "Fingerprint registered successfully. Place your registered finger on the scanner to verify.",
                  "success"
                );
                isRegisteringBiometrics = false;
              }, 1800);
            } else {
              // Real hardware capture failure
              if (bioRegScannerPod) bioRegScannerPod.classList.remove("scanning");
              if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint registration failed";
              if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Please try again.";
              showAlertMessage("doctor-bio-reg-alert", resData?.error || "Fingerprint registration failed. Please try again.", "error");
              if (bioRegStartBtn) bioRegStartBtn.disabled = false;
              isRegisteringBiometrics = false;
            }

          } catch (err) {
            console.error("[Biometric Registration Error]", err);
            if (bioRegScannerPod) bioRegScannerPod.classList.remove("scanning");
            if (bioRegStepTitle) bioRegStepTitle.textContent = "Fingerprint scanner is unavailable";
            if (bioRegStepSubtitle) bioRegStepSubtitle.textContent = "Please check the scanner connection.";
            showAlertMessage("doctor-bio-reg-alert", "Fingerprint scanner is unavailable. Please check the scanner connection.", "error");
            if (bioRegStartBtn) bioRegStartBtn.disabled = false;
            isRegisteringBiometrics = false;
          }
        }, 1200);
      }, 1200);
    });
  }
});


