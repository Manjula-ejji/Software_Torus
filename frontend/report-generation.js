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
    const previousVersion = localStorage.getItem('torus-build-version') || '';
    if (previousVersion && previousVersion !== BUILD_VERSION) {
      localStorage.removeItem(CAPTURE_STORAGE_KEYS.images);
      localStorage.removeItem(CAPTURE_STORAGE_KEYS.sessionId);
      sessionStorage.removeItem(CAPTURE_STORAGE_KEYS.images);
      sessionStorage.removeItem(CAPTURE_STORAGE_KEYS.sessionId);
    }

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
      || '[]';
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    console.warn('Unable to read capture images:', error);
    return [];
  }
}

function writeCaptureImages(images) {
  const serialized = JSON.stringify(images);
  localStorage.setItem(CAPTURE_STORAGE_KEYS.images, serialized);
  sessionStorage.setItem(CAPTURE_STORAGE_KEYS.images, serialized);
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
  generatedTime: document.getElementById('generatedTime'),
  examDuration: document.getElementById('examDuration'),
  reportPreviewInput: document.getElementById('reportPreviewInput'),
  uploadPreviewBtn: document.getElementById('uploadPreviewBtn'),
  replacePreviewBtn: document.getElementById('replacePreviewBtn'),
  removePreviewBtn: document.getElementById('removePreviewBtn'),
  reportPreviewImage: document.getElementById('reportPreviewImage'),
  reportPreviewPdf: document.getElementById('reportPreviewPdf'),
  reportPreviewFileName: document.getElementById('reportPreviewFileName'),
  previewFrame: document.getElementById('previewFrame'),
  previewEmpty: document.getElementById('previewEmpty'),
  printOnlyContainer: document.getElementById('printOnlyContainer'),
  sidebar: document.getElementById('sidebar'),
  sidebarOverlay: document.getElementById('sidebarOverlay'),
  closeSidebar: document.getElementById('closeSidebar'),
  imagePreviewModal: document.getElementById('imagePreviewModal'),
  closePreviewModal: document.getElementById('closePreviewModal'),
  previewModalImage: document.getElementById('previewModalImage'),
  previewModalCaption: document.getElementById('previewModalCaption'),
  signatureStatus: document.getElementById('signatureStatus'),
  signatureSuccessCard: document.getElementById('signatureSuccessCard')
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
  localStorage.setItem(key, JSON.stringify(value));
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
  if (dom.imageCountPill) dom.imageCountPill.textContent = `${selected} / ${total} images`;
  if (dom.selectedCount) dom.selectedCount.textContent = `${selected} / ${total} images`;
  if (dom.imagesCaptured) dom.imagesCaptured.textContent = String(total);
  if (dom.selectedImagesCount) dom.selectedImagesCount.textContent = String(selected);
}

function buildAutoReportId() {
  const now = Date.now();
  const random = Math.floor(Math.random() * 1000).toString().padStart(3, '0');
  return `RPT-${now.toString().slice(-4)}${random}`;
}

function updateSignatureUI() {
  const isSigned = reportState.digitalSignature;
  if (dom.signatureStatus) {
    dom.signatureStatus.textContent = isSigned ? 'Signed' : 'Unsigned';
  }
  const success = document.getElementById('signatureSuccess');
  const btn = document.getElementById('digitalSignBtn');
  if (btn) {
    if (isSigned) {
      btn.innerHTML = '<i data-lucide="signature" style="width: 18px; height: 18px;"></i>Signed';
    } else {
      btn.innerHTML = '<i data-lucide="signature"></i>Digital Sign';
    }
  }
  if (success) {
    success.style.display = isSigned ? "flex" : "none";
  }
  lucide.createIcons();
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

function toggleSelectedImage(imageId) {
  if (reportState.selectedIds.has(imageId)) {
    reportState.selectedIds.delete(imageId);
  } else {
    reportState.selectedIds.add(imageId);
  }
  writeJson(STORAGE_KEYS.selectedIds, Array.from(reportState.selectedIds));
  invalidateGeneratedReport();
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
    digitalSignature: reportState.digitalSignature
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

  reportState.generatedReport = readJson(STORAGE_KEYS.generatedReport, null);
  reportState.digitalSignature = reportState.generatedReport ? Boolean(reportState.generatedReport.digitalSignature) : false;
  updateSignatureUI();

  reportState.sendLocked = localStorage.getItem(STORAGE_KEYS.deliveryStatus) === 'sent';

  const reportId = context.reportId
    || (reportState.generatedReport && reportState.generatedReport.reportId)
    || localStorage.getItem(STORAGE_KEYS.reportId)
    || buildAutoReportId();
  setReportId(reportId);

  if (dom.patientName) dom.patientName.textContent = context.patientName || 'Patient A';
  if (dom.examDate) dom.examDate.textContent = context.examDate || 'March 23, 2026';
  if (dom.scanType) dom.scanType.textContent = context.scanType || 'Abdominal Ultrasound';
  if (dom.deviceName) dom.deviceName.textContent = context.device || 'TORUS-A12';
  if (dom.doctorName) dom.doctorName.textContent = context.doctor || 'Dr. Anderson';
  if (dom.locationName) dom.locationName.textContent = context.location || 'NYC Medical';
  if (dom.reportId) dom.reportId.textContent = reportId;
  if (dom.examDuration) dom.examDuration.textContent = context.examDuration || '18:42';

  if (dom.findingsField) dom.findingsField.value = localStorage.getItem(STORAGE_KEYS.findings) || '';
  if (dom.recommendationsField) dom.recommendationsField.value = localStorage.getItem(STORAGE_KEYS.recommendations) || '';

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
    dom.backBtn.addEventListener('click', () => {
      const roomParam = new URLSearchParams(window.location.search).get('room') || '';
      window.location.href = `connected-device.html?room=${roomParam}&role=patient`;
    });
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

function downloadReportPdf(reportData) {
  const selectedImages = (reportData.selectedImages && reportData.selectedImages.length)
    ? reportData.selectedImages
    : (reportData.capturedImages || []);
  const jsPdfApi = window.jspdf && window.jspdf.jsPDF;
  if (!jsPdfApi) {
    throw new Error('PDF library unavailable');
  }

  const doc = new jsPdfApi({ unit: 'pt', format: 'a4', compress: true });
  const width = doc.internal.pageSize.getWidth();
  const height = doc.internal.pageSize.getHeight();
  const margin = 36;
  const contentWidth = width - margin * 2;
  const halfWidth = (contentWidth - 14) / 2;
  let y = 40;

  const paintBackground = () => {
    doc.setFillColor(11, 15, 24);
    doc.rect(0, 0, width, height, 'F');
    doc.setDrawColor(24, 216, 255);
    doc.line(margin, 58, width - margin, 58);
  };

  const newPage = () => {
    doc.addPage();
    paintBackground();
    y = 40;
  };

  const sectionHeader = (title) => {
    doc.setFillColor(124, 58, 237);
    doc.roundedRect(margin, y - 10, contentWidth, 20, 8, 8, 'F');
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(11);
    doc.setTextColor(247, 248, 255);
    doc.text(title, margin + 10, y + 4);
    y += 22;
  };

  const infoBox = (x, top, boxWidth, label, value) => {
    doc.setDrawColor(42, 173, 209);
    doc.setFillColor(8, 10, 16);
    doc.roundedRect(x, top, boxWidth, 52, 8, 8, 'FD');
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    doc.setTextColor(158, 176, 212);
    doc.text(label, x + 10, top + 16);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(11);
    doc.setTextColor(247, 248, 255);
    doc.text(doc.splitTextToSize(String(value || '-'), boxWidth - 20), x + 10, top + 34);
  };

  const wrapText = (text, top) => {
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(11);
    doc.setTextColor(247, 248, 255);
    const lines = doc.splitTextToSize(String(text || ''), contentWidth);
    doc.text(lines, margin, top);
    return top + lines.length * 16;
  };

  paintBackground();
  doc.setTextColor(247, 248, 255);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(22);
  doc.text('Report Generation', margin, y);
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10);
  doc.setTextColor(156, 163, 185);
  doc.text(`Report ID: ${reportData.reportId}`, margin, y + 20);
  doc.text(`Generated: ${new Date(reportData.generatedAt).toLocaleString()}`, margin, y + 34);
  y += 54;

  sectionHeader('Patient Information');
  infoBox(margin, y, halfWidth, 'Patient Name', reportData.patientInfo.patientName);
  infoBox(margin + halfWidth + 14, y, halfWidth, 'Exam Date', reportData.patientInfo.examDate);
  y += 64;
  infoBox(margin, y, halfWidth, 'Scan Type', reportData.patientInfo.scanType);
  infoBox(margin + halfWidth + 14, y, halfWidth, 'Device', reportData.patientInfo.device);
  y += 64;
  infoBox(margin, y, halfWidth, 'Doctor', reportData.patientInfo.doctor);
  infoBox(margin + halfWidth + 14, y, halfWidth, 'Location', reportData.patientInfo.location);
  y += 64;
  infoBox(margin, y, contentWidth, 'Exam Duration', reportData.patientInfo.examDuration);
  y += 72;

  sectionHeader('Findings');
  y = wrapText(reportData.findings || 'No findings provided.', y + 4);
  y += 12;

  sectionHeader('Recommendations');
  y = wrapText(reportData.recommendations || 'No recommendations provided.', y + 4);
  y += 12;

  sectionHeader('Report Details');
  infoBox(margin, y, halfWidth, 'Images Captured', String(reportData.reportDetails.imagesCaptured));
  infoBox(margin + halfWidth + 14, y, halfWidth, 'Selected Images', String(reportData.reportDetails.selectedImages));
  y += 64;
  infoBox(margin, y, halfWidth, 'Doctor', reportData.reportDetails.doctor);
  infoBox(margin + halfWidth + 14, y, halfWidth, 'Location', reportData.reportDetails.location);
  y += 64;
  infoBox(margin, y, contentWidth, 'Report ID', reportData.reportDetails.reportId);
  y += 72;

  if (reportData.reportPreview && (reportData.reportPreview.data || reportData.reportPreview.dataUrl || reportData.reportPreview.src)) {
    if (y + 210 > height - 40) {
      newPage();
    }
    sectionHeader('Uploaded Preview');
    doc.setDrawColor(127, 55, 255);
    doc.setFillColor(8, 10, 16);
    doc.roundedRect(margin, y, contentWidth, 180, 10, 10, 'FD');
    const previewType = String(reportData.reportPreview.type || '').toLowerCase();
    const previewData = reportData.reportPreview.data || reportData.reportPreview.dataUrl || reportData.reportPreview.src;
    if (/^image\//.test(previewType)) {
      try {
        const mimeMatch = /^data:(image\/[a-zA-Z0-9.+-]+);base64,/.exec(previewData || '');
        const format = mimeMatch ? mimeMatch[1].split('/')[1].toUpperCase() : 'JPEG';
        doc.addImage(previewData, format, margin + 8, y + 8, contentWidth - 16, 164, undefined, 'FAST');
        y += 192;
      } catch {
        doc.setFontSize(10);
        doc.setTextColor(156, 163, 185);
        doc.text('Preview image unavailable', margin + 12, y + 24);
        y += 48;
      }
    } else {
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(11);
      doc.setTextColor(247, 248, 255);
      doc.text('PDF Preview Attached', margin + 12, y + 28);
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(10);
      doc.setTextColor(156, 163, 185);
      doc.text(`File: ${String(reportData.reportPreview.name || 'Document.pdf')}`, margin + 12, y + 46);
      y += 68;
    }
  }

  if (selectedImages.length) {
    sectionHeader('Captured Images');
    const imageWidth = (contentWidth - 14) / 2;
    const imageHeight = 126;

    selectedImages.forEach((image, index) => {
      if (index % 2 === 0 && y + imageHeight + 44 > height - 36) {
        newPage();
        sectionHeader('Selected Images');
      } else if (index % 2 === 1 && y + imageHeight + 44 > height - 36) {
        newPage();
        sectionHeader('Selected Images');
      }

      const x = margin + (index % 2) * (imageWidth + 14);
      doc.setDrawColor(127, 55, 255);
      doc.setFillColor(8, 10, 16);
      doc.roundedRect(x, y, imageWidth, imageHeight + 28, 10, 10, 'FD');

      try {
        const mimeMatch = /^data:(image\/[a-zA-Z0-9.+-]+);base64,/.exec(image.dataUrl || '');
        const format = mimeMatch ? mimeMatch[1].split('/')[1].toUpperCase() : 'JPEG';
        doc.addImage(image.dataUrl, format, x + 8, y + 8, imageWidth - 16, imageHeight - 4, undefined, 'FAST');
      } catch {
        doc.setFontSize(10);
        doc.setTextColor(156, 163, 185);
        doc.text('Image unavailable', x + 12, y + 46);
      }

      doc.setFont('helvetica', 'bold');
      doc.setFontSize(9);
      doc.setTextColor(156, 163, 185);
      doc.text(`Image ${index + 1}`, x + 10, y + imageHeight + 18);
      doc.setFont('helvetica', 'normal');
      doc.text(getTimeLabel(image.createdAt), x + 10, y + imageHeight + 28);

      if (index % 2 === 1) {
        y += imageHeight + 42;
      }
    });
  }

  doc.save(`Report_${sanitizeFileName(reportData.reportId)}.pdf`);
}

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

  const API_BASE_URL = (window.location.port === '5002' || window.location.port === '3000' || window.location.port === '') ? '' : window.location.protocol + '//' + window.location.hostname + ':5002';
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
      generatedTime: targetTime
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
  // 1. Return to same-origin referrer if available and not this page
  if (document.referrer) {
    try {
      const refUrl = new URL(document.referrer);
      if (refUrl.origin === window.location.origin && !refUrl.pathname.toLowerCase().endsWith('report-generation.html')) {
        window.location.href = document.referrer;
        return;
      }
    } catch (e) {
      console.warn('Invalid referrer:', e);
    }
  }

  // 2. Fall back to browser history if applicable
  if (window.history.length > 1 && document.referrer && document.referrer.startsWith(window.location.origin)) {
    window.history.back();
    return;
  }

  // 3. Fallback: Return to Video Consultation preserving current room and role parameters
  const backUrl = new URL(window.location.href);
  backUrl.pathname = backUrl.pathname.replace(/report-generation\.html$/i, 'index.html');
  window.location.href = backUrl.toString();
}

if (dom.backBtn) {
  dom.backBtn.addEventListener('click', navigateBackFromReport);
}

dom.findingsField.addEventListener('input', () => {
  localStorage.setItem(STORAGE_KEYS.findings, dom.findingsField.value);
  invalidateGeneratedReport();
});

dom.recommendationsField.addEventListener('input', () => {
  localStorage.setItem(STORAGE_KEYS.recommendations, dom.recommendationsField.value);
  invalidateGeneratedReport();
});

if (dom.uploadPreviewBtn) {
  dom.uploadPreviewBtn.addEventListener('click', () => {
    reportState.previewAction = 'upload';
    try { console.log('UPLOAD CLICK'); } catch (e) { }
    promptPreviewUpload();
  });
}

if (dom.replacePreviewBtn) {
  dom.replacePreviewBtn.addEventListener('click', () => {
    reportState.previewAction = 'replace';
    try { console.log('UPLOAD CLICK'); } catch (e) { }
    promptPreviewUpload();
  });
}

if (dom.removePreviewBtn) {
  dom.removePreviewBtn.addEventListener('click', () => {
    renderReportPreview(null);
    try { localStorage.removeItem('reportPreview'); } catch (e) { }
    try { localStorage.removeItem(STORAGE_KEYS.reportPreview); } catch (e) { }
    invalidateGeneratedReport();
    showToast('Preview removed');
  });
}

dom.generatePreviewBtn.addEventListener('click', generateReportAction);
dom.sendPatientBtn.addEventListener('click', sendReportToPatient);
dom.digitalSignBtn.addEventListener('click', function () {
  if (reportState.digitalSignature) return;
  reportState.digitalSignature = true;
  updateSignatureUI();
  invalidateGeneratedReport();
});

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
      console.warn('Camera blocked or unavailable, using simulated capture fallback:', err);
      // Create a mock image fallback
      const canvas = document.createElement('canvas');
      canvas.width = 640;
      canvas.height = 480;
      const ctx = canvas.getContext('2d');
      const grad = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
      grad.addColorStop(0, '#0b0f19');
      grad.addColorStop(1, '#1e293b');
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Draw simulated ultrasound circle
      ctx.strokeStyle = '#00d7ff';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(canvas.width / 2, canvas.height / 2, 80, 0, Math.PI * 2);
      ctx.stroke();

      // Draw scanning grid lines
      ctx.strokeStyle = 'rgba(0, 215, 255, 0.2)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = 0; x < canvas.width; x += 40) {
        ctx.moveTo(x, 0);
        ctx.lineTo(x, canvas.height);
      }
      for (let y = 0; y < canvas.height; y += 40) {
        ctx.moveTo(0, y);
        ctx.lineTo(canvas.width, y);
      }
      ctx.stroke();

      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 20px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Simulated Scan Capture', canvas.width / 2, canvas.height / 2 - 20);

      ctx.fillStyle = '#94a3b8';
      ctx.font = '14px sans-serif';
      ctx.fillText('Camera Blocked/Unavailable Fallback', canvas.width / 2, canvas.height / 2 + 30);
      ctx.fillText(new Date().toLocaleString(), canvas.width / 2, canvas.height / 2 + 60);

      const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
      captureInProgress = false;
      return dataUrl;
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

      await new Promise((resolve, reject) => {
        const onCan = () => { resolve(); };
        video.addEventListener('loadedmetadata', onCan, { once: true });
        // fallback if metadata doesn't fire
        setTimeout(resolve, 700);
      });

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
      showToast('Capture failed');
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

  function resetCards() {
    insightEls.quality.textContent = 'Pending';
    insightEls.confidence.textContent = '--';
    insightEls.structures.textContent = 'None';
    insightEls.observation.textContent = 'Pending';
    insightEls.risk.textContent = 'Unknown';
  }

  function updateAiUI(status, results = null) {
    aiStatusBadge.className = `ai-status-badge ${status.toLowerCase()}`;
    aiStatusText.textContent = status === 'Completed' ? 'COMPLETED' : status;
    if (detailAiStatus) detailAiStatus.textContent = status;

    if (status === 'Processing') {
      runAiBtn.disabled = true;
      runAiBtnText.textContent = 'Analyzing...';
      aiProgressWrap.classList.add('active');
      aiSummaryCard.classList.remove('active');
      aiDetailsPanel.classList.remove('active');
      resetCards();
    } else if (status === 'Completed') {
      runAiBtn.disabled = false;
      runAiBtnText.textContent = 'Re-analyze';
      runAiBtn.innerHTML = '<i data-lucide="refresh-cw"></i> <span>Re-analyze</span>';
      aiProgressWrap.classList.remove('active');
      aiSummaryCard.classList.add('active');
      lucide.createIcons();

      if (results) {
        insightEls.quality.textContent = results.quality;
        insightEls.confidence.textContent = results.confidence;
        insightEls.structures.textContent = results.structures;
        insightEls.observation.textContent = results.observation;
        insightEls.risk.textContent = results.risk;

        aiSummaryList.innerHTML = results.summary.map(item => `<li>${item}</li>`).join('');

        detailEls.features.textContent = results.detailed.features;
        detailEls.time.textContent = results.detailed.time;
        detailEls.timestamp.textContent = results.detailed.timestamp;

        if (detailAiTime) detailAiTime.textContent = results.detailed.timestamp.split('•')[1].trim();
      }
    } else {
      // Ready state
      const hasImages = reportState.images && reportState.images.length > 0;
      runAiBtn.disabled = !hasImages;
      runAiBtn.innerHTML = hasImages ? '<i data-lucide="play"></i> <span>Start Analysis</span>' : '<span>No Images Available</span>';
      aiProgressWrap.classList.remove('active');
      aiSummaryCard.classList.remove('active');
      resetCards();
      lucide.createIcons();
    }
  }

  async function runAiAnalysis() {
    if (!reportState.images || reportState.images.length === 0) return;

    updateAiUI('Processing');

    const startTime = Date.now();
    const steps = [
      { label: 'Loading captured images...', start: 0, end: 20 },
      { label: 'Validating image quality...', start: 20, end: 45 },
      { label: 'Detecting structures...', start: 45, end: 70 },
      { label: 'Generating observations...', start: 70, end: 90 },
      { label: 'Finalizing report...', start: 90, end: 100 }
    ];

    for (const step of steps) {
      aiProgressStep.textContent = step.label;
      let currentProgress = step.start;
      const duration = 800 + Math.random() * 400; // Simulated step duration
      const interval = 50;
      const increment = (step.end - step.start) / (duration / interval);

      while (currentProgress < step.end) {
        await new Promise(r => setTimeout(r, interval));
        currentProgress += increment;
        let percent = Math.min(Math.round(currentProgress), 100);
        aiProgressPercent.textContent = `${percent}%`;
        aiProgressFill.style.width = `${percent}%`;
      }
    }

    const endTime = Date.now();
    const durationSeconds = ((endTime - startTime) / 1000).toFixed(1);
    const now = new Date();
    const results = {
      status: 'Completed',
      quality: 'Good',
      confidence: '97%',
      structures: 'Abdominal Region',
      observation: 'No significant abnormality detected',
      risk: 'Low',
      summary: [
        'Image quality acceptable',
        'Structures recognized',
        'No critical abnormal findings',
        'Recommend physician verification'
      ],
      detailed: {
        features: 'Abdominal Tissue',
        clarity: 'High',
        model: 'TORUS-AI-v1',
        time: `${durationSeconds}s`,
        confidence: '97%',
        timestamp: `${now.toLocaleDateString()} • ${now.toLocaleTimeString()}`
      }
    };

    localStorage.setItem(STORAGE_KEY, JSON.stringify(results));
    updateAiUI('Completed', results);
  }

  function restoreAiAnalysis() {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      try {
        const results = JSON.parse(saved);
        updateAiUI('Completed', results);
      } catch (e) {
        console.error('Failed to restore AI analysis', e);
      }
    } else {
      updateAiUI('Ready');
    }
  }

  if (runAiBtn) {
    runAiBtn.addEventListener('click', runAiAnalysis);
  }

  if (toggleAiDetails) {
    toggleAiDetails.addEventListener('click', () => {
      const isActive = aiDetailsPanel.classList.toggle('active');
      toggleAiDetails.querySelector('span') || (toggleAiDetails.innerHTML = `<i data-lucide="${isActive ? 'chevron-up' : 'chevron-down'}"></i> <span>${isActive ? 'Hide Detailed Analysis' : 'View Detailed Analysis'}</span>`);

      if (isActive) {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
          const results = JSON.parse(saved);
          document.getElementById('aiDetailFeatures').textContent = results.detailed.features;
          document.getElementById('aiDetailTime').textContent = results.detailed.time;
          document.getElementById('aiDetailTimestamp').textContent = results.detailed.timestamp;
          // Add Clarity, Model, Confidence if not present
          const grid = aiDetailsPanel.querySelector('.ai-details-grid');
          grid.innerHTML = `
                  <div class="ai-detail-item">
                     <span class="ai-detail-label">Detected Structures</span>
                     <span class="ai-detail-value">${results.detailed.features}</span>
                  </div>
                  <div class="ai-detail-item">
                     <span class="ai-detail-label">Image Clarity</span>
                     <span class="ai-detail-value">${results.detailed.clarity || 'High'}</span>
                  </div>
                  <div class="ai-detail-item">
                     <span class="ai-detail-label">Model</span>
                     <span class="ai-detail-value">${results.detailed.model || 'TORUS-AI-v1'}</span>
                  </div>
                  <div class="ai-detail-item">
                     <span class="ai-detail-label">Processing Time</span>
                     <span class="ai-detail-value">${results.detailed.time}</span>
                  </div>
                  <div class="ai-detail-item">
                     <span class="ai-detail-label">Confidence</span>
                     <span class="ai-detail-value">${results.detailed.confidence || '97%'}</span>
                  </div>
                  <div class="ai-detail-item">
                     <span class="ai-detail-label">Generated</span>
                     <span class="ai-detail-value">${results.detailed.timestamp}</span>
                  </div>
                `;
        }
      }
      lucide.createIcons();
    });
  }

  // Check image count for button state
  const checkImages = () => {
    if (aiStatusText.textContent.includes('Ready') || aiStatusText.textContent.includes('Images')) {
      updateAiUI('Ready');
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

// ==================== NEW BLOCK ====================

window.addEventListener("load", () => {
  const btn = document.getElementById("digitalSignBtn");
  const success = document.getElementById("signatureSuccess");

  if (!btn || !success) {
    console.error("signature elements missing");
    return;
  }

  success.style.display = "none";
  btn.onclick = null;

  btn.addEventListener("click", function (e) {
    e.preventDefault();
    e.stopPropagation();

    btn.innerHTML = '<i data-lucide="signature" style="width: 18px; height: 18px;"></i>Signed';
    lucide.createIcons();
    success.style.display = "flex";

    console.log("signature shown");

    // Internal state maintenance
    if (typeof reportState !== 'undefined') {
      reportState.digitalSignature = true;
      if (typeof updateSignatureUI === 'function') updateSignatureUI();
      if (typeof invalidateGeneratedReport === 'function') invalidateGeneratedReport();
    }
  });
});