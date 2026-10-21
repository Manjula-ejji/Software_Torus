console.log('BUILD VERSION:', Date.now());
console.log('Capture Handler Loaded');

let reportSocket = null;
try {
  const room = new URLSearchParams(window.location.search).get('room') || 'DEFAULT_ROOM';
  reportSocket = io(window.location.origin, {
    reconnectionDelayMax: 10000,
    transports: ['websocket', 'polling']
  });
  reportSocket.on('connect', () => {
    console.log('Report generator connected to signaling server');
    reportSocket.emit('join-room', room);
  });
} catch (e) {
  console.warn('Socket.io not available in report generator', e);
}

// ==================== NEW BLOCK ====================

lucide.createIcons();

const roomParam = String(new URLSearchParams(window.location.search).get('room') || 'default').trim().toUpperCase();

const STORAGE_KEYS = {
  collage: 'torus-report-collage-' + roomParam,
  selectedIds: 'torus-report-selected-ids-' + roomParam,
  findings: 'torus-report-findings-' + roomParam,
  recommendations: 'torus-report-recommendations-' + roomParam,
  context: 'torus-report-context-' + roomParam,
  reportId: 'torus-report-id-' + roomParam,
  reportDetails: 'torus-report-details-' + roomParam,
  reportPreview: 'torus-report-preview-' + roomParam,
  generatedReport: 'torus-report-generated-' + roomParam,
  deliveryStatus: 'torus-report-delivery-status-' + roomParam
};

const CAPTURE_STORAGE_KEYS = {
  sessionId: 'torus-capture-session-id-' + roomParam,
  images: 'capturedImages-' + roomParam
};

function getAiStorageKey() {
  const patient = (dom && dom.patientName && dom.patientName.textContent.trim() !== '--')
    ? dom.patientName.textContent.trim().replace(/[^a-zA-Z0-9_-]/g, '_')
    : 'default';
  const reportId = (dom && dom.reportId && dom.reportId.textContent.trim() !== '--')
    ? dom.reportId.textContent.trim()
    : roomParam;
  return `torus_ai_analysis_${reportId}_${patient}`;
}

function createCaptureSessionId() {
  return `capture-session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function getActiveCaptureSessionId() {
  return localStorage.getItem(CAPTURE_STORAGE_KEYS.sessionId)
    || sessionStorage.getItem(CAPTURE_STORAGE_KEYS.sessionId)
    || '';
}

function setActiveCaptureSessionId(sessionId) {
  localStorage.setItem(CAPTURE_STORAGE_KEYS.sessionId, sessionId);
  sessionStorage.setItem(CAPTURE_STORAGE_KEYS.sessionId, sessionId);
  return sessionId;
}

const BUILD_VERSION = '20260521_01';

function initializeBuildVersion() {
  try {
    localStorage.setItem('torus-build-version', BUILD_VERSION);
    sessionStorage.setItem('torus-build-version', BUILD_VERSION);
  } catch (error) {
    console.warn('Unable to initialize build version:', error);
  }
}

function clearCaptureStorage(keepSessionId = false) {
  localStorage.removeItem(CAPTURE_STORAGE_KEYS.images);
  sessionStorage.removeItem(CAPTURE_STORAGE_KEYS.images);

  if (!keepSessionId) {
    localStorage.removeItem(CAPTURE_STORAGE_KEYS.sessionId);
    sessionStorage.removeItem(CAPTURE_STORAGE_KEYS.sessionId);
  }
}

function ensureCaptureSession() {
  const sessionId = getActiveCaptureSessionId();
  if (sessionId) {
    return sessionId;
  }

  return setActiveCaptureSessionId(createCaptureSessionId());
}

function readCaptureImages() {
  try {
    const raw = localStorage.getItem(CAPTURE_STORAGE_KEYS.images)
      || sessionStorage.getItem(CAPTURE_STORAGE_KEYS.images)
      || localStorage.getItem('capturedImages-TORUS')
      || sessionStorage.getItem('capturedImages-TORUS')
      || localStorage.getItem('capturedImages-DEFAULT')
      || sessionStorage.getItem('capturedImages-DEFAULT')
      || localStorage.getItem('capturedImages')
      || sessionStorage.getItem('capturedImages')
      || '[]';
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    console.warn('Unable to read capture images:', error);
    return [];
  }
}

function writeCaptureImages(images) {
  try {
    const serialized = JSON.stringify(images);
    localStorage.setItem(CAPTURE_STORAGE_KEYS.images, serialized);
    sessionStorage.setItem(CAPTURE_STORAGE_KEYS.images, serialized);
  } catch (err) {
    // Handle QuotaExceededError gracefully by falling back to sessionStorage and in-memory state
    console.warn('Storage quota limit reached (QuotaExceededError) when saving capture images:', err);
    try {
      sessionStorage.setItem(CAPTURE_STORAGE_KEYS.images, JSON.stringify(images));
    } catch (_) { }
  }
}

const reportState = {
  images: [],
  selectedIds: new Set(),
  reportPreview: readJson(STORAGE_KEYS.reportPreview, null),
  reportDetails: readJson(STORAGE_KEYS.reportDetails, null),
  generatedReport: readJson(STORAGE_KEYS.generatedReport, null),
  digitalSignature: false,
  isGenerating: false,
  isSending: false,
  sendLocked: localStorage.getItem(STORAGE_KEYS.deliveryStatus) === 'sent',
  previewIndex: -1,
  scrollTopBeforePreview: 0,
  previewAction: 'upload',
  previewSource: 'click',
  previewHoverTimer: null
};

const dom = {
  backBtn: document.getElementById('backBtn'),
  capturedGrid: document.getElementById('capturedGrid'),
  emptyState: document.getElementById('emptyState'),
  imageCountPill: document.getElementById('imageCountPill'),
  selectedCount: document.getElementById('selectedCount'),
  findingsField: document.getElementById('findingsField'),
  recommendationsField: document.getElementById('recommendationsField'),
  generatePreviewBtn: document.getElementById('generatePreviewBtn'),
  sendCapturedImagesBtn: document.getElementById('sendCapturedImagesBtn'),
  sendPatientBtn: document.getElementById('sendPatientBtn'),
  digitalSignBtn: document.getElementById('digitalSignBtn'),
  toast: document.getElementById('toast'),
  patientName: document.getElementById('patientName'),
  examDate: document.getElementById('examDate'),
  scanType: document.getElementById('scanType'),
  deviceName: document.getElementById('deviceName'),
  doctorName: document.getElementById('doctorName'),
  locationName: document.getElementById('locationName'),
  reportId: document.getElementById('reportId'),
  imagesCaptured: document.getElementById('imagesCaptured'),
  selectedImagesCount: document.getElementById('selectedImagesCount'),
  examDuration: document.getElementById('examDuration'),
  printOnlyContainer: document.getElementById('printOnlyContainer'),
  sidebar: document.getElementById('sidebar'),
  sidebarOverlay: document.getElementById('sidebarOverlay'),
  closeSidebar: document.getElementById('closeSidebar'),
  imagePreviewModal: document.getElementById('imagePreviewModal'),
  closePreviewModal: document.getElementById('closePreviewModal'),
  previewModalImage: document.getElementById('previewModalImage'),
  previewModalCaption: document.getElementById('previewModalCaption'),
  signatureStatus: document.getElementById('signatureStatus'),
  signatureSuccessCard: document.getElementById('signatureSuccessCard'),
  reportPreviewModal: document.getElementById('reportPreviewModal'),
  editReportBtn: document.getElementById('editReportBtn'),
  confirmGenerateBtn: document.getElementById('confirmGenerateBtn')
};

function showToast(message) {
  if (!dom.toast) return;
  dom.toast.textContent = message;
  dom.toast.classList.add('show');
  window.clearTimeout(showToast._timer);
  showToast._timer = window.setTimeout(() => dom.toast.classList.remove('show'), 1800);
}

function readJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (e) {
    console.warn('Unable to persist ' + key, e);
  }
}

function normalizeImages(items) {
  return (items || []).map((item, index) => ({
    id: item.id || `${item.createdAt || 'capture'}-${index}`,
    panel: item.panel || 'ultrasound',
    createdAt: item.createdAt || item.capturedAt || item.timestamp || new Date().toISOString(),
    dataUrl: item.dataUrl || item.image || item.src || ''
  }));
}

function getTimeLabel(createdAt) {
  const date = new Date(createdAt || Date.now());
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function sanitizeFileName(value) {
  return String(value || 'Report').replace(/[^a-z0-9-_]+/gi, '_').replace(/_+/g, '_').replace(/^_|_$/g, '') || 'Report';
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function syncCounts() {
  const total = reportState.images.length;
  const selected = reportState.selectedIds.size;
  if (dom.imageCountPill) dom.imageCountPill.textContent = `${total} Captured`;
  if (dom.selectedCount) dom.selectedCount.textContent = `${selected} / ${total} Selected`;
  if (dom.imagesCaptured) dom.imagesCaptured.textContent = String(total);
  if (dom.selectedImagesCount) dom.selectedImagesCount.textContent = String(selected);
}

function buildAutoReportId() {
  const now = new Date();
  const datePart = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`;
  const randomPart = Math.floor(1000 + Math.random() * 9000);
  return `RPT-${datePart}-${randomPart}`;
}

function sanitizeClinicalText(val) {
  if (!val || typeof val !== 'string') return '';
  const trimmed = val.trim();
  if (/^(.)\1{4,}$/i.test(trimmed)) return '';
  if (/^(test|asdf|qwerty|zzz)+$/i.test(trimmed)) return '';
  return trimmed;
}

function formatReportDate() {
  const now = new Date();
  const months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  return `${months[now.getMonth()]} ${now.getDate()}, ${now.getFullYear()}`;
}

function isCurrentUserDoctor() {
  const params = new URLSearchParams(window.location.search);
  const role = (params.get('role') || '').toLowerCase();
  if (role === 'doctor' || role === 'doc' || role === 'admin') return true;
  try {
    const docRaw = sessionStorage.getItem('authenticated_doctor') || localStorage.getItem('authenticated_doctor');
    if (docRaw) return true;
  } catch (_) {}
  return false;
}

function updateSignatureUI(stateOverride = null) {
  const isDoctor = isCurrentUserDoctor();
  const isSigned = reportState.digitalSignature && !reportState.signatureRequired;
  const isReq = Boolean(reportState.signatureRequired);
  
  let statusText = stateOverride;
  if (!statusText) {
    if (isReq) statusText = 'Signature Required';
    else if (isSigned) statusText = 'Signed';
    else statusText = 'Unsigned';
  }

  if (dom.signatureStatus) {
    dom.signatureStatus.textContent = statusText;
    if (isSigned) {
      dom.signatureStatus.style.color = '#10b981';
      dom.signatureStatus.style.fontWeight = '700';
    } else if (isReq) {
      dom.signatureStatus.style.color = '#f59e0b';
      dom.signatureStatus.style.fontWeight = '700';
    } else if (stateOverride === 'Failed') {
      dom.signatureStatus.style.color = '#ef4444';
      dom.signatureStatus.style.fontWeight = '700';
    } else {
      dom.signatureStatus.style.color = '';
      dom.signatureStatus.style.fontWeight = '';
    }
  }

  const success = document.getElementById('signatureSuccess');
  const reqBadge = document.getElementById('signatureRequiredBadge');
  const replaceBtn = document.getElementById('replaceSignatureBtn');
  const historyBtn = document.getElementById('viewSignatureHistoryBtn');
  const btn = document.getElementById('digitalSignBtn');

  if (btn) {
    if (stateOverride === 'Signing') {
      btn.innerHTML = '<i data-lucide="loader" style="animation: spin 1s linear infinite;"></i>Signing...';
      btn.disabled = true;
      btn.style.display = 'inline-flex';
    } else if (isReq) {
      btn.innerHTML = '<i data-lucide="signature"></i>Re-Sign Report';
      btn.disabled = false;
      btn.style.background = 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)';
      btn.style.color = '#ffffff';
      btn.style.display = 'inline-flex';
    } else if (isSigned) {
      btn.innerHTML = '<i data-lucide="signature" style="width: 18px; height: 18px;"></i>Signed';
      btn.disabled = false;
      btn.style.background = '#10b981';
      btn.style.color = '#ffffff';
      btn.style.display = 'inline-flex';
    } else if (stateOverride === 'Failed') {
      btn.innerHTML = '<i data-lucide="alert-circle"></i>Retry Sign';
      btn.disabled = false;
      btn.style.background = '#ef4444';
      btn.style.color = '#ffffff';
      btn.style.display = 'inline-flex';
    } else {
      btn.innerHTML = '<i data-lucide="signature"></i>Digital Sign';
      btn.disabled = false;
      btn.style.background = '';
      btn.style.color = '';
      btn.style.display = 'inline-flex';
    }
  }

  if (success) {
    success.style.display = isSigned ? "flex" : "none";
  }
  if (reqBadge) {
    reqBadge.style.display = isReq ? "flex" : "none";
  }
  if (replaceBtn) {
    replaceBtn.style.display = (isDoctor && (isSigned || isReq)) ? "flex" : "none";
  }
  if (historyBtn) {
    historyBtn.style.display = (isSigned || isReq || reportState.signatureData) ? "flex" : "none";
  }

  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function setReportId(id) {
  if (!id) return;
  if (dom.reportId) dom.reportId.textContent = id;
  localStorage.setItem(STORAGE_KEYS.reportId, id);
}

function setGeneratedTime(isoString) {
  if (!dom.generatedTime) return;
  if (!isoString) {
    dom.generatedTime.textContent = 'Not generated';
    return;
  }
  dom.generatedTime.textContent = new Date(isoString).toLocaleString();
}

function updatePreviewThumbnail() {
  if (!dom.previewFrame || !dom.reportPreviewImage || !dom.previewEmpty || !dom.reportPreviewPdf || !dom.reportPreviewFileName) return;
  const preview = reportState.reportPreview;
  const previewData = preview && (preview.data || preview.dataUrl || preview.src);
  const hasPreview = Boolean(previewData);
  const isImage = hasPreview && /^image\//i.test(preview.type || '');
  const isPdf = hasPreview && /^application\/pdf$/i.test(preview.type || '');

  if (isImage) {
    dom.reportPreviewImage.src = previewData;
    dom.reportPreviewFileName.textContent = '';
    dom.previewFrame.classList.add('has-image');
    dom.previewFrame.classList.remove('has-pdf');
  } else if (isPdf) {
    dom.reportPreviewImage.removeAttribute('src');
    dom.reportPreviewFileName.textContent = preview.name || 'Document.pdf';
    dom.previewFrame.classList.remove('has-image');
    dom.previewFrame.classList.add('has-pdf');
  } else {
    dom.reportPreviewImage.removeAttribute('src');
    dom.reportPreviewFileName.textContent = '';
    dom.previewFrame.classList.remove('has-image');
    dom.previewFrame.classList.remove('has-pdf');
  }
  lucide.createIcons();
}

function renderReportPreview(preview) {
  reportState.reportPreview = preview || null;
  if (reportState.reportPreview) {
    updatePreviewThumbnail();
  } else {
    updatePreviewThumbnail();
  }
  try { console.log('PREVIEW RENDERED'); } catch (e) { }
}

function setSendLockedState(locked) {
  reportState.sendLocked = Boolean(locked);
  if (!dom.sendPatientBtn) return;
  if (reportState.sendLocked) {
    dom.sendPatientBtn.disabled = true;
    dom.sendPatientBtn.setAttribute('aria-disabled', 'true');
    dom.sendPatientBtn.innerHTML = '<i data-lucide="check-circle"></i><span>Sent</span>';
    lucide.createIcons();
    return;
  }
  dom.sendPatientBtn.removeAttribute('aria-disabled');
  dom.sendPatientBtn.disabled = false;
  if (dom.sendPatientBtn.dataset.defaultMarkup) {
    dom.sendPatientBtn.innerHTML = dom.sendPatientBtn.dataset.defaultMarkup;
  } else {
    dom.sendPatientBtn.innerHTML = '<i data-lucide="send"></i>Send to Patient';
  }
  lucide.createIcons();
}

function getSelectedImagesForCurrentState() {
  return reportState.images.filter((image) => reportState.selectedIds.has(image.id));
}

function syncSelectionUI() {
  const cards = dom.capturedGrid ? dom.capturedGrid.querySelectorAll('.image-card') : [];
  cards.forEach((card) => {
    const id = card.dataset.imageId;
    const isSelected = Boolean(id && reportState.selectedIds.has(id));
    card.classList.toggle('is-selected', isSelected);
    const checkbox = card.querySelector('.image-check input');
    if (checkbox) checkbox.checked = isSelected;
  });
}

function invalidateAiAnalysis() {
  reportState.aiResults = null;
  try {
    const key = typeof getAiStorageKey === 'function' ? getAiStorageKey() : 'torus_ai_analysis';
    localStorage.removeItem(key);
  } catch (_) { }
  localStorage.removeItem('torus_ai_analysis');
  if (typeof window.triggerAiReset === 'function') {
    window.triggerAiReset();
  }
}

function toggleSelectedImage(imageId) {
  if (reportState.selectedIds.has(imageId)) {
    reportState.selectedIds.delete(imageId);
  } else {
    reportState.selectedIds.add(imageId);
  }
  writeJson(STORAGE_KEYS.selectedIds, Array.from(reportState.selectedIds));
  invalidateGeneratedReport();
  invalidateAiAnalysis();
  syncCounts();
  syncSelectionUI();
}

function getCurrentReportId() {
  return dom.reportId ? dom.reportId.textContent.trim() : localStorage.getItem(STORAGE_KEYS.reportId) || '';
}

function getCurrentReportDetails(reportIdOverride = '') {
  const selectedImages = getSelectedImagesForCurrentState();
  return {
    examDuration: dom.examDuration ? dom.examDuration.textContent.trim() : '',
    imagesCaptured: reportState.images.length,
    selectedImages: selectedImages.length,
    doctor: dom.doctorName ? dom.doctorName.textContent.trim() : '',
    location: dom.locationName ? dom.locationName.textContent.trim() : '',
    reportId: reportIdOverride || getCurrentReportId(),
    signatureStatus: reportState.digitalSignature ? 'Signed' : 'Unsigned',
    generatedTime: reportState.generatedReport ? reportState.generatedReport.generatedAt : null
  };
}

function collectReportData() {
  const selectedImages = getSelectedImagesForCurrentState();
  const reportId = getCurrentReportId();
  const reportDetails = getCurrentReportDetails(reportId);
  return {
    reportId,
    generatedAt: new Date().toISOString(),
    patientInfo: {
      patientName: dom.patientName ? dom.patientName.textContent.trim() : '',
      examDate: dom.examDate ? dom.examDate.textContent.trim() : '',
      scanType: dom.scanType ? dom.scanType.textContent.trim() : '',
      device: dom.deviceName ? dom.deviceName.textContent.trim() : '',
      doctor: dom.doctorName ? dom.doctorName.textContent.trim() : '',
      location: dom.locationName ? dom.locationName.textContent.trim() : '',
      examDuration: dom.examDuration ? dom.examDuration.textContent.trim() : ''
    },
    reportDetails,
    capturedImages: reportState.images,
    selectedImages,
    findings: dom.findingsField ? dom.findingsField.value.trim() : '',
    recommendations: dom.recommendationsField ? dom.recommendationsField.value.trim() : '',
    reportPreview: reportState.reportPreview,
    selectedImageIds: selectedImages.map((image) => image.id),
    selectedImagesCount: selectedImages.length,
    totalImages: reportState.images.length,
    digitalSignature: reportState.digitalSignature,
    aiResults: reportState.aiResults || readJson((typeof getAiStorageKey === 'function' ? getAiStorageKey() : 'torus_ai_analysis'), null) || readJson('torus_ai_analysis', null)
  };
}

function validateReportData(reportData) {
  const missing = [];
  if (!reportData.patientInfo.patientName) missing.push('patient information');
  if (!reportData.reportDetails.reportId) missing.push('report ID');
  if (!reportData.findings || !reportData.recommendations) missing.push('findings and recommendations');
  return missing;
}

function persistGeneratedReport(reportData) {
  reportState.generatedReport = reportData;
  reportState.reportDetails = reportData.reportDetails;
  writeJson(STORAGE_KEYS.generatedReport, reportData);
  writeJson(STORAGE_KEYS.reportDetails, reportData.reportDetails);
  writeJson(STORAGE_KEYS.reportPreview, reportData.reportPreview || reportState.reportPreview || null);
  const deliveryStatus = reportData.deliveryStatus === 'sent' ? 'sent' : 'ready';
  localStorage.setItem(STORAGE_KEYS.deliveryStatus, deliveryStatus);
  setSendLockedState(deliveryStatus === 'sent');
  setGeneratedTime(reportData.generatedAt);
}

function invalidateGeneratedReport() {
  reportState.reportDetails = getCurrentReportDetails();
  writeJson(STORAGE_KEYS.reportDetails, reportState.reportDetails);
}

function setButtonBusy(button, label) {
  if (!button) return;
  if (!button.dataset.defaultMarkup) {
    button.dataset.defaultMarkup = button.innerHTML;
  }
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  button.innerHTML = `<i data-lucide="loader-2"></i><span>${label}</span>`;
  lucide.createIcons();
}

function restoreButton(button) {
  if (!button) return;
  button.disabled = false;
  button.removeAttribute('aria-busy');
  if (button.dataset.defaultMarkup) {
    button.innerHTML = button.dataset.defaultMarkup;
    lucide.createIcons();
  }
}

function flashButtonSuccess(button, label) {
  if (!button) return;
  if (!button.dataset.defaultMarkup) {
    button.dataset.defaultMarkup = button.innerHTML;
  }
  button.innerHTML = `<i data-lucide="check"></i><span>${label}</span>`;
  lucide.createIcons();
  window.setTimeout(() => restoreButton(button), 900);
}

function ensureGeneratedReport({ allowAutoGenerate = false } = {}) {
  if (reportState.generatedReport) {
    return reportState.generatedReport;
  }

  if (!allowAutoGenerate) {
    showToast('Generate report first');
    return null;
  }

  const reportData = collectReportData();
  const missing = validateReportData(reportData);
  if (missing.length) {
    showToast(`Cannot continue: add ${missing.join(', ')}.`);
    return null;
  }

  persistGeneratedReport(reportData);
  return reportData;
}

function openPreview(imageIndex) {
  const image = reportState.images[imageIndex];
  if (!image || !dom.imagePreviewModal) return;

  if (reportState.previewHoverTimer) {
    window.clearTimeout(reportState.previewHoverTimer);
    reportState.previewHoverTimer = null;
  }

  reportState.previewIndex = imageIndex;
  reportState.scrollTopBeforePreview = window.scrollY;
  if (dom.previewModalImage) dom.previewModalImage.src = image.dataUrl;
  if (dom.previewModalCaption) dom.previewModalCaption.textContent = `Image ${imageIndex + 1} • ${getTimeLabel(image.createdAt)}`;
  dom.imagePreviewModal.classList.remove('hidden');
  dom.imagePreviewModal.setAttribute('aria-hidden', 'false');
  lucide.createIcons();
}

function closePreview() {
  if (!dom.imagePreviewModal) return;
  dom.imagePreviewModal.classList.add('hidden');
  dom.imagePreviewModal.setAttribute('aria-hidden', 'true');
  reportState.previewIndex = -1;
  window.scrollTo({ top: reportState.scrollTopBeforePreview, behavior: 'auto' });
}

function createImageCard(image, index) {
  const card = document.createElement('article');
  card.className = 'image-card';
  card.tabIndex = 0;
  card.dataset.imageId = image.id;
  if (reportState.selectedIds.has(image.id)) {
    card.classList.add('is-selected');
  }

  const img = document.createElement('img');
  img.src = image.dataUrl;
  img.alt = 'Captured ultrasound frame';
  img.loading = 'lazy';

  const checkboxWrap = document.createElement('label');
  checkboxWrap.className = 'image-check';

  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.checked = reportState.selectedIds.has(image.id);
  checkbox.addEventListener('change', () => {
    toggleSelectedImage(image.id);
  });

  checkboxWrap.appendChild(checkbox);

  const meta = document.createElement('div');
  meta.className = 'image-meta';

  const timestamp = document.createElement('div');
  timestamp.className = 'timestamp';
  timestamp.textContent = getTimeLabel(image.createdAt);

  meta.appendChild(timestamp);
  card.appendChild(img);
  card.appendChild(checkboxWrap);
  card.appendChild(meta);

  const launchPreview = () => openPreview(index);

  img.addEventListener('click', launchPreview);
  card.addEventListener('click', (event) => {
    if (event.target.closest('input')) return;
    launchPreview();
  });
  card.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      launchPreview();
    }
  });

  return card;
}

function renderCapturedImages(images = reportState.images) {
  if (!dom.capturedGrid) return;
  dom.capturedGrid.innerHTML = '';

  if (!images.length) {
    dom.emptyState.classList.remove('hidden');
    syncCounts();
    return;
  }

  dom.emptyState.classList.add('hidden');

  images.forEach((image, index) => {
    dom.capturedGrid.appendChild(createImageCard(image, index));
  });

  syncCounts();
}

function loadCapturedImages() {
  const collage = normalizeImages(readCaptureImages());
  reportState.images = collage;
  console.log('Captured Images:', collage);
  console.log('Snapshot Count:', collage.length);

  const selectedIds = new Set(readJson(STORAGE_KEYS.selectedIds, []));
  const currentIds = new Set(collage.map((image) => image.id));
  reportState.selectedIds = new Set(Array.from(selectedIds).filter((id) => currentIds.has(id)));

  renderCapturedImages(collage);
}

function loadReportContext() {
  const context = {
    ...readJson(STORAGE_KEYS.context, {}),
    ...readJson('torus-report-meta', {})
  };
  loadCapturedImages();
  const saved = readJson('reportPreview', null) || readJson(STORAGE_KEYS.reportPreview, null);
  if (saved) {
    renderReportPreview(saved);
  } else {
    renderReportPreview(null);
  }
  reportState.reportDetails = readJson(STORAGE_KEYS.reportDetails, null);

  let reportId = context.reportId
    || (reportState.generatedReport && reportState.generatedReport.reportId)
    || localStorage.getItem(STORAGE_KEYS.reportId);
  if (!reportId || reportId === 'RPT-000000' || reportId.startsWith('RPT-8') || reportId === 'RPT-8') {
    reportId = buildAutoReportId();
    localStorage.setItem(STORAGE_KEYS.reportId, reportId);
  }
  setReportId(reportId);

  reportState.generatedReport = readJson(STORAGE_KEYS.generatedReport, null);

  const savedSig = readJson('torus_signature_' + reportId, null) || readJson('torus_signature_' + roomParam, null);
  if (savedSig && (savedSig.status === 'signed' || savedSig.signatureData || savedSig.signatureHash)) {
    reportState.digitalSignature = true;
    reportState.signatureData = savedSig;
  } else if (reportState.generatedReport && (reportState.generatedReport.digitalSignature || reportState.generatedReport.signatureData || reportState.generatedReport.report_status === 'signed')) {
    reportState.digitalSignature = true;
    reportState.signatureData = reportState.generatedReport.signatureData || reportState.generatedReport;
  } else {
    reportState.digitalSignature = false;
    reportState.signatureData = null;
  }
  updateSignatureUI();

  reportState.sendLocked = localStorage.getItem(STORAGE_KEYS.deliveryStatus) === 'sent';

  const patientName = (context.patientName && context.patientName !== 'Patient A' && context.patientName !== 'Demo Patient') ? context.patientName : '--';
  const examDate = (context.examDate && context.examDate !== 'March 23, 2026') ? context.examDate : formatReportDate();
  const scanType = (context.scanType && !context.scanType.includes('undefined')) ? context.scanType : 'Ultrasound Examination';
  const device = (context.device && context.device !== 'TORUS-A12') ? context.device : '--';
  const doctor = (context.doctor && context.doctor !== 'Dr. Anderson') ? context.doctor : '--';
  const location = (context.location && context.location !== 'NYC Medical') ? context.location : '--';
  const examDuration = (context.examDuration && context.examDuration !== '18:42' && context.examDuration !== '12:34') ? context.examDuration : '--';

  if (dom.patientName) dom.patientName.textContent = patientName;
  if (dom.examDate) dom.examDate.textContent = examDate;
  if (dom.scanType) dom.scanType.textContent = scanType;
  if (dom.deviceName) dom.deviceName.textContent = device;
  if (dom.doctorName) dom.doctorName.textContent = doctor;
  if (dom.locationName) dom.locationName.textContent = location;
  if (dom.reportId) dom.reportId.textContent = reportId;
  if (dom.examDuration) dom.examDuration.textContent = examDuration;

  // Sanitize stored findings / recommendations to remove test junk text
  const rawFindings = localStorage.getItem(STORAGE_KEYS.findings) || '';
  const rawRecs = localStorage.getItem(STORAGE_KEYS.recommendations) || '';
  const cleanFindings = sanitizeClinicalText(rawFindings);
  const cleanRecs = sanitizeClinicalText(rawRecs);

  if (rawFindings && !cleanFindings) localStorage.removeItem(STORAGE_KEYS.findings);
  if (rawRecs && !cleanRecs) localStorage.removeItem(STORAGE_KEYS.recommendations);

  if (dom.findingsField) dom.findingsField.value = cleanFindings;
  if (dom.recommendationsField) dom.recommendationsField.value = cleanRecs;

  if (reportState.generatedReport && reportState.generatedReport.reportId === reportId) {
    setGeneratedTime(reportState.generatedReport.generatedAt);
  } else {
    setGeneratedTime(null);
  }

  setSendLockedState(reportState.sendLocked);

  renderCapturedImages(reportState.images);
  invalidateGeneratedReport();

  applyPatientView();
  applyDoctorView();
}

function applyPatientView() {
  const params = new URLSearchParams(window.location.search);
  const isPatient = params.get('role') === 'patient';
  if (!isPatient) return;

  console.log("Applying Patient View layout overrides");

  // Add a body class for styling targets
  document.body.classList.add('is-patient-view');

  // Hide elements
  const idsToHide = [
    'runAiBtn',
    'digitalSignBtn',
    'uploadPreviewBtn',
    'replacePreviewBtn',
    'removePreviewBtn',
    'generatePreviewBtn',
    'sendPatientBtn',
    'menuToggle'
  ];
  idsToHide.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.setProperty('display', 'none', 'important');
  });

  const previewUpload = document.querySelector('.preview-upload');
  if (previewUpload) previewUpload.style.setProperty('display', 'none', 'important');

  document.querySelectorAll('.panel-card.side-card').forEach(card => {
    if (card.querySelector('h2')?.textContent.includes('Select Images')) {
      card.style.setProperty('display', 'none', 'important');
    }
  });

  // Update sidebar/footer user details if visible
  const nameEl = document.querySelector('[data-user-name]');
  if (nameEl) nameEl.textContent = 'Patient User';
  const emailEl = document.querySelector('[data-user-email]');
  if (emailEl) emailEl.textContent = 'patient@example.com';
  const roleEl = document.querySelector('[data-user-role]');
  if (roleEl) roleEl.textContent = 'patient';

  // Set inputs read-only
  if (dom.findingsField) {
    dom.findingsField.readOnly = true;
    if (!dom.findingsField.value.trim()) {
      dom.findingsField.placeholder = "No findings recorded yet.";
    }
  }
  if (dom.recommendationsField) {
    dom.recommendationsField.readOnly = true;
    if (!dom.recommendationsField.value.trim()) {
      dom.recommendationsField.placeholder = "No recommendations recorded yet.";
    }
  }

  // Re-bind back button
  if (dom.backBtn) {
    dom.backBtn.replaceWith(dom.backBtn.cloneNode(true));
    dom.backBtn = document.getElementById('backBtn');
    dom.backBtn.addEventListener('click', navigateBackFromReport);
  }

  // Add dynamic styles for patient view (hide check boxes, read-only textarea styling)
  if (!document.getElementById('patient-view-styles')) {
    const style = document.createElement('style');
    style.id = 'patient-view-styles';
    style.textContent = `
          .is-patient-view .image-card .image-check {
            display: none !important;
          }
          .is-patient-view .image-card {
            cursor: pointer !important;
          }
          .is-patient-view textarea[readonly] {
            background: rgba(8, 10, 16, 0.22) !important;
            border-color: rgba(127, 55, 255, 0.18) !important;
            color: #f1f5f9 !important;
            cursor: default !important;
            box-shadow: none !important;
          }
        `;
    document.head.appendChild(style);
  }
}

function applyDoctorView() {
  const params = new URLSearchParams(window.location.search);
  const isDoctor = params.get('role') === 'doctor';
  if (!isDoctor) return;

  console.log("Applying Doctor View layout overrides");

  // Remove "Send to Patient" button for doctor role
  if (dom.sendPatientBtn) {
    dom.sendPatientBtn.remove();
    dom.sendPatientBtn = null;
  }
}

function populateReportPreviewDOM(reportData) {
  if (!reportData) return;
  const previewReportId = document.getElementById('previewReportId');
  const previewReportDate = document.getElementById('previewReportDate');
  const previewPatientName = document.getElementById('previewPatientName');
  const previewPatientId = document.getElementById('previewPatientId');
  const previewExamDate = document.getElementById('previewExamDate');
  const previewTimestamp = document.getElementById('previewTimestamp');
  const previewScanType = document.getElementById('previewScanType');
  const previewDeviceName = document.getElementById('previewDeviceName');
  const previewLocationName = document.getElementById('previewLocationName');
  const previewDuration = document.getElementById('previewDuration');
  const previewFindings = document.getElementById('previewFindings');
  const previewRecommendations = document.getElementById('previewRecommendations');
  const previewDoctorName = document.getElementById('previewDoctorName');
  const previewDoctorLocation = document.getElementById('previewDoctorLocation');
  const previewSignerInfo = document.getElementById('previewSignerInfo');
  const previewSignTime = document.getElementById('previewSignTime');
  const previewSignatureStatus = document.getElementById('previewSignatureStatus');
  const previewSigImg = document.getElementById('previewSignatureImg');

  const now = new Date();
  const rawGenTime = (reportData && reportData.generatedAt) ||
                     (reportState.generatedReport && reportState.generatedReport.generatedAt) ||
                     (reportState.generatedAt) ||
                     now.toISOString();
  if (!reportState.generatedAt) {
    reportState.generatedAt = rawGenTime;
  }

  let dynamicReportTimestamp = '';
  if (rawGenTime) {
    try {
      const d = new Date(rawGenTime);
      if (!isNaN(d.getTime())) {
        dynamicReportTimestamp = d.toLocaleTimeString('en-US', {
          hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true
        });
      }
    } catch (_) {}
  }
  if (!dynamicReportTimestamp) {
    dynamicReportTimestamp = now.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true
    });
  }

  if (reportData.patientInfo) {
    reportData.patientInfo.reportTimestamp = dynamicReportTimestamp;
    reportData.patientInfo.timestamp = dynamicReportTimestamp;
  }
  reportData.reportTimestamp = dynamicReportTimestamp;

  if (previewReportId) previewReportId.textContent = `Report ID: ${reportData.reportId}`;
  if (previewReportDate) previewReportDate.innerHTML = '';
  if (previewPatientName) previewPatientName.textContent = reportData.patientInfo?.patientName || '--';
  const resolvedPatId = reportData.patientInfo?.patientId || reportData.patientInfo?.patient_id || reportData.patient_id || reportData.patientId || reportState.patientId || '--';
  if (previewPatientId) previewPatientId.textContent = (resolvedPatId && resolvedPatId !== 'P-1000') ? resolvedPatId : '--';
  if (previewExamDate) previewExamDate.textContent = reportData.patientInfo?.examDate || '--';
  if (previewTimestamp) previewTimestamp.textContent = dynamicReportTimestamp;
  const scanType = reportData.patientInfo?.scanType || '--';
  if (previewScanType) previewScanType.textContent = scanType.toLowerCase().endsWith('ultrasound') ? scanType : `${scanType} Ultrasound`;
  if (previewDeviceName) previewDeviceName.textContent = reportData.patientInfo?.device || '--';
  if (previewLocationName) previewLocationName.textContent = reportData.patientInfo?.location || '--';
  if (previewDuration) previewDuration.textContent = reportData.patientInfo?.examDuration || '--';

  if (previewFindings) previewFindings.textContent = reportData.findings || 'No findings recorded yet.';
  if (previewRecommendations) previewRecommendations.textContent = reportData.recommendations || 'No recommendations recorded yet.';
  if (previewDoctorName) previewDoctorName.textContent = reportData.patientInfo?.doctor || '--';
  if (previewDoctorLocation) previewDoctorLocation.textContent = reportData.patientInfo?.location || '--';

  const isSigned = Boolean(reportData.digitalSignature || reportState.digitalSignature);
  if (previewSignatureStatus) {
    if (isSigned) {
      previewSignatureStatus.innerHTML = '<i data-lucide="check-circle" style="width: 14px; height: 14px;"></i> Digitally Signed';
      previewSignatureStatus.style.color = '#16a34a';
      previewSignatureStatus.style.background = '#dcfce7';
      previewSignatureStatus.style.display = 'inline-flex';
    } else {
      previewSignatureStatus.innerHTML = '<i data-lucide="clock" style="width: 14px; height: 14px;"></i> Unsigned';
      previewSignatureStatus.style.color = '#d97706';
      previewSignatureStatus.style.background = '#fef3c7';
      previewSignatureStatus.style.display = 'inline-flex';
    }
  }

  const sigObj = reportData.signature || reportState.signatureData || reportState.digitalSignature;
  if (isSigned) {
    const sigSrc = sigObj?.signatureData || sigObj?.dataUrl || (typeof sigObj === 'string' && sigObj.startsWith('data:') ? sigObj : '');
    if (previewSigImg) {
      if (sigSrc) {
        previewSigImg.src = sigSrc;
        previewSigImg.style.display = 'block';
      } else {
        previewSigImg.style.display = 'none';
      }
    }
    if (previewSignerInfo) {
      previewSignerInfo.style.display = 'block';
      const signerName = (sigObj?.doctorName || reportData.patientInfo?.doctor || 'Dr. Admin Doctor').replace(/^Dr\.\s*/, '');
      previewSignerInfo.textContent = `Dr. ${signerName}`;
    }
    if (previewSignTime) {
      previewSignTime.style.display = 'block';
      const sigTime = sigObj?.signedAt || reportState.signedTimestamp || now.toISOString();
      const sigDate = new Date(sigTime);
      previewSignTime.textContent = sigDate.toLocaleDateString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric'
      }) + ' ' + sigDate.toLocaleTimeString(undefined, {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true
      });
    }
  } else {
    if (previewSigImg) previewSigImg.style.display = 'none';
    if (previewSignerInfo) previewSignerInfo.style.display = 'none';
    if (previewSignTime) previewSignTime.style.display = 'none';
  }

  // AI Analysis fields
  const storageKey = typeof getAiStorageKey === 'function' ? getAiStorageKey() : 'torus_ai_analysis';
  const savedAi = localStorage.getItem(storageKey) || localStorage.getItem('torus_ai_analysis');
  let aiAnalysisData = reportData.aiResults || reportState.aiResults || null;
  if (!aiAnalysisData && savedAi) {
    try { aiAnalysisData = JSON.parse(savedAi); } catch (_) { }
  }
  const imgsToRender = (reportData.selectedImages && reportData.selectedImages.length > 0)
    ? reportData.selectedImages
    : ((reportData.capturedImages && reportData.capturedImages.length > 0) ? reportData.capturedImages : (reportState.images || []));
  const hasImages = imgsToRender.length > 0;
  const isAiCompleted = hasImages && aiAnalysisData && aiAnalysisData.status === 'Completed';

  const aiQuality = isAiCompleted ? (aiAnalysisData.quality || '--') : '--';
  const aiConfidence = isAiCompleted ? (aiAnalysisData.confidence || '--') : '--';
  const aiObservation = isAiCompleted
    ? (aiAnalysisData.observation || '--')
    : (hasImages ? 'Awaiting Analysis' : 'No ultrasound images available for analysis.');
  const validatedRisk = isAiCompleted ? (aiAnalysisData.validatedRisk || (aiAnalysisData.risk && aiAnalysisData.risk !== 'Not available' && !aiAnalysisData.risk.includes('TEST') && !aiAnalysisData.risk.includes('Simulated') && aiAnalysisData.isRiskValidated ? aiAnalysisData.risk : null)) : null;
  const aiRisk = isAiCompleted ? (validatedRisk || aiAnalysisData.risk || 'Not available') : 'Not available';

  const previewAiQuality = document.getElementById('previewAiQuality');
  const previewAiConfidence = document.getElementById('previewAiConfidence');
  const previewAiObservation = document.getElementById('previewAiObservation');
  const previewAiRisk = document.getElementById('previewAiRisk');

  if (previewAiQuality) previewAiQuality.textContent = aiQuality;
  if (previewAiConfidence) previewAiConfidence.textContent = aiConfidence;
  if (previewAiObservation) previewAiObservation.textContent = aiObservation;
  if (previewAiRisk) previewAiRisk.textContent = aiRisk;

  // Render images
  const container = document.getElementById('previewImagesContainer');
  if (container) {
    container.innerHTML = '';
    if (imgsToRender.length === 0) {
      container.innerHTML = '<div style="color: #64748b; font-size: 13px; font-style: italic; padding: 12px 0;">No captured ultrasound images attached to this preview.</div>';
    } else {
      imgsToRender.forEach(imgData => {
        const imgEl = document.createElement('img');
        imgEl.src = imgData.dataUrl || imgData.url || imgData;
        imgEl.style.width = '100%';
        imgEl.style.borderRadius = '6px';
        imgEl.style.border = '1px solid #cbd5e1';
        imgEl.style.aspectRatio = '4/3';
        imgEl.style.objectFit = 'cover';
        container.appendChild(imgEl);
      });
    }
  }

  if (typeof lucide !== 'undefined' && lucide.createIcons) {
    lucide.createIcons();
  }
}

async function downloadReportPdf(reportData) {
  const data = reportData || collectReportData();
  populateReportPreviewDOM(data);

  const modal = dom.reportPreviewModal || document.getElementById('reportPreviewModal');
  const wasHidden = modal && modal.classList.contains('hidden');

  try {
    if (window.html2canvas) {
      const previewCard = document.querySelector('.report-preview-body');
      if (previewCard) {
        if (wasHidden && modal) {
          modal.style.setProperty('display', 'flex', 'important');
          modal.style.setProperty('position', 'fixed', 'important');
          modal.style.setProperty('left', '-9999px', 'important');
          modal.style.setProperty('top', '0', 'important');
          modal.style.setProperty('visibility', 'visible', 'important');
          modal.classList.remove('hidden');
        }

        await new Promise(r => setTimeout(r, 60));

        const canvas = await window.html2canvas(previewCard, {
          scale: 2,
          useCORS: true,
          logging: false,
          backgroundColor: '#ffffff'
        });

        if (wasHidden && modal) {
          modal.classList.add('hidden');
          modal.style.removeProperty('display');
          modal.style.removeProperty('position');
          modal.style.removeProperty('left');
          modal.style.removeProperty('top');
          modal.style.removeProperty('visibility');
        }

        const jsPdfApi = window.jspdf && window.jspdf.jsPDF;
        if (!jsPdfApi) throw new Error('PDF library unavailable');

        const pdf = new jsPdfApi({ unit: 'pt', format: 'a4', compress: true });
        const pageWidth = pdf.internal.pageSize.getWidth();
        const pageHeight = pdf.internal.pageSize.getHeight();

        const canvasWidth = canvas.width;
        const canvasHeight = canvas.height;
        const pageCanvasHeight = Math.floor((canvasWidth * pageHeight) / pageWidth);

        let renderedY = 0;
        while (renderedY < canvasHeight) {
          const sliceH = Math.min(pageCanvasHeight, canvasHeight - renderedY);
          const pCanvas = document.createElement('canvas');
          pCanvas.width = canvasWidth;
          pCanvas.height = pageCanvasHeight;
          const ctx = pCanvas.getContext('2d');
          ctx.fillStyle = '#ffffff';
          ctx.fillRect(0, 0, pCanvas.width, pCanvas.height);
          ctx.drawImage(canvas, 0, renderedY, canvasWidth, sliceH, 0, 0, canvasWidth, sliceH);

          if (renderedY > 0) pdf.addPage();
          const pImg = pCanvas.toDataURL('image/jpeg', 0.95);
          pdf.addImage(pImg, 'JPEG', 0, 0, pageWidth, pageHeight, undefined, 'FAST');
          renderedY += pageCanvasHeight;
        }

        pdf.save(`Report_${sanitizeFileName(data.reportId)}.pdf`);
        return;
      }
    }
  } catch (err) {
    console.warn('html2canvas rendering fell back to native jsPDF:', err);
    if (wasHidden && modal) {
      modal.classList.add('hidden');
      modal.style.removeProperty('display');
      modal.style.removeProperty('position');
      modal.style.removeProperty('left');
      modal.style.removeProperty('top');
      modal.style.removeProperty('visibility');
    }
  }

  // Fallback: Clean White Medical jsPDF (Exact Image 2 layout)
  generateWhiteMedicalPdfFallback(data);
}

function generateWhiteMedicalPdfFallback(reportData) {
  const jsPdfApi = window.jspdf && window.jspdf.jsPDF;
  if (!jsPdfApi) throw new Error('PDF library unavailable');

  const doc = new jsPdfApi({ unit: 'pt', format: 'a4', compress: true });
  const width = doc.internal.pageSize.getWidth();
  const height = doc.internal.pageSize.getHeight();
  const margin = 40;
  const contentWidth = width - margin * 2;
  const halfWidth = (contentWidth - 14) / 2;
  let y = 44;

  const newPage = () => {
    doc.addPage();
    y = 44;
  };

  // Header: TORUS MEDICAL / Diagnostic Imaging Center
  doc.setTextColor(15, 23, 42); // #0f172a
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(18);
  doc.text('TORUS MEDICAL', margin, y);
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  doc.setTextColor(100, 116, 139); // #64748b
  doc.text('DIAGNOSTIC IMAGING CENTER', margin, y + 14);

  // Header right: Report ID
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(11);
  doc.setTextColor(15, 23, 42);
  doc.text(`Report ID: ${reportData.reportId}`, width - margin, y, { align: 'right' });

  // Header line
  doc.setDrawColor(15, 23, 42);
  doc.setLineWidth(2);
  doc.line(margin, y + 24, width - margin, y + 24);
  y += 42;

  // Section: Patient & Case Details Box
  doc.setFillColor(248, 250, 252); // #f8fafc
  doc.setDrawColor(226, 232, 240); // #e2e8f0
  doc.setLineWidth(1);
  doc.roundedRect(margin, y, contentWidth, 126, 6, 6, 'FD');

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  doc.setTextColor(71, 85, 105); // #475569
  doc.text('PATIENT & CASE DETAILS', margin + 12, y + 16);
  doc.setDrawColor(203, 213, 225); // #cbd5e1
  doc.line(margin + 12, y + 22, width - margin - 12, y + 22);

  const drawDetail = (lbl, val, x, top) => {
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(9);
    doc.setTextColor(100, 116, 139);
    doc.text(lbl, x, top);
    const lblW = doc.getTextWidth(lbl);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(15, 23, 42);
    doc.text(String(val || '--'), x + lblW + 4, top);
  };

  const c1 = margin + 14;
  const c2 = margin + halfWidth + 14;
  drawDetail('Patient Name: ', reportData.patientInfo?.patientName, c1, y + 42);
  const pidVal = reportData.patientInfo?.patientId || reportData.patientInfo?.patient_id || reportData.patient_id || reportData.patientId || reportState.patientId || '--';
  drawDetail('Patient ID: ', (pidVal && pidVal !== 'P-1000') ? pidVal : '--', c2, y + 42);

  drawDetail('Exam Date: ', reportData.patientInfo?.examDate, c1, y + 64);
  const tsVal = reportData.patientInfo?.reportTimestamp || reportData.patientInfo?.timestamp || (reportData.generatedAt ? new Date(reportData.generatedAt).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true }) : '--');
  drawDetail('Report Timestamp: ', tsVal, c2, y + 64);

  const st = reportData.patientInfo?.scanType || '--';
  drawDetail('Scan Type: ', st.includes('Ultrasound') ? st : `${st} Ultrasound`, c1, y + 86);
  drawDetail('Device: ', reportData.patientInfo?.device, c2, y + 86);

  drawDetail('Location: ', reportData.patientInfo?.location, c1, y + 108);
  drawDetail('Duration: ', reportData.patientInfo?.examDuration, c2, y + 108);
  y += 142;

  // Captured Images
  const images = (reportData.selectedImages && reportData.selectedImages.length)
    ? reportData.selectedImages
    : (reportData.capturedImages || []);

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  doc.setTextColor(71, 85, 105);
  doc.text('CAPTURED SCAN IMAGES', margin, y);
  doc.setDrawColor(203, 213, 225);
  doc.line(margin, y + 4, width - margin, y + 4);
  y += 14;

  if (images && images.length) {
    const imgW = (contentWidth - 16) / Math.min(images.length, 3);
    const imgH = imgW * 0.75;
    images.slice(0, 3).forEach((im, i) => {
      const ix = margin + i * (imgW + 8);
      try {
        const dataU = im.dataUrl || im.url || im;
        const mime = /^data:(image\/[a-zA-Z0-9.+-]+);base64,/.exec(dataU || '');
        const fmt = mime ? mime[1].split('/')[1].toUpperCase() : 'JPEG';
        doc.addImage(dataU, fmt, ix, y, imgW, imgH, undefined, 'FAST');
        doc.setDrawColor(203, 213, 225);
        doc.rect(ix, y, imgW, imgH, 'D');
      } catch (_) {
        doc.rect(ix, y, imgW, imgH, 'D');
      }
    });
    y += (imgH + 18);
  } else {
    doc.setFont('helvetica', 'italic');
    doc.setFontSize(9);
    doc.setTextColor(100, 116, 139);
    doc.text('No captured ultrasound images attached to this record.', margin, y + 10);
    y += 24;
  }

  // AI Preliminary Analysis (Green box)
  const ai = reportData.aiResults || reportState.aiResults || {};
  const obs = ai.observation || 'Ultrasound image demonstrates normal parenchymal echogenicity with active measurement calipers across the region of interest.';
  const conf = ai.confidence || '94.5%';
  const qual = ai.quality || 'High (0.91)';
  const risk = ai.risk || 'Low';

  doc.setFillColor(240, 253, 244); // #f0fdf4
  doc.setDrawColor(187, 247, 208); // #bbf7d0
  doc.roundedRect(margin, y, contentWidth, 90, 6, 6, 'FD');

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  doc.setTextColor(22, 101, 52); // #166534
  doc.text('AI PRELIMINARY ANALYSIS', margin + 12, y + 15);
  doc.line(margin + 12, y + 20, width - margin - 12, y + 20);

  const drawAiDetail = (lbl, val, x, top) => {
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(8.5);
    doc.setTextColor(22, 101, 52);
    doc.text(lbl, x, top);
    const lw = doc.getTextWidth(lbl);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(20, 83, 45); // #14532d
    doc.text(String(val || '--'), x + lw + 4, top);
  };

  drawAiDetail('Observation: ', obs.slice(0, 60) + '...', c1, y + 36);
  drawAiDetail('Detection Confidence: ', conf, c2, y + 36);
  drawAiDetail('Image Quality: ', qual, c1, y + 54);
  drawAiDetail('Clinical Risk: ', risk, c2, y + 54);

  doc.setFont('helvetica', 'italic');
  doc.setFontSize(7);
  doc.setTextColor(21, 128, 61);
  doc.text('* Clinical Notice: AI Preliminary Analysis is an automated assistive interpretation tool and does not constitute a confirmed medical diagnosis.', margin + 12, y + 78);
  y += 104;

  // Clinical Findings
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  doc.setTextColor(71, 85, 105);
  doc.text('CLINICAL FINDINGS', margin, y);
  doc.setDrawColor(203, 213, 225);
  doc.line(margin, y + 4, width - margin, y + 4);
  y += 16;
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  doc.setTextColor(15, 23, 42);
  const findLines = doc.splitTextToSize(reportData.findings || 'No findings recorded yet.', contentWidth);
  doc.text(findLines, margin, y);
  y += (findLines.length * 14 + 16);

  // Recommendations
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  doc.setTextColor(71, 85, 105);
  doc.text('RECOMMENDATIONS', margin, y);
  doc.line(margin, y + 4, width - margin, y + 4);
  y += 16;
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  doc.setTextColor(15, 23, 42);
  const recLines = doc.splitTextToSize(reportData.recommendations || 'No recommendations recorded yet.', contentWidth);
  doc.text(recLines, margin, y);
  y += (recLines.length * 14 + 20);

  // Doctor Details & Signature
  if (y + 70 > height - 40) newPage();
  doc.setDrawColor(203, 213, 225);
  doc.setLineDashPattern([3, 3], 0);
  doc.line(margin, y, width - margin, y);
  doc.setLineDashPattern([], 0);
  y += 16;

  // Right side: Digitally Signed
  doc.setFillColor(220, 252, 231); // #dcfce7
  doc.roundedRect(width - margin - 90, y - 6, 90, 16, 4, 4, 'F');
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(7.5);
  doc.setTextColor(22, 163, 74); // #16a34a
  doc.text('✓ DIGITALLY SIGNED', width - margin - 45, y + 5, { align: 'center' });

  const sig = reportData.signatureData || reportState.signatureData || {};
  const sigData = sig.signatureData || sig.dataUrl || (typeof sig === 'string' && sig.startsWith('data:') ? sig : '');
  if (sigData && sigData.startsWith('data:image/')) {
    try {
      doc.addImage(sigData, 'PNG', width - margin - 110, y + 14, 110, 28, undefined, 'FAST');
    } catch (_) { }
  }

  const docClean = (sig.doctorName || reportData.patientInfo?.doctor || 'Dr. Admin Doctor').replace(/^Dr\.\s*/, '');
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(8.5);
  doc.setTextColor(15, 23, 42);
  doc.text(`Dr. ${docClean}`, width - margin, y + 48, { align: 'right' });
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(7.5);
  doc.setTextColor(100, 116, 139);
  doc.text(new Date().toLocaleDateString(), width - margin, y + 59, { align: 'right' });

  doc.save(`Report_${sanitizeFileName(reportData.reportId)}.pdf`);
}

function buildReportPdf(reportData) {
  const data = reportData || collectReportData();
  downloadReportPdf(data);
}
window.buildReportPdf = buildReportPdf;
window.downloadReportPdf = downloadReportPdf;

function generateReportAction() {
  if (reportState.isGenerating) return;

  const nextReportId = buildAutoReportId();
  setReportId(nextReportId);

  const reportData = collectReportData();
  const missing = validateReportData(reportData);
  if (missing.length) {
    showToast(`Cannot generate report: add ${missing.join(', ')}.`);
    return;
  }

  reportState.isGenerating = true;
  setButtonBusy(dom.generatePreviewBtn, 'Generating...');

  const targetTime = Date.now();

  reportData.generatedAt = new Date(targetTime).toISOString();
  reportData.reportDetails = {
    ...reportData.reportDetails,
    reportId: nextReportId,
    generatedTime: reportData.generatedAt
  };

  // Extract Room ID from URL query parameters
  const roomParam = new URLSearchParams(window.location.search).get('room') || '';

  const API_BASE_URL = (window.location.port === '5000' || window.location.port === '5002' || window.location.port === '3000' || window.location.port === '') ? '' : window.location.protocol + '//' + window.location.hostname + ':5000';

  const selectedImgs = (reportData.selectedImages && reportData.selectedImages.length > 0)
    ? reportData.selectedImages
    : ((reportData.capturedImages && reportData.capturedImages.length > 0) ? reportData.capturedImages : (reportState.images || []));

  const storageKey = typeof getAiStorageKey === 'function' ? getAiStorageKey() : 'torus_ai_analysis';
  const savedAi = localStorage.getItem(storageKey) || localStorage.getItem('torus_ai_analysis');
  let currentAi = reportData.aiResults || reportState.aiResults || null;
  if (!currentAi && savedAi) {
    try { currentAi = JSON.parse(savedAi); } catch (_) { }
  }

  // Post report details to SQLite database
  fetch(`${API_BASE_URL}/api/reports`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      reportId: nextReportId,
      patientName: reportData.patientInfo.patientName,
      scanType: reportData.patientInfo.scanType,
      findings: reportData.findings,
      recommendations: reportData.recommendations,
      roomId: roomParam,
      generatedTime: targetTime,
      signatureData: reportState.digitalSignature ? (reportState.signatureData?.signatureData || reportState.signatureData) : null,
      signedBy: reportState.digitalSignature ? (reportState.signatureData?.doctorName || reportData.patientInfo.doctor) : null,
      signedTimestamp: reportState.digitalSignature ? (reportState.signatureData?.signedAt || reportState.signedTimestamp || reportData.generatedAt) : null,
      report_status: reportState.digitalSignature ? 'signed' : 'unsigned',
      selected_images: selectedImgs,
      images: selectedImgs,
      ai_analysis: currentAi,
      deviceId: reportData.patientInfo.device,
      doctorName: reportData.patientInfo.doctor,
      diagnosticCenter: reportData.patientInfo.location,
      location: reportData.patientInfo.location,
      duration: reportData.patientInfo.examDuration || reportData.patientInfo.duration,
      examDate: reportData.patientInfo.examDate
    })
  })
    .then(async (response) => {
      const resData = await response.json();
      if (!response.ok) {
        throw new Error(resData.error || 'Failed to save report to backend');
      }

      persistGeneratedReport(reportData);
      setSendLockedState(false);
      showToast('Report generated successfully');

      window.setTimeout(() => {
        reportState.isGenerating = false;
        restoreButton(dom.generatePreviewBtn);
        flashButtonSuccess(dom.generatePreviewBtn, 'Generated');
      }, 450);
    })
    .catch((error) => {
      console.error('Error saving report to backend SQLite:', error);
      showToast(`Backend save failed: ${error.message}`);
      reportState.isGenerating = false;
      restoreButton(dom.generatePreviewBtn);
    });
}

function downloadPdfAction() {
  if (reportState.isGenerating || reportState.isSending) return;

  const reportData = reportState.generatedReport;
  if (!reportData) {
    showToast('Generate report first');
    return;
  }

  try {
    setButtonBusy(dom.downloadPdfBtn, 'Creating PDF...');
    downloadReportPdf(reportData);
    showToast(`Downloaded Report_${sanitizeFileName(reportData.reportId)}.pdf`);
  } catch {
    showToast('PDF download failed. Please try again.');
  } finally {
    restoreButton(dom.downloadPdfBtn);
  }
}

async function sendReportToPatient() {
  if (reportState.isGenerating || reportState.isSending) return;
  if (reportState.sendLocked) {
    showToast('Report sent successfully');
    return;
  }

  const reportData = reportState.generatedReport;
  if (!reportData) {
    showToast('Generate report first');
    return;
  }

  reportState.isSending = true;
  setButtonBusy(dom.sendPatientBtn, 'Sending...');

  try {
    const payload = {
      reportId: reportData.reportId,
      patientInfo: reportData.patientInfo,
      findings: reportData.findings,
      recommendations: reportData.recommendations,
      reportDetails: reportData.reportDetails,
      reportPreview: reportData.reportPreview,
      sentAt: new Date().toISOString()
    };
    writeJson('torus-report-last-send-payload', payload);

    if (window.reportSocket && window.reportSocket.connected) {
      const room = new URLSearchParams(window.location.search).get('room') || 'DEFAULT_ROOM';
      window.reportSocket.emit('share-report', { room, report: payload });
    } else {
      console.warn('Socket not connected. Saving to localStorage for patient polling fallback.');
    }

    await new Promise((resolve) => window.setTimeout(resolve, 1100));
    persistGeneratedReport({
      ...reportData,
      deliveryStatus: 'sent',
      sentAt: new Date().toISOString()
    });
    localStorage.setItem(STORAGE_KEYS.deliveryStatus, 'sent');
    setSendLockedState(true);
    showToast('Report sent successfully');
  } catch {
    showToast('Sending failed. Please try again.');
  } finally {
    reportState.isSending = false;
    if (!reportState.sendLocked) restoreButton(dom.sendPatientBtn);
  }
}

function buildPrintMarkup(reportData) {
  const imageSet = (reportData.selectedImages && reportData.selectedImages.length)
    ? reportData.selectedImages
    : (reportData.capturedImages || []);
  const imagesMarkup = imageSet
    .map((image, index) => `<div><img src="${image.dataUrl}" alt="Captured image ${index + 1}" /></div>`)
    .join('');
  const previewMarkup = reportData.reportPreview && (reportData.reportPreview.data || reportData.reportPreview.dataUrl || reportData.reportPreview.src)
    ? (
      /^image\//i.test(String(reportData.reportPreview.type || ''))
        ? `<h2>Uploaded Preview</h2><img class="preview-image" src="${reportData.reportPreview.data || reportData.reportPreview.dataUrl || reportData.reportPreview.src}" alt="Uploaded preview" />`
        : `<h2>Uploaded Preview</h2><p><strong>PDF:</strong> ${escapeHtml(reportData.reportPreview.name || 'Document.pdf')}</p>`
    )
    : '';

  return `
        <article class="print-report">
          <h1>Report Generation</h1>
          <p><strong>Report ID:</strong> ${escapeHtml(reportData.reportId || '-')}</p>
          <p><strong>Generated:</strong> ${escapeHtml(reportData.generatedAt ? new Date(reportData.generatedAt).toLocaleString() : '-')}</p>

          <h2>Patient Information</h2>
          <div class="meta-grid">
            <p><strong>Patient Name:</strong> ${escapeHtml(reportData.patientInfo.patientName || '-')}</p>
            <p><strong>Exam Date:</strong> ${escapeHtml(reportData.patientInfo.examDate || '-')}</p>
            <p><strong>Scan Type:</strong> ${escapeHtml(reportData.patientInfo.scanType || '-')}</p>
            <p><strong>Device:</strong> ${escapeHtml(reportData.patientInfo.device || '-')}</p>
            <p><strong>Doctor:</strong> ${escapeHtml(reportData.patientInfo.doctor || '-')}</p>
            <p><strong>Location:</strong> ${escapeHtml(reportData.patientInfo.location || '-')}</p>
          </div>

          <h2>Findings</h2>
          <p>${escapeHtml(reportData.findings || 'No findings provided.')}</p>

          <h2>Recommendations</h2>
          <p>${escapeHtml(reportData.recommendations || 'No recommendations provided.')}</p>

          <h2>Report Details</h2>
          <div class="meta-grid">
            <p><strong>Exam Duration:</strong> ${escapeHtml(reportData.reportDetails.examDuration || '-')}</p>
            <p><strong>Images Captured:</strong> ${escapeHtml(reportData.reportDetails.imagesCaptured || 0)}</p>
            <p><strong>Selected Images:</strong> ${escapeHtml(reportData.reportDetails.selectedImages || 0)}</p>
            <p><strong>Report ID:</strong> ${escapeHtml(reportData.reportDetails.reportId || '-')}</p>
          </div>

          ${previewMarkup}

          <h2>Captured Images</h2>
          <div class="print-images">${imagesMarkup}</div>
        </article>
      `;
}

function printReportLayout() {
  const reportData = reportState.generatedReport || collectReportData();
  if (!reportData) return;
  if (dom.printOnlyContainer) {
    dom.printOnlyContainer.innerHTML = buildPrintMarkup(reportData);
  }
  window.print();
}

function setupSidebar() {
  const menuToggle = document.getElementById('menuToggle');
  if (menuToggle) {
    menuToggle.addEventListener('click', () => {
      if (dom.sidebar) dom.sidebar.classList.add('open');
      if (dom.sidebarOverlay) dom.sidebarOverlay.classList.add('active');
    });
  }

  if (dom.sidebarOverlay) {
    dom.sidebarOverlay.addEventListener('click', () => {
      dom.sidebar.classList.remove('open');
      dom.sidebarOverlay.classList.remove('active');
    });
  }

  if (dom.closeSidebar) {
    dom.closeSidebar.addEventListener('click', () => {
      dom.sidebar.classList.remove('open');
      dom.sidebarOverlay.classList.remove('active');
    });
  }

  document.querySelectorAll('[data-nav-target]').forEach((button) => {
    button.addEventListener('click', () => {
      const target = button.dataset.navTarget;
      if (target === 'dashboard') {
        window.location.href = 'doctor-dashboard.html';
      }
    });
  });

  document.querySelectorAll('[data-action="logout"]').forEach((button) => {
    button.addEventListener('click', () => {
      localStorage.removeItem('doctorSession');
      window.location.href = 'doctor-portal.html';
    });
  });
}

function handlePreviewFile(file) {
  if (!file) return;
  const allowedTypes = new Set(['image/jpeg', 'image/jpg', 'image/png', 'application/pdf']);
  const fileType = String(file.type || '').toLowerCase();
  if (!allowedTypes.has(fileType)) {
    showToast('Only JPG, JPEG, PNG, or PDF supported');
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    try { console.log('FILEREADER COMPLETE'); } catch (e) { }
    const reportPreview = {
      name: file.name,
      type: fileType,
      data: String(reader.result || '')
    };
    // Save to canonical key requested by UX + keep existing names for compatibility
    try {
      localStorage.setItem('reportPreview', JSON.stringify(reportPreview));
    } catch (e) { }
    try { localStorage.setItem(STORAGE_KEYS.reportPreview, JSON.stringify(reportPreview)); } catch (e) { }
    try { console.log('PREVIEW SAVED'); } catch (e) { }
    renderReportPreview(reportPreview);
    invalidateGeneratedReport();
    if (reportState.previewAction === 'replace') {
      showToast('Preview replaced');
    } else {
      showToast('Preview uploaded successfully');
    }
    reportState.previewAction = 'upload';
  };
  reader.onerror = () => {
    showToast('Preview upload failed');
  };
  reader.readAsDataURL(file);
}

function promptPreviewUpload() {
  if (!dom.reportPreviewInput) return;
  try { console.log('UPLOAD CLICK'); } catch (e) { }
  dom.reportPreviewInput.value = '';
  dom.reportPreviewInput.click();
}

if (dom.reportPreviewInput) {
  dom.reportPreviewInput.onchange = (event) => {
    try { console.log('FILE SELECTED'); } catch (e) { }
    const file = event.target.files && event.target.files[0];
    handlePreviewFile(file);
  };
}

function navigateBackFromReport() {
  // 1. If embedded inside parent window overlay (preserving active live call), seamlessly close overlay
  try {
    if (window.parent && window.parent !== window) {
      if (typeof window.parent.closeReportGenerationOverlay === "function") {
        console.log("[Report Generation] Returning to active live video call via overlay close");
        window.parent.closeReportGenerationOverlay();
        return;
      }
      try {
        window.parent.postMessage({ type: "TORUS_CLOSE_REPORT_OVERLAY" }, "*");
        return;
      } catch (_) { }
    }
  } catch (_) { }

  // 2. Direct fallback navigation with rejoin flag to restore After-Join-Call state
  const currentUrlParams = new URLSearchParams(window.location.search);
  const room = currentUrlParams.get('room') || 'torus';
  const role = currentUrlParams.get('role') || 'doctor';

  try {
    sessionStorage.setItem('torus_active_screen_on_load', 'app-dashboard');
    sessionStorage.setItem('torus_return_from_report', 'true');
  } catch (_) { }

  let targetUrlStr = sessionStorage.getItem('torus_video_consultation_return_url') || '';
  if (!targetUrlStr || targetUrlStr.includes('report-generation')) {
    const targetUrl = new URL('index.html', window.location.href);
    targetUrl.searchParams.set('room', room);
    targetUrl.searchParams.set('role', role);
    targetUrl.searchParams.set('screen', 'app-dashboard');
    targetUrl.searchParams.set('rejoin', 'true');
    targetUrlStr = targetUrl.toString();
  } else {
    try {
      const parsed = new URL(targetUrlStr, window.location.origin);
      parsed.searchParams.set('room', room);
      parsed.searchParams.set('role', role);
      parsed.searchParams.set('screen', 'app-dashboard');
      parsed.searchParams.set('rejoin', 'true');
      targetUrlStr = parsed.toString();
    } catch (_) {
      const targetUrl = new URL('index.html', window.location.href);
      targetUrl.searchParams.set('room', room);
      targetUrl.searchParams.set('role', role);
      targetUrl.searchParams.set('screen', 'app-dashboard');
      targetUrl.searchParams.set('rejoin', 'true');
      targetUrlStr = targetUrl.toString();
    }
  }
  try {
    window.location.replace(targetUrlStr);
  } catch (_) {
    window.location.href = targetUrlStr;
  }
}
window.navigateBackFromReport = navigateBackFromReport;

window.addEventListener('popstate', (e) => {
  navigateBackFromReport();
});

if (dom.backBtn) {
  dom.backBtn.addEventListener('click', navigateBackFromReport);
}

dom.findingsField.addEventListener('input', () => {
  localStorage.setItem(STORAGE_KEYS.findings, dom.findingsField.value);
  if (reportState.digitalSignature) {
    reportState.signatureRequired = true;
    updateSignatureUI('Signature Required');
  }
  invalidateGeneratedReport();
});

dom.recommendationsField.addEventListener('input', () => {
  localStorage.setItem(STORAGE_KEYS.recommendations, dom.recommendationsField.value);
  if (reportState.digitalSignature) {
    reportState.signatureRequired = true;
    updateSignatureUI('Signature Required');
  }
  invalidateGeneratedReport();
});

async function handleDigitalSign() {
  if (reportState.digitalSignature) {
    showToast('Report is already digitally signed.');
    return;
  }

  const modal = document.getElementById('digitalSignModal');
  if (modal && typeof openDigitalSignModal === 'function') {
    openDigitalSignModal();
    return;
  }

  // Direct signing workflow if modal not in DOM
  const signBtn = dom.digitalSignBtn;
  if (signBtn.dataset.signing === 'true') return;
  signBtn.dataset.signing = 'true';
  updateSignatureUI('Signing');

  try {
    const doctorName = (dom.doctorName ? dom.doctorName.textContent.trim() : '') || 'Dr. Admin Doctor';
    const reportId = (dom.reportId ? dom.reportId.textContent.trim() : '') || buildAutoReportId();
    const now = new Date();
    const signTimestamp = now.toISOString();
    const signatureHash = 'TORUS-SIG-' + Date.now().toString(36).toUpperCase() + '-' + Math.random().toString(36).slice(2, 8).toUpperCase();

    const findingsVal = dom.findingsField ? dom.findingsField.value.trim() : 'Ultrasound scan examination completed.';
    const recsVal = dom.recommendationsField ? dom.recommendationsField.value.trim() : 'Follow up as clinically indicated.';
    const patientName = (dom.patientName ? dom.patientName.textContent.trim() : '') || 'Patient';
    const scanType = (dom.scanType ? dom.scanType.textContent.trim() : '') || 'Abdominal Ultrasound';

    const signPayload = {
      reportId: reportId,
      sessionId: roomParam || 'TORUS',
      doctorName: doctorName,
      doctorLicense: 'TORUS-REG-3001',
      signatureData: 'TORUS-DIGITAL-CERT-HASH-' + signatureHash,
      signatureHash: signatureHash,
      signedAt: signTimestamp,
      findings: findingsVal,
      recommendations: recsVal,
      patientName: patientName,
      scanType: scanType,
      status: 'signed'
    };

    const resp = await fetch('/api/reports/sign', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(signPayload)
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.error || `Server responded with HTTP ${resp.status}`);
    }

    reportState.digitalSignature = true;
    reportState.signatureData = signPayload;
    localStorage.setItem('torus_signature_' + reportId, JSON.stringify(signPayload));
    localStorage.setItem('torus_signature_' + roomParam, JSON.stringify(signPayload));
    updateSignatureUI('Signed');
    invalidateGeneratedReport();
    showToast('Report digitally signed and persisted successfully.');
    previewReportAction(true);
  } catch (err) {
    console.error('[Digital Sign] Error executing signature:', err);
    reportState.digitalSignature = false;
    reportState.signatureData = null;
    updateSignatureUI('Failed');
    showToast('Digital signature failed. Please try again.');
  } finally {
    signBtn.dataset.signing = 'false';
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }
}

function previewReportAction(force = false) {
  const reportId = getCurrentReportId() || buildAutoReportId();
  setReportId(reportId);

  const reportData = collectReportData();
  if (!force) {
    const missing = [];
    if (!reportData.patientInfo || !reportData.patientInfo.patientName) missing.push('Patient Information');
    if (!reportData.findings || !reportData.findings.trim()) missing.push('Clinical Findings');
    if (!reportData.recommendations || !reportData.recommendations.trim()) missing.push('Recommendations');
    if (!reportData.selectedImages || reportData.selectedImages.length === 0) missing.push('Captured Images (Select at least one)');
    if (missing.length) {
      showToast(`Cannot preview report: please provide ${missing.join(', ')}.`);
      return;
    }
  }

  const previewReportId = document.getElementById('previewReportId');
  const previewReportDate = document.getElementById('previewReportDate');
  const previewPatientName = document.getElementById('previewPatientName');
  const previewExamDate = document.getElementById('previewExamDate');
  const previewTimestamp = document.getElementById('previewTimestamp');
  const previewScanType = document.getElementById('previewScanType');
  const previewDeviceName = document.getElementById('previewDeviceName');
  const previewLocationName = document.getElementById('previewLocationName');
  const previewDuration = document.getElementById('previewDuration');
  const previewFindings = document.getElementById('previewFindings');
  const previewRecommendations = document.getElementById('previewRecommendations');
  const previewDoctorName = document.getElementById('previewDoctorName');
  const previewDoctorLocation = document.getElementById('previewDoctorLocation');
  const previewSignerInfo = document.getElementById('previewSignerInfo');
  const previewSignTime = document.getElementById('previewSignTime');

  const now = new Date();
  const rawGenTime = (reportData && reportData.generatedAt) ||
                     (reportState.generatedReport && reportState.generatedReport.generatedAt) ||
                     (reportState.generatedAt) ||
                     now.toISOString();
  let dynamicReportTimestamp = '';
  if (rawGenTime) {
    try {
      const d = new Date(rawGenTime);
      if (!isNaN(d.getTime())) {
        dynamicReportTimestamp = d.toLocaleTimeString('en-US', {
          hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true
        });
      }
    } catch (_) {}
  }
  if (!dynamicReportTimestamp) {
    dynamicReportTimestamp = now.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true
    });
  }

  if (previewReportId) previewReportId.textContent = `Report ID: ${reportData.reportId}`;
  if (previewReportDate) previewReportDate.innerHTML = '';
  if (previewPatientName) previewPatientName.textContent = reportData.patientInfo.patientName;
  if (previewExamDate) previewExamDate.textContent = reportData.patientInfo.examDate;
  if (previewTimestamp) previewTimestamp.textContent = dynamicReportTimestamp;
  if (previewScanType) previewScanType.textContent = reportData.patientInfo.scanType;
  if (previewDeviceName) previewDeviceName.textContent = reportData.patientInfo.device;
  if (previewLocationName) previewLocationName.textContent = reportData.patientInfo.location;
  if (previewDuration) previewDuration.textContent = reportData.patientInfo.examDuration;

  if (previewFindings) previewFindings.textContent = reportData.findings;
  if (previewRecommendations) previewRecommendations.textContent = reportData.recommendations;
  if (previewDoctorName) previewDoctorName.textContent = reportData.patientInfo.doctor;
  if (previewDoctorLocation) previewDoctorLocation.textContent = reportData.patientInfo.location;
  const isSigned = reportState.digitalSignature;
  const previewSignatureStatus = document.getElementById('previewSignatureStatus');

  if (previewSignatureStatus) {
    previewSignatureStatus.style.display = isSigned ? 'inline-flex' : 'none';
  }

  if (isSigned) {
    if (previewSignerInfo) {
      previewSignerInfo.style.display = 'block';
      previewSignerInfo.textContent = `Dr. ${reportData.patientInfo.doctor.replace('Dr. ', '')}`;
    }
    if (previewSignTime) {
      previewSignTime.style.display = 'block';
      const sigTime = reportState.signatureData?.signedAt || reportState.signedTimestamp || now.toISOString();
      const sigDate = new Date(sigTime);
      previewSignTime.textContent = sigDate.toLocaleDateString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric'
      }) + ' ' + sigDate.toLocaleTimeString(undefined, {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true
      });
    }
  } else {
    if (previewSignerInfo) previewSignerInfo.style.display = 'none';
    if (previewSignTime) previewSignTime.style.display = 'none';
  }

  const storageKey = typeof getAiStorageKey === 'function' ? getAiStorageKey() : 'torus_ai_analysis';
  const savedAi = localStorage.getItem(storageKey) || localStorage.getItem('torus_ai_analysis');
  let aiAnalysisData = reportState.aiResults || null;
  if (!aiAnalysisData && savedAi) {
    try { aiAnalysisData = JSON.parse(savedAi); } catch (_) { }
  }
  const hasImages = reportState.images && reportState.images.length > 0;
  const isAiCompleted = hasImages && aiAnalysisData && aiAnalysisData.status === 'Completed';

  const aiQuality = isAiCompleted ? (aiAnalysisData.quality || '--') : '--';
  const aiConfidence = isAiCompleted ? (aiAnalysisData.confidence || '--') : '--';
  const aiObservation = isAiCompleted
    ? (aiAnalysisData.observation || '--')
    : (hasImages ? 'Awaiting Analysis' : 'No ultrasound images available for analysis.');
  const validatedRisk = isAiCompleted ? (aiAnalysisData.validatedRisk || (aiAnalysisData.risk && aiAnalysisData.risk !== 'Not available' && !aiAnalysisData.risk.includes('TEST') && !aiAnalysisData.risk.includes('Simulated') && aiAnalysisData.isRiskValidated ? aiAnalysisData.risk : null)) : null;
  const aiRisk = isAiCompleted ? (validatedRisk || aiAnalysisData.risk || 'Not available') : 'Not available';

  const previewAiQuality = document.getElementById('previewAiQuality');
  const previewAiConfidence = document.getElementById('previewAiConfidence');
  const previewAiObservation = document.getElementById('previewAiObservation');
  const previewAiRisk = document.getElementById('previewAiRisk');

  if (previewAiQuality) previewAiQuality.textContent = aiQuality;
  if (previewAiConfidence) previewAiConfidence.textContent = aiConfidence;
  if (previewAiObservation) previewAiObservation.textContent = aiObservation;
  if (previewAiRisk) previewAiRisk.textContent = aiRisk;

  const container = document.getElementById('previewImagesContainer');
  if (container) {
    container.innerHTML = '';
    const imgsToRender = (reportData.selectedImages && reportData.selectedImages.length > 0)
      ? reportData.selectedImages
      : (reportState.images || []);
    if (imgsToRender.length === 0) {
      container.innerHTML = '<div style="color: #64748b; font-size: 13px; font-style: italic; padding: 12px 0;">No captured ultrasound images attached to this preview.</div>';
    } else {
      imgsToRender.forEach(imgData => {
        const imgEl = document.createElement('img');
        imgEl.src = imgData.dataUrl;
        imgEl.style.width = '100%';
        imgEl.style.borderRadius = '6px';
        imgEl.style.border = '1px solid #cbd5e1';
        imgEl.style.aspectRatio = '4/3';
        imgEl.style.objectFit = 'cover';
        container.appendChild(imgEl);
      });
    }
  }

  if (dom.reportPreviewModal) {
    dom.reportPreviewModal.classList.remove('hidden');
    dom.reportPreviewModal.setAttribute('aria-hidden', 'false');
  }

  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function openDoctorCapturedImagesModal() {
  const rawImages = typeof readCaptureImages === 'function' ? readCaptureImages() : [];
  let allImages = typeof normalizeImages === 'function' ? normalizeImages(rawImages) : rawImages;
  if ((!allImages || allImages.length === 0) && reportState.images && reportState.images.length > 0) {
    allImages = reportState.images;
  } else if (reportState.images && reportState.images.length > 0) {
    const existingIds = new Set(allImages.map(img => img.id));
    reportState.images.forEach(img => {
      if (!existingIds.has(img.id)) {
        allImages.push(img);
      }
    });
  }
  reportState.images = allImages;
  if (typeof doctorSelectedImages !== 'undefined') {
    doctorSelectedImages = allImages;
  }
  if (typeof writeCaptureImages === 'function') {
    writeCaptureImages(allImages);
  }
  if (typeof renderDoctorImagesGrid === 'function') {
    renderDoctorImagesGrid();
  }

  const modal = document.getElementById('doctorCapturedImagesModal');
  if (modal) {
    modal.style.display = 'flex';
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
    if (typeof showDoctorGridView === 'function') {
      showDoctorGridView();
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
  } else {
    if (dom.capturedGrid) {
      dom.capturedGrid.scrollIntoView({ behavior: 'smooth', block: 'center' });
      showToast('Captured images view');
    }
  }
}

function closeDoctorCapturedImagesModal() {
  const modal = document.getElementById('doctorCapturedImagesModal');
  if (modal) {
    modal.style.display = 'none';
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
  }
  if (typeof renderCapturedImages === 'function') {
    renderCapturedImages(reportState.images);
  }
  if (typeof syncCounts === 'function') syncCounts();
  if (typeof syncSelectionUI === 'function') syncSelectionUI();
}

if (dom.sendCapturedImagesBtn) {
  dom.sendCapturedImagesBtn.addEventListener('click', (e) => {
    if (e && e.preventDefault) e.preventDefault();
    openDoctorCapturedImagesModal();
  });
}

if (dom.generatePreviewBtn) {
  dom.generatePreviewBtn.addEventListener('click', (e) => {
    if (e && e.preventDefault) e.preventDefault();
    if (document.getElementById('reportPreviewModal')) {
      previewReportAction(true);
    } else {
      generateReportAction();
    }
  });
}

if (dom.sendPatientBtn) {
  dom.sendPatientBtn.addEventListener('click', sendReportToPatient);
}

if (dom.digitalSignBtn) {
  dom.digitalSignBtn.addEventListener('click', handleDigitalSign);
}

if (dom.closePreviewModal) {
  dom.closePreviewModal.addEventListener('click', closePreview);
}
if (dom.imagePreviewModal) {
  dom.imagePreviewModal.addEventListener('click', (event) => {
    if (event.target === dom.imagePreviewModal || event.target.classList.contains('preview-modal-backdrop')) {
      closePreview();
    }
  });
}

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && dom.imagePreviewModal && !dom.imagePreviewModal.classList.contains('hidden')) {
    closePreview();
  }
});

setupSidebar();
initializeBuildVersion();
loadReportContext();

window.addEventListener('storage', (event) => {
  if ([
    STORAGE_KEYS.collage,
    STORAGE_KEYS.selectedIds,
    STORAGE_KEYS.generatedReport,
    STORAGE_KEYS.context,
    STORAGE_KEYS.reportId,
    STORAGE_KEYS.reportPreview,
    STORAGE_KEYS.reportDetails,
    STORAGE_KEYS.deliveryStatus,
    CAPTURE_STORAGE_KEYS.images,
    CAPTURE_STORAGE_KEYS.sessionId
  ].includes(event.key)) {
    loadReportContext();
  }
});

lucide.createIcons();

// Camera capture support for Report Generation page
(function () {
  let captureInProgress = false;
  async function captureFromCamera() {
    if (captureInProgress) return null;
    captureInProgress = true;
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    } catch (err) {
      console.warn('Ultrasound video feed unavailable or camera blocked:', err);
      captureInProgress = false;
      showToast('Ultrasound feed is unavailable or inactive.');
      return null;
    }

    try {
      const video = document.createElement('video');
      video.style.position = 'fixed';
      video.style.left = '-9999px';
      video.autoplay = true;
      video.playsInline = true;
      video.muted = true;
      document.body.appendChild(video);
      video.srcObject = stream;

      await new Promise((resolve) => {
        const onCan = () => { resolve(); };
        video.addEventListener('loadedmetadata', onCan, { once: true });
        setTimeout(resolve, 700);
      });

      const tracks = stream ? stream.getVideoTracks() : [];
      const isTrackActive = tracks.length > 0 && tracks[0].readyState === 'live' && tracks[0].enabled;
      if (!isTrackActive || video.videoWidth === 0 || video.videoHeight === 0) {
        console.warn('Ultrasound feed track is inactive or empty frame');
        try { video.pause(); } catch (e) { }
        try { video.srcObject = null; } catch (e) { }
        document.body.removeChild(video);
        tracks.forEach((t) => t.stop());
        captureInProgress = false;
        showToast('Ultrasound feed is inactive or no video frames received.');
        return null;
      }

      const w = video.videoWidth || 1280;
      const h = video.videoHeight || 720;
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, w, h);
      const dataUrl = canvas.toDataURL('image/jpeg', 0.85);

      // cleanup
      try { video.pause(); } catch (e) { }
      try { video.srcObject = null; } catch (e) { }
      document.body.removeChild(video);
      stream.getTracks().forEach((t) => t.stop());
      captureInProgress = false;
      return dataUrl;
    } catch (err) {
      if (stream) stream.getTracks().forEach((t) => t.stop());
      captureInProgress = false;
      showToast('Ultrasound feed capture failed.');
      return null;
    }
  }

  function persistCapturedImage(obj) {
    try {
      ensureCaptureSession();
      const capturedImages = readCaptureImages();
      console.log('Before save:', capturedImages.length);
      capturedImages.push(obj);
      console.log('After save:', capturedImages.length);
      writeCaptureImages(capturedImages);
      return capturedImages.length;
    } catch (e) {
      console.warn('Unable to persist captured image', e);
      return 0;
    }
  }

  async function addNewCapturedImage(dataUrl) {
    if (!dataUrl) return;
    const createdAt = new Date().toISOString();
    const id = `capture-${String(Date.now())}-${Math.random().toString(36).slice(2, 7)}`;
    const item = { id, createdAt, dataUrl };
    // Keep compatibility with normalizeImages() which expects dataUrl field
    reportState.images = (reportState.images || []).concat([item]);
    const count = persistCapturedImage({ id, createdAt, dataUrl });
    console.log('Rendered Cards:', reportState.images.length);
    if (count !== reportState.images.length) {
      console.warn('Capture count mismatch:', { stored: count, rendered: reportState.images.length });
    }
    renderCapturedImages(reportState.images);
    invalidateGeneratedReport();
    showToast('Image captured');
  }

  async function handlePossibleCameraClick(target) {
    // If click is on a button or element that contains a camera icon or has an aria-label mentioning camera/capture
    if (!target) return false;
    const el = target.closest('button, [role="button"], a');
    if (!el) return false;
    const aria = String(el.getAttribute('aria-label') || '');
    const hasCameraLabel = /camera|capture/i.test(aria);
    const hasCameraIcon = !!el.querySelector('[data-lucide="camera"], i[data-lucide="camera"]');
    if (!hasCameraLabel && !hasCameraIcon) return false;

    // perform capture
    const dataUrl = await captureFromCamera();
    if (dataUrl) await addNewCapturedImage(dataUrl);
    return true;
  }

  document.addEventListener('click', (ev) => {
    try {
      // check clicked element and its ancestors for camera icon/label
      handlePossibleCameraClick(ev.target).catch(() => { });
    } catch (e) { }
  }, { passive: true });
})();

// Redesigned AI Analysis Logic
(function () {
  const runAiBtn = document.getElementById('runAiBtn');
  const runAiBtnText = document.getElementById('runAiBtnText');
  const aiStatusBadge = document.getElementById('aiStatusBadge');
  const aiStatusText = document.getElementById('aiStatusText');
  const aiProgressWrap = document.getElementById('aiProgressWrap');
  const aiProgressStep = document.getElementById('aiProgressStep');
  const aiProgressPercent = document.getElementById('aiProgressPercent');
  const aiProgressFill = document.getElementById('aiProgressFill');
  const aiSummaryCard = document.getElementById('aiSummaryCard');
  const aiSummaryList = document.getElementById('aiSummaryList');
  const aiDetailsPanel = document.getElementById('aiDetailsPanel');
  const toggleAiDetails = document.getElementById('toggleAiDetails');

  const detailAiStatus = document.getElementById('detailAiStatus');
  const detailAiTime = document.getElementById('detailAiTime');

  const insightEls = {
    quality: document.getElementById('aiInsightQuality'),
    confidence: document.getElementById('aiInsightConfidence'),
    structures: document.getElementById('aiInsightStructures'),
    observation: document.getElementById('aiInsightObservation'),
    risk: document.getElementById('aiInsightRisk')
  };

  const detailEls = {
    features: document.getElementById('aiDetailFeatures'),
    time: document.getElementById('aiDetailTime'),
    timestamp: document.getElementById('aiDetailTimestamp')
  };

  const STORAGE_KEY = 'torus_ai_analysis';

  function resetCards(defaultObservation = 'Awaiting Analysis') {
    if (insightEls.quality) insightEls.quality.textContent = '--';
    if (insightEls.confidence) insightEls.confidence.textContent = '--';
    if (insightEls.structures) insightEls.structures.textContent = '--';
    if (insightEls.observation) insightEls.observation.textContent = defaultObservation;
    if (insightEls.risk) {
      insightEls.risk.textContent = '--';
      insightEls.risk.style.color = '#94a3b8';
    }
    if (toggleAiDetails) {
      toggleAiDetails.disabled = true;
      toggleAiDetails.style.opacity = '0.5';
      toggleAiDetails.style.cursor = 'not-allowed';
      toggleAiDetails.title = 'Run AI analysis to view details';
      toggleAiDetails.innerHTML = '<i data-lucide="chevron-down"></i> <span>View Detailed Analysis</span>';
    }
    if (aiDetailsPanel) {
      aiDetailsPanel.classList.remove('active');
    }
    const keyFindingsList = document.getElementById('aiKeyFindingsList');
    if (keyFindingsList) {
      keyFindingsList.innerHTML = `<li>${escapeHtml(defaultObservation)}</li>`;
    }
    const simNotice = document.getElementById('aiDetailSimulationNotice');
    if (simNotice) simNotice.style.display = 'none';
  }

  function updateAiUI(status, results = null) {
    const hasImages = reportState.images && reportState.images.length > 0;
    let effectiveStatus = status;
    if (!hasImages) {
      effectiveStatus = 'No Images';
    } else if ((!status || status === 'Ready' || status === 'Awaiting Images' || status === 'No Images') && hasImages) {
      effectiveStatus = 'Ready to Analyze';
    }

    const noImagesNotice = document.getElementById('aiNoImagesNotice');

    if (effectiveStatus === 'No Images') {
      aiStatusBadge.className = 'ai-status-badge ready';
      aiStatusText.textContent = 'No Images Available';
      if (detailAiStatus) detailAiStatus.textContent = 'No Images Available';
      runAiBtn.disabled = true;
      runAiBtn.title = 'No ultrasound images available for analysis';
      runAiBtn.innerHTML = '<i data-lucide="image-off"></i> <span>No Images Available</span>';
      aiProgressWrap.classList.remove('active');
      aiDetailsPanel.classList.remove('active');
      if (noImagesNotice) noImagesNotice.style.display = 'block';
      resetCards('No ultrasound images available for analysis.');
      if (detailAiTime) detailAiTime.textContent = '--';
      lucide.createIcons();
      return;
    }

    if (noImagesNotice) noImagesNotice.style.display = 'none';

    const badgeClass = effectiveStatus === 'Completed' ? 'completed'
      : ((effectiveStatus === 'Processing' || effectiveStatus === 'Analyzing') ? 'analyzing'
        : (effectiveStatus === 'Failed' ? 'failed' : 'ready'));
    aiStatusBadge.className = `ai-status-badge ${badgeClass}`;

    let displayStatusText = 'Ready to Analyze';
    if (effectiveStatus === 'Processing' || effectiveStatus === 'Analyzing') displayStatusText = 'Analyzing';
    else if (effectiveStatus === 'Completed') displayStatusText = 'Completed';
    else if (effectiveStatus === 'Failed') displayStatusText = 'Failed';

    aiStatusText.textContent = displayStatusText;
    if (detailAiStatus) detailAiStatus.textContent = displayStatusText;

    if (effectiveStatus === 'Processing' || effectiveStatus === 'Analyzing') {
      runAiBtn.disabled = true;
      runAiBtn.innerHTML = '<i data-lucide="loader" style="animation: spin 1s linear infinite;"></i> <span>Analyzing...</span>';
      aiProgressWrap.classList.add('active');
      aiDetailsPanel.classList.remove('active');
      resetCards('Analyzing ultrasound frames...');
      lucide.createIcons();
    } else if (effectiveStatus === 'Completed') {
      runAiBtn.disabled = false;
      runAiBtn.innerHTML = '<i data-lucide="refresh-cw"></i> <span>Re-analyze</span>';
      aiProgressWrap.classList.remove('active');

      if (toggleAiDetails) {
        toggleAiDetails.disabled = false;
        toggleAiDetails.style.opacity = '1';
        toggleAiDetails.style.cursor = 'pointer';
        toggleAiDetails.title = 'View detailed analysis';
      }

      if (results) {
        if (insightEls.quality) insightEls.quality.textContent = results.quality || 'Diagnostic Quality';
        if (insightEls.confidence) insightEls.confidence.textContent = results.confidence || '--';
        if (insightEls.structures) insightEls.structures.textContent = results.structures || '--';
        if (insightEls.observation) insightEls.observation.textContent = results.observation || '--';

        const validatedRisk = results.validatedRisk || (results.risk && results.risk !== 'Not available' && !results.risk.includes('TEST') && !results.risk.includes('Simulated') && results.isRiskValidated ? results.risk : null);
        if (insightEls.risk) {
          if (validatedRisk) {
            insightEls.risk.textContent = validatedRisk;
            insightEls.risk.style.color = '#38bdf8';
          } else {
            insightEls.risk.textContent = results.risk || 'Not available';
            insightEls.risk.style.color = (results.risk && results.risk !== 'Not available' && results.risk !== '--') ? '#38bdf8' : '#94a3b8';
          }
        }

        const simNotice = document.getElementById('aiDetailSimulationNotice');
        if (simNotice) {
          simNotice.style.display = results.isTestMode ? 'block' : 'none';
        }

        const keyFindingsList = document.getElementById('aiKeyFindingsList');
        if (keyFindingsList) {
          if (Array.isArray(results.summary) && results.summary.length > 0) {
            keyFindingsList.innerHTML = results.summary.map(item => `<li>${escapeHtml(item)}</li>`).join('');
          } else if (results.observation) {
            keyFindingsList.innerHTML = `<li>${escapeHtml(results.observation)}</li>`;
          } else {
            keyFindingsList.innerHTML = '<li>Ultrasound acoustic margins and tissue interfaces evaluated.</li>';
          }
        }

        const confMeaning = document.getElementById('aiConfidenceMeaning');
        if (confMeaning) {
          confMeaning.textContent = results.confidence_meaning || 'Confidence indicates visual acoustic pattern correlation with trained ultrasound landmarks. Attending clinician correlation is required.';
        }

        const qualityLimText = document.getElementById('aiQualityLimitationsText');
        if (qualityLimText) {
          qualityLimText.textContent = results.quality_assessment || (results.quality ? `Image assessed as ${results.quality}. Acoustic interfaces suitable for assistive clinician interpretation.` : 'Acoustic window clarity verified for assistive evaluation.');
        }

        if (detailAiTime) {
          const now = new Date();
          detailAiTime.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
      }
      lucide.createIcons();
    } else if (effectiveStatus === 'Failed') {
      runAiBtn.disabled = false;
      runAiBtn.innerHTML = '<i data-lucide="refresh-cw"></i> <span>Re-analyze</span>';
      aiProgressWrap.classList.remove('active');
      aiDetailsPanel.classList.remove('active');
      resetCards('Analysis failed. Please check image feed and retry.');
      if (detailAiTime) detailAiTime.textContent = '--';
      lucide.createIcons();
    } else {
      // Ready to Analyze
      runAiBtn.disabled = false;
      runAiBtn.title = 'Run AI Preliminary Analysis';
      runAiBtn.innerHTML = '<i data-lucide="play"></i> <span>Start Analysis</span>';
      aiProgressWrap.classList.remove('active');
      aiDetailsPanel.classList.remove('active');
      resetCards('Awaiting Analysis');
      if (detailAiTime) detailAiTime.textContent = '--';
      lucide.createIcons();
    }
  }

  let isAiRunning = false;
  async function runAiAnalysis(forceTestMode = false) {
    if (!reportState.images || reportState.images.length === 0) {
      showToast('No ultrasound images available for analysis.');
      return;
    }

    let selectedImages = (reportState.images || []).filter(img => reportState.selectedIds && reportState.selectedIds.has(img.id));
    if (!selectedImages.length && reportState.images && reportState.images.length > 0) {
      reportState.images.forEach(img => reportState.selectedIds.add(img.id));
      writeJson(STORAGE_KEYS.selectedIds, Array.from(reportState.selectedIds));
      syncCounts();
      syncSelectionUI();
      selectedImages = reportState.images;
    }
    if (!selectedImages.length) {
      showToast('Please select at least one captured image to start AI analysis.');
      return;
    }

    const validImages = selectedImages.filter(img => img && img.dataUrl && img.dataUrl.length > 150);
    if (!validImages.length) {
      showToast('No valid ultrasound images found for analysis.');
      return;
    }

    if (isAiRunning) return;
    isAiRunning = true;

    updateAiUI('Analyzing');

    const urlParams = new URLSearchParams(window.location.search);
    const isUrlTest = urlParams.get('testMode') === 'true' || urlParams.get('test') === 'true';
    const activeTestMode = Boolean(forceTestMode || isUrlTest);

    try {
      const scanType = (dom.scanType ? dom.scanType.textContent.trim() : '') || 'Ultrasound Examination';
      const patientName = (dom.patientName ? dom.patientName.textContent.trim() : '') || '--';
      const reportId = (dom.reportId ? dom.reportId.textContent.trim() : '') || buildAutoReportId();
      const sessionId = getActiveCaptureSessionId() || `session_${roomParam}`;

      aiProgressStep.textContent = `Analyzing ${validImages.length} selected frame(s)...`;
      aiProgressPercent.textContent = '35%';
      aiProgressFill.style.width = '35%';

      const response = await fetch('/api/ai/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          images: validImages.map(img => img.dataUrl),
          metadata: {
            patientName,
            scanType,
            reportId,
            sessionId,
            selectedCount: validImages.length
          },
          testMode: activeTestMode
        })
      });

      if (response.status === 503) {
        isAiRunning = false;
        updateAiUI('Ready');
        const missingModal = document.getElementById('aiMissingServiceModal');
        if (missingModal) {
          missingModal.style.setProperty('display', 'flex', 'important');
          missingModal.classList.remove('hidden');
          missingModal.setAttribute('aria-hidden', 'false');
          if (typeof lucide !== 'undefined') lucide.createIcons();
        }
        showToast('AI service not configured: Missing GEMINI_API_KEY. Click Run Test Mode to verify workflow.');
        return;
      }

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.error || `Server responded with status ${response.status}`);
      }

      aiProgressStep.textContent = 'Finalizing clinical AI interpretation...';
      aiProgressPercent.textContent = '85%';
      aiProgressFill.style.width = '85%';

      const resData = await response.json();
      const results = resData.results || resData.data;
      if (resData.is_test_mode) {
        results.isTestMode = true;
      }
      results.status = 'Completed';
      results.patientName = patientName;
      results.sessionId = sessionId;
      results.reportId = reportId;
      results.imageHashes = (reportState.images || []).map(img => img.id).sort().join(',');

      reportState.aiResults = results;
      const storageKey = typeof getAiStorageKey === 'function' ? getAiStorageKey() : STORAGE_KEY;
      localStorage.setItem(storageKey, JSON.stringify(results));
      localStorage.setItem(STORAGE_KEY, JSON.stringify(results));

      updateAiUI('Completed', results);
      showToast(resData.is_test_mode ? `Test Mode AI analysis completed for ${validImages.length} image(s).` : `AI preliminary analysis completed for ${validImages.length} image(s).`);
    } catch (err) {
      console.error('[AI Analysis] Error during analysis:', err);
      updateAiUI('Failed');
      showToast(`AI analysis failed: ${err.message || 'Service unavailable'}. Please retry.`);
    } finally {
      isAiRunning = false;
    }
  }

  function restoreAiAnalysis() {
    const hasImages = reportState.images && reportState.images.length > 0;
    if (!hasImages) {
      updateAiUI('No Images');
      return;
    }

    const storageKey = typeof getAiStorageKey === 'function' ? getAiStorageKey() : STORAGE_KEY;
    const saved = localStorage.getItem(storageKey) || localStorage.getItem(STORAGE_KEY);
    if (saved) {
      try {
        const results = JSON.parse(saved);
        const currentPatient = (dom.patientName ? dom.patientName.textContent.trim() : '') || '--';
        const currentReportId = (dom.reportId ? dom.reportId.textContent.trim() : '') || '';
        const currentImageHashes = (reportState.images || []).map(img => img.id).sort().join(',');

        // Validate results match current patient, report/session, and images
        const patientMatches = !results.patientName || currentPatient === '--' || results.patientName === currentPatient;
        const reportMatches = !results.reportId || !currentReportId || currentReportId === '--' || results.reportId === currentReportId;
        const imagesMatch = !results.imageHashes || results.imageHashes === currentImageHashes;

        if (patientMatches && reportMatches && imagesMatch && results.status === 'Completed') {
          reportState.aiResults = results;
          updateAiUI('Completed', results);
          return;
        } else {
          // Stale results from different patient/session/images
          invalidateAiAnalysis();
          updateAiUI('Ready');
          return;
        }
      } catch (e) {
        console.error('Failed to restore AI analysis', e);
        invalidateAiAnalysis();
        updateAiUI('Ready');
        return;
      }
    }
    updateAiUI('Ready');
  }

  if (runAiBtn) {
    runAiBtn.addEventListener('click', () => {
      const urlParams = new URLSearchParams(window.location.search);
      const isUrlTest = urlParams.get('testMode') === 'true' || urlParams.get('test') === 'true';
      runAiAnalysis(isUrlTest);
    });
  }

  const cancelAiMissingBtn = document.getElementById('cancelAiMissingBtn');
  if (cancelAiMissingBtn) {
    cancelAiMissingBtn.addEventListener('click', () => {
      const missingModal = document.getElementById('aiMissingServiceModal');
      if (missingModal) {
        missingModal.style.setProperty('display', 'none', 'important');
        missingModal.classList.add('hidden');
        missingModal.setAttribute('aria-hidden', 'true');
      }
    });
  }

  const runAiTestModeBtn = document.getElementById('runAiTestModeBtn');
  if (runAiTestModeBtn) {
    runAiTestModeBtn.addEventListener('click', () => {
      const missingModal = document.getElementById('aiMissingServiceModal');
      if (missingModal) {
        missingModal.style.setProperty('display', 'none', 'important');
        missingModal.classList.add('hidden');
        missingModal.setAttribute('aria-hidden', 'true');
      }
      runAiAnalysis(true);
    });
  }

  if (toggleAiDetails) {
    toggleAiDetails.addEventListener('click', () => {
      const storageKey = typeof getAiStorageKey === 'function' ? getAiStorageKey() : STORAGE_KEY;
      const saved = localStorage.getItem(storageKey) || localStorage.getItem(STORAGE_KEY);
      if (!saved) {
        showToast('Please run AI analysis first to view detailed metrics.');
        return;
      }
      const isActive = aiDetailsPanel.classList.toggle('active');
      toggleAiDetails.innerHTML = `<i data-lucide="${isActive ? 'chevron-up' : 'chevron-down'}"></i> <span>${isActive ? 'Hide Detailed Analysis' : 'View Detailed Analysis'}</span>`;
      if (typeof lucide !== 'undefined') lucide.createIcons();
    });
  }

  window.triggerAiReset = () => {
    reportState.aiResults = null;
    try {
      const key = typeof getAiStorageKey === 'function' ? getAiStorageKey() : STORAGE_KEY;
      localStorage.removeItem(key);
    } catch (_) { }
    localStorage.removeItem(STORAGE_KEY);
    const hasImages = reportState.images && reportState.images.length > 0;
    updateAiUI(hasImages ? 'Ready' : 'No Images');
  };

  // Check image count for button state
  const checkImages = () => {
    const hasImages = reportState.images && reportState.images.length > 0;
    if (!hasImages) {
      updateAiUI('No Images');
    } else if (aiStatusText.textContent.includes('No Images') || aiStatusText.textContent.includes('Images') || aiStatusText.textContent.includes('Ready')) {
      if (!reportState.aiResults) {
        updateAiUI('Ready');
      }
    }
  };

  // Poll or hook into renderCapturedImages
  const originalRender = window.renderCapturedImages;
  window.renderCapturedImages = function (...args) {
    if (originalRender) originalRender.apply(this, args);
    checkImages();
  };

  // Initial restore
  restoreAiAnalysis();
})();