/**
 * CloudBox Frontend Client
 * Fully async integration with FastAPI backend:
 * - JWT authentication & session management
 * - Direct-to-S3 Presigned URL upload with SHA-256 client hashing & live progress
 * - Dynamic folder tree and breadcrumb navigation
 * - Version history inspection & rollback downloads
 * - Public share token generation & token-based access
 */

const API_BASE = '/api/v1';

// Automatically clean up trailing '?' from earlier form submissions without reloading
if (window.location.search === '?' || (window.location.search && !window.location.search.includes('share='))) {
  window.history.replaceState({}, document.title, window.location.pathname);
}

const state = {
  token: localStorage.getItem('cloudbox_jwt') || null,
  user: null,
  currentFolderId: null,
  breadcrumbs: [{ id: null, name: 'Home' }],
  folders: [],
  files: [],
  expandedFolderIds: new Set(),
  folderTreeData: null,
  navToken: 0,
  sessionShareLinks: {},

  // Drive Filters & Sorting
  filesSearch: '',
  filesType: '',
  filesSortBy: 'created_at',
  filesOrder: 'desc',

  // Shares Filters & Sorting
  sharesSearch: '',
  sharesStatus: '',
  sharesType: '',
  sharesPermission: '',
  sharesSortBy: 'created_at',
  sharesOrder: 'desc',

  // Trash Filters & Sorting
  trashSearch: '',
  trashType: '',
  trashSortBy: 'deleted_at',
  trashOrder: 'desc',

  // Admin Filters & Sorting
  adminSearch: '',
  adminStatus: '',
  adminRole: '',
  adminSortBy: 'created_at',
  adminOrder: 'desc',
};

// --- DOM Elements ---
const el = {
  authView: document.getElementById('auth-view'),
  dashboardView: document.getElementById('dashboard-view'),
  publicShareView: document.getElementById('public-share-view'),
  toastContainer: document.getElementById('toast-container'),

  // Auth
  tabLogin: document.getElementById('tab-login'),
  tabSignup: document.getElementById('tab-signup'),
  authTabHeader: document.getElementById('auth-tab-header'),
  loginForm: document.getElementById('login-form'),
  signupForm: document.getElementById('signup-form'),
  forgotPasswordForm: document.getElementById('forgot-password-form'),
  linkForgotPassword: document.getElementById('link-forgot-password'),
  linkBackToLogin: document.getElementById('link-back-to-login'),
  loginEmail: document.getElementById('login-email'),
  loginPassword: document.getElementById('login-password'),
  signupName: document.getElementById('signup-name'),
  signupEmail: document.getElementById('signup-email'),
  signupPassword: document.getElementById('signup-password'),
  resetEmail: document.getElementById('reset-email'),
  resetNewPassword: document.getElementById('reset-new-password'),
  resetConfirmPassword: document.getElementById('reset-confirm-password'),
  resetOtp: document.getElementById('reset-otp'),
  btnSendOtp: document.getElementById('btn-send-otp'),
  otpTimerInfo: document.getElementById('otp-timer-info'),
  otpCountdown: document.getElementById('otp-countdown'),
  btnSubmitResetPassword: document.getElementById('btn-submit-reset-password'),
  userEmailDisplay: document.getElementById('user-email-display'),
  btnDeleteAccount: document.getElementById('btn-delete-account'),
  btnMobileDeleteAccount: document.getElementById('btn-mobile-delete-account'),
  logoutBtn: document.getElementById('logout-btn'),

  // Quota
  quotaUsedText: document.getElementById('quota-used-text'),
  quotaTotalText: document.getElementById('quota-total-text'),
  quotaBarFill: document.getElementById('quota-bar-fill'),

  // Navigation
  fileInput: document.getElementById('file-input'),
  sidebarUploadBtn: document.getElementById('sidebar-upload-trigger-btn'),
  sidebarFolderTree: document.getElementById('sidebar-folder-tree'),
  mobileMenuBtn: document.getElementById('mobile-menu-btn'),
  sidebarBackdrop: document.getElementById('sidebar-backdrop'),
  dashboardSidebar: document.getElementById('dashboard-sidebar'),
  sidebarCloseBtn: document.getElementById('sidebar-close-btn'),
  mobileUserEmail: document.getElementById('mobile-user-email'),
  mobileAdminBadge: document.getElementById('mobile-admin-badge'),
  mobileQuotaText: document.getElementById('mobile-quota-text'),
  mobileQuotaBarFill: document.getElementById('mobile-quota-bar-fill'),
  breadcrumbs: document.getElementById('breadcrumbs'),
  foldersContainer: document.getElementById('folders-container'),
  filesTbody: document.getElementById('files-tbody'),
  emptyFolderState: document.getElementById('empty-folder-state'),
  refreshBtn: document.getElementById('refresh-btn'),
  newFolderModalBtn: document.getElementById('new-folder-modal-btn'),
  btnTrashContents: document.getElementById('btn-trash-contents'),
  btnRenameCurrentFolder: document.getElementById('btn-rename-current-folder'),
  btnMoveCurrentFolder: document.getElementById('btn-move-current-folder'),
  btnDeleteCurrentFolder: document.getElementById('btn-delete-current-folder'),
  quickNewFolderBtn: document.getElementById('btn-quick-new-folder'),
  navAllFiles: document.getElementById('nav-all-files'),
  navSharesManager: document.getElementById('nav-shares-manager'),
  navTrashManager: document.getElementById('nav-trash-manager'),
  fileManagerSection: document.getElementById('file-manager-section'),
  sharesManagerSection: document.getElementById('shares-manager-section'),
  trashManagerSection: document.getElementById('trash-manager-section'),
  sharesTbody: document.getElementById('shares-tbody'),
  emptySharesState: document.getElementById('empty-shares-state'),
  refreshSharesBtn: document.getElementById('refresh-shares-btn'),
  trashTbody: document.getElementById('trash-tbody'),
  emptyTrashState: document.getElementById('empty-trash-state'),
  btnRestoreAllTrash: document.getElementById('btn-restore-all-trash'),
  btnEmptyTrash: document.getElementById('btn-empty-trash'),
  btnPurgeTrash: document.getElementById('btn-purge-trash'),
  trashRefreshBtn: document.getElementById('trash-refresh-btn'),

  // Drive Filters & Sort Controls
  filesSearchInput: document.getElementById('files-search-input'),
  filesSearchClear: document.getElementById('files-search-clear'),
  filesTypeFilter: document.getElementById('files-type-filter'),
  filesSortSelect: document.getElementById('files-sort-select'),

  // Shares Filters & Sort Controls
  sharesSearchInput: document.getElementById('shares-search-input'),
  sharesSearchClear: document.getElementById('shares-search-clear'),
  sharesStatusFilter: document.getElementById('shares-status-filter'),
  sharesTypeFilter: document.getElementById('shares-type-filter'),
  sharesPermissionFilter: document.getElementById('shares-permission-filter'),
  sharesSortSelect: document.getElementById('shares-sort-select'),

  // Trash Filters & Sort Controls
  trashSearchInput: document.getElementById('trash-search-input'),
  trashSearchClear: document.getElementById('trash-search-clear'),
  trashTypeFilter: document.getElementById('trash-type-filter'),
  trashSortSelect: document.getElementById('trash-sort-select'),

  // Admin Dashboard
  adminBadge: document.getElementById('admin-badge'),
  navAdminDashboard: document.getElementById('nav-admin-dashboard'),
  adminManagerSection: document.getElementById('admin-manager-section'),
  btnRefreshAdmin: document.getElementById('btn-refresh-admin'),
  btnAdminReclaimAll: document.getElementById('btn-admin-reclaim-all'),
  statTotalUsers: document.getElementById('stat-total-users'),
  statActiveUsers: document.getElementById('stat-active-users'),
  statStorageUsed: document.getElementById('stat-storage-used'),
  statStorageQuota: document.getElementById('stat-storage-quota'),
  statS3FreeTierPercent: document.getElementById('stat-s3-free-tier-percent'),
  statTotalFiles: document.getElementById('stat-total-files'),
  statTotalBlobs: document.getElementById('stat-total-blobs'),
  statTotalShares: document.getElementById('stat-total-shares'),
  adminSearchInput: document.getElementById('admin-search-input'),
  adminSearchClear: document.getElementById('admin-search-clear'),
  adminStatusFilter: document.getElementById('admin-status-filter'),
  adminRoleFilter: document.getElementById('admin-role-filter'),
  adminSortSelect: document.getElementById('admin-sort-select'),
  adminUsersTbody: document.getElementById('admin-users-tbody'),
  adminUsersEmpty: document.getElementById('admin-users-empty'),
  modalEditQuota: document.getElementById('modal-edit-quota'),
  editQuotaUserEmail: document.getElementById('edit-quota-user-email'),
  editQuotaUserId: document.getElementById('edit-quota-user-id'),
  formEditQuota: document.getElementById('form-edit-quota'),
  customQuotaMbInput: document.getElementById('custom-quota-mb-input'),

  // Progress Bar
  uploadProgressContainer: document.getElementById('upload-progress-container'),
  uploadFilename: document.getElementById('upload-filename'),
  uploadPercent: document.getElementById('upload-percent'),
  uploadProgressFill: document.getElementById('upload-progress-fill'),

  // Modals
  modalNewFolder: document.getElementById('modal-new-folder'),
  formNewFolder: document.getElementById('form-new-folder'),
  folderNameInput: document.getElementById('folder-name-input'),

  modalShare: document.getElementById('modal-share'),
  formShare: document.getElementById('form-share'),
  shareModalItemName: document.getElementById('share-modal-item-name'),
  shareTargetId: document.getElementById('share-target-id'),
  shareTargetType: document.getElementById('share-target-type'),
  sharePermission: document.getElementById('share-permission'),
  shareExpiryPreset: document.getElementById('share-expiry-preset'),
  shareCustomExpiryGroup: document.getElementById('share-custom-expiry-group'),
  shareCustomExpiry: document.getElementById('share-custom-expiry'),
  shareResultContainer: document.getElementById('share-result-container'),
  shareLinkOutput: document.getElementById('share-link-output'),
  copyShareBtn: document.getElementById('copy-share-btn'),

  // Public Share
  publicShareLoading: document.getElementById('public-share-loading'),
  publicShareContent: document.getElementById('public-share-content'),
  publicShareAuthor: document.getElementById('public-share-author'),
  publicShareAuthorText: document.getElementById('public-share-author-text'),
  publicSharePermBadge: document.getElementById('public-share-perm-badge'),
  publicShareName: document.getElementById('public-share-name'),
  publicShareMeta: document.getElementById('public-share-meta'),
  publicShareIcon: document.getElementById('public-share-icon'),
  publicShareThumb: document.getElementById('public-share-thumb'),
  publicShareActions: document.getElementById('public-share-actions'),
  publicDownloadBtn: document.getElementById('public-download-btn'),
  backToLoginBtn: document.getElementById('back-to-login-btn'),
  publicPreviewContainer: document.getElementById('public-preview-container'),
  publicPreviewTopbar: document.getElementById('public-preview-topbar'),
  previewActiveName: document.getElementById('preview-active-name'),
  btnClosePublicPreview: document.getElementById('btn-close-public-preview'),
  previewCodeBox: document.getElementById('preview-code-box'),
  codeViewerLangIcon: document.getElementById('code-viewer-lang-icon'),
  codeViewerFilename: document.getElementById('code-viewer-filename'),
  codeViewerLinesBadge: document.getElementById('code-viewer-lines-badge'),
  codeViewerViewOnlyBadge: document.getElementById('code-viewer-view-only-badge'),
  btnCopyCode: document.getElementById('btn-copy-code'),
  codeViewerBody: document.getElementById('code-viewer-body'),
  codeLineNumbers: document.getElementById('code-line-numbers'),
  codeContentText: document.getElementById('code-content-text'),
  previewImageBox: document.getElementById('preview-image-box'),
  previewImageElem: document.getElementById('preview-image-elem'),
  imageViewShield: document.getElementById('image-view-shield'),
  previewVideoBox: document.getElementById('preview-video-box'),
  previewVideoElem: document.getElementById('preview-video-elem'),
  previewAudioBox: document.getElementById('preview-audio-box'),
  previewAudioElem: document.getElementById('preview-audio-elem'),
  previewPdfBox: document.getElementById('preview-pdf-box'),
  previewPdfElem: document.getElementById('preview-pdf-elem'),
  pdfCanvasContainer: document.getElementById('pdf-canvas-container'),
  pdfRenderCanvas: document.getElementById('pdf-render-canvas'),
  pdfViewShield: document.getElementById('pdf-view-shield'),
  btnPdfPrev: document.getElementById('btn-pdf-prev'),
  btnPdfNext: document.getElementById('btn-pdf-next'),
  btnPdfZoomIn: document.getElementById('btn-pdf-zoom-in'),
  btnPdfZoomOut: document.getElementById('btn-pdf-zoom-out'),
  btnPdfZoomFit: document.getElementById('btn-pdf-zoom-fit'),
  pdfZoomDisplay: document.getElementById('pdf-zoom-display'),
  pdfPageNumDisplay: document.getElementById('pdf-page-num-display'),
  btnDownloadEntireFolder: document.getElementById('btn-download-entire-folder'),
  previewUnsupportedBox: document.getElementById('preview-unsupported-box'),
  previewUnsupportedMsg: document.getElementById('preview-unsupported-msg'),
  publicFolderContents: document.getElementById('public-folder-contents'),
  publicFolderBreadcrumbs: document.getElementById('public-folder-breadcrumbs'),
  publicFolderTbody: document.getElementById('public-folder-tbody'),
  publicFolderEmpty: document.getElementById('public-folder-empty'),

  // Confirmation Modal
  modalConfirm: document.getElementById('modal-confirm'),
  confirmModalTitle: document.getElementById('confirm-modal-title'),
  confirmModalMessage: document.getElementById('confirm-modal-message'),
  confirmModalIcon: document.getElementById('confirm-modal-icon'),
  confirmModalCancelBtn: document.getElementById('confirm-modal-cancel'),
  confirmModalConfirmBtn: document.getElementById('confirm-modal-confirm'),

  // In-App File Preview Modal
  modalFilePreview: document.getElementById('modal-file-preview'),
  inappPreviewIcon: document.getElementById('inapp-preview-icon'),
  inappPreviewFilename: document.getElementById('inapp-preview-filename'),
  inappPreviewSubmeta: document.getElementById('inapp-preview-submeta'),
  inappPreviewDownloadBtn: document.getElementById('inapp-preview-download-btn'),
  btnCloseInappPreview: document.getElementById('btn-close-inapp-preview'),
  inappPreviewLoading: document.getElementById('inapp-preview-loading'),
  inappPreviewImageBox: document.getElementById('inapp-preview-image-box'),
  inappPreviewImage: document.getElementById('inapp-preview-image'),
  inappPreviewPdfBox: document.getElementById('inapp-preview-pdf-box'),
  inappBtnPdfPrev: document.getElementById('inapp-btn-pdf-prev'),
  inappPdfPageNum: document.getElementById('inapp-pdf-page-num'),
  inappPdfPageCount: document.getElementById('inapp-pdf-page-count'),
  inappBtnPdfNext: document.getElementById('inapp-btn-pdf-next'),
  inappBtnPdfZoomOut: document.getElementById('inapp-btn-pdf-zoom-out'),
  inappBtnPdfZoomFit: document.getElementById('inapp-btn-pdf-zoom-fit'),
  inappBtnPdfZoomIn: document.getElementById('inapp-btn-pdf-zoom-in'),
  inappPdfCanvasContainer: document.getElementById('inapp-pdf-canvas-container'),
  inappPdfRenderCanvas: document.getElementById('inapp-pdf-render-canvas'),
  inappPreviewPdfIframe: document.getElementById('inapp-preview-pdf-iframe'),
  inappPreviewVideoBox: document.getElementById('inapp-preview-video-box'),
  inappPreviewVideo: document.getElementById('inapp-preview-video'),
  inappPreviewAudioBox: document.getElementById('inapp-preview-audio-box'),
  inappPreviewAudio: document.getElementById('inapp-preview-audio'),
  inappPreviewCodeBox: document.getElementById('inapp-preview-code-box'),
  inappCodeLangIcon: document.getElementById('inapp-code-lang-icon'),
  inappCodeFilename: document.getElementById('inapp-code-filename'),
  inappCodeLinesBadge: document.getElementById('inapp-code-lines-badge'),
  inappBtnCopyCode: document.getElementById('inapp-btn-copy-code'),
  inappCodeViewerBody: document.getElementById('inapp-code-viewer-body'),
  inappCodeLineNumbers: document.getElementById('inapp-code-line-numbers'),
  inappCodeContentText: document.getElementById('inapp-code-content-text'),
  inappPreviewUnsupportedBox: document.getElementById('inapp-preview-unsupported-box'),
  inappBtnFallbackDownload: document.getElementById('inapp-btn-fallback-download'),

  // Rename Item Modal
  modalRename: document.getElementById('modal-rename'),
  renameModalTitle: document.getElementById('rename-modal-title'),
  renameModalSubtitle: document.getElementById('rename-modal-subtitle'),
  formRename: document.getElementById('form-rename'),
  renameTargetId: document.getElementById('rename-target-id'),
  renameTargetType: document.getElementById('rename-target-type'),
  renameNameInput: document.getElementById('rename-name-input'),
  btnSubmitRename: document.getElementById('btn-submit-rename'),

  // Move Item Modal
  modalMove: document.getElementById('modal-move'),
  moveModalTitle: document.getElementById('move-modal-title'),
  moveModalSubtitle: document.getElementById('move-modal-subtitle'),
  formMove: document.getElementById('form-move'),
  moveTargetId: document.getElementById('move-target-id'),
  moveTargetType: document.getElementById('move-target-type'),
  moveDestinationSelect: document.getElementById('move-destination-select'),
  btnSubmitMove: document.getElementById('btn-submit-move'),
};

// --- Utilities ---

function openMobileSidebar() {
  if (el.dashboardSidebar) el.dashboardSidebar.classList.add('open');
  if (el.sidebarBackdrop) el.sidebarBackdrop.classList.remove('hidden');
  document.body.classList.add('sidebar-open');
}

function closeMobileSidebar() {
  if (el.dashboardSidebar) el.dashboardSidebar.classList.remove('open');
  if (el.sidebarBackdrop) el.sidebarBackdrop.classList.add('hidden');
  document.body.classList.remove('sidebar-open');
}

function showToast(message, type = 'info', duration = 4000) {
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  el.toastContainer.appendChild(toast);
  setTimeout(() => toast.remove(), duration);
}

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

async function handleRefreshWithFeedback(btn, asyncFn, successMsg = 'Refreshed!') {
  if (!btn) return;
  const originalHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="inline-spin">🔄</span> Refreshing...`;
  try {
    await asyncFn();
    showToast(successMsg, 'success');
  } catch (err) {
    showToast(`Refresh failed: ${err.message}`, 'error');
  } finally {
    btn.innerHTML = originalHtml;
    btn.disabled = false;
  }
}

function showConfirmModal({
  title = 'Confirm Action',
  message = 'Are you sure you want to proceed?',
  confirmText = 'Confirm',
  confirmClass = 'btn-danger',
  icon = '⚠️',
  onConfirm = null,
} = {}) {
  return new Promise((resolve) => {
    el.confirmModalTitle.textContent = title;
    el.confirmModalMessage.textContent = message;
    el.confirmModalConfirmBtn.textContent = confirmText;
    el.confirmModalIcon.textContent = icon;
    el.confirmModalConfirmBtn.className = `btn ${confirmClass}`;

    const cleanup = () => {
      el.modalConfirm.classList.add('hidden');
      el.confirmModalConfirmBtn.onclick = null;
      el.confirmModalCancelBtn.onclick = null;
    };

    el.confirmModalConfirmBtn.onclick = async () => {
      cleanup();
      if (typeof onConfirm === 'function') {
        try {
          await onConfirm();
        } catch (err) {
          console.error('Error in onConfirm:', err);
        }
      }
      resolve(true);
    };

    el.confirmModalCancelBtn.onclick = () => {
      cleanup();
      resolve(false);
    };

    el.modalConfirm.classList.remove('hidden');
  });
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatDate(isoStr) {
  if (!isoStr) return '--';
  const d = new Date(isoStr);
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

async function computeSHA256(file) {
  const buffer = await file.arrayBuffer();
  const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
}

// --- API Client Helpers ---

async function apiRequest(endpoint, options = {}) {
  const headers = options.headers || {};
  if (state.token) {
    headers['Authorization'] = `Bearer ${state.token}`;
  }
  if (!(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    let errorMsg = data?.error?.message;
    if (!errorMsg && typeof data?.detail === 'string') {
      errorMsg = data.detail;
    } else if (!errorMsg && Array.isArray(data?.detail) && data.detail[0]?.msg) {
      errorMsg = data.detail[0].msg;
    } else if (!errorMsg) {
      errorMsg = response.statusText || 'Request failed';
    }
    throw new Error(errorMsg);
  }
  return data;
}

// --- Authentication & Client State Reset ---

function resetAppState() {
  // 1. Reset in-memory state
  state.token = null;
  state.user = null;
  state.files = [];
  state.folders = [];
  state.shares = [];
  state.trash = [];
  state.adminUsers = [];
  state.breadcrumbs = [];
  state.currentFolderId = null;
  state.expandedFolderIds = new Set();
  state.folderTreeData = null;
  state.navToken = 0;
  state.filesSearch = '';
  state.filesType = '';
  state.filesSortBy = 'created_at';
  state.filesOrder = 'desc';
  state.sessionShareLinks = {};

  // 2. Wipe DOM content to prevent any cross-account data leaks
  if (el.filesTbody) el.filesTbody.innerHTML = '';
  if (el.sidebarFolderTree) el.sidebarFolderTree.innerHTML = '';
  if (el.sharesTbody) el.sharesTbody.innerHTML = '';
  if (el.trashTbody) el.trashTbody.innerHTML = '';
  if (el.adminUsersTbody) el.adminUsersTbody.innerHTML = '';
  if (el.breadcrumbs) el.breadcrumbs.innerHTML = '';
  if (el.userEmailDisplay) el.userEmailDisplay.textContent = '';
  if (el.mobileUserEmail) el.mobileUserEmail.textContent = '';

  // Reset quota indicators
  if (el.quotaUsedText) el.quotaUsedText.textContent = '0 B';
  if (el.quotaTotalText) el.quotaTotalText.textContent = '0 B';
  if (el.quotaBarFill) {
    el.quotaBarFill.style.width = '0%';
    el.quotaBarFill.style.backgroundColor = 'var(--primary)';
  }
  if (el.mobileQuotaText) el.mobileQuotaText.textContent = '0 B / 0 B';
  if (el.mobileQuotaBarFill) {
    el.mobileQuotaBarFill.style.width = '0%';
    el.mobileQuotaBarFill.style.backgroundColor = 'var(--primary)';
  }

  // Reset admin controls & navigation
  if (el.adminBadge) el.adminBadge.classList.add('hidden');
  if (el.navAdminDashboard) el.navAdminDashboard.classList.add('hidden');
  if (el.mobileAdminBadge) el.mobileAdminBadge.classList.add('hidden');
  if (el.adminManagerSection) el.adminManagerSection.classList.add('hidden');

  // Reset section back to files
  if (typeof switchSection === 'function') {
    switchSection('files');
  }

  // Clear search inputs & empty states
  if (el.filesSearchInput) el.filesSearchInput.value = '';
  if (el.filesSearchClear) el.filesSearchClear.classList.add('hidden');
  if (el.emptyFolderState) el.emptyFolderState.classList.add('hidden');
}

function setAuthenticatedState(isAuthenticated) {
  const preloadStyle = document.getElementById('auth-preload-style');
  if (preloadStyle) preloadStyle.remove();

  if (isAuthenticated) {
    el.authView.classList.add('hidden');
    el.dashboardView.classList.remove('hidden');
  } else {
    el.dashboardView.classList.add('hidden');
    el.authView.classList.remove('hidden');
  }
}

async function handleLogin(email, password) {
  try {
    resetAppState();
    const data = await apiRequest('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    state.token = data.access_token;
    localStorage.setItem('cloudbox_jwt', state.token);
    showToast('Logged in successfully', 'success');
    await initApp();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function handleSignup(email, password, full_name) {
  const trimmedName = (full_name || '').trim();
  if (!trimmedName) {
    showToast('Please enter your full name', 'error');
    if (el.signupName) el.signupName.focus();
    return;
  }
  try {
    await apiRequest('/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ email, password, full_name: trimmedName }),
    });
    showToast('Account created! Logging you in...', 'success');
    await handleLogin(email, password);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function handleLogout() {
  localStorage.removeItem('cloudbox_jwt');
  resetAppState();
  setAuthenticatedState(false);
  showToast('Logged out');
}

// --- Quota & User Profile ---

async function loadUserProfile() {
  const user = await apiRequest('/auth/me');
  state.user = user;
  el.userEmailDisplay.textContent = user.email;
  if (el.mobileUserEmail) el.mobileUserEmail.textContent = user.email;

  // Toggle Admin Dashboard Visibility
  if (user.is_superuser) {
    if (el.adminBadge) el.adminBadge.classList.remove('hidden');
    if (el.navAdminDashboard) el.navAdminDashboard.classList.remove('hidden');
    if (el.mobileAdminBadge) el.mobileAdminBadge.classList.remove('hidden');
  } else {
    if (el.adminBadge) el.adminBadge.classList.add('hidden');
    if (el.navAdminDashboard) el.navAdminDashboard.classList.add('hidden');
    if (el.mobileAdminBadge) el.mobileAdminBadge.classList.add('hidden');
  }

  const quota = await apiRequest('/auth/quota');
  const usedFormatted = formatBytes(quota.storage_used_bytes);
  const totalFormatted = formatBytes(quota.storage_quota_bytes);
  el.quotaUsedText.textContent = usedFormatted;
  el.quotaTotalText.textContent = totalFormatted;
  if (el.mobileQuotaText) el.mobileQuotaText.textContent = `${usedFormatted} / ${totalFormatted}`;

  const pctWidth = `${Math.min(100, quota.storage_used_percentage)}%`;
  el.quotaBarFill.style.width = pctWidth;
  if (el.mobileQuotaBarFill) el.mobileQuotaBarFill.style.width = pctWidth;

  const barColor = quota.storage_used_percentage > 90 ? 'var(--danger)' :
                   quota.storage_used_percentage > 75 ? 'var(--warning)' : 'var(--primary)';
  el.quotaBarFill.style.backgroundColor = barColor;
  if (el.mobileQuotaBarFill) el.mobileQuotaBarFill.style.backgroundColor = barColor;
}

function updateSortHeaders(selector, currentSortBy, currentOrder) {
  document.querySelectorAll(selector).forEach((th) => {
    const sortKey = th.getAttribute('data-sort');
    th.classList.remove('sort-asc', 'sort-desc');
    const icon = th.querySelector('.sort-icon');
    if (icon) icon.textContent = '';

    if (sortKey === currentSortBy) {
      th.classList.add(currentOrder === 'asc' ? 'sort-asc' : 'sort-desc');
      if (icon) icon.textContent = currentOrder === 'asc' ? ' ▲' : ' ▼';
    }
  });
}

// --- Folders & Navigation ---

function renderFolderSkeleton() {
  if (!el.filesTbody) return;
  if (el.emptyFolderState) el.emptyFolderState.classList.add('hidden');

  let skeletonHtml = '';
  for (let i = 0; i < 4; i++) {
    skeletonHtml += `
      <tr class="folder-skeleton-row">
        <td>
          <div class="skeleton-shimmer">
            <div class="skeleton-box skeleton-icon"></div>
            <div class="skeleton-box skeleton-title"></div>
          </div>
        </td>
        <td><div class="skeleton-box skeleton-sm"></div></td>
        <td><div class="skeleton-box skeleton-badge"></div></td>
        <td><div class="skeleton-box skeleton-sm"></div></td>
        <td class="text-right"><div class="skeleton-box skeleton-sm" style="margin-left: auto;"></div></td>
      </tr>
    `;
  }
  el.filesTbody.innerHTML = skeletonHtml;
}

async function loadFolderView(folderId = null) {
  state.currentFolderId = folderId;
  const thisNavToken = ++state.navToken;

  // Toggle folder action buttons in header (visible only inside subfolders)
  if (el.btnRenameCurrentFolder) {
    if (folderId) {
      el.btnRenameCurrentFolder.classList.remove('hidden');
    } else {
      el.btnRenameCurrentFolder.classList.add('hidden');
    }
  }
  if (el.btnMoveCurrentFolder) {
    if (folderId) {
      el.btnMoveCurrentFolder.classList.remove('hidden');
    } else {
      el.btnMoveCurrentFolder.classList.add('hidden');
    }
  }
  if (el.btnDeleteCurrentFolder) {
    if (folderId) {
      el.btnDeleteCurrentFolder.classList.remove('hidden');
    } else {
      el.btnDeleteCurrentFolder.classList.add('hidden');
    }
  }

  if (folderId) {
    state.expandedFolderIds.add(folderId);
  }

  // Instant visual feedback: highlight tree node immediately and show skeleton rows
  renderSidebarTree();
  renderFolderSkeleton();

  try {
    // 1. Prepare parallel API requests
    const crumbUrl = folderId ? `/folders/breadcrumbs?folder_id=${folderId}` : '/folders/breadcrumbs';
    const breadcrumbsPromise = apiRequest(crumbUrl);

    let folderUrl = folderId ? `/folders/?parent_id=${folderId}` : '/folders/';
    const folderParams = new URLSearchParams();
    if (state.filesSearch) folderParams.set('search', state.filesSearch);
    if (state.filesSortBy === 'name' || state.filesSortBy === 'created_at') {
      folderParams.set('sort_by', state.filesSortBy);
      folderParams.set('order', state.filesOrder);
    }
    const fQuery = folderParams.toString();
    if (fQuery) folderUrl += (folderUrl.includes('?') ? '&' : '?') + fQuery;
    const foldersPromise = state.filesType ? Promise.resolve([]) : apiRequest(folderUrl);

    let filesUrl = folderId ? `/files/?folder_id=${folderId}` : '/files/';
    const fileParams = new URLSearchParams();
    if (state.filesSearch) fileParams.set('search', state.filesSearch);
    if (state.filesType) fileParams.set('file_type', state.filesType);
    fileParams.set('sort_by', state.filesSortBy);
    fileParams.set('order', state.filesOrder);
    filesUrl += (filesUrl.includes('?') ? '&' : '?') + fileParams.toString();
    const filesPromise = apiRequest(filesUrl);

    // 2. Fetch all concurrently with Promise.all
    const [breadcrumbs, folders, files] = await Promise.all([
      breadcrumbsPromise,
      foldersPromise,
      filesPromise,
    ]);

    // Guard against race conditions if user navigated away while request was in-flight
    if (thisNavToken !== state.navToken) return;

    state.breadcrumbs = breadcrumbs || [];
    state.folders = folders || [];
    state.files = files || [];

    if (Array.isArray(state.breadcrumbs)) {
      state.breadcrumbs.forEach((crumb) => {
        if (crumb.id) state.expandedFolderIds.add(crumb.id);
      });
    }

    renderBreadcrumbs();
    renderFiles();
    renderSidebarTree();
    updateSortHeaders('.sortable-th', state.filesSortBy, state.filesOrder);
  } catch (err) {
    if (thisNavToken === state.navToken) {
      showToast(err.message, 'error');
    }
  }
}

function renderBreadcrumbs() {
  el.breadcrumbs.innerHTML = '';
  state.breadcrumbs.forEach((crumb, idx) => {
    const isLast = idx === state.breadcrumbs.length - 1;
    const span = document.createElement('span');
    span.className = `crumb ${isLast ? 'active' : ''}`;
    span.textContent = crumb.name;
    if (!isLast) {
      span.onclick = () => loadFolderView(crumb.id);
      el.breadcrumbs.appendChild(span);
      const sep = document.createElement('span');
      sep.textContent = ' / ';
      sep.style.color = 'var(--text-muted)';
      el.breadcrumbs.appendChild(sep);
    } else {
      el.breadcrumbs.appendChild(span);
    }
  });
}

function renderFolders() {
  // Folders are now rendered directly inside the Files table
}

async function deleteFolder(folderId, folderName) {
  const confirmed = await showConfirmModal({
    title: 'Move Folder to Trash',
    message: `Move folder '${folderName}' and all its files and subfolders to Trash? (Retained for 14 days)`,
    confirmText: 'Move to Trash',
    confirmClass: 'btn-danger',
    icon: '🗑️',
  });
  if (!confirmed) return;

  try {
    await apiRequest(`/folders/${folderId}`, { method: 'DELETE' });
    showToast(`Folder '${folderName}' and all its contents moved to trash`, 'success');
    state.expandedFolderIds.delete(folderId);

    const targetFolderId = state.currentFolderId === folderId ? null : state.currentFolderId;
    await loadSidebarTree(true);
    await Promise.all([
      loadUserProfile(),
      loadFolderView(targetFolderId),
    ]);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function renderSidebarTree() {
  if (!el.sidebarFolderTree) return;
  el.sidebarFolderTree.innerHTML = '';

  const tree = state.folderTreeData;
  if (!tree || tree.length === 0) {
    state.expandedFolderIds.clear();
    el.sidebarFolderTree.innerHTML = '<div class="text-muted" style="font-size:0.75rem; padding: 0.35rem 0.5rem;">No folders yet</div>';
    return;
  }

  function renderNode(node, depth = 0) {
    const hasChildren = Boolean(node.children && node.children.length > 0);
    const isExpanded = state.expandedFolderIds.has(node.id);
    const isActive = state.currentFolderId === node.id;

    const item = document.createElement('div');
    item.className = `tree-node ${isActive ? 'active' : ''}`;
    item.style.paddingLeft = `${depth * 14 + 6}px`;

    // 1. Expand / Collapse toggle icon
    const toggleSpan = document.createElement('span');
    if (hasChildren) {
      toggleSpan.className = 'tree-toggle';
      toggleSpan.textContent = isExpanded ? '▾' : '▸';
      toggleSpan.title = isExpanded ? 'Collapse subfolders' : 'Expand subfolders';
      toggleSpan.onclick = (e) => {
        e.stopPropagation();
        if (state.expandedFolderIds.has(node.id)) {
          state.expandedFolderIds.delete(node.id);
        } else {
          state.expandedFolderIds.add(node.id);
        }
        renderSidebarTree();
      };
    } else {
      toggleSpan.className = 'tree-toggle-spacer';
    }
    item.appendChild(toggleSpan);

    // 2. Folder icon
    const iconSpan = document.createElement('span');
    iconSpan.className = 'tree-node-icon';
    iconSpan.textContent = isExpanded && hasChildren ? '📂' : '📁';
    item.appendChild(iconSpan);

    // 3. Folder name
    const nameSpan = document.createElement('span');
    nameSpan.className = 'tree-node-name';
    nameSpan.textContent = node.name;
    nameSpan.title = node.name;
    item.appendChild(nameSpan);

    // 4. Clicking folder row: navigates to folder and reveals its subfolders
    item.onclick = (e) => {
      e.stopPropagation();
      closeMobileSidebar();
      if (hasChildren) {
        if (state.currentFolderId === node.id) {
          if (state.expandedFolderIds.has(node.id)) {
            state.expandedFolderIds.delete(node.id);
          } else {
            state.expandedFolderIds.add(node.id);
          }
          renderSidebarTree();
          return;
        } else {
          state.expandedFolderIds.add(node.id);
        }
      }
      loadFolderView(node.id);
    };

    el.sidebarFolderTree.appendChild(item);

    // 5. Render children ONLY if this folder is expanded!
    if (hasChildren && isExpanded) {
      node.children.forEach((child) => renderNode(child, depth + 1));
    }
  }

  tree.forEach((root) => renderNode(root, 0));
}

let sidebarTreePromise = null;
async function loadSidebarTree(forceReload = false) {
  if (forceReload) {
    state.folderTreeData = null;
    sidebarTreePromise = null;
  }
  if (!state.folderTreeData) {
    if (!sidebarTreePromise) {
      sidebarTreePromise = apiRequest('/folders/tree')
        .then((tree) => {
          state.folderTreeData = Array.isArray(tree) ? tree : [];
          sidebarTreePromise = null;
          return state.folderTreeData;
        })
        .catch((err) => {
          sidebarTreePromise = null;
          console.error('Failed to load tree:', err);
          return [];
        });
    }
    await sidebarTreePromise;
  }
  renderSidebarTree();
}

// --- Files & Direct S3 Upload Pipeline ---

function renderFiles() {
  el.filesTbody.innerHTML = '';

  if (state.files.length === 0 && state.folders.length === 0) {
    el.emptyFolderState.classList.remove('hidden');
    return;
  }
  el.emptyFolderState.classList.add('hidden');

  // 1. Render Folders in the table
  state.folders.forEach((folder) => {
    const tr = document.createElement('tr');
    tr.className = 'folder-table-row';
    tr.innerHTML = `
      <td>
        <div class="file-cell folder-link-cell" style="cursor: pointer;" title="Open folder ${folder.name}">
          <span class="file-icon">📁</span>
          <strong>${folder.name}</strong>
        </div>
      </td>
      <td>—</td>
      <td><span class="file-badge badge-ready">FOLDER</span></td>
      <td>${formatDate(folder.updated_at || folder.created_at)}</td>
      <td class="text-right">
        <button class="btn btn-secondary btn-sm btn-folder-rename" title="Rename Folder">✏️</button>
        <button class="btn btn-secondary btn-sm btn-folder-move" title="Move Folder">📁➡️</button>
        <button class="btn btn-secondary btn-sm btn-folder-share" title="Share Folder">🔗</button>
        <button class="btn btn-danger btn-sm btn-folder-delete" title="Move Folder to Trash">🗑️</button>
      </td>
    `;

    tr.querySelector('.folder-link-cell').onclick = () => loadFolderView(folder.id);

    tr.querySelector('.btn-folder-rename').onclick = (e) => {
      e.stopPropagation();
      openRenameModal('folder', folder.id, folder.name);
    };

    tr.querySelector('.btn-folder-move').onclick = (e) => {
      e.stopPropagation();
      openMoveModal('folder', folder.id, folder.name, folder.parent_id);
    };

    tr.querySelector('.btn-folder-share').onclick = (e) => {
      e.stopPropagation();
      openShareModal('folder', folder.id, folder.name);
    };

    tr.querySelector('.btn-folder-delete').onclick = (e) => {
      e.stopPropagation();
      deleteFolder(folder.id, folder.name);
    };

    el.filesTbody.appendChild(tr);
  });

  // 2. Render Files in the table
  state.files.forEach((file) => {
    const tr = document.createElement('tr');

    const badgeClass =
      file.status === 'READY' ? 'badge-ready' : file.status === 'FAILED' ? 'badge-failed' : 'badge-pending';

    const thumbHtml = file.thumbnail_url
      ? `<img src="${file.thumbnail_url}" class="file-thumb" alt="thumb" />`
      : `<span>📄</span>`;

    tr.innerHTML = `
      <td>
        <div class="file-cell clickable file-preview-trigger" title="Preview ${file.name}">
          ${thumbHtml}
          <strong>${file.name}</strong>
        </div>
      </td>
      <td>${formatBytes(file.file_size)}</td>
      <td><span class="file-badge ${badgeClass}">${file.status}</span></td>
      <td>${formatDate(file.updated_at || file.created_at)}</td>
      <td class="text-right">
        <button class="btn btn-secondary btn-sm btn-preview" data-id="${file.id}" title="Preview File">👁️</button>
        <button class="btn btn-primary btn-sm btn-download" data-id="${file.id}" title="Download">📥</button>
        <button class="btn btn-secondary btn-sm btn-rename" data-id="${file.id}" title="Rename File">✏️</button>
        <button class="btn btn-secondary btn-sm btn-move" data-id="${file.id}" title="Move File">📁➡️</button>
        <button class="btn btn-secondary btn-sm btn-share" data-id="${file.id}" data-name="${file.name}" title="Share">🔗</button>
        <button class="btn btn-danger btn-sm btn-delete" data-id="${file.id}" title="Delete">🗑️</button>
      </td>
    `;

    tr.querySelector('.file-preview-trigger').onclick = () => openInAppFilePreview(file.id, file);
    tr.querySelector('.btn-preview').onclick = (e) => {
      e.stopPropagation();
      openInAppFilePreview(file.id, file);
    };
    tr.querySelector('.btn-download').onclick = (e) => {
      e.stopPropagation();
      downloadFile(file.id);
    };
    tr.querySelector('.btn-rename').onclick = (e) => {
      e.stopPropagation();
      openRenameModal('file', file.id, file.name);
    };
    tr.querySelector('.btn-move').onclick = (e) => {
      e.stopPropagation();
      openMoveModal('file', file.id, file.name, file.folder_id);
    };
    tr.querySelector('.btn-share').onclick = (e) => {
      e.stopPropagation();
      openShareModal('file', file.id, file.name);
    };
    tr.querySelector('.btn-delete').onclick = (e) => {
      e.stopPropagation();
      deleteFile(file.id);
    };

    el.filesTbody.appendChild(tr);
  });
}

async function uploadFilePipeline(file) {
  try {
    el.uploadProgressContainer.classList.remove('hidden');
    el.uploadFilename.textContent = `Preparing ${file.name}...`;
    el.uploadPercent.textContent = '0%';
    el.uploadProgressFill.style.width = '0%';

    // Step 1: Compute SHA-256 checksum in client
    const checksum = await computeSHA256(file);

    // Step 2: Request presigned S3 upload URL from FastAPI
    const presignedData = await apiRequest('/files/upload-url', {
      method: 'POST',
      body: JSON.stringify({
        name: file.name,
        file_size: file.size,
        content_type: file.type || 'application/octet-stream',
        folder_id: state.currentFolderId,
      }),
    });

    // Step 3: Direct PUT bytes to S3 presigned URL with progress tracking
    el.uploadFilename.textContent = `Uploading ${file.name}...`;
    await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open(presignedData.http_method, presignedData.upload_url, true);

      // Set headers from backend presigned payload
      if (presignedData.headers) {
        Object.entries(presignedData.headers).forEach(([k, v]) => {
          xhr.setRequestHeader(k, v);
        });
      }

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const percent = Math.round((e.loaded / e.total) * 100);
          el.uploadPercent.textContent = `${percent}%`;
          el.uploadProgressFill.style.width = `${percent}%`;
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve();
        } else {
          reject(new Error(`Upload failed with status ${xhr.status}`));
        }
      };
      xhr.onerror = () => reject(new Error('Network error during upload'));
      xhr.send(file);
    });

    // Step 4: Finalize upload with metadata & trigger background worker
    el.uploadFilename.textContent = `Processing ${file.name}...`;
    await apiRequest('/files/complete-upload', {
      method: 'POST',
      body: JSON.stringify({
        temp_s3_key: presignedData.temp_s3_key,
        name: file.name,
        file_size: file.size,
        content_type: file.type || 'application/octet-stream',
        checksum_sha256: checksum,
        folder_id: state.currentFolderId,
        file_id: presignedData.file_id,
      }),
    });

    showToast(`Uploaded ${file.name} successfully!`, 'success');
    await Promise.all([
      loadUserProfile(),
      loadFolderView(state.currentFolderId),
    ]);
  } catch (err) {
    showToast(`Upload failed: ${err.message}`, 'error');
  } finally {
    setTimeout(() => {
      el.uploadProgressContainer.classList.add('hidden');
    }, 1500);
  }
}

async function downloadFile(fileId) {
  try {
    const data = await apiRequest(`/files/${fileId}/download`);
    window.open(data.download_url, '_blank');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function deleteFile(fileId) {
  const confirmed = await showConfirmModal({
    title: 'Move File to Trash',
    message: 'Move this file to Trash? It will be retained for 14 days before being permanently deleted.',
    confirmText: 'Move to Trash',
    confirmClass: 'btn-danger',
    icon: '🗑️',
  });
  if (!confirmed) return;

  try {
    await apiRequest(`/files/${fileId}`, { method: 'DELETE' });
    showToast('File moved to trash (retained for 14 days)', 'success');
    await Promise.all([
      loadUserProfile(),
      loadFolderView(state.currentFolderId),
    ]);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// --- Modals & Sharing ---

function getShareConfigKey() {
  const permission = el.sharePermission.value;
  const preset = el.shareExpiryPreset.value;
  const custom = preset === 'custom' ? (el.shareCustomExpiry.value || 'none') : preset || 'permanent';
  return `${permission}_${custom}`;
}

function updateShareModalState() {
  const key = getShareConfigKey();
  const submitBtn = el.formShare.querySelector('button[type="submit"]');

  if (state.sessionShareLinks && state.sessionShareLinks[key]) {
    el.shareLinkOutput.value = state.sessionShareLinks[key];
    el.shareResultContainer.classList.remove('hidden');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Link Generated ✓';
    }
  } else {
    el.shareResultContainer.classList.add('hidden');
    el.shareLinkOutput.value = '';
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Generate Share Link';
    }
  }
}

function openShareModal(type, targetId, itemName) {
  el.shareTargetType.value = type;
  el.shareTargetId.value = targetId;
  el.shareModalItemName.textContent = `${type.toUpperCase()}: ${itemName}`;
  el.sharePermission.value = 'download';
  el.shareExpiryPreset.value = '';
  el.shareCustomExpiryGroup.classList.add('hidden');
  el.shareCustomExpiry.value = '';

  // Set minimum date to current date/time
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  el.shareCustomExpiry.min = now.toISOString().slice(0, 16);

  el.shareLinkOutput.value = '';

  // Reset link map for this new modal opening session
  state.sessionShareLinks = {};

  updateShareModalState();
  el.modalShare.classList.remove('hidden');
}

async function handleGenerateShareLink(e) {
  e.preventDefault();

  const key = getShareConfigKey();
  const submitBtn = el.formShare.querySelector('button[type="submit"]');

  // If already generated for this exact permission/expiry in this session, do not recreate
  if (state.sessionShareLinks && state.sessionShareLinks[key]) {
    el.shareLinkOutput.value = state.sessionShareLinks[key];
    el.shareLinkOutput.select();
    showToast('Share link already created for this permission', 'info');
    return;
  }

  const type = el.shareTargetType.value;
  const targetId = el.shareTargetId.value;
  const permission = el.sharePermission.value;

  const payload = {
    permission,
    [type === 'file' ? 'file_id' : 'folder_id']: targetId,
  };

  const preset = el.shareExpiryPreset.value;

  if (preset === 'custom') {
    const customDateVal = el.shareCustomExpiry.value;
    if (!customDateVal) {
      showToast('Please select an expiration date & time', 'error');
      return;
    }
    const targetDate = new Date(customDateVal);
    if (targetDate.getTime() <= Date.now()) {
      showToast('Expiration date must be in the future', 'error');
      return;
    }
    payload.expires_at = targetDate.toISOString();
  } else if (preset) {
    payload.expires_in_hours = parseInt(preset);
  }

  try {
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Generating...';
    }

    const res = await apiRequest('/shares/', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    const fullUrl = `${window.location.origin}/#share=${res.share_token}`;
    state.sessionShareLinks[key] = fullUrl;
    el.shareLinkOutput.value = fullUrl;
    el.shareResultContainer.classList.remove('hidden');

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Link Generated ✓';
    }

    showToast(`Share link created (${permission === 'download' ? 'Download & View' : 'View Only'})!`, 'success');
  } catch (err) {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Generate Share Link';
    }
    showToast(err.message, 'error');
  }
}

// --- Rename & Move Modals ---

function openRenameModal(type, id, currentName) {
  if (!el.modalRename) return;

  el.renameTargetType.value = type;
  el.renameTargetId.value = id;
  el.renameModalTitle.textContent = type === 'folder' ? 'Rename Folder' : 'Rename File';
  el.renameModalSubtitle.textContent = `Current name: ${currentName}`;
  el.renameNameInput.value = currentName;
  el.modalRename.classList.remove('hidden');

  setTimeout(() => {
    el.renameNameInput.focus();
    if (type === 'file' && currentName.includes('.')) {
      const dotIdx = currentName.lastIndexOf('.');
      if (dotIdx > 0) {
        el.renameNameInput.setSelectionRange(0, dotIdx);
        return;
      }
    }
    el.renameNameInput.select();
  }, 50);
}

async function handleRenameSubmit(e) {
  e.preventDefault();
  const type = el.renameTargetType.value;
  const id = el.renameTargetId.value;
  const newName = el.renameNameInput.value.trim();

  if (!newName) {
    showToast('Name cannot be empty', 'error');
    return;
  }

  try {
    if (el.btnSubmitRename) {
      el.btnSubmitRename.disabled = true;
      el.btnSubmitRename.textContent = 'Saving...';
    }

    if (type === 'folder') {
      await apiRequest(`/folders/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ name: newName }),
      });
      showToast(`Folder renamed to '${newName}'`, 'success');
    } else {
      await apiRequest(`/files/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ name: newName }),
      });
      showToast(`File renamed to '${newName}'`, 'success');
    }

    el.modalRename.classList.add('hidden');
    state.folderTreeData = null;
    await Promise.all([
      loadSidebarTree(true),
      loadFolderView(state.currentFolderId),
    ]);
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    if (el.btnSubmitRename) {
      el.btnSubmitRename.disabled = false;
      el.btnSubmitRename.textContent = 'Save';
    }
  }
}

async function openMoveModal(type, id, currentName, currentParentId) {
  if (!el.modalMove) return;

  el.moveTargetType.value = type;
  el.moveTargetId.value = id;
  el.moveModalTitle.textContent = type === 'folder' ? 'Move Folder' : 'Move File';
  el.moveModalSubtitle.textContent = `Moving: ${currentName}`;
  el.moveDestinationSelect.innerHTML = '<option value="" disabled selected>Loading destinations...</option>';
  if (el.btnSubmitMove) el.btnSubmitMove.disabled = true;

  el.modalMove.classList.remove('hidden');

  try {
    const tree = await apiRequest('/folders/tree');
    el.moveDestinationSelect.innerHTML = '';

    // Collect forbidden folder IDs if type is 'folder' (itself and all descendants)
    const forbiddenIds = new Set();
    if (type === 'folder') {
      forbiddenIds.add(id);
      function collectDescendants(nodes) {
        for (const node of nodes) {
          if (node.id === id) {
            function addChildren(n) {
              if (n.children && n.children.length > 0) {
                for (const child of n.children) {
                  forbiddenIds.add(child.id);
                  addChildren(child);
                }
              }
            }
            addChildren(node);
            return true;
          }
          if (node.children && node.children.length > 0) {
            if (collectDescendants(node.children)) return true;
          }
        }
        return false;
      }
      collectDescendants(tree);
    }

    // Root option (Home)
    const rootOption = document.createElement('option');
    rootOption.value = 'root';
    const isCurrentRoot = !currentParentId;
    if (isCurrentRoot) {
      rootOption.textContent = '🏠 Home (Root Directory) — (Current Location)';
      rootOption.disabled = true;
    } else {
      rootOption.textContent = '🏠 Home (Root Directory)';
    }
    el.moveDestinationSelect.appendChild(rootOption);

    // Recursive helper to populate tree options
    function appendOptions(nodes, depth = 1) {
      for (const node of nodes) {
        const opt = document.createElement('option');
        opt.value = node.id;
        const indent = '\u00A0\u00A0'.repeat(depth * 2);
        if (type === 'folder' && forbiddenIds.has(node.id)) {
          opt.textContent = `${indent}📁 ${node.name} — (Cannot move here)`;
          opt.disabled = true;
        } else if (node.id === currentParentId) {
          opt.textContent = `${indent}📁 ${node.name} — (Current Location)`;
          opt.disabled = true;
        } else {
          opt.textContent = `${indent}📁 ${node.name}`;
        }
        el.moveDestinationSelect.appendChild(opt);

        if (node.children && node.children.length > 0) {
          appendOptions(node.children, depth + 1);
        }
      }
    }

    appendOptions(tree);

    // Select the first non-disabled option
    let hasSelectable = false;
    for (const option of el.moveDestinationSelect.options) {
      if (!option.disabled) {
        option.selected = true;
        hasSelectable = true;
        break;
      }
    }

    if (el.btnSubmitMove) {
      el.btnSubmitMove.disabled = !hasSelectable;
    }
  } catch (err) {
    showToast(`Failed to load folder destinations: ${err.message}`, 'error');
    el.moveDestinationSelect.innerHTML = '<option value="" disabled selected>Error loading folders</option>';
  }
}

async function handleMoveSubmit(e) {
  e.preventDefault();
  const type = el.moveTargetType.value;
  const id = el.moveTargetId.value;
  const selectedOpt = el.moveDestinationSelect.selectedOptions[0];
  if (!selectedOpt || selectedOpt.disabled) {
    showToast('Please select a valid destination folder', 'error');
    return;
  }

  const selectedVal = el.moveDestinationSelect.value;
  const destinationId = (selectedVal === 'root' || !selectedVal) ? null : selectedVal;

  try {
    if (el.btnSubmitMove) {
      el.btnSubmitMove.disabled = true;
      el.btnSubmitMove.textContent = 'Moving...';
    }

    if (type === 'folder') {
      await apiRequest(`/folders/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ parent_id: destinationId }),
      });
      showToast('Folder moved successfully!', 'success');
    } else {
      await apiRequest(`/files/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ folder_id: destinationId }),
      });
      showToast('File moved successfully!', 'success');
    }

    el.modalMove.classList.add('hidden');
    state.folderTreeData = null;
    await Promise.all([
      loadUserProfile(),
      loadSidebarTree(true),
      loadFolderView(state.currentFolderId),
    ]);
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    if (el.btnSubmitMove) {
      el.btnSubmitMove.disabled = false;
      el.btnSubmitMove.textContent = 'Move Here';
    }
  }
}

async function handleDeleteAccount() {
  const email = state.user?.email || 'your account';
  const confirmed = await showConfirmModal({
    title: 'Permanently Delete Account',
    message: `Are you sure you want to permanently delete account '${email}'? All your files, folders, shared links, and account data will be immediately and irreversibly destroyed.`,
    confirmText: 'Delete My Account',
    confirmClass: 'btn-danger',
    icon: '🗑️',
  });
  if (!confirmed) return;

  try {
    await apiRequest('/auth/me', { method: 'DELETE' });
    showToast('Your account and all associated data have been permanently deleted', 'success');
    handleLogout();
  } catch (err) {
    showToast(`Failed to delete account: ${err.message}`, 'error');
  }
}

// --- Public Share Viewer (Token Access) ---

let currentPdfDoc = null;
let currentPdfPage = 1;
let totalPdfPages = 0;
let isRenderingPdfPage = false;
let pendingPdfPage = null;
let pdfUserZoom = null; // null = auto fit to screen

async function renderPdfPage(num) {
  if (!currentPdfDoc) return;
  isRenderingPdfPage = true;
  const canvas = el.pdfRenderCanvas || document.getElementById('pdf-render-canvas');
  const pageNumDisplay = el.pdfPageNumDisplay || document.getElementById('pdf-page-num-display');
  const zoomDisplay = el.pdfZoomDisplay || document.getElementById('pdf-zoom-display');
  const prevBtn = el.btnPdfPrev || document.getElementById('btn-pdf-prev');
  const nextBtn = el.btnPdfNext || document.getElementById('btn-pdf-next');
  const container = el.pdfCanvasContainer || document.getElementById('pdf-canvas-container');

  try {
    const page = await currentPdfDoc.getPage(num);
    const unscaledViewport = page.getViewport({ scale: 1.0 });

    // Compute fit-to-screen scale so the whole page fits comfortably without scrolling
    const containerWidth = container ? container.clientWidth - 40 : 700;
    const availableHeight = Math.max(450, Math.min(window.innerHeight * 0.70, 720));

    const scaleWidth = (containerWidth > 0 ? containerWidth : 600) / unscaledViewport.width;
    const scaleHeight = availableHeight / unscaledViewport.height;
    const fitScale = Math.min(scaleWidth, scaleHeight);

    let actualScale = fitScale;
    if (pdfUserZoom !== null) {
      actualScale = pdfUserZoom;
      if (zoomDisplay) zoomDisplay.textContent = `${Math.round(actualScale * 100)}%`;
    } else {
      if (zoomDisplay) zoomDisplay.textContent = 'Fit';
    }

    // High-DPI support: render at device pixel ratio for crisp, sharp text
    const dpr = window.devicePixelRatio || 1;
    const renderViewport = page.getViewport({ scale: actualScale * dpr });

    if (canvas) {
      canvas.width = renderViewport.width;
      canvas.height = renderViewport.height;
      const cssWidth = Math.round(renderViewport.width / dpr);
      const cssHeight = Math.round(renderViewport.height / dpr);
      canvas.style.width = `${cssWidth}px`;
      canvas.style.height = `${cssHeight}px`;

      const ctx = canvas.getContext('2d');
      const renderContext = {
        canvasContext: ctx,
        viewport: renderViewport,
      };
      await page.render(renderContext).promise;

      if (el.pdfViewShield) {
        el.pdfViewShield.style.width = `${cssWidth}px`;
        el.pdfViewShield.style.height = `${cssHeight}px`;
      }
    }

    currentPdfPage = num;
    if (pageNumDisplay) pageNumDisplay.textContent = `Page ${num} / ${totalPdfPages}`;
    if (prevBtn) prevBtn.disabled = (num <= 1);
    if (nextBtn) nextBtn.disabled = (num >= totalPdfPages);
  } catch (err) {
    console.error('Error rendering PDF page:', err);
  } finally {
    isRenderingPdfPage = false;
    if (pendingPdfPage !== null) {
      const p = pendingPdfPage;
      pendingPdfPage = null;
      renderPdfPage(p);
    }
  }
}

function queueRenderPdfPage(num) {
  if (isRenderingPdfPage) {
    pendingPdfPage = num;
  } else {
    renderPdfPage(num);
  }
}

async function renderPublicSharePreview(data) {
  // Hide all preview boxes first
  if (el.previewCodeBox) el.previewCodeBox.classList.add('hidden');
  if (el.previewImageBox) el.previewImageBox.classList.add('hidden');
  if (el.previewVideoBox) el.previewVideoBox.classList.add('hidden');
  if (el.previewAudioBox) el.previewAudioBox.classList.add('hidden');
  if (el.previewPdfBox) el.previewPdfBox.classList.add('hidden');
  if (el.pdfCanvasContainer) el.pdfCanvasContainer.classList.add('hidden');
  if (el.previewPdfElem) el.previewPdfElem.classList.add('hidden');
  if (el.previewUnsupportedBox) el.previewUnsupportedBox.classList.add('hidden');
  if (el.publicPreviewContainer) el.publicPreviewContainer.classList.add('hidden');

  if (!data || !data.preview_url || data.item_type !== 'file') {
    return;
  }

  const filename = (data.name || '').toLowerCase();
  const ext = filename.includes('.') ? filename.split('.').pop() : '';
  const ct = (data.content_type || '').toLowerCase();

  const codeExts = [
    'py', 'js', 'jsx', 'ts', 'tsx', 'html', 'htm', 'css', 'scss', 'json', 'xml',
    'yaml', 'yml', 'md', 'markdown', 'txt', 'csv', 'sql', 'sh', 'bash', 'zsh',
    'c', 'cpp', 'cc', 'h', 'hpp', 'java', 'rs', 'go', 'rb', 'php', 'ini', 'env',
    'toml', 'log', 'dockerfile', 'makefile', 'conf'
  ];
  const imgExts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico'];
  const videoExts = ['mp4', 'webm', 'ogg', 'mov', 'mkv', 'm4v'];
  const audioExts = ['mp3', 'wav', 'ogg', 'm4a', 'aac', 'flac'];

  const isViewOnly = data.permission === 'view';

  // 1. Photo / Image
  if (ct.startsWith('image/') || imgExts.includes(ext)) {
    if (el.previewImageElem && el.previewImageBox && el.publicPreviewContainer) {
      // Fast display: use thumbnail as instant preview while full high-res loads
      if (data.thumbnail_url) {
        el.previewImageElem.src = data.thumbnail_url;
        el.previewImageElem.classList.add('img-loading-preview');
        const highRes = new Image();
        highRes.src = data.preview_url;
        highRes.onload = () => {
          el.previewImageElem.src = data.preview_url;
          el.previewImageElem.classList.remove('img-loading-preview');
        };
      } else {
        el.previewImageElem.src = data.preview_url;
      }

      if (isViewOnly) {
        if (el.imageViewShield) el.imageViewShield.classList.remove('hidden');
        el.previewImageElem.classList.add('protected');
        el.previewImageElem.oncontextmenu = (e) => { e.preventDefault(); return false; };
        el.previewImageElem.ondragstart = (e) => { e.preventDefault(); return false; };
        if (el.imageViewShield) el.imageViewShield.oncontextmenu = (e) => { e.preventDefault(); return false; };
      } else {
        if (el.imageViewShield) el.imageViewShield.classList.add('hidden');
        el.previewImageElem.classList.remove('protected');
        el.previewImageElem.oncontextmenu = null;
        el.previewImageElem.ondragstart = null;
        if (el.imageViewShield) el.imageViewShield.oncontextmenu = null;
      }
      el.previewImageBox.classList.remove('hidden');
      el.publicPreviewContainer.classList.remove('hidden');
    }
    return;
  }

  // 2. Video Player
  if (ct.startsWith('video/') || videoExts.includes(ext)) {
    if (el.previewVideoElem && el.previewVideoBox && el.publicPreviewContainer) {
      el.previewVideoElem.src = data.preview_url;
      if (isViewOnly) {
        el.previewVideoElem.setAttribute('controlsList', 'nodownload');
        el.previewVideoElem.setAttribute('disablePictureInPicture', 'true');
        el.previewVideoElem.oncontextmenu = (e) => { e.preventDefault(); return false; };
      } else {
        el.previewVideoElem.removeAttribute('controlsList');
        el.previewVideoElem.removeAttribute('disablePictureInPicture');
        el.previewVideoElem.oncontextmenu = null;
      }
      el.previewVideoBox.classList.remove('hidden');
      el.publicPreviewContainer.classList.remove('hidden');
    }
    return;
  }

  // 3. Audio Player
  if (ct.startsWith('audio/') || audioExts.includes(ext)) {
    if (el.previewAudioElem && el.previewAudioBox && el.publicPreviewContainer) {
      el.previewAudioElem.src = data.preview_url;
      if (isViewOnly) {
        el.previewAudioElem.setAttribute('controlsList', 'nodownload');
        el.previewAudioElem.oncontextmenu = (e) => { e.preventDefault(); return false; };
      } else {
        el.previewAudioElem.removeAttribute('controlsList');
        el.previewAudioElem.oncontextmenu = null;
      }
      el.previewAudioBox.classList.remove('hidden');
      el.publicPreviewContainer.classList.remove('hidden');
    }
    return;
  }

  // 4. PDF Document
  if (ct === 'application/pdf' || ext === 'pdf') {
    if (el.previewPdfBox && el.publicPreviewContainer) {
      if (isViewOnly && window.pdfjsLib) {
        // Protected View-Only Mode: Canvas render with PDF.js
        if (el.previewPdfElem) {
          el.previewPdfElem.src = '';
          el.previewPdfElem.classList.add('hidden');
        }
        if (el.pdfCanvasContainer) el.pdfCanvasContainer.classList.remove('hidden');
        if (el.pdfViewShield) {
          el.pdfViewShield.classList.remove('hidden');
          el.pdfViewShield.oncontextmenu = (e) => { e.preventDefault(); return false; };
        }
        if (el.pdfRenderCanvas) {
          el.pdfRenderCanvas.oncontextmenu = (e) => { e.preventDefault(); return false; };
          el.pdfRenderCanvas.onselectstart = (e) => { e.preventDefault(); return false; };
        }

        try {
          if (window.pdfjsLib.GlobalWorkerOptions && !window.pdfjsLib.GlobalWorkerOptions.workerSrc) {
            window.pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
          }
          const loadingTask = window.pdfjsLib.getDocument(data.preview_url);
          currentPdfDoc = await loadingTask.promise;
          pdfUserZoom = null;
          totalPdfPages = currentPdfDoc.numPages;
          currentPdfPage = 1;

          if (el.btnPdfPrev) {
            el.btnPdfPrev.onclick = () => {
              if (currentPdfPage > 1) {
                queueRenderPdfPage(currentPdfPage - 1);
              }
            };
          }
          if (el.btnPdfNext) {
            el.btnPdfNext.onclick = () => {
              if (currentPdfPage < totalPdfPages) {
                queueRenderPdfPage(currentPdfPage + 1);
              }
            };
          }
          if (el.btnPdfZoomIn) {
            el.btnPdfZoomIn.onclick = () => {
              const currentScale = pdfUserZoom || 0.8;
              pdfUserZoom = Math.min(2.5, +(currentScale + 0.15).toFixed(2));
              queueRenderPdfPage(currentPdfPage);
            };
          }
          if (el.btnPdfZoomOut) {
            el.btnPdfZoomOut.onclick = () => {
              const currentScale = pdfUserZoom || 0.8;
              pdfUserZoom = Math.max(0.35, +(currentScale - 0.15).toFixed(2));
              queueRenderPdfPage(currentPdfPage);
            };
          }
          if (el.btnPdfZoomFit) {
            el.btnPdfZoomFit.onclick = () => {
              pdfUserZoom = null;
              queueRenderPdfPage(currentPdfPage);
            };
          }

          await renderPdfPage(1);
        } catch (pdfErr) {
          console.error('PDF.js render failed, falling back to iframe:', pdfErr);
          if (el.pdfCanvasContainer) el.pdfCanvasContainer.classList.add('hidden');
          if (el.previewPdfElem) {
            el.previewPdfElem.src = data.preview_url;
            el.previewPdfElem.classList.remove('hidden');
          }
        }
      } else {
        // Normal / Downloadable Mode: Native browser PDF viewer iframe
        if (el.pdfCanvasContainer) el.pdfCanvasContainer.classList.add('hidden');
        if (el.pdfViewShield) el.pdfViewShield.classList.add('hidden');
        if (el.previewPdfElem) {
          el.previewPdfElem.src = data.preview_url;
          el.previewPdfElem.classList.remove('hidden');
        }
      }
      el.previewPdfBox.classList.remove('hidden');
      el.publicPreviewContainer.classList.remove('hidden');
    }
    return;
  }

  // 5. Code & Text File
  if (ct.startsWith('text/') || ct === 'application/json' || ct === 'application/javascript' || ct === 'application/xml' || codeExts.includes(ext)) {
    if (el.previewCodeBox && el.publicPreviewContainer) {
      el.codeViewerFilename.textContent = data.name;

      let langIcon = '📜';
      if (ext === 'py') langIcon = '🐍';
      else if (['js', 'jsx', 'ts', 'tsx'].includes(ext)) langIcon = '🟨';
      else if (['html', 'htm'].includes(ext)) langIcon = '🌐';
      else if (['css', 'scss'].includes(ext)) langIcon = '🎨';
      else if (ext === 'json') langIcon = '📦';
      else if (ext === 'md' || ext === 'markdown') langIcon = '📝';
      else if (ext === 'sql') langIcon = '🗄️';
      else if (['sh', 'bash', 'zsh'].includes(ext)) langIcon = '💻';
      else if (['c', 'cpp', 'cc', 'h', 'hpp'].includes(ext)) langIcon = '⚙️';
      else if (ext === 'rs') langIcon = '🦀';
      else if (ext === 'go') langIcon = '🐹';
      else if (ext === 'java') langIcon = '☕';
      if (el.codeViewerLangIcon) el.codeViewerLangIcon.textContent = langIcon;

      el.codeContentText.textContent = 'Loading file contents...';
      el.codeLineNumbers.textContent = '1';

      if (isViewOnly) {
        if (el.btnCopyCode) el.btnCopyCode.classList.add('hidden');
        if (el.codeViewerViewOnlyBadge) el.codeViewerViewOnlyBadge.classList.remove('hidden');
        if (el.codeViewerBody) el.codeViewerBody.classList.add('view-only-code');
        el.previewCodeBox.oncontextmenu = (e) => { e.preventDefault(); return false; };
      } else {
        if (el.btnCopyCode) el.btnCopyCode.classList.remove('hidden');
        if (el.codeViewerViewOnlyBadge) el.codeViewerViewOnlyBadge.classList.add('hidden');
        if (el.codeViewerBody) el.codeViewerBody.classList.remove('view-only-code');
        el.previewCodeBox.oncontextmenu = null;
      }

      el.previewCodeBox.classList.remove('hidden');
      el.publicPreviewContainer.classList.remove('hidden');

      try {
        const resp = await fetch(data.preview_url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const text = await resp.text();

        el.codeContentText.textContent = text;
        const lines = text.split('\n');
        const lineCount = lines.length;
        if (el.codeViewerLinesBadge) {
          el.codeViewerLinesBadge.textContent = `${lineCount} line${lineCount === 1 ? '' : 's'}`;
        }

        // Generate line numbers gutter
        const lineNums = [];
        for (let i = 1; i <= lineCount; i++) {
          lineNums.push(i);
        }
        el.codeLineNumbers.textContent = lineNums.join('\n');

        // Copy button handler (only if download/copy permission allowed)
        if (!isViewOnly && el.btnCopyCode) {
          el.btnCopyCode.onclick = () => {
            navigator.clipboard.writeText(text);
            showToast('Code copied to clipboard!', 'success');
          };
        }
      } catch (err) {
        el.codeContentText.textContent = `Error loading file contents: ${err.message}`;
      }
    }
    return;
  }

  // 6. Unsupported Binary Format Fallback
  if (el.previewUnsupportedBox && el.publicPreviewContainer) {
    if (el.previewUnsupportedMsg) {
      el.previewUnsupportedMsg.textContent = data.permission === 'download'
        ? 'This binary file cannot be viewed inline in the browser. You can download it using the button above.'
        : 'This binary file is view-only and cannot be rendered directly in the browser.';
    }
    el.previewUnsupportedBox.classList.remove('hidden');
    el.publicPreviewContainer.classList.remove('hidden');
  }
}

function getFileTypeIcon(filename, contentType = '') {
  const ext = (filename || '').split('.').pop().toLowerCase();
  const ct = (contentType || '').toLowerCase();
  if (ct.startsWith('image/') || ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext)) return '🖼️';
  if (ct.startsWith('video/') || ['mp4', 'webm', 'mov', 'mkv'].includes(ext)) return '🎥';
  if (ct.startsWith('audio/') || ['mp3', 'wav', 'ogg', 'm4a'].includes(ext)) return '🎵';
  if (ct === 'application/pdf' || ext === 'pdf') return '📕';
  if (['zip', 'tar', 'gz', 'rar', '7z'].includes(ext)) return '📦';
  if (['py', 'js', 'jsx', 'ts', 'tsx', 'html', 'css', 'json', 'sql', 'sh', 'cpp', 'java', 'rs', 'go', 'md'].includes(ext)) return '💻';
  return '📄';
}

// --- In-App File Preview Modal ---

function closeInAppFilePreview() {
  if (el.modalFilePreview) el.modalFilePreview.classList.add('hidden');

  // Pause and reset media players to avoid continued background playback
  if (el.inappPreviewVideo) {
    el.inappPreviewVideo.pause();
    el.inappPreviewVideo.src = '';
  }
  if (el.inappPreviewAudio) {
    el.inappPreviewAudio.pause();
    el.inappPreviewAudio.src = '';
  }
  if (el.inappPreviewImage) {
    el.inappPreviewImage.src = '';
  }
  if (el.inappPreviewPdfIframe) {
    el.inappPreviewPdfIframe.src = '';
    el.inappPreviewPdfIframe.classList.add('hidden');
  }
  if (el.inappPdfCanvasContainer) {
    el.inappPdfCanvasContainer.classList.remove('hidden');
  }
  if (el.inappPdfRenderCanvas) {
    const ctx = el.inappPdfRenderCanvas.getContext('2d');
    if (ctx) ctx.clearRect(0, 0, el.inappPdfRenderCanvas.width, el.inappPdfRenderCanvas.height);
  }
}

async function openInAppFilePreview(fileId, fileMeta = null) {
  if (!el.modalFilePreview) return;

  // Show modal and loading state
  el.modalFilePreview.classList.remove('hidden');
  if (el.inappPreviewLoading) el.inappPreviewLoading.classList.remove('hidden');

  // Hide all preview sub-boxes initially
  if (el.inappPreviewImageBox) el.inappPreviewImageBox.classList.add('hidden');
  if (el.inappPreviewPdfBox) el.inappPreviewPdfBox.classList.add('hidden');
  if (el.inappPreviewVideoBox) el.inappPreviewVideoBox.classList.add('hidden');
  if (el.inappPreviewAudioBox) el.inappPreviewAudioBox.classList.add('hidden');
  if (el.inappPreviewCodeBox) el.inappPreviewCodeBox.classList.add('hidden');
  if (el.inappPreviewUnsupportedBox) el.inappPreviewUnsupportedBox.classList.add('hidden');

  const filename = fileMeta?.name || 'File Preview';
  const fileSize = fileMeta?.file_size ? formatBytes(fileMeta.file_size) : '';
  const contentType = fileMeta?.content_type || 'application/octet-stream';

  if (el.inappPreviewFilename) el.inappPreviewFilename.textContent = filename;
  if (el.inappPreviewSubmeta) el.inappPreviewSubmeta.textContent = `${fileSize} • ${contentType}`;
  if (el.inappPreviewIcon) el.inappPreviewIcon.textContent = getFileTypeIcon(filename, contentType);

  try {
    // Fetch fresh preview & download presigned URLs
    const data = await apiRequest(`/files/${fileId}/preview`);

    if (el.inappPreviewLoading) el.inappPreviewLoading.classList.add('hidden');

    // Update download button
    if (el.inappPreviewDownloadBtn) {
      el.inappPreviewDownloadBtn.href = data.download_url;
      el.inappPreviewDownloadBtn.setAttribute('download', data.filename);
      el.inappPreviewDownloadBtn.onclick = (e) => {
        e.preventDefault();
        window.location.href = data.download_url;
      };
    }
    if (el.inappBtnFallbackDownload) {
      el.inappBtnFallbackDownload.href = data.download_url;
      el.inappBtnFallbackDownload.setAttribute('download', data.filename);
      el.inappBtnFallbackDownload.onclick = (e) => {
        e.preventDefault();
        window.location.href = data.download_url;
      };
    }

    const ext = (data.filename || '').split('.').pop().toLowerCase();
    const ct = (data.content_type || '').toLowerCase();
    const codeExts = [
      'txt', 'py', 'js', 'jsx', 'ts', 'tsx', 'html', 'htm', 'css', 'scss', 'json', 'md', 'markdown',
      'xml', 'yaml', 'yml', 'sql', 'sh', 'bash', 'zsh', 'c', 'cpp', 'cc', 'h', 'hpp', 'rs', 'go',
      'java', 'rb', 'php', 'ini', 'conf', 'env', 'log', 'csv'
    ];

    // 1. Photo / Image
    if (ct.startsWith('image/') || ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico'].includes(ext)) {
      if (el.inappPreviewImageBox && el.inappPreviewImage) {
        el.inappPreviewImage.src = data.preview_url;
        el.inappPreviewImageBox.classList.remove('hidden');
      }
      return;
    }

    // 2. Video Player
    if (ct.startsWith('video/') || ['mp4', 'webm', 'mov', 'ogg', 'mkv'].includes(ext)) {
      if (el.inappPreviewVideoBox && el.inappPreviewVideo) {
        el.inappPreviewVideo.src = data.preview_url;
        el.inappPreviewVideoBox.classList.remove('hidden');
      }
      return;
    }

    // 3. Audio Player
    if (ct.startsWith('audio/') || ['mp3', 'wav', 'ogg', 'm4a', 'aac', 'flac'].includes(ext)) {
      if (el.inappPreviewAudioBox && el.inappPreviewAudio) {
        el.inappPreviewAudio.src = data.preview_url;
        el.inappPreviewAudioBox.classList.remove('hidden');
      }
      return;
    }

    // 4. PDF Document via PDF.js Canvas
    if (ct === 'application/pdf' || ext === 'pdf') {
      if (el.inappPreviewPdfBox) {
        el.inappPreviewPdfBox.classList.remove('hidden');

        if (window.pdfjsLib && el.inappPdfRenderCanvas) {
          try {
            window.pdfjsLib.GlobalWorkerOptions.workerSrc =
              'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

            const loadingTask = window.pdfjsLib.getDocument({
              url: data.preview_url,
              withCredentials: false,
            });
            const pdfDoc = await loadingTask.promise;

            let inappCurrentPage = 1;
            const inappTotalPages = pdfDoc.numPages;
            let inappUserZoom = null;
            let inappPageRendering = false;
            let inappPageNumPending = null;

            if (el.inappPdfPageCount) el.inappPdfPageCount.textContent = inappTotalPages;

            const renderInappPdfPage = async (num) => {
              inappPageRendering = true;
              const page = await pdfDoc.getPage(num);

              let scale = inappUserZoom;
              if (!scale) {
                const containerWidth = (el.inappPdfCanvasContainer ? el.inappPdfCanvasContainer.clientWidth : 750) - 32;
                const unscaledViewport = page.getViewport({ scale: 1.0 });
                scale = containerWidth / unscaledViewport.width;
                scale = Math.max(0.4, Math.min(scale, 1.6));
              }

              const viewport = page.getViewport({ scale });
              const canvas = el.inappPdfRenderCanvas;
              const ctx = canvas.getContext('2d');
              canvas.height = viewport.height;
              canvas.width = viewport.width;

              const renderContext = { canvasContext: ctx, viewport: viewport };
              const renderTask = page.render(renderContext);

              await renderTask.promise;
              inappPageRendering = false;
              if (inappPageNumPending !== null) {
                const pending = inappPageNumPending;
                inappPageNumPending = null;
                renderInappPdfPage(pending);
              }

              if (el.inappPdfPageNum) el.inappPdfPageNum.textContent = num;
              if (el.inappBtnPdfPrev) el.inappBtnPdfPrev.disabled = num <= 1;
              if (el.inappBtnPdfNext) el.inappBtnPdfNext.disabled = num >= inappTotalPages;
            };

            const queueRenderInappPage = (num) => {
              if (inappPageRendering) {
                inappPageNumPending = num;
              } else {
                renderInappPdfPage(num);
              }
            };

            if (el.inappBtnPdfPrev) {
              el.inappBtnPdfPrev.onclick = () => {
                if (inappCurrentPage <= 1) return;
                inappCurrentPage--;
                queueRenderInappPage(inappCurrentPage);
              };
            }
            if (el.inappBtnPdfNext) {
              el.inappBtnPdfNext.onclick = () => {
                if (inappCurrentPage >= inappTotalPages) return;
                inappCurrentPage++;
                queueRenderInappPage(inappCurrentPage);
              };
            }
            if (el.inappBtnPdfZoomIn) {
              el.inappBtnPdfZoomIn.onclick = () => {
                const cur = inappUserZoom || 1.0;
                inappUserZoom = Math.min(2.5, +(cur + 0.2).toFixed(2));
                queueRenderInappPage(inappCurrentPage);
              };
            }
            if (el.inappBtnPdfZoomOut) {
              el.inappBtnPdfZoomOut.onclick = () => {
                const cur = inappUserZoom || 1.0;
                inappUserZoom = Math.max(0.4, +(cur - 0.2).toFixed(2));
                queueRenderInappPage(inappCurrentPage);
              };
            }
            if (el.inappBtnPdfZoomFit) {
              el.inappBtnPdfZoomFit.onclick = () => {
                inappUserZoom = null;
                queueRenderInappPage(inappCurrentPage);
              };
            }

            await renderInappPdfPage(1);
          } catch (pdfErr) {
            console.error('In-app PDF render failed, falling back to iframe:', pdfErr);
            if (el.inappPdfCanvasContainer) el.inappPdfCanvasContainer.classList.add('hidden');
            if (el.inappPreviewPdfIframe) {
              el.inappPreviewPdfIframe.src = data.preview_url;
              el.inappPreviewPdfIframe.classList.remove('hidden');
            }
          }
        } else if (el.inappPreviewPdfIframe) {
          el.inappPreviewPdfIframe.src = data.preview_url;
          el.inappPreviewPdfIframe.classList.remove('hidden');
        }
      }
      return;
    }

    // 5. Code & Text File
    if (ct.startsWith('text/') || ct === 'application/json' || ct === 'application/javascript' || ct === 'application/xml' || codeExts.includes(ext)) {
      if (el.inappPreviewCodeBox) {
        if (el.inappCodeFilename) el.inappCodeFilename.textContent = data.filename;

        let langIcon = '📜';
        if (ext === 'py') langIcon = '🐍';
        else if (['js', 'jsx', 'ts', 'tsx'].includes(ext)) langIcon = '🟨';
        else if (['html', 'htm'].includes(ext)) langIcon = '🌐';
        else if (['css', 'scss'].includes(ext)) langIcon = '🎨';
        else if (ext === 'json') langIcon = '📦';
        else if (ext === 'md' || ext === 'markdown') langIcon = '📝';
        else if (ext === 'sql') langIcon = '🗄️';
        else if (['sh', 'bash', 'zsh'].includes(ext)) langIcon = '💻';
        else if (['c', 'cpp', 'cc', 'h', 'hpp'].includes(ext)) langIcon = '⚙️';
        else if (ext === 'rs') langIcon = '🦀';
        else if (ext === 'go') langIcon = '🐹';
        else if (ext === 'java') langIcon = '☕';
        if (el.inappCodeLangIcon) el.inappCodeLangIcon.textContent = langIcon;

        if (el.inappCodeContentText) el.inappCodeContentText.textContent = 'Loading file contents...';
        if (el.inappCodeLineNumbers) el.inappCodeLineNumbers.textContent = '1';

        el.inappPreviewCodeBox.classList.remove('hidden');

        try {
          const resp = await fetch(data.preview_url);
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          const text = await resp.text();

          if (el.inappCodeContentText) el.inappCodeContentText.textContent = text;
          const lines = text.split('\n');
          const lineCount = lines.length;
          if (el.inappCodeLinesBadge) {
            el.inappCodeLinesBadge.textContent = `${lineCount} line${lineCount === 1 ? '' : 's'}`;
          }

          const lineNums = [];
          for (let i = 1; i <= lineCount; i++) {
            lineNums.push(i);
          }
          if (el.inappCodeLineNumbers) el.inappCodeLineNumbers.textContent = lineNums.join('\n');

          if (el.inappBtnCopyCode) {
            el.inappBtnCopyCode.onclick = () => {
              navigator.clipboard.writeText(text);
              showToast('Code copied to clipboard!', 'success');
            };
          }
        } catch (err) {
          if (el.inappCodeContentText) el.inappCodeContentText.textContent = `Error loading contents: ${err.message}`;
        }
      }
      return;
    }

    // 6. Unsupported Binary Fallback
    if (el.inappPreviewUnsupportedBox) {
      el.inappPreviewUnsupportedBox.classList.remove('hidden');
    }
  } catch (err) {
    showToast(`Failed to load file preview: ${err.message}`, 'error');
    closeInAppFilePreview();
  }
}

async function loadPublicFolderContents(shareToken, subfolderId = null) {
  try {
    const url = subfolderId
      ? `/shares/public/${shareToken}?subfolder_id=${subfolderId}`
      : `/shares/public/${shareToken}`;
    const data = await apiRequest(url);
    renderPublicFolderContents(shareToken, data);
  } catch (err) {
    showToast(`Error loading folder: ${err.message}`, 'error');
  }
}

function renderPublicFolderContents(shareToken, data) {
  if (!el.publicFolderContents) return;
  el.publicFolderContents.classList.remove('hidden');

  if (el.btnDownloadEntireFolder) {
    if (data.permission === 'download') {
      el.btnDownloadEntireFolder.classList.remove('hidden');
      el.btnDownloadEntireFolder.onclick = async (e) => {
        e.preventDefault();
        const origText = el.btnDownloadEntireFolder.textContent;
        try {
          el.btnDownloadEntireFolder.disabled = true;
          el.btnDownloadEntireFolder.textContent = '⏳ Preparing ZIP...';
          showToast('Packaging folder ZIP archive, please wait...', 'info');

          const response = await fetch(`/api/v1/shares/public/${shareToken}/download-folder`);
          if (!response.ok) {
            let errMsg = `Server returned status ${response.status}`;
            try {
              const errBody = await response.json();
              if (errBody?.error?.message) {
                errMsg = errBody.error.message;
              } else if (errBody?.detail) {
                errMsg = errBody.detail;
              } else if (errBody?.message) {
                errMsg = errBody.message;
              }
            } catch (_) {}
            throw new Error(errMsg);
          }

          const resData = await response.json();
          if (resData && resData.download_url) {
            const tempAnchor = document.createElement('a');
            tempAnchor.href = resData.download_url;
            tempAnchor.setAttribute('download', resData.filename || `${data.name || 'folder'}.zip`);
            document.body.appendChild(tempAnchor);
            tempAnchor.click();
            document.body.removeChild(tempAnchor);
            showToast('Folder ZIP download started!', 'success');
          } else {
            throw new Error('Download URL not returned by server');
          }
        } catch (err) {
          showToast(`Download failed: ${err.message}`, 'error');
        } finally {
          el.btnDownloadEntireFolder.disabled = false;
          el.btnDownloadEntireFolder.textContent = origText;
        }
      };
    } else {
      el.btnDownloadEntireFolder.classList.add('hidden');
      el.btnDownloadEntireFolder.onclick = null;
    }
  }

  // Breadcrumbs
  if (el.publicFolderBreadcrumbs) {
    el.publicFolderBreadcrumbs.innerHTML = '';
    const crumbs = data.breadcrumbs || [{ id: data.folder_id, name: data.name }];
    crumbs.forEach((crumb, idx) => {
      const isLast = idx === crumbs.length - 1;
      const span = document.createElement('span');
      if (isLast) {
        span.className = 'public-breadcrumb-item active';
        span.textContent = `📁 ${crumb.name}`;
      } else {
        span.className = 'public-breadcrumb-item';
        span.textContent = `📁 ${crumb.name}`;
        span.onclick = () => loadPublicFolderContents(shareToken, crumb.id);
      }
      el.publicFolderBreadcrumbs.appendChild(span);

      if (!isLast) {
        const sep = document.createElement('span');
        sep.className = 'public-breadcrumb-separator';
        sep.textContent = '/';
        el.publicFolderBreadcrumbs.appendChild(sep);
      }
    });
  }

  // Files & Subfolders Table
  if (el.publicFolderTbody) {
    el.publicFolderTbody.innerHTML = '';
    const subfolders = data.subfolders || [];
    const files = data.files || [];

    if (subfolders.length === 0 && files.length === 0) {
      if (el.publicFolderEmpty) el.publicFolderEmpty.classList.remove('hidden');
    } else {
      if (el.publicFolderEmpty) el.publicFolderEmpty.classList.add('hidden');

      // 1. Render Subfolders
      subfolders.forEach((sf) => {
        const tr = document.createElement('tr');
        tr.className = 'folder-row';
        tr.innerHTML = `
          <td>
            <div class="public-item-cell">
              <span class="file-icon">📁</span>
              <span class="file-name-text"><strong>${escapeHtml(sf.name)}</strong></span>
            </div>
          </td>
          <td>—</td>
          <td>—</td>
          <td class="text-right">
            <button type="button" class="btn btn-outline btn-xs btn-open-subfolder">Open ➔</button>
          </td>
        `;
        tr.onclick = () => loadPublicFolderContents(shareToken, sf.id);
        el.publicFolderTbody.appendChild(tr);
      });

      // 2. Render Files
      files.forEach((f) => {
        const tr = document.createElement('tr');
        tr.className = 'file-row';
        const icon = getFileTypeIcon(f.name, f.content_type);
        const downloadBtnHtml = data.permission === 'download'
          ? `<button type="button" class="btn btn-primary btn-xs btn-dl-file" title="Download">📥 Download</button>`
          : '';

        tr.innerHTML = `
          <td>
            <div class="public-item-cell" style="cursor: pointer;" title="Preview ${escapeHtml(f.name)}">
              <span class="file-icon">${icon}</span>
              <span class="file-name-text">${escapeHtml(f.name)}</span>
            </div>
          </td>
          <td>${formatBytes(f.file_size || 0)}</td>
          <td>${f.created_at ? formatDate(f.created_at) : '—'}</td>
          <td class="text-right">
            <div class="public-action-btns">
              <button type="button" class="btn btn-outline btn-xs btn-prev-file" title="Preview">👁️ Preview</button>
              ${downloadBtnHtml}
            </div>
          </td>
        `;

        // Click row / preview button to preview
        const onPreview = () => previewFileInSharedFolder(shareToken, f.id, data.permission);
        tr.querySelector('.public-item-cell').onclick = onPreview;
        tr.querySelector('.btn-prev-file').onclick = (e) => {
          e.stopPropagation();
          onPreview();
        };

        if (data.permission === 'download') {
          const dlBtn = tr.querySelector('.btn-dl-file');
          if (dlBtn) {
            dlBtn.onclick = async (e) => {
              e.stopPropagation();
              await downloadFileInSharedFolder(shareToken, f.id, f.name);
            };
          }
        }

        el.publicFolderTbody.appendChild(tr);
      });
    }
  }
}

async function previewFileInSharedFolder(shareToken, fileId, permission) {
  try {
    const fileData = await apiRequest(`/shares/public/${shareToken}/file/${fileId}`);
    if (el.publicPreviewContainer) el.publicPreviewContainer.classList.remove('hidden');
    if (el.publicPreviewTopbar) el.publicPreviewTopbar.classList.remove('hidden');
    if (el.previewActiveName) el.previewActiveName.textContent = `Viewing: ${fileData.name}`;

    if (fileData.download_url) {
      el.publicDownloadBtn.href = fileData.download_url;
      el.publicDownloadBtn.setAttribute('download', fileData.name);
      el.publicDownloadBtn.classList.remove('hidden');
      if (el.publicShareActions) el.publicShareActions.classList.remove('hidden');
    } else {
      el.publicDownloadBtn.classList.add('hidden');
      if (el.publicShareActions) el.publicShareActions.classList.add('hidden');
    }

    await renderPublicSharePreview(fileData);
    el.publicPreviewContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (err) {
    showToast(`Error previewing file: ${err.message}`, 'error');
  }
}

async function downloadFileInSharedFolder(shareToken, fileId, fileName) {
  try {
    const fileData = await apiRequest(`/shares/public/${shareToken}/file/${fileId}`);
    if (fileData.download_url) {
      const a = document.createElement('a');
      a.href = fileData.download_url;
      a.setAttribute('download', fileName);
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      showToast(`Downloading ${fileName}...`, 'info');
    } else {
      showToast('Download is not permitted for this folder.', 'warning');
    }
  } catch (err) {
    showToast(`Download failed: ${err.message}`, 'error');
  }
}

async function checkPublicShareRoute() {
  const hash = window.location.hash;
  const searchParams = new URLSearchParams(window.location.search);
  let shareToken = searchParams.get('share');

  if (!shareToken && hash.startsWith('#share=')) {
    shareToken = hash.replace('#share=', '');
  }

  if (shareToken) {
    el.authView.classList.add('hidden');
    el.dashboardView.classList.add('hidden');
    el.publicShareView.classList.remove('hidden');
    el.publicShareLoading.classList.remove('hidden');
    el.publicShareContent.classList.add('hidden');

    try {
      const data = await apiRequest(`/shares/public/${shareToken}`);
      el.publicShareLoading.classList.add('hidden');
      el.publicShareContent.classList.remove('hidden');

      // Wire close preview button
      if (el.btnClosePublicPreview) {
        el.btnClosePublicPreview.onclick = () => {
          if (el.publicPreviewContainer) el.publicPreviewContainer.classList.add('hidden');
          if (el.publicPreviewTopbar) el.publicPreviewTopbar.classList.add('hidden');
          if (el.publicShareActions) el.publicShareActions.classList.add('hidden');
          if (el.previewPdfElem) el.previewPdfElem.src = '';
          if (el.pdfCanvasContainer) el.pdfCanvasContainer.classList.add('hidden');
          currentPdfDoc = null;
          pdfUserZoom = null;
        };
      }

      // Sharer Attribution
      if (el.publicShareAuthorText) {
        if (data.shared_by_name) {
          const emailPart = data.shared_by_email && data.shared_by_email !== data.shared_by_name
            ? ` (${data.shared_by_email})`
            : '';
          el.publicShareAuthorText.textContent = `Shared by ${data.shared_by_name}${emailPart}`;
        } else {
          el.publicShareAuthorText.textContent = 'Shared by CloudBox User';
        }
      }

      // Permission Badge
      if (el.publicSharePermBadge) {
        if (data.permission === 'view') {
          el.publicSharePermBadge.className = 'badge badge-view';
          el.publicSharePermBadge.textContent = '👁️ View Only';
        } else {
          el.publicSharePermBadge.className = 'badge badge-download';
          el.publicSharePermBadge.textContent = '📥 View & Download';
        }
      }

      el.publicShareName.textContent = data.name;
      el.publicShareMeta.textContent = `Size: ${formatBytes(data.file_size || 0)} | Type: ${data.content_type || data.item_type}`;

      if (data.item_type === 'folder') {
        el.publicShareIcon.textContent = '📁';
        if (el.publicShareThumb) el.publicShareThumb.classList.add('hidden');
        if (el.publicShareIcon) el.publicShareIcon.classList.remove('hidden');
        if (el.publicShareActions) el.publicShareActions.classList.add('hidden');
        if (el.publicPreviewContainer) el.publicPreviewContainer.classList.add('hidden');
        renderPublicFolderContents(shareToken, data);
      } else {
        if (el.publicFolderContents) el.publicFolderContents.classList.add('hidden');
        if (el.publicPreviewTopbar) el.publicPreviewTopbar.classList.add('hidden');

        const isImage = (data.content_type && data.content_type.startsWith('image/')) ||
                        /\.(jpe?g|png|gif|webp|svg|bmp|ico)$/i.test(data.name || '');

        if (isImage) {
          // Do not show top thumbnail or large icon for images - directly show the full preview below
          if (el.publicShareThumb) el.publicShareThumb.classList.add('hidden');
          if (el.publicShareIcon) el.publicShareIcon.classList.add('hidden');
        } else if (data.thumbnail_url) {
          el.publicShareThumb.src = data.thumbnail_url;
          el.publicShareThumb.classList.remove('hidden');
          el.publicShareIcon.classList.add('hidden');
        } else {
          el.publicShareIcon.textContent = getFileTypeIcon(data.name, data.content_type);
          el.publicShareIcon.classList.remove('hidden');
          if (el.publicShareThumb) el.publicShareThumb.classList.add('hidden');
        }

        if (data.download_url) {
          el.publicDownloadBtn.href = data.download_url;
          el.publicDownloadBtn.setAttribute('download', data.name);
          el.publicDownloadBtn.classList.remove('hidden');
          if (el.publicShareActions) el.publicShareActions.classList.remove('hidden');
        } else {
          el.publicDownloadBtn.classList.add('hidden');
          if (el.publicShareActions) el.publicShareActions.classList.add('hidden');
        }

        // Render In-Browser Preview
        await renderPublicSharePreview(data);
      }
    } catch (err) {
      el.publicShareLoading.textContent = `Error accessing shared link: ${err.message}`;
    }
    return true;
  }
  return false;
}

// --- App Initialization ---

async function initApp() {
  if (await checkPublicShareRoute()) return;

  if (!state.token) {
    resetAppState();
    setAuthenticatedState(false);
    return;
  }

  try {
    await Promise.all([
      loadUserProfile(),
      loadSidebarTree(true),
      loadFolderView(null),
    ]);
    setAuthenticatedState(true);
  } catch (err) {
    console.error('Failed to initialize app session:', err);
    handleLogout();
  }
}

// --- Event Listeners ---

// Tab switching & Password Reset views
function switchToLoginTab() {
  if (el.authTabHeader) el.authTabHeader.classList.remove('hidden');
  el.tabLogin.classList.add('active');
  el.tabSignup.classList.remove('active');
  el.loginForm.classList.remove('hidden');
  el.signupForm.classList.add('hidden');
  if (el.forgotPasswordForm) el.forgotPasswordForm.classList.add('hidden');
}

function switchToSignupTab() {
  if (el.authTabHeader) el.authTabHeader.classList.remove('hidden');
  el.tabSignup.classList.add('active');
  el.tabLogin.classList.remove('active');
  el.signupForm.classList.remove('hidden');
  el.loginForm.classList.add('hidden');
  if (el.forgotPasswordForm) el.forgotPasswordForm.classList.add('hidden');
}

function switchToForgotPasswordTab() {
  if (el.authTabHeader) el.authTabHeader.classList.add('hidden');
  el.loginForm.classList.add('hidden');
  el.signupForm.classList.add('hidden');
  if (el.forgotPasswordForm) {
    el.forgotPasswordForm.classList.remove('hidden');
    if (el.loginEmail && el.loginEmail.value) {
      el.resetEmail.value = el.loginEmail.value;
    }
    el.resetNewPassword.value = '';
    el.resetConfirmPassword.value = '';
    el.resetOtp.value = '';
    if (el.resetEmail.value) {
      el.resetNewPassword.focus();
    } else {
      el.resetEmail.focus();
    }
  }
}

el.tabLogin.onclick = switchToLoginTab;
el.tabSignup.onclick = switchToSignupTab;
if (el.linkForgotPassword) {
  el.linkForgotPassword.onclick = (e) => {
    e.preventDefault();
    switchToForgotPasswordTab();
  };
}
if (el.linkBackToLogin) {
  el.linkBackToLogin.onclick = (e) => {
    e.preventDefault();
    switchToLoginTab();
  };
}

// OTP 5-minute Countdown and Cooldown Timers
let otpCountdownInterval = null;
let otpCooldownInterval = null;

function startOtpCountdown(seconds = 300) {
  clearInterval(otpCountdownInterval);
  if (!el.otpTimerInfo || !el.otpCountdown) return;

  el.otpTimerInfo.classList.remove('hidden');
  let remaining = seconds;

  function renderTimer() {
    const mins = Math.floor(remaining / 60).toString().padStart(2, '0');
    const secs = (remaining % 60).toString().padStart(2, '0');
    el.otpCountdown.textContent = `${mins}:${secs}`;

    if (remaining <= 0) {
      clearInterval(otpCountdownInterval);
      el.otpCountdown.textContent = '00:00 (Expired)';
      showToast('Verification code has expired. Please request a new OTP.', 'error');
    }
    remaining--;
  }

  renderTimer();
  otpCountdownInterval = setInterval(renderTimer, 1000);
}

function startOtpCooldown(cooldownSeconds = 60) {
  clearInterval(otpCooldownInterval);
  if (!el.btnSendOtp) return;

  el.btnSendOtp.disabled = true;
  let cooldown = cooldownSeconds;

  function renderCooldown() {
    if (cooldown <= 0) {
      clearInterval(otpCooldownInterval);
      el.btnSendOtp.disabled = false;
      el.btnSendOtp.textContent = 'Resend OTP';
      return;
    }
    el.btnSendOtp.textContent = `Resend (${cooldown}s)`;
    cooldown--;
  }

  renderCooldown();
  otpCooldownInterval = setInterval(renderCooldown, 1000);
}

// Send OTP Button
if (el.btnSendOtp) {
  el.btnSendOtp.onclick = async () => {
    const email = el.resetEmail ? el.resetEmail.value.trim() : '';
    if (!email || !email.includes('@')) {
      showToast('Please enter your account email address first', 'error');
      if (el.resetEmail) el.resetEmail.focus();
      return;
    }

    try {
      el.btnSendOtp.disabled = true;
      el.btnSendOtp.textContent = 'Sending...';

      const data = await apiRequest('/auth/forgot-password/send-otp', {
        method: 'POST',
        body: JSON.stringify({ email }),
      });

      if (data.delivered === false) {
        showToast(data.message || 'Email delivery failed. Code logged.', 'warning', 8000);
        if (data.debug_otp && el.resetOtp) {
          el.resetOtp.value = data.debug_otp;
        }
      } else {
        showToast(data.message || 'OTP sent! Valid for 5 minutes.', 'success');
        if (data.debug_otp && el.resetOtp && !el.resetOtp.value) {
          el.resetOtp.value = data.debug_otp;
        }
      }
      startOtpCountdown(data.expires_in_seconds || 300);
      startOtpCooldown(60);
      if (el.resetOtp) el.resetOtp.focus();
    } catch (err) {
      showToast(err.message, 'error');
      el.btnSendOtp.disabled = false;
      el.btnSendOtp.textContent = 'Send OTP';
    }
  };
}

// Forgot Password Form Submit
if (el.forgotPasswordForm) {
  el.forgotPasswordForm.onsubmit = async (e) => {
    e.preventDefault();
    const email = el.resetEmail ? el.resetEmail.value.trim() : '';
    const newPassword = el.resetNewPassword ? el.resetNewPassword.value : '';
    const confirmPassword = el.resetConfirmPassword ? el.resetConfirmPassword.value : '';
    const otp = el.resetOtp ? el.resetOtp.value.trim() : '';

    if (!email || !email.includes('@')) {
      showToast('Please enter a valid email address', 'error');
      if (el.resetEmail) el.resetEmail.focus();
      return;
    }
    if (!newPassword || newPassword.length < 6) {
      showToast('New password must be at least 6 characters', 'error');
      if (el.resetNewPassword) el.resetNewPassword.focus();
      return;
    }
    if (newPassword !== confirmPassword) {
      showToast('New passwords do not match!', 'error');
      if (el.resetConfirmPassword) el.resetConfirmPassword.focus();
      return;
    }
    if (!otp || otp.length !== 6 || !/^\d{6}$/.test(otp)) {
      showToast('Please enter the 6-digit verification code sent to your email', 'error');
      if (el.resetOtp) el.resetOtp.focus();
      return;
    }

    try {
      if (el.btnSubmitResetPassword) {
        el.btnSubmitResetPassword.disabled = true;
        el.btnSubmitResetPassword.textContent = 'Resetting...';
      }

      const res = await apiRequest('/auth/forgot-password/reset', {
        method: 'POST',
        body: JSON.stringify({
          email,
          new_password: newPassword,
          confirm_password: confirmPassword,
          otp,
        }),
      });

      showToast(res.message || 'Password reset successfully! Please log in.', 'success');
      clearInterval(otpCountdownInterval);
      clearInterval(otpCooldownInterval);
      if (el.otpTimerInfo) el.otpTimerInfo.classList.add('hidden');
      if (el.btnSendOtp) {
        el.btnSendOtp.disabled = false;
        el.btnSendOtp.textContent = 'Send OTP';
      }

      switchToLoginTab();
      if (el.loginEmail) el.loginEmail.value = email;
      if (el.loginPassword) {
        el.loginPassword.value = '';
        el.loginPassword.focus();
      }
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      if (el.btnSubmitResetPassword) {
        el.btnSubmitResetPassword.disabled = false;
        el.btnSubmitResetPassword.textContent = 'Reset Password';
      }
    }
  };
}

// Forms
el.loginForm.onsubmit = (e) => {
  e.preventDefault();
  handleLogin(el.loginEmail.value, el.loginPassword.value);
};
el.signupForm.onsubmit = (e) => {
  e.preventDefault();
  handleSignup(el.signupEmail.value, el.signupPassword.value, el.signupName.value);
};
el.logoutBtn.onclick = handleLogout;
if (el.btnDeleteAccount) el.btnDeleteAccount.onclick = handleDeleteAccount;
if (el.btnMobileDeleteAccount) {
  el.btnMobileDeleteAccount.onclick = () => {
    closeMobileSidebar();
    handleDeleteAccount();
  };
}
if (el.refreshBtn) {
  el.refreshBtn.onclick = () => handleRefreshWithFeedback(
    el.refreshBtn,
    async () => {
      await Promise.all([
        loadUserProfile(),
        loadSidebarTree(true),
        loadFolderView(state.currentFolderId),
      ]);
    },
    'Files & folder view refreshed!'
  );
}

// Navigation
function switchSection(section) {
  closeMobileSidebar();
  el.fileManagerSection.classList.add('hidden');
  el.sharesManagerSection.classList.add('hidden');
  el.trashManagerSection.classList.add('hidden');
  if (el.adminManagerSection) el.adminManagerSection.classList.add('hidden');

  el.navAllFiles.classList.remove('active');
  el.navSharesManager.classList.remove('active');
  el.navTrashManager.classList.remove('active');
  if (el.navAdminDashboard) el.navAdminDashboard.classList.remove('active');

  if (section === 'files') {
    el.fileManagerSection.classList.remove('hidden');
    el.navAllFiles.classList.add('active');
  } else if (section === 'shares') {
    el.sharesManagerSection.classList.remove('hidden');
    el.navSharesManager.classList.add('active');
  } else if (section === 'trash') {
    el.trashManagerSection.classList.remove('hidden');
    el.navTrashManager.classList.add('active');
  } else if (section === 'admin') {
    if (el.adminManagerSection) el.adminManagerSection.classList.remove('hidden');
    if (el.navAdminDashboard) el.navAdminDashboard.classList.add('active');
  }
}

el.navAllFiles.onclick = async () => {
  switchSection('files');
  await loadUserProfile();
  await loadFolderView(state.currentFolderId);
};

async function loadSharesView() {
  switchSection('shares');
  await loadUserProfile();

  try {
    const params = new URLSearchParams();
    if (state.sharesSearch) params.set('search', state.sharesSearch);
    if (state.sharesStatus) params.set('status', state.sharesStatus);
    if (state.sharesType) params.set('item_type', state.sharesType);
    if (state.sharesPermission) params.set('permission', state.sharesPermission);
    params.set('sort_by', state.sharesSortBy);
    params.set('order', state.sharesOrder);

    const shares = await apiRequest(`/shares/?${params.toString()}`);
    el.sharesTbody.innerHTML = '';
    updateSortHeaders('.sortable-shares-th', state.sharesSortBy, state.sharesOrder);

    if (!shares || shares.length === 0) {
      if (el.emptySharesState) el.emptySharesState.classList.remove('hidden');
      return;
    }
    if (el.emptySharesState) el.emptySharesState.classList.add('hidden');

    shares.forEach((s) => {
      const type = s.file_id ? '📄 File' : '📁 Folder';
      const expiresText = s.expires_at ? formatDate(s.expires_at) : 'Permanent';

      let statusBadge = '';
      if (!s.is_active) {
        statusBadge = '<span class="file-badge badge-error">Inactive</span>';
      } else if (s.expires_at && new Date(s.expires_at) < new Date()) {
        statusBadge = '<span class="file-badge badge-error">Expired</span>';
      } else {
        statusBadge = '<span class="file-badge badge-ready">Active</span>';
      }

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>
          <div class="file-cell">
            <strong>${s.item_name}</strong>
          </div>
        </td>
        <td>${type}</td>
        <td><span style="text-transform: capitalize;">${s.permission}</span></td>
        <td>${expiresText}</td>
        <td>${statusBadge}</td>
        <td>${s.access_count} view${s.access_count === 1 ? '' : 's'}</td>
        <td class="text-right">
          <button class="btn btn-outline btn-sm btn-copy-share" data-url="${window.location.origin}/#share=${s.share_token}" title="Copy Link">📋 Copy</button>
          <button class="btn btn-danger btn-sm btn-revoke" data-id="${s.id}" title="Revoke Link">Revoke</button>
        </td>
      `;
      tr.querySelector('.btn-copy-share').onclick = () => {
        const fullShareUrl = `${window.location.origin}/#share=${s.share_token}`;
        navigator.clipboard.writeText(fullShareUrl);
        showToast('Share link copied to clipboard!', 'success');
      };
      tr.querySelector('.btn-revoke').onclick = async () => {
        await apiRequest(`/shares/${s.id}`, { method: 'DELETE' });
        showToast('Revoked share link');
        await loadSharesView();
      };
      el.sharesTbody.appendChild(tr);
    });
  } catch (err) {
    showToast(err.message, 'error');
  }
}

el.navSharesManager.onclick = loadSharesView;

if (el.refreshSharesBtn) {
  el.refreshSharesBtn.onclick = () => handleRefreshWithFeedback(
    el.refreshSharesBtn,
    async () => {
      await loadSharesView();
    },
    'Shared links refreshed!'
  );
}

if (el.trashRefreshBtn) {
  el.trashRefreshBtn.onclick = () => handleRefreshWithFeedback(
    el.trashRefreshBtn,
    async () => {
      await loadTrashView();
    },
    'Trash refreshed!'
  );
}

async function loadTrashView() {
  switchSection('trash');
  await loadUserProfile();
  try {
    const fParams = new URLSearchParams();
    if (state.trashSearch) fParams.set('search', state.trashSearch);
    fParams.set('sort_by', state.trashSortBy === 'file_size' ? 'name' : state.trashSortBy);
    fParams.set('order', state.trashOrder);

    const fileParams = new URLSearchParams();
    if (state.trashSearch) fileParams.set('search', state.trashSearch);
    if (state.trashType && state.trashType !== 'folders_only' && state.trashType !== 'files_only') {
      fileParams.set('file_type', state.trashType);
    }
    fileParams.set('sort_by', state.trashSortBy);
    fileParams.set('order', state.trashOrder);

    const fetchFolders = state.trashType !== 'files_only' && (state.trashType === '' || state.trashType === 'folders_only');
    const fetchFiles = state.trashType !== 'folders_only';

    const [trashFolders, trashFiles] = await Promise.all([
      fetchFolders ? apiRequest(`/folders/trash?${fParams.toString()}`).catch(() => []) : Promise.resolve([]),
      fetchFiles ? apiRequest(`/files/trash?${fileParams.toString()}`).catch(() => []) : Promise.resolve([]),
    ]);

    el.trashTbody.innerHTML = '';
    updateSortHeaders('.sortable-trash-th', state.trashSortBy, state.trashOrder);

    const totalItems = (trashFolders?.length || 0) + (trashFiles?.length || 0);

    if (totalItems === 0) {
      el.emptyTrashState.classList.remove('hidden');
      return;
    }
    el.emptyTrashState.classList.add('hidden');

    // 1. Render Folders in Trash
    (trashFolders || []).forEach((f) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>
          <div class="file-name-cell">
            <span class="file-icon">📁</span>
            <strong>${f.name}</strong>
          </div>
        </td>
        <td>— (Folder)</td>
        <td>${formatDate(f.deleted_at)}</td>
        <td>
          <span style="display:inline-block; padding:0.2rem 0.5rem; background:#fee2e2; color:#991b1b; border-radius:4px; font-size:0.75rem; font-weight:600;">
            ⏳ ${f.days_until_purge} day${f.days_until_purge === 1 ? '' : 's'} remaining
          </span>
        </td>
        <td class="text-right">
          <button class="btn btn-outline btn-sm btn-restore" title="Restore folder and active contents">♻️ Restore</button>
          <button class="btn btn-danger btn-sm btn-perm-delete" title="Delete folder and all contents permanently">🗑️ Delete Forever</button>
        </td>
      `;

      tr.querySelector('.btn-restore').onclick = async () => {
        try {
          await apiRequest(`/folders/${f.id}/restore`, { method: 'POST' });
          showToast(`Restored folder '${f.name}'`, 'success');
          await loadSidebarTree(true);
          await Promise.all([
            loadUserProfile(),
            loadTrashView(),
          ]);
        } catch (err) {
          showToast(err.message, 'error');
        }
      };

      tr.querySelector('.btn-perm-delete').onclick = async () => {
        const confirmed = await showConfirmModal({
          title: 'Delete Folder Permanently',
          message: `Permanently delete folder '${f.name}' and ALL contents immediately? This cannot be undone.`,
          confirmText: 'Delete Forever',
          confirmClass: 'btn-danger',
          icon: '⚠️',
        });
        if (!confirmed) return;

        try {
          await apiRequest(`/folders/${f.id}/permanent`, { method: 'DELETE' });
          showToast(`Permanently deleted folder '${f.name}'`, 'success');
          await loadSidebarTree(true);
          await Promise.all([
            loadUserProfile(),
            loadTrashView(),
          ]);
        } catch (err) {
          showToast(err.message, 'error');
        }
      };

      el.trashTbody.appendChild(tr);
    });

    // 2. Render Files in Trash
    (trashFiles || []).forEach((f) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>
          <div class="file-name-cell">
            <span class="file-icon">📄</span>
            <strong>${f.name}</strong>
          </div>
        </td>
        <td>${formatBytes(f.file_size)}</td>
        <td>${formatDate(f.deleted_at)}</td>
        <td>
          <span style="display:inline-block; padding:0.2rem 0.5rem; background:#fee2e2; color:#991b1b; border-radius:4px; font-size:0.75rem; font-weight:600;">
            ⏳ ${f.days_until_purge} day${f.days_until_purge === 1 ? '' : 's'} remaining
          </span>
        </td>
        <td class="text-right">
          <button class="btn btn-outline btn-sm btn-restore" title="Restore back to active drive">♻️ Restore</button>
          <button class="btn btn-danger btn-sm btn-perm-delete" title="Delete permanently now">🗑️ Delete Forever</button>
        </td>
      `;

      tr.querySelector('.btn-restore').onclick = async () => {
        try {
          await apiRequest(`/files/${f.id}/restore`, { method: 'POST' });
          showToast(`Restored '${f.name}'`, 'success');
          await loadUserProfile();
          await loadTrashView();
        } catch (err) {
          showToast(err.message, 'error');
        }
      };

      tr.querySelector('.btn-perm-delete').onclick = async () => {
        const confirmed = await showConfirmModal({
          title: 'Delete File Permanently',
          message: `Permanently purge '${f.name}' immediately? This cannot be undone.`,
          confirmText: 'Delete Forever',
          confirmClass: 'btn-danger',
          icon: '⚠️',
        });
        if (!confirmed) return;

        try {
          await apiRequest(`/files/${f.id}/permanent`, { method: 'DELETE' });
          showToast(`Permanently purged '${f.name}'`, 'success');
          await loadUserProfile();
          await loadTrashView();
        } catch (err) {
          showToast(err.message, 'error');
        }
      };

      el.trashTbody.appendChild(tr);
    });
  } catch (err) {
    showToast(err.message, 'error');
  }
}

el.navTrashManager.onclick = loadTrashView;

// --- Admin Dashboard & User Management ---

async function loadAdminView() {
  switchSection('admin');
  await loadUserProfile();
  await Promise.all([loadAdminStats(), loadAdminUsers()]);
}

async function loadAdminStats() {
  try {
    const stats = await apiRequest('/admin/stats');
    if (el.statTotalUsers) el.statTotalUsers.textContent = stats.total_users;
    if (el.statActiveUsers) el.statActiveUsers.textContent = stats.active_users;
    if (el.statStorageUsed) el.statStorageUsed.textContent = formatBytes(stats.total_storage_used_bytes);
    if (el.statStorageQuota) el.statStorageQuota.textContent = formatBytes(stats.total_storage_quota_bytes);
    if (el.statTotalFiles) el.statTotalFiles.textContent = stats.total_files;
    if (el.statTotalBlobs) el.statTotalBlobs.textContent = stats.total_blobs;
    if (el.statTotalShares) el.statTotalShares.textContent = stats.total_shares;

    // 5GB AWS S3 Free Tier calculation
    const freeTierBytes = 5 * 1024 * 1024 * 1024; // 5 GB
    const freeTierPct = ((stats.total_storage_used_bytes / freeTierBytes) * 100).toFixed(1);
    if (el.statS3FreeTierPercent) {
      el.statS3FreeTierPercent.textContent = `${freeTierPct}%`;
      if (freeTierPct > 80) el.statS3FreeTierPercent.style.color = 'var(--danger)';
      else if (freeTierPct > 50) el.statS3FreeTierPercent.style.color = 'var(--warning)';
      else el.statS3FreeTierPercent.style.color = 'var(--primary)';
    }
  } catch (err) {
    showToast(`Error loading admin stats: ${err.message}`, 'error');
  }
}

async function loadAdminUsers() {
  try {
    const params = new URLSearchParams();
    if (state.adminSearch) params.set('search', state.adminSearch);
    if (state.adminStatus) params.set('status', state.adminStatus);
    if (state.adminRole) params.set('role', state.adminRole);
    if (state.adminSortBy) params.set('sort_by', state.adminSortBy);
    if (state.adminOrder) params.set('order', state.adminOrder);

    const users = await apiRequest(`/admin/users?${params.toString()}`);
    el.adminUsersTbody.innerHTML = '';

    if (!users || users.length === 0) {
      el.adminUsersEmpty.classList.remove('hidden');
      return;
    }
    el.adminUsersEmpty.classList.add('hidden');

    users.forEach((u) => {
      const tr = document.createElement('tr');
      const isCurrentAdmin = state.user && state.user.id === u.id;

      const roleBadge = u.is_superuser
        ? '<span class="badge badge-admin">👑 Admin</span>'
        : '<span class="badge badge-user">User</span>';

      const statusBadge = u.is_active
        ? '<span class="badge badge-active">Active</span>'
        : '<span class="badge badge-disabled">Disabled</span>';

      const percent = Math.min(100, u.storage_used_percentage || 0);
      let barClass = '';
      if (percent > 90) barClass = 'danger';
      else if (percent > 75) barClass = 'warning';

      tr.innerHTML = `
        <td>
          <div class="file-name-cell">
            <span class="file-icon">👤</span>
            <div>
              <strong>${u.email}</strong>
              ${u.full_name ? `<div style="font-size:0.75rem; color:var(--text-muted);">${u.full_name}</div>` : ''}
              ${isCurrentAdmin ? '<span style="font-size:0.7rem; color:var(--primary); font-weight:600;">(You)</span>' : ''}
            </div>
          </div>
        </td>
        <td>${roleBadge}</td>
        <td>${statusBadge}</td>
        <td>
          <div class="user-quota-cell">
            <div class="user-quota-meta">
              <span>${formatBytes(u.storage_used_bytes)} / ${formatBytes(u.storage_quota_bytes)}</span>
              <span>${percent}%</span>
            </div>
            <div class="user-quota-bar-bg">
              <div class="user-quota-bar-fill ${barClass}" style="width: ${percent}%;"></div>
            </div>
          </div>
        </td>
        <td>
          <span style="font-size:0.8125rem;">📁 ${u.folder_count} &nbsp;|&nbsp; 📄 ${u.file_count}</span>
        </td>
        <td style="font-size:0.8125rem; color:var(--text-muted);">${formatDate(u.created_at)}</td>
        <td class="text-right">
          <button class="btn btn-outline btn-sm btn-edit-quota" title="Edit storage quota">✏️ Quota</button>
          ${
            !isCurrentAdmin
              ? `<button class="btn btn-outline btn-sm btn-toggle-role" title="${u.is_superuser ? 'Demote to regular user' : 'Promote to admin'}">
                  ${u.is_superuser ? 'Demote' : 'Make Admin'}
                </button>
                <button class="btn ${u.is_active ? 'btn-outline-danger' : 'btn-outline'} btn-sm btn-toggle-status" title="${u.is_active ? 'Disable user account' : 'Activate user account'}">
                  ${u.is_active ? 'Disable' : 'Enable'}
                </button>
                <button class="btn btn-outline-danger btn-sm btn-wipe-storage" title="Permanently wipe all files & folders from S3 for this user">
                  💥 Wipe Files
                </button>
                <button class="btn btn-outline-danger btn-sm btn-delete-user" title="Permanently delete user account and all S3 data">
                  🗑️ Delete
                </button>`
              : ''
          }
        </td>
      `;

      // Button Handlers
      tr.querySelector('.btn-edit-quota').onclick = () => openEditQuotaModal(u);

      const btnToggleRole = tr.querySelector('.btn-toggle-role');
      if (btnToggleRole) {
        btnToggleRole.onclick = () => handleToggleUserAdmin(u);
      }

      const btnToggleStatus = tr.querySelector('.btn-toggle-status');
      if (btnToggleStatus) {
        btnToggleStatus.onclick = () => handleToggleUserStatus(u);
      }

      const btnWipeStorage = tr.querySelector('.btn-wipe-storage');
      if (btnWipeStorage) {
        btnWipeStorage.onclick = () => handleWipeUserStorage(u);
      }

      const btnDeleteUser = tr.querySelector('.btn-delete-user');
      if (btnDeleteUser) {
        btnDeleteUser.onclick = () => handleDeleteUser(u);
      }

      el.adminUsersTbody.appendChild(tr);
    });
  } catch (err) {
    showToast(`Error loading users: ${err.message}`, 'error');
  }
}

function openEditQuotaModal(user) {
  el.editQuotaUserId.value = user.id;
  el.editQuotaUserEmail.textContent = `${user.email} (Current: ${formatBytes(user.storage_quota_bytes)})`;
  const currentMb = Math.round(user.storage_quota_bytes / (1024 * 1024));
  el.customQuotaMbInput.value = currentMb;

  // Highlight active preset button if matching
  document.querySelectorAll('.quota-preset-btn').forEach((btn) => {
    btn.classList.toggle('active', parseInt(btn.getAttribute('data-mb'), 10) === currentMb);
  });

  el.modalEditQuota.classList.remove('hidden');
}

async function handleSaveQuota(e) {
  e.preventDefault();
  const userId = el.editQuotaUserId.value;
  const quotaMb = parseInt(el.customQuotaMbInput.value, 10);
  if (!quotaMb || quotaMb < 1) {
    showToast('Please enter a valid quota greater than 1 MB', 'warning');
    return;
  }

  const quotaBytes = quotaMb * 1024 * 1024;
  try {
    await apiRequest(`/admin/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify({ storage_quota_bytes: quotaBytes }),
    });
    showToast(`Updated quota to ${formatBytes(quotaBytes)}`, 'success');
    el.modalEditQuota.classList.add('hidden');
    await loadAdminUsers();
    await loadAdminStats();
    if (state.user && state.user.id === userId) {
      await loadUserProfile();
    }
  } catch (err) {
    showToast(`Failed to update quota: ${err.message}`, 'error');
  }
}

async function handleToggleUserStatus(user) {
  const newStatus = !user.is_active;
  const actionText = newStatus ? 'activate' : 'disable';
  const confirmed = await showConfirmModal({
    title: `${newStatus ? 'Activate' : 'Disable'} User Account`,
    message: `Are you sure you want to ${actionText} login access for '${user.email}'?`,
    confirmText: newStatus ? 'Activate Account' : 'Disable Account',
    confirmClass: newStatus ? 'btn-primary' : 'btn-danger',
  });
  if (!confirmed) return;

  try {
    await apiRequest(`/admin/users/${user.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_active: newStatus }),
    });
    showToast(`User account ${newStatus ? 'activated' : 'disabled'}`, 'success');
    await loadAdminUsers();
    await loadAdminStats();
  } catch (err) {
    showToast(`Failed to update user: ${err.message}`, 'error');
  }
}

async function handleToggleUserAdmin(user) {
  const newRole = !user.is_superuser;
  const actionText = newRole ? 'grant admin privileges to' : 'revoke admin privileges from';
  const confirmed = await showConfirmModal({
    title: `${newRole ? 'Promote' : 'Demote'} Administrator`,
    message: `Are you sure you want to ${actionText} '${user.email}'?`,
    confirmText: newRole ? 'Promote to Admin' : 'Demote to User',
    confirmClass: newRole ? 'btn-primary' : 'btn-danger',
  });
  if (!confirmed) return;

  try {
    await apiRequest(`/admin/users/${user.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_superuser: newRole }),
    });
    showToast(`Updated privileges for '${user.email}'`, 'success');
    await loadAdminUsers();
    await loadAdminStats();
  } catch (err) {
    showToast(`Failed to update user: ${err.message}`, 'error');
  }
}

async function handleWipeUserStorage(user) {
  const confirmed = await showConfirmModal({
    title: `Wipe S3 Storage: ${user.email}`,
    message: `Are you sure you want to permanently delete ALL files and folders for '${user.email}' from Amazon S3? This will immediately free ${formatBytes(user.storage_used_bytes)} of cloud storage. The user account will remain active with 0 bytes used.`,
    confirmText: 'Wipe All Files from S3',
    confirmClass: 'btn-danger',
  });
  if (!confirmed) return;

  try {
    const res = await apiRequest(`/admin/users/${user.id}/wipe-storage`, {
      method: 'POST',
    });
    showToast(res.message || `Wiped storage for ${user.email}`, 'success');
    await loadAdminUsers();
    await loadAdminStats();
  } catch (err) {
    showToast(`Failed to wipe storage: ${err.message}`, 'error');
  }
}

async function handleDeleteUser(user) {
  const confirmed = await showConfirmModal({
    title: `Delete User Account: ${user.email}`,
    message: `Are you sure you want to permanently delete user '${user.email}' and ALL of their files from Amazon S3? This action cannot be undone.`,
    confirmText: 'Delete User & All Files',
    confirmClass: 'btn-danger',
  });
  if (!confirmed) return;

  try {
    const res = await apiRequest(`/admin/users/${user.id}`, {
      method: 'DELETE',
    });
    showToast(res.message || `Deleted user account '${user.email}'`, 'success');
    await loadAdminUsers();
    await loadAdminStats();
  } catch (err) {
    showToast(`Failed to delete user: ${err.message}`, 'error');
  }
}

async function handleReclaimAllS3Space() {
  const confirmed = await showConfirmModal({
    title: '🚨 Emergency AWS Free Tier Reclaim',
    message: 'Are you sure you want to permanently delete ALL files and folders for ALL non-admin users from Amazon S3? This will wipe out all user data to protect your 5GB AWS Free Tier limit. User accounts will stay active with 0 bytes used.',
    confirmText: 'Reclaim All S3 Space',
    confirmClass: 'btn-danger',
  });
  if (!confirmed) return;

  try {
    const res = await apiRequest('/admin/wipe-all-storage', {
      method: 'POST',
    });
    showToast(res.message || 'Successfully reclaimed S3 storage!', 'success');
    await loadAdminUsers();
    await loadAdminStats();
  } catch (err) {
    showToast(`Failed to reclaim space: ${err.message}`, 'error');
  }
}

if (el.btnAdminReclaimAll) {
  el.btnAdminReclaimAll.onclick = handleReclaimAllS3Space;
}


if (el.navAdminDashboard) el.navAdminDashboard.onclick = loadAdminView;
if (el.btnRefreshAdmin) {
  el.btnRefreshAdmin.onclick = () => handleRefreshWithFeedback(
    el.btnRefreshAdmin,
    async () => {
      await loadAdminStats();
      await loadAdminUsers();
    },
    'Admin metrics & users refreshed!'
  );
}

let adminSearchTimer = null;
if (el.adminSearchInput) {
  el.adminSearchInput.oninput = () => {
    state.adminSearch = el.adminSearchInput.value.trim();
    if (el.adminSearchClear) {
      el.adminSearchClear.classList.toggle('hidden', !state.adminSearch);
    }
    clearTimeout(adminSearchTimer);
    adminSearchTimer = setTimeout(() => {
      loadAdminUsers();
    }, 250);
  };
}
if (el.adminSearchClear) {
  el.adminSearchClear.onclick = () => {
    el.adminSearchInput.value = '';
    state.adminSearch = '';
    el.adminSearchClear.classList.add('hidden');
    loadAdminUsers();
  };
}
if (el.adminStatusFilter) {
  el.adminStatusFilter.onchange = () => {
    state.adminStatus = el.adminStatusFilter.value;
    loadAdminUsers();
  };
}
if (el.adminRoleFilter) {
  el.adminRoleFilter.onchange = () => {
    state.adminRole = el.adminRoleFilter.value;
    loadAdminUsers();
  };
}
if (el.adminSortSelect) {
  el.adminSortSelect.onchange = () => {
    const [sortBy, order] = el.adminSortSelect.value.split(':');
    state.adminSortBy = sortBy;
    state.adminOrder = order || 'desc';
    loadAdminUsers();
  };
}

if (el.formEditQuota) {
  el.formEditQuota.onsubmit = handleSaveQuota;
}
document.querySelectorAll('.quota-preset-btn').forEach((btn) => {
  btn.onclick = () => {
    const mb = btn.getAttribute('data-mb');
    el.customQuotaMbInput.value = mb;
    document.querySelectorAll('.quota-preset-btn').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
  };
});

// --- Filter & Sort Event Listeners ---

// 1. Files / Drive Toolbar
let filesSearchTimer = null;
if (el.filesSearchInput) {
  el.filesSearchInput.oninput = () => {
    state.filesSearch = el.filesSearchInput.value.trim();
    if (el.filesSearchClear) {
      el.filesSearchClear.classList.toggle('hidden', !state.filesSearch);
    }
    clearTimeout(filesSearchTimer);
    filesSearchTimer = setTimeout(() => {
      loadFolderView(state.currentFolderId);
    }, 250);
  };
}
if (el.filesSearchClear) {
  el.filesSearchClear.onclick = () => {
    el.filesSearchInput.value = '';
    state.filesSearch = '';
    el.filesSearchClear.classList.add('hidden');
    loadFolderView(state.currentFolderId);
  };
}
if (el.filesTypeFilter) {
  el.filesTypeFilter.onchange = () => {
    state.filesType = el.filesTypeFilter.value;
    loadFolderView(state.currentFolderId);
  };
}
if (el.filesSortSelect) {
  el.filesSortSelect.onchange = () => {
    const [sb, ord] = el.filesSortSelect.value.split(':');
    state.filesSortBy = sb;
    state.filesOrder = ord;
    loadFolderView(state.currentFolderId);
  };
}
document.querySelectorAll('.sortable-th').forEach((th) => {
  th.onclick = () => {
    const key = th.getAttribute('data-sort');
    if (state.filesSortBy === key) {
      state.filesOrder = state.filesOrder === 'asc' ? 'desc' : 'asc';
    } else {
      state.filesSortBy = key;
      state.filesOrder = key === 'name' ? 'asc' : 'desc';
    }
    if (el.filesSortSelect) {
      el.filesSortSelect.value = `${state.filesSortBy}:${state.filesOrder}`;
    }
    loadFolderView(state.currentFolderId);
  };
});

// 2. Shares Toolbar
let sharesSearchTimer = null;
if (el.sharesSearchInput) {
  el.sharesSearchInput.oninput = () => {
    state.sharesSearch = el.sharesSearchInput.value.trim();
    if (el.sharesSearchClear) {
      el.sharesSearchClear.classList.toggle('hidden', !state.sharesSearch);
    }
    clearTimeout(sharesSearchTimer);
    sharesSearchTimer = setTimeout(() => {
      loadSharesView();
    }, 250);
  };
}
if (el.sharesSearchClear) {
  el.sharesSearchClear.onclick = () => {
    el.sharesSearchInput.value = '';
    state.sharesSearch = '';
    el.sharesSearchClear.classList.add('hidden');
    loadSharesView();
  };
}
if (el.sharesStatusFilter) {
  el.sharesStatusFilter.onchange = () => {
    state.sharesStatus = el.sharesStatusFilter.value;
    loadSharesView();
  };
}
if (el.sharesTypeFilter) {
  el.sharesTypeFilter.onchange = () => {
    state.sharesType = el.sharesTypeFilter.value;
    loadSharesView();
  };
}
if (el.sharesPermissionFilter) {
  el.sharesPermissionFilter.onchange = () => {
    state.sharesPermission = el.sharesPermissionFilter.value;
    loadSharesView();
  };
}
if (el.sharesSortSelect) {
  el.sharesSortSelect.onchange = () => {
    const [sb, ord] = el.sharesSortSelect.value.split(':');
    state.sharesSortBy = sb;
    state.sharesOrder = ord;
    loadSharesView();
  };
}
document.querySelectorAll('.sortable-shares-th').forEach((th) => {
  th.onclick = () => {
    const key = th.getAttribute('data-sort');
    if (state.sharesSortBy === key) {
      state.sharesOrder = state.sharesOrder === 'asc' ? 'desc' : 'asc';
    } else {
      state.sharesSortBy = key;
      state.sharesOrder = key === 'name' ? 'asc' : 'desc';
    }
    if (el.sharesSortSelect) {
      el.sharesSortSelect.value = `${state.sharesSortBy}:${state.sharesOrder}`;
    }
    loadSharesView();
  };
});

// 3. Trash Toolbar
let trashSearchTimer = null;
if (el.trashSearchInput) {
  el.trashSearchInput.oninput = () => {
    state.trashSearch = el.trashSearchInput.value.trim();
    if (el.trashSearchClear) {
      el.trashSearchClear.classList.toggle('hidden', !state.trashSearch);
    }
    clearTimeout(trashSearchTimer);
    trashSearchTimer = setTimeout(() => {
      loadTrashView();
    }, 250);
  };
}
if (el.trashSearchClear) {
  el.trashSearchClear.onclick = () => {
    el.trashSearchInput.value = '';
    state.trashSearch = '';
    el.trashSearchClear.classList.add('hidden');
    loadTrashView();
  };
}
if (el.trashTypeFilter) {
  el.trashTypeFilter.onchange = () => {
    state.trashType = el.trashTypeFilter.value;
    loadTrashView();
  };
}
if (el.trashSortSelect) {
  el.trashSortSelect.onchange = () => {
    const [sb, ord] = el.trashSortSelect.value.split(':');
    state.trashSortBy = sb;
    state.trashOrder = ord;
    loadTrashView();
  };
}
document.querySelectorAll('.sortable-trash-th').forEach((th) => {
  th.onclick = () => {
    const key = th.getAttribute('data-sort');
    if (state.trashSortBy === key) {
      state.trashOrder = state.trashOrder === 'asc' ? 'desc' : 'asc';
    } else {
      state.trashSortBy = key;
      state.trashOrder = key === 'name' ? 'asc' : 'desc';
    }
    if (el.trashSortSelect) {
      el.trashSortSelect.value = `${state.trashSortBy}:${state.trashOrder}`;
    }
    loadTrashView();
  };
});

el.btnRestoreAllTrash.onclick = async () => {
  const confirmed = await showConfirmModal({
    title: 'Restore All Items',
    message: 'Restore all files and folders in Trash back to your active drive?',
    confirmText: 'Restore All',
    confirmClass: 'btn-primary',
    icon: '♻️',
  });
  if (!confirmed) return;

  try {
    const res = await apiRequest('/files/trash/restore-all', { method: 'POST' });
    showToast(res.message || 'All trash restored', 'success');
    state.folderTreeData = null;
    await loadSidebarTree(true);
    await Promise.all([
      loadUserProfile(),
      loadTrashView(),
    ]);
  } catch (err) {
    showToast(err.message, 'error');
  }
};

el.btnEmptyTrash.onclick = async () => {
  const confirmed = await showConfirmModal({
    title: 'Empty Trash Bin',
    message: 'Permanently delete ALL files and folders in Trash forever? This cannot be undone.',
    confirmText: 'Empty Trash',
    confirmClass: 'btn-danger',
    icon: '⚠️',
  });
  if (!confirmed) return;

  try {
    const res = await apiRequest('/files/trash/empty', { method: 'DELETE' });
    showToast(res.message || 'Trash emptied successfully', 'success');
    state.folderTreeData = null;
    await loadSidebarTree(true);
    await Promise.all([
      loadUserProfile(),
      loadTrashView(),
    ]);
  } catch (err) {
    showToast(err.message, 'error');
  }
};

el.btnPurgeTrash.onclick = async () => {
  try {
    const res = await apiRequest('/files/purge-expired?retention_days=14', { method: 'POST' });
    showToast(res.message || 'Retention cleanup completed', 'success');
    state.folderTreeData = null;
    await loadSidebarTree(true);
    await loadTrashView();
  } catch (err) {
    showToast(err.message, 'error');
  }
};

el.btnTrashContents.onclick = async () => {
  const folderName = state.currentFolderId
    ? (state.breadcrumbs[state.breadcrumbs.length - 1]?.name || 'this folder')
    : 'the Root directory';
  const confirmed = await showConfirmModal({
    title: 'Trash Folder Contents',
    message: `Move all files and subfolders in ${folderName} to Trash?`,
    confirmText: 'Move All to Trash',
    confirmClass: 'btn-danger',
    icon: '🗑️',
  });
  if (!confirmed) return;

  try {
    const url = state.currentFolderId
      ? `/folders/trash-contents?folder_id=${state.currentFolderId}`
      : `/folders/trash-contents`;
    const res = await apiRequest(url, { method: 'POST' });
    showToast(res.message || 'Folder contents moved to trash', 'success');
    state.folderTreeData = null;
    await loadSidebarTree(true);
    await Promise.all([
      loadUserProfile(),
      loadFolderView(state.currentFolderId),
    ]);
  } catch (err) {
    showToast(err.message, 'error');
  }
};

// Upload trigger
el.sidebarUploadBtn.onclick = () => {
  closeMobileSidebar();
  el.fileInput.click();
};
el.fileInput.onchange = async (e) => {
  const files = Array.from(e.target.files);
  for (const file of files) {
    await uploadFilePipeline(file);
  }
  el.fileInput.value = '';
};

// New folder modals
el.newFolderModalBtn.onclick = () => el.modalNewFolder.classList.remove('hidden');
el.quickNewFolderBtn.onclick = () => {
  closeMobileSidebar();
  el.modalNewFolder.classList.remove('hidden');
};
el.formNewFolder.onsubmit = async (e) => {
  e.preventDefault();
  const name = el.folderNameInput.value.trim();
  if (!name) return;
  try {
    await apiRequest('/folders/', {
      method: 'POST',
      body: JSON.stringify({ name, parent_id: state.currentFolderId }),
    });
    showToast(`Folder '${name}' created`, 'success');
    el.folderNameInput.value = '';
    el.modalNewFolder.classList.add('hidden');
    state.folderTreeData = null;
    await Promise.all([
      loadSidebarTree(true),
      loadFolderView(state.currentFolderId),
    ]);
  } catch (err) {
    showToast(err.message, 'error');
  }
};

if (el.btnRenameCurrentFolder) {
  el.btnRenameCurrentFolder.onclick = () => {
    if (!state.currentFolderId) return;
    const currentCrumb = state.breadcrumbs[state.breadcrumbs.length - 1];
    const folderName = currentCrumb ? currentCrumb.name : 'Current Folder';
    openRenameModal('folder', state.currentFolderId, folderName);
  };
}

if (el.btnMoveCurrentFolder) {
  el.btnMoveCurrentFolder.onclick = () => {
    if (!state.currentFolderId) return;
    const currentCrumb = state.breadcrumbs[state.breadcrumbs.length - 1];
    const folderName = currentCrumb ? currentCrumb.name : 'Current Folder';
    const parentCrumb = state.breadcrumbs.length >= 2 ? state.breadcrumbs[state.breadcrumbs.length - 2] : null;
    const parentId = parentCrumb ? parentCrumb.id : null;
    openMoveModal('folder', state.currentFolderId, folderName, parentId);
  };
}

el.btnDeleteCurrentFolder.onclick = () => {
  if (!state.currentFolderId) return;
  const currentCrumb = state.breadcrumbs[state.breadcrumbs.length - 1];
  const folderName = currentCrumb ? currentCrumb.name : 'Current Folder';
  deleteFolder(state.currentFolderId, folderName);
};

// Rename & Move form submissions
if (el.formRename) {
  el.formRename.onsubmit = handleRenameSubmit;
}
if (el.formMove) {
  el.formMove.onsubmit = handleMoveSubmit;
}
if (el.moveDestinationSelect) {
  el.moveDestinationSelect.onchange = () => {
    const selectedOpt = el.moveDestinationSelect.selectedOptions[0];
    if (el.btnSubmitMove) {
      el.btnSubmitMove.disabled = !selectedOpt || selectedOpt.disabled;
    }
  };
}

// Share form
el.formShare.onsubmit = handleGenerateShareLink;
el.sharePermission.onchange = updateShareModalState;
if (el.shareExpiryPreset) {
  el.shareExpiryPreset.onchange = () => {
    if (el.shareExpiryPreset.value === 'custom') {
      el.shareCustomExpiryGroup.classList.remove('hidden');
    } else {
      el.shareCustomExpiryGroup.classList.add('hidden');
    }
    updateShareModalState();
  };
}
if (el.shareCustomExpiry) {
  el.shareCustomExpiry.oninput = updateShareModalState;
}
el.copyShareBtn.onclick = () => {
  navigator.clipboard.writeText(el.shareLinkOutput.value);
  showToast('Copied to clipboard!', 'success');
};

// Modal close buttons
document.querySelectorAll('.modal-close').forEach((btn) => {
  btn.onclick = () => {
    btn.closest('.modal').classList.add('hidden');
  };
});

// Dismiss modals on backdrop click
document.querySelectorAll('.modal').forEach((modal) => {
  modal.addEventListener('click', (e) => {
    if (e.target === modal && modal !== el.modalConfirm && modal !== el.modalFilePreview) {
      modal.classList.add('hidden');
    }
  });
});

// In-app file preview close handlers
if (el.btnCloseInappPreview) {
  el.btnCloseInappPreview.onclick = (e) => {
    e.preventDefault();
    closeInAppFilePreview();
  };
}
if (el.modalFilePreview) {
  el.modalFilePreview.onclick = (e) => {
    if (e.target === el.modalFilePreview) {
      closeInAppFilePreview();
    }
  };
}

// Mobile Drawer Event Listeners
if (el.mobileMenuBtn) el.mobileMenuBtn.onclick = openMobileSidebar;
if (el.sidebarCloseBtn) el.sidebarCloseBtn.onclick = closeMobileSidebar;
if (el.sidebarBackdrop) el.sidebarBackdrop.onclick = closeMobileSidebar;

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeMobileSidebar();
    closeInAppFilePreview();
    document.querySelectorAll('.modal:not(.hidden)').forEach((m) => {
      if (m !== el.modalConfirm) {
        m.classList.add('hidden');
      }
    });
  }
});

if (el.backToLoginBtn) {
  el.backToLoginBtn.onclick = () => {
    window.location.hash = '';
    window.location.search = '';
    initApp();
  };
}

window.addEventListener('hashchange', checkPublicShareRoute);
window.addEventListener('DOMContentLoaded', initApp);

