// Obrigado - Frontend Reactive Controller

let networkInstance = null;
let currentGraphLayout = 'hierarchical-ud'; // 'hierarchical-ud', 'hierarchical-lr', 'hierarchical-dag', 'organic'
let currentGraphSpacing = 'standard';       // 'compact', 'standard', 'spacious'
let cachedGraphRawData = null;
let isolatedSubtreeNodeId = null;
let currentSphereFilter = 'all';
let currentBriefingType = 'morning';
let inspectedNodeId = null;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

// --- Global Toast Notification System ---

function showToast(message, type = 'info', durationMs = 3000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = "pointer-events-auto flex items-center space-x-2.5 px-4 py-3 rounded-xl shadow-2xl border text-xs font-medium transition-all duration-300 transform translate-y-[-8px] opacity-0";

  let iconName = 'info';
  if (type === 'success') {
    toast.className += " bg-slate-900/95 text-emerald-300 border-emerald-500/50 shadow-emerald-950/40";
    iconName = 'check-circle-2';
  } else if (type === 'error') {
    toast.className += " bg-slate-900/95 text-rose-300 border-rose-500/50 shadow-rose-950/40";
    iconName = 'alert-triangle';
  } else if (type === 'warning') {
    toast.className += " bg-slate-900/95 text-amber-300 border-amber-500/50 shadow-amber-950/40";
    iconName = 'alert-circle';
  } else {
    toast.className += " bg-slate-900/95 text-indigo-300 border-indigo-500/50 shadow-indigo-950/40";
    iconName = 'sparkles';
  }

  toast.innerHTML = `
    <i data-lucide="${iconName}" class="w-4 h-4 shrink-0"></i>
    <span class="flex-1 leading-snug">${escapeHtml(message)}</span>
  `;

  container.appendChild(toast);
  if (typeof lucide !== 'undefined') lucide.createIcons();

  requestAnimationFrame(() => {
    toast.classList.remove('translate-y-[-8px]', 'opacity-0');
    toast.classList.add('translate-y-0', 'opacity-100');
  });

  setTimeout(() => {
    toast.classList.add('opacity-0', 'scale-95');
    setTimeout(() => toast.remove(), 300);
  }, durationMs);
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Initialize on Load
document.addEventListener('DOMContentLoaded', () => {
  loadAuthUserProfile();
  initServiceWorker();
  lucide.createIcons();
  setupKeyboardShortcuts();
  loadInitialData();
  checkUrlAlerts();
});

async function loadAuthUserProfile() {
  try {
    const res = await fetch('/api/auth/status');
    if (res.status === 401) {
      window.location.href = '/login';
      return;
    }
    const data = await res.json();
    if (!data.authenticated && data.auth_enabled) {
      window.location.href = '/login';
      return;
    }

    const user = data.user;
    if (user) {
      const nameEl = document.getElementById('user-name-display');
      const emailEl = document.getElementById('user-email-display');
      const avatarImg = document.getElementById('user-avatar');
      const avatarFallback = document.getElementById('user-avatar-fallback');

      if (nameEl) nameEl.innerText = user.name || user.email.split('@')[0];
      if (emailEl) emailEl.innerText = user.email;

      if (user.picture && avatarImg && avatarFallback) {
        avatarImg.src = user.picture;
        avatarImg.classList.remove('hidden');
        avatarFallback.classList.add('hidden');
      } else if (avatarFallback) {
        avatarFallback.innerText = (user.name || user.email || 'U').charAt(0).toUpperCase();
      }
    }
  } catch (err) {
    console.warn("Could not load user auth status:", err);
  }
}

function toggleUserDropdown() {
  const menu = document.getElementById('user-dropdown-menu');
  if (menu) {
    menu.classList.toggle('hidden');
  }
}

// Close user dropdown if clicked outside
document.addEventListener('click', (e) => {
  const container = document.getElementById('user-profile-container');
  const menu = document.getElementById('user-dropdown-menu');
  if (container && menu && !container.contains(e.target)) {
    menu.classList.add('hidden');
  }
});

async function handleLogout() {
  try {
    const res = await fetch('/api/auth/logout', { method: 'POST' });
    const data = await res.json();
    window.location.href = data.redirect || '/login';
  } catch (err) {
    window.location.href = '/login';
  }
}

function checkUrlAlerts() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('calendar_linked') === 'true') {
    showToast("🎉 Google Calendar linked successfully! Events are actively synchronized.", "success", 5000);
    window.history.replaceState({}, document.title, window.location.pathname);
  } else if (params.get('calendar_error') === 'true') {
    showToast("❌ Google Calendar connection could not be completed.", "error", 5000);
    window.history.replaceState({}, document.title, window.location.pathname);
  }
}

function setupKeyboardShortcuts() {
  const noteInput = document.getElementById('note-input');
  if (noteInput) {
    noteInput.addEventListener('keydown', (e) => {
      // Enter without Shift submits; Shift+Enter creates a new line
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleUnifiedSubmit();
      }
    });
  }
}

function switchTab(tabName) {
  const views = ['capture', 'history', 'graph', 'matrix', 'people', 'briefing', 'analytics', 'prompts', 'settings'];
  views.forEach(v => {
    const el = document.getElementById(`view-${v}`);
    const btn = document.getElementById(`tab-btn-${v}`);
    if (el) el.classList.add('hidden');
    if (btn) {
      btn.classList.remove('bg-indigo-600', 'text-white', 'shadow-sm');
      btn.classList.add('text-slate-400');
    }
  });

  const activeView = document.getElementById(`view-${tabName}`);
  const activeBtn = document.getElementById(`tab-btn-${tabName}`);
  if (activeView) activeView.classList.remove('hidden');
  if (activeBtn) {
    activeBtn.classList.add('bg-indigo-600', 'text-white', 'shadow-sm');
    activeBtn.classList.remove('text-slate-400');
  }

  // Refresh data on tab switch
  if (tabName === 'history') {
    loadRecentCaptures();
  } else if (tabName === 'graph') {
    setTimeout(loadGraphData, 50);
  } else if (tabName === 'matrix') {
    loadMatrixData();
  } else if (tabName === 'people') {
    loadPeople();
  } else if (tabName === 'briefing') {
    loadLatestBriefing(currentBriefingType);
  } else if (tabName === 'analytics') {
    loadTokenAnalytics();
  } else if (tabName === 'prompts') {
    loadPrompts();
  } else if (tabName === 'settings') {
    loadSettings();
  }

  lucide.createIcons();
}

async function loadInitialData() {
  initChatStream();
  loadCalendarPill();
  loadPromptsBadge();
  loadRecentCaptures();
  loadPendingElicitations();
}

// --- Conversational Chat Stream & Elicitation State ---
let activeElicitation = null;
let pendingElicitationsQueue = [];
let promptedElicitationIds = new Set();
let chatMsgCounter = 0;

function initChatStream() {
  const container = document.getElementById('chat-stream-container');
  if (!container || container.children.length > 0) return;

  container.innerHTML = `
    <div class="flex items-start space-x-2.5 max-w-[95%] sm:max-w-[85%] animate-fadeIn">
      <div class="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-tr from-indigo-600 to-purple-600 flex items-center justify-center text-white shrink-0 shadow-md">
        <i data-lucide="bot" class="w-4 h-4"></i>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-2xl rounded-tl-sm p-3.5 sm:p-4 text-xs sm:text-sm text-slate-200 shadow-xl space-y-2 leading-relaxed">
        <div class="flex items-center space-x-1.5">
          <span class="font-bold text-slate-100">Obrigado Assistant</span>
          <span class="text-[10px] px-1.5 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800/60 font-semibold">Executive AI</span>
        </div>
        <p class="text-slate-300">
          Hi! Type or dictate your notes, deliverables, meetings, or thoughts below. I will automatically extract commitments, map project graphs, schedule focus blocks, and ask any clarifying questions right here.
        </p>
      </div>
    </div>
  `;
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function scrollChatToBottom() {
  const container = document.getElementById('chat-stream-container');
  if (container) {
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
  }
}

function appendUserChatMessage(text) {
  const container = document.getElementById('chat-stream-container');
  if (!container) return;

  const msgDiv = document.createElement('div');
  msgDiv.className = 'flex items-start justify-end space-x-2 max-w-[90%] sm:max-w-[80%] ml-auto animate-fadeIn';
  msgDiv.innerHTML = `
    <div class="bg-indigo-600 text-white rounded-2xl rounded-tr-sm p-3 sm:p-3.5 text-xs sm:text-sm shadow-md leading-relaxed break-words">
      <p class="whitespace-pre-wrap">${escapeHtml(text)}</p>
      <div class="text-[10px] text-indigo-200 text-right mt-1 opacity-75">${new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</div>
    </div>
    <div class="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-indigo-800 flex items-center justify-center text-indigo-200 shrink-0 shadow-sm text-xs font-bold">
      You
    </div>
  `;
  container.appendChild(msgDiv);
  scrollChatToBottom();
}

function showChatTyping(message = "Analyzing note & updating knowledge graph...") {
  const container = document.getElementById('chat-stream-container');
  if (!container) return null;

  const msgId = `chat-typing-${++chatMsgCounter}`;
  const msgDiv = document.createElement('div');
  msgDiv.id = msgId;
  msgDiv.className = 'flex items-start space-x-2.5 max-w-[90%] sm:max-w-[80%] animate-fadeIn';
  msgDiv.innerHTML = `
    <div class="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-tr from-indigo-600 to-purple-600 flex items-center justify-center text-white shrink-0 shadow-md">
      <svg class="animate-spin h-3.5 w-3.5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
      </svg>
    </div>
    <div class="bg-slate-900 border border-slate-800 rounded-2xl rounded-tl-sm px-3.5 py-2.5 text-xs text-indigo-300 flex items-center space-x-2 shadow-md">
      <span>${escapeHtml(message)}</span>
    </div>
  `;
  container.appendChild(msgDiv);
  scrollChatToBottom();
  return msgId;
}

function removeChatMessage(id) {
  if (!id) return;
  const el = document.getElementById(id);
  if (el) el.remove();
}

function appendAssistantErrorBubble(message) {
  const container = document.getElementById('chat-stream-container');
  if (!container) return;

  const msgDiv = document.createElement('div');
  msgDiv.className = 'flex items-start space-x-2.5 max-w-[90%] sm:max-w-[80%] animate-fadeIn';
  msgDiv.innerHTML = `
    <div class="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-rose-900 flex items-center justify-center text-rose-300 shrink-0 shadow-md">
      <i data-lucide="alert-triangle" class="w-4 h-4"></i>
    </div>
    <div class="bg-rose-950/60 border border-rose-800/70 rounded-2xl rounded-tl-sm p-3 text-xs text-rose-200 shadow-md">
      ${escapeHtml(message)}
    </div>
  `;
  container.appendChild(msgDiv);
  if (typeof lucide !== 'undefined') lucide.createIcons();
  scrollChatToBottom();
}

function appendAssistantChatCaptureResult(data, originalText) {
  const container = document.getElementById('chat-stream-container');
  if (!container) return;

  const msgDiv = document.createElement('div');
  msgDiv.className = 'flex items-start space-x-2.5 max-w-[95%] sm:max-w-[85%] animate-fadeIn';

  let entitiesBadges = (data.created_entities || []).map(e => {
    let color = 'bg-slate-800 text-slate-300';
    if (e.node_type === 'project') color = 'bg-blue-950 text-blue-300 border border-blue-800/70';
    if (e.node_type === 'obligation') color = 'bg-amber-950 text-amber-300 border border-amber-800/70';
    if (e.node_type === 'person') color = 'bg-purple-950 text-purple-300 border border-purple-800/70';
    if (e.node_type === 'event') color = 'bg-emerald-950 text-emerald-300 border border-emerald-800/70';
    return `<span class="px-2 py-0.5 rounded-full text-[11px] font-medium ${color}">[${e.node_type}] ${escapeHtml(e.title)}</span>`;
  }).join(' ');

  let calActionsHtml = '';
  if (data.calendar_actions && data.calendar_actions.length > 0) {
    calActionsHtml = data.calendar_actions.map(ca => `
      <div class="flex items-center space-x-2 text-xs text-emerald-400 bg-emerald-950/40 p-2 rounded-lg border border-emerald-800/50">
        <i data-lucide="calendar-check" class="w-3.5 h-3.5 shrink-0"></i>
        <span><strong>Scheduled on Calendar:</strong> ${escapeHtml(ca.decision?.summary || '')} (${escapeHtml(ca.decision?.start_time || '')})</span>
      </div>
    `).join('');
  }

  let peopleHtml = '';
  if (data.people_profiles && data.people_profiles.length > 0) {
    peopleHtml = data.people_profiles.map(prof => `
      <div class="flex items-center space-x-2 text-xs text-purple-300 bg-purple-950/40 p-2 rounded-lg border border-purple-800/50">
        <i data-lucide="user-check" class="w-3.5 h-3.5 text-purple-400 shrink-0"></i>
        <span><strong>Remembered Person:</strong> ${escapeHtml(prof.name)} (${escapeHtml(prof.role_or_title || prof.relationship_type || '')})</span>
      </div>
    `).join('');
  }

  let promptsHtml = '';
  if (data.prompts_generated && data.prompts_generated.length > 0) {
    promptsHtml = data.prompts_generated.map(p => `
      <div class="flex items-center space-x-2 text-xs text-amber-400 bg-amber-950/40 p-2 rounded-lg border border-amber-800/50">
        <i data-lucide="alert-circle" class="w-3.5 h-3.5 shrink-0"></i>
        <span><strong>Nudge:</strong> ${escapeHtml(p.message)}</span>
      </div>
    `).join('');
  }

  let riskHtml = '';
  if (data.workload_risk && data.workload_risk.risk_flagged) {
    const wr = data.workload_risk;
    const badgeColor = wr.risk_level === 'critical' ? 'bg-rose-950 text-rose-300 border-rose-800 animate-pulse' :
                       (wr.risk_level === 'high' ? 'bg-rose-950 text-rose-300 border-rose-800' : 'bg-amber-950 text-amber-300 border-amber-800');
    const recsHtml = (wr.recommendations || []).map(r => `<div class="flex items-start space-x-1.5"><span class="text-rose-400 font-bold shrink-0">•</span><span>${escapeHtml(r)}</span></div>`).join('');
    riskHtml = `
      <div class="p-3 rounded-xl border border-rose-800/70 bg-rose-950/25 space-y-2 text-xs">
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-1.5 font-bold text-rose-300">
            <i data-lucide="alert-triangle" class="w-4 h-4 text-rose-400 shrink-0"></i>
            <span>Workload Overload Warning</span>
          </div>
          <span class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${badgeColor}">${wr.risk_level.toUpperCase()} OVERLOAD</span>
        </div>
        <p class="text-xs text-slate-200 leading-snug">${escapeHtml(wr.summary)}</p>
        <div class="grid grid-cols-3 gap-1.5 py-1 text-[11px] font-mono text-center">
          <div class="bg-slate-900/80 p-1.5 rounded-lg border border-slate-800">
            <span class="block text-[9px] text-slate-400">Stress Load</span>
            <span class="font-bold text-rose-400">${wr.stress_score}%</span>
          </div>
          <div class="bg-slate-900/80 p-1.5 rounded-lg border border-slate-800">
            <span class="block text-[9px] text-slate-400">Q1 Urgent</span>
            <span class="font-bold text-amber-400">${wr.q1_urgent_count}</span>
          </div>
          <div class="bg-slate-900/80 p-1.5 rounded-lg border border-slate-800">
            <span class="block text-[9px] text-slate-400">Collisions</span>
            <span class="font-bold text-amber-400">${wr.colliding_deadlines_count}</span>
          </div>
        </div>
        ${recsHtml ? `<div class="space-y-1 text-[11px] text-slate-300 pt-0.5">${recsHtml}</div>` : ''}
        <div class="pt-1 flex items-center justify-between text-[11px] border-t border-rose-900/40">
          <span class="text-slate-400">Notification pushed to Pixel 10 XL</span>
          <button onclick="switchTab('matrix')" class="text-indigo-400 hover:text-indigo-300 font-medium underline flex items-center space-x-1">
            <span>Eisenhower Review</span>
          </button>
        </div>
      </div>
    `;
  }

  msgDiv.innerHTML = `
    <div class="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-tr from-indigo-600 to-purple-600 flex items-center justify-center text-white shrink-0 shadow-md">
      <i data-lucide="bot" class="w-4 h-4"></i>
    </div>
    <div class="bg-slate-900 border border-slate-800 rounded-2xl rounded-tl-sm p-3.5 sm:p-4 text-xs sm:text-sm text-slate-200 shadow-xl space-y-2.5 w-full leading-relaxed">
      <div class="flex items-center justify-between gap-2 border-b border-slate-800/80 pb-2">
        <span class="text-[10px] uppercase font-bold text-indigo-400 tracking-wider">Note Comprehended</span>
        <span class="text-[10px] text-slate-500 font-mono">${new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
      </div>
      <p class="font-medium text-slate-100 text-xs sm:text-sm">${escapeHtml(data.summary)}</p>
      ${entitiesBadges ? `
        <div class="space-y-1 pt-1">
          <span class="text-[10px] uppercase font-semibold text-slate-400 tracking-wider">Extracted Entities:</span>
          <div class="flex flex-wrap gap-1.5 pt-0.5">${entitiesBadges}</div>
        </div>
      ` : ''}
      ${calActionsHtml}
      ${peopleHtml}
      ${promptsHtml}
      ${riskHtml}
      <div class="text-[11px] text-slate-500 pt-1 border-t border-slate-800/60 flex items-center justify-between">
        <span class="truncate">Triage: ${escapeHtml(data.triage_reasoning || 'Evaluated priority')}</span>
        <button onclick="switchTab('graph')" class="text-indigo-400 hover:text-indigo-300 font-medium flex items-center space-x-1 shrink-0 ml-2">
          <span>View Graph</span>
          <i data-lucide="arrow-right" class="w-3 h-3"></i>
        </button>
      </div>
    </div>
  `;

  container.appendChild(msgDiv);
  if (typeof lucide !== 'undefined') lucide.createIcons();
  scrollChatToBottom();
}

// Workload Overload Risk Banner Controllers
function displayWorkloadRiskBanner(risk) {
  const banner = document.getElementById('workload-risk-banner');
  if (!banner || !risk || !risk.risk_flagged) return;

  const levelBadge = document.getElementById('workload-risk-banner-level');
  const scoreSpan = document.getElementById('workload-risk-banner-score');
  const summaryP = document.getElementById('workload-risk-banner-summary');
  const recsDiv = document.getElementById('workload-risk-banner-recs');
  const icon = document.getElementById('workload-risk-banner-icon');

  if (scoreSpan) scoreSpan.innerText = `Stress Score: ${risk.stress_score}%`;
  if (summaryP) summaryP.innerText = risk.summary;

  let badgeCls = 'px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ';
  let borderCls = 'mt-3 p-3.5 rounded-xl border transition-all duration-300 ';

  if (risk.risk_level === 'critical') {
    badgeCls += 'bg-rose-950 text-rose-300 border border-rose-800 animate-pulse';
    borderCls += 'bg-rose-950/40 border-rose-800 shadow-lg shadow-rose-950/30';
    if (levelBadge) levelBadge.innerText = 'Critical Workload Overload';
    if (icon) icon.className = 'p-1 rounded-lg text-rose-400 bg-rose-950/80 border border-rose-800/80 shrink-0 mt-0.5';
  } else if (risk.risk_level === 'high') {
    badgeCls += 'bg-rose-950 text-rose-300 border border-rose-800';
    borderCls += 'bg-rose-950/30 border-rose-800/70 shadow-md';
    if (levelBadge) levelBadge.innerText = 'High Workload Risk';
    if (icon) icon.className = 'p-1 rounded-lg text-rose-400 bg-rose-950/60 border border-rose-800/50 shrink-0 mt-0.5';
  } else {
    badgeCls += 'bg-amber-950 text-amber-300 border border-amber-800';
    borderCls += 'bg-amber-950/30 border-amber-800/60 shadow-md';
    if (levelBadge) levelBadge.innerText = 'Moderate Overload Risk';
    if (icon) icon.className = 'p-1 rounded-lg text-amber-400 bg-amber-950/60 border border-amber-800/50 shrink-0 mt-0.5';
  }

  if (levelBadge) levelBadge.className = badgeCls;
  banner.className = borderCls;

  if (recsDiv && risk.recommendations) {
    recsDiv.innerHTML = risk.recommendations.map(r => `<div>• ${escapeHtml(r)}</div>`).join('');
  }

  banner.classList.remove('hidden');
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function dismissWorkloadRiskBanner() {
  const banner = document.getElementById('workload-risk-banner');
  if (banner) banner.classList.add('hidden');
}

// Unified Submit: Note capture OR active clarification answer
function handleUnifiedSubmit() {
  const input = document.getElementById('note-input');
  const text = input ? input.value.trim() : '';
  if (!text) {
    input?.focus();
    return;
  }

  if (activeElicitation) {
    const elId = activeElicitation.id;
    const nodeTitle = activeElicitation.node_title;
    submitElicitationAnswerFromChat(elId, text, nodeTitle);
  } else {
    submitNote();
  }
}

function setActiveElicitation(el) {
  activeElicitation = el;
  const bar = document.getElementById('active-el-bar');
  const questionSpan = document.getElementById('active-el-question');
  const input = document.getElementById('note-input');
  const submitText = document.getElementById('submit-note-text');

  if (bar && questionSpan) {
    questionSpan.innerText = `${el.node_title}: ${el.question}`;
    bar.classList.remove('hidden');
  }
  if (input) {
    input.placeholder = `Clarifying "${el.node_title}": type your response and press Enter...`;
    input.focus();
  }
  if (submitText) {
    submitText.innerText = "Send Answer";
  }
}

function cancelActiveElicitation() {
  const bar = document.getElementById('active-el-bar');
  const input = document.getElementById('note-input');
  const submitText = document.getElementById('submit-note-text');

  if (bar) bar.classList.add('hidden');
  if (input) {
    input.placeholder = "Type or dictate a note, task, meeting, or thought... (Press Enter to send)";
  }
  if (submitText) {
    submitText.innerText = "Send";
  }

  if (activeElicitation) {
    pendingElicitationsQueue = pendingElicitationsQueue.filter(item => item.id !== activeElicitation.id);
  }
  activeElicitation = null;

  if (pendingElicitationsQueue.length > 0) {
    setActiveElicitation(pendingElicitationsQueue[0]);
  }
}

async function loadPendingElicitations() {
  try {
    const res = await fetch('/api/elicitations/pending');
    if (res.ok) {
      const data = await res.json();
      renderLiveElicitations(data);
    }
  } catch (err) {}
}

async function loadRecentCaptures() {
  try {
    const res = await fetch('/api/notes/recent?limit=30');
    if (!res.ok) return;
    const items = await res.json();

    const container = document.getElementById('capture-stream');
    if (!container) return;

    container.innerHTML = '';
    if (!items || items.length === 0) {
      container.innerHTML = `
        <div class="text-center py-12 border border-dashed border-slate-800 rounded-2xl bg-slate-900/40">
          <i data-lucide="archive" class="w-8 h-8 text-slate-500 mx-auto mb-2 opacity-80"></i>
          <h4 class="text-sm font-semibold text-slate-300">No Captured Notes Yet</h4>
          <p class="text-xs text-slate-500 mt-1">Capture your first note on the Capture tab to see it archived here.</p>
        </div>
      `;
      if (typeof lucide !== 'undefined') lucide.createIcons();
      return;
    }

    // Display in reverse chronological order (items is newest-first; reversing before prepend keeps newest at top)
    items.slice().reverse().forEach(item => {
      const formatted = {
        summary: item.content.length > 80 ? item.content.slice(0, 80) + '...' : item.content,
        created_entities: item.created_entities || [],
        calendar_actions: [],
        prompts_generated: [],
        people_profiles: [],
        triage_reasoning: 'Extracted and structured in Obrigado',
        elicitations: item.elicitations || []
      };
      renderIngestionResult(formatted, item.content, new Date(item.created_at).toLocaleString());
    });
  } catch (err) {
    console.error("Could not load recent captures:", err);
  }
}

// --- Quick Note Capture & Ingestion ---

async function submitNote() {
  const input = document.getElementById('note-input');
  const content = input?.value.trim();
  if (!content) {
    input?.focus();
    return;
  }

  // Clear input immediately for smooth conversational UX
  input.value = '';

  // Append user bubble to chat stream
  appendUserChatMessage(content);

  // Show inline assistant typing spinner
  const typingId = showChatTyping("Analyzing note with Gemini & updating knowledge graph...");

  const autoCal = document.getElementById('auto-cal-check')?.checked || false;
  const loader = document.getElementById('ingest-loader');
  const submitBtn = document.getElementById('submit-note-btn');
  const submitText = document.getElementById('submit-note-text');
  const submitIcon = document.getElementById('submit-note-icon');

  if (loader) loader.classList.remove('hidden');
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.classList.add('opacity-80', 'cursor-not-allowed');
  }
  if (submitText) submitText.innerText = "Analyzing...";
  if (submitIcon) {
    submitIcon.outerHTML = `
      <svg id="submit-note-icon" class="animate-spin w-3.5 h-3.5 text-white shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
      </svg>
    `;
  }

  showToast("Processing note with Gemini intelligence...", "info", 3000);

  try {
    const res = await fetch('/api/notes/capture', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: content,
        source_type: 'text',
        auto_sync_calendar: autoCal
      })
    });

    if (!res.ok) throw new Error(await res.text());

    const data = await res.json();
    removeChatMessage(typingId);

    // Append to interactive chat stream
    appendAssistantChatCaptureResult(data, content);

    // Also archive to History tab feed
    renderIngestionResult(data, content);

    // Workload Capacity Overload Check
    if (data.workload_risk && data.workload_risk.risk_flagged) {
      displayWorkloadRiskBanner(data.workload_risk);
      const isSevere = ['high', 'critical'].includes(data.workload_risk.risk_level);
      showToast(
        `⚠️ Workload Risk: ${data.workload_risk.risk_level.toUpperCase()} overload risk detected (${data.workload_risk.q1_urgent_count} urgent tasks, ${data.workload_risk.colliding_deadlines_count} collisions)!`,
        isSevere ? 'warning' : 'info',
        6000
      );
    } else {
      dismissWorkloadRiskBanner();
    }

    showToast("✓ Note ingested and knowledge graph updated!", "success", 3500);
    loadPromptsBadge();
    loadGraphData();
    loadMatrixData();
    loadPeople();

    // If elicitations returned, queue and prompt them in chat
    if (data.elicitations && data.elicitations.length > 0) {
      renderLiveElicitations(data.elicitations);
    }
  } catch (err) {
    removeChatMessage(typingId);
    // If connection dropped or timed out, verify if note was already saved by server
    try {
      await new Promise(r => setTimeout(r, 800));
      const checkRes = await fetch('/api/notes/recent?limit=1');
      if (checkRes.ok) {
        const recent = await checkRes.json();
        if (recent.length > 0 && recent[0].content === content) {
          appendAssistantChatCaptureResult(recent[0], content);
          renderIngestionResult(recent[0], content);
          loadRecentCaptures();
          loadPromptsBadge();
          loadGraphData();
          loadMatrixData();
          loadPeople();
          if (recent[0].elicitations && recent[0].elicitations.length > 0) {
            renderLiveElicitations(recent[0].elicitations);
          }
          showToast("✓ Note captured and synced successfully!", "success", 3000);
          return;
        }
      }
    } catch (_) {}

    appendAssistantErrorBubble(`Failed to ingest note: ${err.message}`);
    showToast(`Failed to ingest note: ${err.message}`, "error", 4500);
  } finally {
    if (loader) loader.classList.add('hidden');
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.classList.remove('opacity-80', 'cursor-not-allowed');
    }
    const curIcon = document.getElementById('submit-note-icon');
    if (curIcon) {
      curIcon.outerHTML = `<i data-lucide="send" id="submit-note-icon" class="w-3.5 h-3.5"></i>`;
    }
    if (submitText) submitText.innerText = activeElicitation ? "Send Answer" : "Send";
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }
}

function renderIngestionResult(data, originalText, timeString = null) {
  const container = document.getElementById('capture-stream');
  
  // Clear empty state if present
  if (container.innerHTML.includes('No notes captured')) {
    container.innerHTML = '';
  }

  const card = document.createElement('div');
  card.className = "bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4 shadow-lg animate-fadeIn";

  // Header
  let entitiesBadges = data.created_entities.map(e => {
    let color = 'bg-slate-800 text-slate-300';
    if (e.node_type === 'project') color = 'bg-blue-950 text-blue-300 border border-blue-800';
    if (e.node_type === 'obligation') color = 'bg-amber-950 text-amber-300 border border-amber-800';
    if (e.node_type === 'person') color = 'bg-purple-950 text-purple-300 border border-purple-800';
    if (e.node_type === 'event') color = 'bg-emerald-950 text-emerald-300 border border-emerald-800';
    return `<span class="px-2 py-0.5 rounded-full text-[11px] font-medium ${color}">[${e.node_type}] ${e.title}</span>`;
  }).join(' ');

  let calActionsHtml = '';
  if (data.calendar_actions && data.calendar_actions.length > 0) {
    calActionsHtml = data.calendar_actions.map(ca => `
      <div class="flex items-center space-x-2 text-xs text-emerald-400 bg-emerald-950/40 p-2 rounded-lg border border-emerald-800/50">
        <i data-lucide="calendar-check" class="w-3.5 h-3.5"></i>
        <span><strong>Scheduled on Calendar:</strong> ${ca.decision.summary} (${ca.decision.start_time})</span>
      </div>
    `).join('');
  }

  let promptsHtml = '';
  if (data.prompts_generated && data.prompts_generated.length > 0) {
    promptsHtml = data.prompts_generated.map(p => `
      <div class="flex items-center space-x-2 text-xs text-amber-400 bg-amber-950/40 p-2 rounded-lg border border-amber-800/50">
        <i data-lucide="alert-circle" class="w-3.5 h-3.5"></i>
        <span><strong>Prompt Triggered:</strong> ${p.message}</span>
      </div>
    `).join('');
  }

  let peopleHtml = '';
  if (data.people_profiles && data.people_profiles.length > 0) {
    peopleHtml = data.people_profiles.map(prof => `
      <div class="flex items-center space-x-2 text-xs text-purple-300 bg-purple-950/40 p-2 rounded-lg border border-purple-800/50">
        <i data-lucide="user-check" class="w-3.5 h-3.5 text-purple-400"></i>
        <span><strong>Remembered Person:</strong> ${prof.name} (${prof.role_or_title || prof.relationship_type}) ${prof.memories && prof.memories.length > 0 ? `· <em>"${prof.memories[0]}"</em>` : ''}</span>
      </div>
    `).join('');
  }

  const displayTime = timeString || new Date().toLocaleTimeString();

  card.innerHTML = `
    <div class="flex items-start justify-between">
      <div class="space-y-1">
        <span class="text-[10px] uppercase font-semibold text-indigo-400 tracking-wider">Ingested Summary</span>
        <p class="font-semibold text-slate-200 text-sm">${data.summary}</p>
      </div>
      <span class="text-[10px] text-slate-500 font-mono">${displayTime}</span>
    </div>

    <p class="text-xs text-slate-400 italic bg-slate-950/60 p-2.5 rounded-lg border border-slate-800/50">"${originalText}"</p>

    <div class="space-y-1.5">
      <span class="text-[10px] uppercase font-semibold text-slate-500 tracking-wider">Graph Entities Extracted</span>
      <div class="flex flex-wrap gap-1.5">${entitiesBadges}</div>
    </div>

    ${calActionsHtml}
    ${promptsHtml}
    ${peopleHtml}

    <div class="text-[11px] text-slate-500 pt-2 border-t border-slate-800/60 flex items-center justify-between">
      <span>Decision Model Triage: ${data.triage_reasoning || 'Evaluated priority & calendar'}</span>
      <button onclick="switchTab('graph')" class="text-indigo-400 hover:text-indigo-300 font-medium flex items-center space-x-1">
        <span>View in Graph</span>
        <i data-lucide="arrow-right" class="w-3 h-3"></i>
      </button>
    </div>
  `;

  container.prepend(card);

  // Render Live Elicitation Questions if present
  if (data.elicitations && data.elicitations.length > 0) {
    renderLiveElicitations(data.elicitations);
  }

  lucide.createIcons();
}

// --- Conversational Clarification & Elicitation Handlers ---

function renderLiveElicitations(elicitations) {
  if (!elicitations || elicitations.length === 0) return;

  elicitations.forEach(el => {
    if (!promptedElicitationIds.has(el.id)) {
      promptedElicitationIds.add(el.id);
      pendingElicitationsQueue.push(el);
      promptElicitationInChat(el);
    }
  });

  // Activate the top pending clarification if nothing is currently active
  if (!activeElicitation && pendingElicitationsQueue.length > 0) {
    setActiveElicitation(pendingElicitationsQueue[0]);
  }
}

function promptElicitationInChat(el) {
  const container = document.getElementById('chat-stream-container');
  if (!container) return;

  const escapedNodeTitle = (el.node_title || '').replace(/'/g, "\\'");
  const optionsHtml = (el.suggested_options || []).map((opt) => {
    const escapedOpt = opt.replace(/'/g, "\\'");
    return `
      <button onclick="answerElicitationChip('${el.id}', '${escapedOpt}', '${escapedNodeTitle}')"
              class="px-2.5 py-1 rounded-lg bg-indigo-950/70 hover:bg-indigo-600 hover:text-white text-indigo-300 text-xs font-medium border border-indigo-800/80 transition shadow-sm active:scale-95 text-left">
        ${escapeHtml(opt)}
      </button>
    `;
  }).join(' ');

  const msgDiv = document.createElement('div');
  msgDiv.id = `chat-el-msg-${el.id}`;
  msgDiv.className = 'flex items-start space-x-2.5 max-w-[95%] sm:max-w-[85%] animate-fadeIn';
  msgDiv.innerHTML = `
    <div class="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-tr from-purple-600 to-pink-600 flex items-center justify-center text-white shrink-0 shadow-md">
      <i data-lucide="help-circle" class="w-4 h-4"></i>
    </div>
    <div class="bg-slate-900 border border-purple-800/60 rounded-2xl rounded-tl-sm p-3.5 sm:p-4 text-xs sm:text-sm text-slate-100 shadow-xl space-y-2.5 w-full">
      <div class="flex items-center justify-between gap-2 border-b border-purple-900/40 pb-2">
        <div class="flex items-center space-x-1.5 truncate">
          <span class="w-2 h-2 rounded-full bg-purple-400 animate-pulse shrink-0"></span>
          <span class="text-[10px] uppercase font-bold text-purple-300 tracking-wider">Clarification Needed</span>
          <span class="text-xs text-slate-400 truncate">· ${escapeHtml(el.node_title)}</span>
        </div>
        <button onclick="dismissElicitationChat('${el.id}')" class="text-slate-500 hover:text-slate-300 text-xs px-2 py-0.5 rounded hover:bg-slate-800 transition" title="Dismiss clarification">
          Skip
        </button>
      </div>
      <p class="font-medium text-slate-100 text-xs sm:text-sm leading-relaxed">${escapeHtml(el.question)}</p>
      ${optionsHtml ? `
        <div class="space-y-1.5 pt-1">
          <span class="text-[10px] text-purple-300/80 font-semibold uppercase tracking-wider">Quick 1-Click Suggestions:</span>
          <div class="flex flex-wrap gap-1.5 pt-0.5">${optionsHtml}</div>
        </div>
      ` : ''}
      <div class="text-[11px] text-slate-400 pt-1 flex items-center space-x-1 border-t border-slate-800/50">
        <i data-lucide="corner-down-right" class="w-3 h-3 text-purple-400 shrink-0"></i>
        <span>Use the text box below to answer, or click a suggestion above.</span>
      </div>
    </div>
  `;

  container.appendChild(msgDiv);
  if (typeof lucide !== 'undefined') lucide.createIcons();
  scrollChatToBottom();
}

function answerElicitationChip(id, answer, nodeTitle) {
  submitElicitationAnswerFromChat(id, answer, nodeTitle);
}

async function dismissElicitationChat(id) {
  try {
    const elMsg = document.getElementById(`chat-el-msg-${id}`);
    if (elMsg) {
      elMsg.classList.add('opacity-40');
    }
    await fetch(`/api/elicitations/${id}/dismiss`, { method: 'POST' });
    showToast("Clarification skipped", "info", 2000);
    if (activeElicitation && activeElicitation.id === id) {
      cancelActiveElicitation();
    } else {
      pendingElicitationsQueue = pendingElicitationsQueue.filter(item => item.id !== id);
    }
    if (elMsg) elMsg.remove();
  } catch (err) {
    console.error("Error dismissing elicitation:", err);
  }
}

async function submitElicitationAnswerFromChat(id, answer, nodeTitle) {
  const input = document.getElementById('note-input');
  if (input) input.value = '';

  // Append user message bubble to chat
  appendUserChatMessage(answer);

  // Show typing spinner in chat
  const typingId = showChatTyping(`Refining "${nodeTitle}" with: "${answer}"...`);

  // UI feedback on submit button
  const submitBtn = document.getElementById('submit-note-btn');
  const submitText = document.getElementById('submit-note-text');
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.classList.add('opacity-80', 'cursor-not-allowed');
  }
  if (submitText) submitText.innerText = "Refining...";

  showToast(`Processing clarification: "${answer}"...`, 'info', 2500);

  try {
    const res = await fetch('/api/elicitations/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ elicitation_id: id, user_answer: answer })
    });

    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    removeChatMessage(typingId);

    // Update the elicitation prompt bubble in chat to confirmed state
    const elMsg = document.getElementById(`chat-el-msg-${id}`);
    if (elMsg) {
      elMsg.className = 'flex items-center space-x-2.5 text-xs text-emerald-300 bg-emerald-950/40 border border-emerald-800/60 rounded-xl p-3 max-w-[95%] sm:max-w-[85%] animate-fadeIn';
      elMsg.innerHTML = `
        <div class="w-6 h-6 rounded-full bg-emerald-900 border border-emerald-600 flex items-center justify-center text-emerald-300 shrink-0">
          <i data-lucide="check" class="w-3.5 h-3.5"></i>
        </div>
        <div>
          <span class="font-semibold text-emerald-200">Clarification Saved:</span>
          <span>Applied "<strong>${escapeHtml(answer)}</strong>" to <em>${escapeHtml(nodeTitle)}</em>.</span>
        </div>
      `;
      if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    showToast(`✓ Clarification saved! Record successfully refined.`, 'success', 3500);

    // Refresh views with updated knowledge
    loadGraphData();
    loadMatrixData();
    loadPeople();

    // Advance queue
    pendingElicitationsQueue = pendingElicitationsQueue.filter(item => item.id !== id);
    activeElicitation = null;
    cancelActiveElicitation();

  } catch (err) {
    removeChatMessage(typingId);
    showToast(`Failed to refine record: ${err.message}`, 'error', 4500);
    appendAssistantErrorBubble(`Failed to save clarification: ${err.message}`);
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.classList.remove('opacity-80', 'cursor-not-allowed');
    }
    if (submitText) {
      submitText.innerText = activeElicitation ? "Send Answer" : "Send";
    }
  }
}

// Aliases for compatibility
function answerElicitation(id, answer, clickedBtn = null, nodeTitle = '') {
  submitElicitationAnswerFromChat(id, answer, nodeTitle);
}
function dismissElicitation(id) {
  dismissElicitationChat(id);
}

// --- Voice Recording ---

async function toggleVoiceRecord() {
  const btn = document.getElementById('record-btn');
  const btnText = document.getElementById('record-btn-text');
  const icon = document.getElementById('record-icon');

  if (!isRecording) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunks.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        await uploadAudioBlob(audioBlob);
      };

      mediaRecorder.start();
      isRecording = true;
      btn.classList.add('bg-rose-950', 'border-rose-700', 'text-rose-300');
      btnText.innerText = "Recording... (Click to Finish)";
      icon.classList.add('animate-ping');
    } catch (err) {
      alert("Microphone access denied or not supported.");
    }
  } else {
    mediaRecorder.stop();
    isRecording = false;
    btn.classList.remove('bg-rose-950', 'border-rose-700', 'text-rose-300');
    btnText.innerText = "Voice Memo";
    icon.classList.remove('animate-ping');
  }
}

// --- Real-Time Speech Dictation ---

let speechRecognizer = null;
let isDictating = false;

function toggleLiveDictation() {
  const btn = document.getElementById('dictate-btn');
  const btnText = document.getElementById('dictate-btn-text');
  const icon = document.getElementById('dictate-icon');
  const textarea = document.getElementById('note-input');

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    alert("Live dictation is not natively supported by your browser. You can still use the Voice Memo button!");
    return;
  }

  if (!isDictating) {
    try {
      speechRecognizer = new SpeechRecognition();
      speechRecognizer.continuous = true;
      speechRecognizer.interimResults = true;
      speechRecognizer.lang = 'en-US';

      speechRecognizer.onresult = (event) => {
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            const text = event.results[i][0].transcript.trim();
            textarea.value = (textarea.value + ' ' + text).trim();
          }
        }
      };

      speechRecognizer.onerror = (e) => {
        console.warn("Dictation status/error:", e);
        stopDictationUI();
      };

      speechRecognizer.onend = () => {
        if (isDictating) {
          try { speechRecognizer.start(); } catch (err) {}
        }
      };

      speechRecognizer.start();
      isDictating = true;
      btn.classList.add('bg-purple-950', 'border-purple-700', 'text-purple-300');
      btnText.innerText = "Listening...";
      icon.classList.add('animate-spin');
    } catch (err) {
      alert("Microphone permission required for speech dictation.");
    }
  } else {
    stopDictationUI();
  }
}

function stopDictationUI() {
  if (speechRecognizer) {
    speechRecognizer.onend = null;
    try { speechRecognizer.stop(); } catch (e) {}
  }
  isDictating = false;
  const btn = document.getElementById('dictate-btn');
  const btnText = document.getElementById('dictate-btn-text');
  const icon = document.getElementById('dictate-icon');
  if (btn) btn.classList.remove('bg-purple-950', 'border-purple-700', 'text-purple-300');
  if (btnText) btnText.innerText = "Live Dictate";
  if (icon) icon.classList.remove('animate-spin');
}

async function uploadAudioBlob(blob) {
  const loader = document.getElementById('ingest-loader');
  loader.classList.remove('hidden');

  const formData = new FormData();
  formData.append('file', blob, 'voicememo.webm');

  try {
    const res = await fetch('/api/notes/upload-audio', {
      method: 'POST',
      body: formData
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    appendAssistantChatCaptureResult(data, "[Voice Recording Processed by Gemini]");
    renderIngestionResult(data, "[Voice Recording Processed by Gemini]");
    if (data.workload_risk && data.workload_risk.risk_flagged) {
      displayWorkloadRiskBanner(data.workload_risk);
    }
    showToast("✓ Voice memo processed and knowledge graph updated!", "success", 3000);
    loadPromptsBadge();
    loadGraphData();
    loadMatrixData();
    loadPeople();
    if (data.elicitations && data.elicitations.length > 0) {
      renderLiveElicitations(data.elicitations);
    }
  } catch (err) {
    alert(`Audio processing failed: ${err.message}`);
  } finally {
    loader.classList.add('hidden');
  }
}

async function uploadAudioFile(input) {
  if (!input.files || input.files.length === 0) return;
  const file = input.files[0];
  const loader = document.getElementById('ingest-loader');
  loader.classList.remove('hidden');

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/notes/upload-audio', {
      method: 'POST',
      body: formData
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    appendAssistantChatCaptureResult(data, `[Audio File: ${file.name}]`);
    renderIngestionResult(data, `[Audio File: ${file.name}]`);
    if (data.workload_risk && data.workload_risk.risk_flagged) {
      displayWorkloadRiskBanner(data.workload_risk);
    }
    showToast("✓ Audio file processed and knowledge graph updated!", "success", 3000);
    loadPromptsBadge();
    loadGraphData();
    loadMatrixData();
    loadPeople();
    if (data.elicitations && data.elicitations.length > 0) {
      renderLiveElicitations(data.elicitations);
    }
  } catch (err) {
    alert(`Audio upload failed: ${err.message}`);
  } finally {
    loader.classList.add('hidden');
    input.value = '';
  }
}

// --- Knowledge Graph Explorer (Vis.js Hierarchical Engine) ---

function formatNodeLabel(title, type, quadrant) {
  let icon = '⚡ ';
  if (type === 'organization') icon = '🏢 ';
  else if (type === 'project') icon = '📁 ';
  else if (type === 'person') icon = '👤 ';
  else if (type === 'event') icon = '📅 ';
  else if (type === 'reference') icon = '📄 ';
  else if (quadrant === 'Q1_DO_FIRST') icon = '🔥 ';

  const cleanTitle = (title || 'Untitled').trim();
  const words = cleanTitle.split(/\s+/);
  const lines = [];
  let current = icon;

  for (const word of words) {
    if ((current + ' ' + word).trim().length > 22 && current !== icon) {
      lines.push(current.trim());
      current = word;
    } else {
      current = (current === icon ? icon + word : current + ' ' + word);
    }
  }
  if (current.trim()) lines.push(current.trim());

  if (lines.length > 3) {
    lines[2] = lines[2].slice(0, 19) + '...';
    return lines.slice(0, 3).join('\n');
  }
  return lines.join('\n');
}

function createVisNode(n, mode) {
  let bg = '#1e293b';
  let border = '#475569';
  let fontColor = '#f8fafc';
  let shape = 'box';

  if (n.node_type === 'organization') {
    bg = '#0f172a';
    border = '#38bdf8'; // Sky blue
    shape = 'box';
  } else if (n.node_type === 'project') {
    bg = '#1e1b4b';
    border = '#818cf8'; // Indigo
    shape = 'box';
  } else if (n.node_type === 'obligation') {
    if (n.eisenhower_quadrant === 'Q1_DO_FIRST') {
      bg = '#4c0519';
      border = '#fb7185'; // Rose / Urgent
    } else {
      bg = '#451a03';
      border = '#f59e0b'; // Amber / Action
    }
    shape = 'box';
  } else if (n.node_type === 'person') {
    bg = '#3b0764';
    border = '#c084fc'; // Purple
    shape = 'ellipse';
  } else if (n.node_type === 'event') {
    bg = '#042f2e';
    border = '#2dd4bf'; // Teal
    shape = 'box';
  } else if (n.node_type === 'reference') {
    bg = '#1e293b';
    border = '#94a3b8';
    shape = 'box';
  }

  if (n.status === 'completed') {
    bg = '#064e3b';
    border = '#22c55e';
  }

  const tooltip = `${n.title}\nType: ${(n.node_type || '').toUpperCase()} · Category: ${n.category || 'general'}\nStatus: ${n.status || 'pending'}${n.description ? '\n\n' + n.description : ''}`;

  const nodeObj = {
    id: n.id,
    label: formatNodeLabel(n.title, n.node_type, n.eisenhower_quadrant),
    title: tooltip,
    color: {
      background: bg,
      border: border,
      highlight: { background: '#4338ca', border: '#a5b4fc' },
      hover: { background: '#312e81', border: '#c7d2fe' }
    },
    font: {
      color: fontColor,
      size: (n.node_type === 'organization' ? 12 : 11),
      face: 'Inter, system-ui, sans-serif'
    },
    shape: shape,
    margin: { top: 8, bottom: 8, left: 12, right: 12 },
    borderWidth: 2,
    shadow: { enabled: true, color: 'rgba(0,0,0,0.45)', size: 6, x: 2, y: 3 },
    rawNode: n
  };

  // Assign explicit hierarchy level if structured hierarchical layout
  if (mode === 'hierarchical-ud' || mode === 'hierarchical-lr') {
    nodeObj.level = n.hierarchy_level || 3;
  }

  return nodeObj;
}

function createVisEdge(e, mode) {
  const isHierarchical = mode && mode.startsWith('hierarchical');
  const dir = mode === 'hierarchical-lr' ? 'horizontal' : 'vertical';
  const relText = e.relation_type ? e.relation_type.replace(/_/g, ' ').toLowerCase() : '';

  return {
    id: e.id,
    from: e.source,
    to: e.target,
    label: relText,
    font: {
      color: '#64748b',
      size: 8,
      align: 'middle',
      background: '#090d16',
      strokeWidth: 0
    },
    arrows: { to: { enabled: true, scaleFactor: 0.65 } },
    color: {
      color: '#334155',
      highlight: '#818cf8',
      hover: '#94a3b8'
    },
    smooth: isHierarchical
      ? { type: 'cubicBezier', forceDirection: dir, roundness: 0.45 }
      : { type: 'continuous', roundness: 0.2 },
    rawEdge: e
  };
}

function getGraphLayoutOptions(mode, spacing) {
  let levelSep = 150;
  let nodeSpac = 170;
  let treeSpac = 210;

  if (spacing === 'compact') {
    levelSep = 110;
    nodeSpac = 130;
    treeSpac = 160;
  } else if (spacing === 'spacious') {
    levelSep = 200;
    nodeSpac = 220;
    treeSpac = 260;
  }

  if (mode === 'hierarchical-ud') {
    return {
      layout: {
        hierarchical: {
          enabled: true,
          direction: 'UD',
          sortMethod: 'directed',
          levelSeparation: levelSep,
          nodeSpacing: nodeSpac,
          treeSpacing: treeSpac,
          blockShifting: true,
          edgeMinimization: true,
          parentCentralization: true,
          shakeTowards: 'roots'
        }
      },
      physics: {
        hierarchicalRepulsion: {
          centralGravity: 0.0,
          springLength: 100,
          springConstant: 0.01,
          nodeDistance: nodeSpac,
          damping: 0.09
        },
        solver: 'hierarchicalRepulsion',
        stabilization: { enabled: true, iterations: 200, updateInterval: 25 }
      }
    };
  } else if (mode === 'hierarchical-lr') {
    return {
      layout: {
        hierarchical: {
          enabled: true,
          direction: 'LR',
          sortMethod: 'directed',
          levelSeparation: levelSep,
          nodeSpacing: nodeSpac,
          treeSpacing: treeSpac,
          blockShifting: true,
          edgeMinimization: true,
          parentCentralization: true,
          shakeTowards: 'roots'
        }
      },
      physics: {
        hierarchicalRepulsion: {
          centralGravity: 0.0,
          springLength: 100,
          springConstant: 0.01,
          nodeDistance: nodeSpac,
          damping: 0.09
        },
        solver: 'hierarchicalRepulsion',
        stabilization: { enabled: true, iterations: 200, updateInterval: 25 }
      }
    };
  } else if (mode === 'hierarchical-dag') {
    return {
      layout: {
        hierarchical: {
          enabled: true,
          direction: 'UD',
          sortMethod: 'directed',
          levelSeparation: levelSep,
          nodeSpacing: nodeSpac,
          treeSpacing: treeSpac,
          blockShifting: true,
          edgeMinimization: true,
          parentCentralization: true,
          shakeTowards: 'leaves'
        }
      },
      physics: {
        hierarchicalRepulsion: {
          centralGravity: 0.0,
          springLength: 100,
          springConstant: 0.01,
          nodeDistance: nodeSpac,
          damping: 0.09
        },
        solver: 'hierarchicalRepulsion',
        stabilization: { enabled: true, iterations: 200, updateInterval: 25 }
      }
    };
  } else {
    // 'organic'
    return {
      layout: { hierarchical: { enabled: false } },
      physics: {
        solver: 'forceAtlas2Based',
        forceAtlas2Based: {
          gravitationalConstant: -70,
          centralGravity: 0.015,
          springLength: 170,
          springConstant: 0.06,
          damping: 0.4,
          avoidOverlap: 0.8
        },
        maxVelocity: 50,
        minVelocity: 0.1,
        stabilization: { enabled: true, iterations: 160, updateInterval: 25 }
      }
    };
  }
}

async function loadGraphData() {
  const categoryFilter = document.getElementById('graph-category-filter')?.value || '';
  const url = categoryFilter ? `/api/graph/network?category=${categoryFilter}` : '/api/graph/network';

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    cachedGraphRawData = data;

    filterAndRenderGraph();
  } catch (err) {
    console.error("Failed to load graph network:", err);
    showToast(`Failed to load knowledge graph: ${err.message}`, 'error');
  }
}

function changeGraphLayout(mode) {
  currentGraphLayout = mode;
  filterAndRenderGraph();
}

function changeGraphSpacing(spacing) {
  currentGraphSpacing = spacing;
  filterAndRenderGraph();
}

function filterAndRenderGraph() {
  if (!cachedGraphRawData) return;
  const typeFilter = document.getElementById('graph-type-filter')?.value || '';

  let nodes = cachedGraphRawData.nodes || [];
  let edges = cachedGraphRawData.edges || [];

  if (isolatedSubtreeNodeId) {
    const connectedSet = new Set([isolatedSubtreeNodeId]);
    let changed = true;
    while (changed) {
      changed = false;
      for (const edge of edges) {
        if (connectedSet.has(edge.source) && !connectedSet.has(edge.target)) {
          connectedSet.add(edge.target);
          changed = true;
        } else if (connectedSet.has(edge.target) && !connectedSet.has(edge.source)) {
          connectedSet.add(edge.source);
          changed = true;
        }
      }
    }
    nodes = nodes.filter(n => connectedSet.has(n.id));
    edges = edges.filter(e => connectedSet.has(e.source) && connectedSet.has(e.target));
  } else if (typeFilter) {
    const matchingNodeIds = new Set(nodes.filter(n => n.node_type === typeFilter).map(n => n.id));
    for (const e of edges) {
      if (matchingNodeIds.has(e.source)) matchingNodeIds.add(e.target);
      if (matchingNodeIds.has(e.target)) matchingNodeIds.add(e.source);
    }
    nodes = nodes.filter(n => matchingNodeIds.has(n.id));
    edges = edges.filter(e => matchingNodeIds.has(e.source) && matchingNodeIds.has(e.target));
  }

  renderGraphNetwork(nodes, edges);
}

function renderGraphNetwork(nodes, edges) {
  const container = document.getElementById('graph-container');
  if (!container) return;

  const visNodes = nodes.map(n => createVisNode(n, currentGraphLayout));
  const visEdges = edges.map(e => createVisEdge(e, currentGraphLayout));

  const graphData = {
    nodes: new vis.DataSet(visNodes),
    edges: new vis.DataSet(visEdges)
  };

  const layoutOpts = getGraphLayoutOptions(currentGraphLayout, currentGraphSpacing);

  const baseOptions = {
    ...layoutOpts,
    interaction: {
      hover: true,
      tooltipDelay: 150,
      navigationButtons: false,
      keyboard: true,
      zoomView: true,
      zoomSpeed: 0.15
    }
  };

  const emptyState = document.getElementById('graph-empty-state');
  if (nodes.length === 0) {
    if (emptyState) emptyState.classList.remove('hidden');
    closeInspector();
    if (typeof lucide !== 'undefined') lucide.createIcons();
  } else {
    if (emptyState) emptyState.classList.add('hidden');
  }

  if (networkInstance) {
    try { networkInstance.destroy(); } catch (e) {}
  }

  networkInstance = new vis.Network(container, graphData, baseOptions);

  networkInstance.on('click', (params) => {
    if (params.nodes.length > 0) {
      const selectedId = params.nodes[0];
      const selected = nodes.find(n => n.id === selectedId);
      if (selected) inspectNode(selected);
    } else {
      closeInspector();
    }
  });

  networkInstance.once('stabilizationIterationsDone', () => {
    networkInstance.fit({ animation: { duration: 300, easingFunction: 'easeInOutQuad' } });
  });
}

function searchGraphNodes(query) {
  if (!networkInstance || !cachedGraphRawData) return;
  const q = (query || '').toLowerCase().trim();
  if (!q) return;

  const matched = (cachedGraphRawData.nodes || []).find(n =>
    (n.title && n.title.toLowerCase().includes(q)) ||
    (n.description && n.description.toLowerCase().includes(q)) ||
    (n.node_type && n.node_type.toLowerCase().includes(q))
  );

  if (matched) {
    networkInstance.selectNodes([matched.id]);
    networkInstance.focus(matched.id, {
      scale: 1.15,
      animation: { duration: 350, easingFunction: 'easeInOutQuad' }
    });
    inspectNode(matched);
  }
}

function focusNodeSubtree(targetNodeId) {
  if (!targetNodeId || !cachedGraphRawData) return;
  isolatedSubtreeNodeId = targetNodeId;

  const btnReset = document.getElementById('btn-reset-subtree');
  if (btnReset) btnReset.classList.remove('hidden');

  filterAndRenderGraph();

  showToast('Focused on connected subtree', 'info');
}

function resetNodeSubtree() {
  isolatedSubtreeNodeId = null;
  const btnReset = document.getElementById('btn-reset-subtree');
  if (btnReset) btnReset.classList.add('hidden');

  filterAndRenderGraph();
}

function zoomGraph(direction) {
  if (!networkInstance) return;
  const currentScale = networkInstance.getScale();
  const newScale = direction === 'in' ? currentScale * 1.3 : currentScale * 0.7;
  networkInstance.moveTo({
    scale: newScale,
    animation: { duration: 250, easingFunction: 'easeInOutQuad' }
  });
}

function resetGraphView() {
  if (!networkInstance) return;
  networkInstance.fit({
    animation: { duration: 350, easingFunction: 'easeInOutQuad' }
  });
}

function inspectNode(node) {
  inspectedNodeId = node.id;
  const panel = document.getElementById('node-inspector');
  panel.classList.remove('hidden');

  document.getElementById('inspect-title').innerText = node.title;
  document.getElementById('inspect-desc').innerText = node.description || 'No description';
  document.getElementById('inspect-type-badge').innerText = `${node.node_type} · ${node.category}`;
  document.getElementById('inspect-quadrant').innerText = node.eisenhower_quadrant.replace('_', ' ');
  document.getElementById('inspect-due').innerText = node.due_date || 'No due date';
  document.getElementById('inspect-urgency').innerText = node.urgency_score;
  document.getElementById('inspect-importance').innerText = node.importance_score;
  document.getElementById('inspect-cal').innerText = node.calendar_sync_status || 'none';

  const toggleBtn = document.getElementById('inspect-toggle-btn');
  if (node.status === 'completed') {
    toggleBtn.innerHTML = `<i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i><span>Reopen Item</span>`;
    toggleBtn.className = "w-full py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-white text-xs font-semibold transition flex items-center justify-center space-x-1.5";
  } else {
    toggleBtn.innerHTML = `<i data-lucide="check" class="w-3.5 h-3.5"></i><span>Mark as Completed</span>`;
    toggleBtn.className = "w-full py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition flex items-center justify-center space-x-1.5";
  }

  lucide.createIcons();
}

function closeInspector() {
  document.getElementById('node-inspector').classList.add('hidden');
  inspectedNodeId = null;
}

async function toggleInspectedStatus() {
  if (!inspectedNodeId) return;
  try {
    const res = await fetch(`/api/obligations/${inspectedNodeId}/toggle-status`, { method: 'POST' });
    const data = await res.json();
    if (data.unblocked_dependents && data.unblocked_dependents.length > 0) {
      showToast(`🎉 You just unblocked ${data.unblocked_dependents.length} tasks!`, "success", 5000);
    } else {
      showToast("✓ Obligation status updated", "success", 2500);
    }
    loadGraphData();
    loadMatrixData();
    closeInspector();
  } catch (err) {
    showToast(`Failed to update status: ${err.message}`, "error");
  }
}

async function syncInspectedToCalendar() {
  if (!inspectedNodeId) return;
  showToast("Scheduling item to calendar...", "info", 2000);
  try {
    const res = await fetch(`/api/calendar/sync-node/${inspectedNodeId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    const data = await res.json();
    showToast(`✓ Scheduled: ${data.status || 'Success'}`, "success", 3000);
    loadGraphData();
  } catch (err) {
    showToast(`Calendar sync failed: ${err.message}`, "error", 4000);
  }
}

function downloadInspectedICS() {
  if (!inspectedNodeId) return;
  window.location.href = `/api/calendar/export-ics/${inspectedNodeId}`;
}

// --- Eisenhower Matrix & Projects ---

function setSphereFilter(sphere) {
  currentSphereFilter = sphere;
  ['all', 'work', 'personal'].forEach(s => {
    const btn = document.getElementById(`sphere-${s}`);
    if (btn) {
      if (s === sphere) {
        btn.className = "px-3 py-1 text-xs rounded-lg font-medium bg-indigo-600 text-white";
      } else {
        btn.className = "px-3 py-1 text-xs rounded-lg font-medium bg-slate-900 text-slate-400 hover:text-white border border-slate-800";
      }
    }
  });
  loadMatrixData();
}

let currentEnergyFilter = 'all';

function setEnergyFilter(energy) {
  currentEnergyFilter = energy;
  ['all', 'quick', 'deep'].forEach(e => {
    const btn = document.getElementById(`energy-${e}`);
    if (btn) {
      if (e === energy) {
        btn.className = "px-2.5 py-1 rounded font-medium bg-indigo-600 text-white";
      } else {
        btn.className = "px-2.5 py-1 rounded text-slate-400 hover:text-white";
      }
    }
  });
  loadMatrixData();
}

function filterByEnergy(items) {
  if (!items) return [];
  if (currentEnergyFilter === 'all') return items;
  if (currentEnergyFilter === 'quick') {
    return items.filter(i => (i.estimated_minutes && i.estimated_minutes <= 25) || i.energy_required === 'low');
  }
  if (currentEnergyFilter === 'deep') {
    return items.filter(i => (i.estimated_minutes && i.estimated_minutes >= 45) || i.energy_required === 'high');
  }
  return items;
}

async function loadMatrixData() {
  const cat = currentSphereFilter === 'all' ? '' : currentSphereFilter;
  const matrixUrl = cat ? `/api/obligations/eisenhower?category=${cat}` : '/api/obligations/eisenhower';
  const projectsUrl = cat ? `/api/obligations/projects?category=${cat}` : '/api/obligations/projects';

  try {
    const [matRes, projRes, capRes] = await Promise.all([
      fetch(matrixUrl),
      fetch(projectsUrl),
      fetch('/api/obligations/workload-capacity')
    ]);
    const mat = await matRes.json();
    const projs = await projRes.json();

    if (capRes.ok) {
      const cap = await capRes.json();
      renderWorkloadCapacityCard(cap);
    }

    renderQuadrant('q1-list', filterByEnergy(mat.Q1_DO_FIRST), 'q1-count-badge');
    renderQuadrant('q2-list', filterByEnergy(mat.Q2_SCHEDULE), 'q2-count-badge');
    renderQuadrant('q3-list', filterByEnergy(mat.Q3_DELEGATE), 'q3-count-badge');
    renderQuadrant('q4-list', filterByEnergy(mat.Q4_DONT_DO), 'q4-count-badge');

    renderProjects(projs);
  } catch (err) {
    console.error("Failed to load matrix data:", err);
  }
}

function renderWorkloadCapacityCard(cap) {
  if (!cap) return;

  const badge = document.getElementById('capacity-status-badge');
  const stressPct = document.getElementById('capacity-stress-pct');
  const stressBar = document.getElementById('capacity-stress-bar');
  const activeMetric = document.getElementById('cap-metric-active');
  const q1Metric = document.getElementById('cap-metric-q1');
  const collMetric = document.getElementById('cap-metric-collisions');
  const overdueMetric = document.getElementById('cap-metric-overdue');
  const focusMetric = document.getElementById('cap-metric-focus');
  const summaryP = document.getElementById('capacity-advisory-summary');
  const recsContainer = document.getElementById('capacity-recommendations-list');
  const iconWrap = document.getElementById('capacity-meter-icon-wrap');

  if (activeMetric) activeMetric.innerText = cap.total_active_obligations || 0;
  if (q1Metric) q1Metric.innerText = cap.q1_urgent_count || 0;
  if (collMetric) collMetric.innerText = cap.colliding_deadlines_count || 0;
  if (overdueMetric) overdueMetric.innerText = cap.overdue_count || 0;
  if (focusMetric) focusMetric.innerText = `${(cap.estimated_focus_hours || 0).toFixed(1)} hrs`;
  if (stressPct) stressPct.innerText = `Stress: ${cap.stress_score || 0}%`;

  if (stressBar) {
    const score = Math.max(5, Math.min(100, cap.stress_score || 0));
    stressBar.style.width = `${score}%`;
    if (score >= 75) {
      stressBar.className = "h-full bg-rose-500 transition-all duration-500";
    } else if (score >= 50) {
      stressBar.className = "h-full bg-amber-500 transition-all duration-500";
    } else if (score >= 30) {
      stressBar.className = "h-full bg-yellow-500 transition-all duration-500";
    } else {
      stressBar.className = "h-full bg-emerald-500 transition-all duration-500";
    }
  }

  if (badge) {
    let text = "Healthy Load";
    let cls = "px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-emerald-950 text-emerald-300 border border-emerald-800";
    if (cap.risk_level === 'critical') {
      text = "Critical Overload";
      cls = "px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-rose-950 text-rose-300 border border-rose-800 animate-pulse";
    } else if (cap.risk_level === 'high') {
      text = "High Workload Risk";
      cls = "px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-rose-950 text-rose-300 border border-rose-800";
    } else if (cap.risk_level === 'medium') {
      text = "Moderate Pressure";
      cls = "px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-amber-950 text-amber-300 border border-amber-800";
    }
    badge.innerText = text;
    badge.className = cls;
  }

  if (iconWrap) {
    if (cap.risk_level === 'critical' || cap.risk_level === 'high') {
      iconWrap.className = "w-8 h-8 rounded-xl bg-rose-950/70 border border-rose-700/60 flex items-center justify-center text-rose-400 shadow-sm";
    } else if (cap.risk_level === 'medium') {
      iconWrap.className = "w-8 h-8 rounded-xl bg-amber-950/70 border border-amber-700/60 flex items-center justify-center text-amber-400 shadow-sm";
    } else {
      iconWrap.className = "w-8 h-8 rounded-xl bg-indigo-950/70 border border-indigo-700/60 flex items-center justify-center text-indigo-400 shadow-sm";
    }
  }

  if (summaryP) {
    summaryP.innerText = cap.summary || "Current capacity is balanced. Cognitive workload is within normal bounds.";
  }

  if (recsContainer) {
    if (cap.recommendations && cap.recommendations.length > 0) {
      recsContainer.innerHTML = cap.recommendations.map(r => `
        <div class="flex items-start space-x-1.5">
          <span class="text-amber-400 font-bold shrink-0">•</span>
          <span>${escapeHtml(r)}</span>
        </div>
      `).join('');
    } else {
      recsContainer.innerHTML = `<span class="italic text-slate-500">No immediate workload interventions required. Keep up the steady cadence!</span>`;
    }
  }

  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderQuadrant(listId, items, countBadgeId) {
  const list = document.getElementById(listId);
  const badge = document.getElementById(countBadgeId);
  if (badge) badge.innerText = items.length;

  if (!list) return;
  if (items.length === 0) {
    list.innerHTML = `<div class="text-xs text-slate-600 italic py-3 text-center">No obligations in this quadrant.</div>`;
    return;
  }

  list.innerHTML = items.map(item => `
    <div class="flex items-center justify-between p-2.5 rounded-lg bg-slate-950/70 border border-slate-800/80 hover:border-slate-700 transition">
      <div class="flex items-center space-x-2.5 overflow-hidden">
        <input type="checkbox" onchange="toggleObligation('${item.id}')" class="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0 cursor-pointer">
        <div class="truncate">
          <p class="text-xs font-medium text-slate-200 truncate">${item.title}</p>
          <div class="flex items-center space-x-2 text-[10px] text-slate-500">
            <span>Due: ${item.due_date ? item.due_date.split('T')[0] : 'None'}</span>
            <span>·</span>
            <span>U: ${item.urgency_score} / I: ${item.importance_score}</span>
          </div>
        </div>
      </div>
      <div class="flex items-center space-x-1 shrink-0">
        <button onclick="snoozeObligation('${item.id}')" class="p-1 rounded text-slate-500 hover:text-amber-400" title="Snooze 1 Day">
          <i data-lucide="clock" class="w-3.5 h-3.5"></i>
        </button>
      </div>
    </div>
  `).join('');

  lucide.createIcons();
}

async function toggleObligation(id) {
  try {
    const res = await fetch(`/api/obligations/${id}/toggle-status`, { method: 'POST' });
    const data = await res.json();
    if (data.unblocked_dependents && data.unblocked_dependents.length > 0) {
      const titles = data.unblocked_dependents.map(d => d.title).join(', ');
      showToast(`🎉 Unblocked ${data.unblocked_dependents.length} tasks: ${titles}`, "success", 5000);
    } else {
      showToast("✓ Obligation status updated", "success", 2000);
    }
    loadMatrixData();
    loadGraphData();
  } catch (err) {
    showToast("Failed to update status", "error");
  }
}

async function snoozeObligation(id) {
  try {
    await fetch(`/api/obligations/${id}/snooze?days=1`, { method: 'POST' });
    showToast("⏳ Snoozed obligation by 1 day", "info", 2000);
    loadMatrixData();
  } catch (err) {
    showToast("Failed to snooze obligation", "error");
  }
}

function renderProjects(projects) {
  const container = document.getElementById('projects-grid');
  if (!container) return;

  if (projects.length === 0) {
    container.innerHTML = `<div class="col-span-3 text-xs text-slate-600 py-6 text-center border border-dashed border-slate-800 rounded-xl">No active projects yet. Mention projects in your notes!</div>`;
    return;
  }

  container.innerHTML = projects.map(p => {
    const m = p.metrics;
    return `
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
        <div class="flex items-start justify-between">
          <span class="text-[10px] uppercase font-semibold text-blue-400 bg-blue-950/70 border border-blue-900 px-2 py-0.5 rounded-full">${p.project.category}</span>
          <span class="text-xs font-mono font-bold text-indigo-400">${m.progress_percent}%</span>
        </div>
        <div>
          <h4 class="font-bold text-slate-200 text-sm">${p.project.title}</h4>
          <p class="text-xs text-slate-500 line-clamp-1">${p.project.description || 'Active Project'}</p>
        </div>
        <!-- Progress bar -->
        <div class="w-full bg-slate-950 rounded-full h-1.5 overflow-hidden">
          <div class="bg-gradient-to-r from-blue-500 to-indigo-500 h-1.5 rounded-full" style="width: ${m.progress_percent}%"></div>
        </div>
        <div class="flex justify-between text-[11px] text-slate-400 pt-1">
          <span>${m.completed} / ${m.total} done</span>
          <span>${m.blocked > 0 ? `<strong class="text-rose-400">${m.blocked} blocked</strong>` : 'Clean runway'}</span>
        </div>
      </div>
    `;
  }).join('');
}

// --- Daily Briefings ---

let isSpeaking = false;

function toggleBriefingTTS() {
  const btnText = document.getElementById('tts-btn-text');
  const icon = document.getElementById('tts-icon');

  if (!('speechSynthesis' in window)) {
    alert("Text-to-speech is not supported by your current browser.");
    return;
  }

  if (isSpeaking) {
    window.speechSynthesis.cancel();
    isSpeaking = false;
    btnText.innerText = "Read Aloud";
    if (icon) icon.classList.remove('animate-pulse');
    return;
  }

  const container = document.getElementById('briefing-markdown');
  if (!container) return;

  const rawText = container.innerText.trim();
  if (!rawText || rawText.includes("Loading") || rawText.includes("Synthesizing")) {
    alert("No completed briefing to read aloud.");
    return;
  }

  const utterance = new SpeechSynthesisUtterance(rawText);
  utterance.rate = 1.0;
  utterance.pitch = 1.0;

  utterance.onend = () => {
    isSpeaking = false;
    btnText.innerText = "Read Aloud";
    if (icon) icon.classList.remove('animate-pulse');
  };

  utterance.onerror = () => {
    isSpeaking = false;
    btnText.innerText = "Read Aloud";
    if (icon) icon.classList.remove('animate-pulse');
  };

  window.speechSynthesis.speak(utterance);
  isSpeaking = true;
  btnText.innerText = "Stop Reading";
  if (icon) icon.classList.add('animate-pulse');
}

function setBriefingTab(type) {
  currentBriefingType = type;
  ['morning', 'evening', 'cto', 'history'].forEach(t => {
    const el = document.getElementById(`subtab-${t}`);
    if (el) {
      if (t === type) {
        el.className = "py-2.5 font-semibold text-indigo-400 border-b-2 border-indigo-500 flex items-center space-x-1.5 shrink-0 whitespace-nowrap";
      } else {
        el.className = "py-2.5 font-semibold text-slate-400 hover:text-slate-200 border-b-2 border-transparent flex items-center space-x-1.5 shrink-0 whitespace-nowrap";
      }
    }
  });

  const cardContent = document.getElementById('briefing-content-card');
  const cardHistory = document.getElementById('briefing-history-card');

  if (type === 'history') {
    cardContent.classList.add('hidden');
    cardHistory.classList.remove('hidden');
    loadBriefingHistory();
  } else {
    cardContent.classList.remove('hidden');
    cardHistory.classList.add('hidden');
    loadLatestBriefing(type);
  }
}

async function loadLatestBriefing(type) {
  const container = document.getElementById('briefing-markdown');
  const typeLabel = type === 'cto' ? 'Leadership' : type;
  container.innerHTML = `<div class="text-slate-500 text-xs text-center py-10">Loading latest ${typeLabel} briefing...</div>`;

  try {
    const res = await fetch(`/api/briefings/latest?summary_type=${type}`);
    const data = await res.json();
    if (data && data.content_markdown) {
      container.innerHTML = marked.parse(data.content_markdown);
    } else {
      container.innerHTML = `<div class="text-slate-500 text-xs text-center py-10">No ${typeLabel} briefing generated yet. Click generate above!</div>`;
    }
  } catch (err) {
    container.innerHTML = `<div class="text-rose-400 text-xs">Error loading briefing: ${err.message}</div>`;
  }
}

async function triggerBriefingGen(type) {
  setBriefingTab(type);
  const container = document.getElementById('briefing-markdown');
  const typeDisplay = type === 'cto' ? 'Leadership' : (type.charAt(0).toUpperCase() + type.slice(1));
  container.innerHTML = `
    <div class="flex flex-col items-center justify-center py-16 space-y-3 text-indigo-400">
      <svg class="animate-spin h-6 w-6 text-indigo-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
      </svg>
      <span class="text-xs font-medium">Synthesizing ${typeDisplay} executive briefing with Gemini...</span>
    </div>
  `;
  showToast(`Synthesizing fresh ${typeDisplay} executive briefing...`, "info", 3000);

  try {
    const res = await fetch('/api/briefings/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ summary_type: type })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    container.innerHTML = marked.parse(data.content_markdown);
    showToast(`✓ ${typeDisplay} briefing ready!`, "success", 3000);
    loadBriefingHistory();
  } catch (err) {
    showToast(`Failed to generate briefing: ${err.message}`, "error", 4000);
    container.innerHTML = `<div class="text-rose-400 text-xs p-4 bg-rose-950/40 border border-rose-800/50 rounded-xl">Failed to generate briefing: ${escapeHtml(err.message)}</div>`;
  }
}

async function loadBriefingHistory() {
  const list = document.getElementById('history-list');
  try {
    const res = await fetch('/api/briefings/history');
    const items = await res.json();
    if (items.length === 0) {
      list.innerHTML = `<div class="text-xs text-slate-600 py-6 text-center">No past briefings stored yet.</div>`;
      return;
    }
    list.innerHTML = items.map(b => {
      let badgeClass = 'bg-slate-800 text-slate-300';
      let label = b.summary_type;
      if (b.summary_type === 'morning') {
        badgeClass = 'bg-amber-950 text-amber-300 border border-amber-800/60';
        label = 'Morning';
      } else if (b.summary_type === 'evening') {
        badgeClass = 'bg-indigo-950 text-indigo-300 border border-indigo-800/60';
        label = 'Evening';
      } else if (b.summary_type === 'cto') {
        badgeClass = 'bg-purple-950 text-purple-300 border border-purple-800/60';
        label = 'Leadership';
      }
      return `
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase ${badgeClass}">${label}</span>
              <span class="text-xs font-semibold text-slate-200">${escapeHtml(b.summary_date || '')}</span>
            </div>
            <span class="text-[10px] text-slate-500">${new Date(b.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
          </div>
          <div class="text-xs text-slate-300 line-clamp-3 prose prose-invert max-w-none">
            ${marked.parse(b.content_markdown.slice(0, 300) + '...')}
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    list.innerHTML = `<div class="text-rose-400 text-xs">Error loading history.</div>`;
  }
}

// --- Briefing Prompt & Tone Customization ---

let currentPromptEditType = 'morning';
let cachedPromptConfigs = {};

async function openBriefingPromptModal(initialType = null) {
  const modal = document.getElementById('briefing-prompt-modal');
  if (!modal) return;

  // Determine initial type (morning, evening, or cto)
  if (initialType && ['morning', 'evening', 'cto'].includes(initialType)) {
    currentPromptEditType = initialType;
  } else if (['morning', 'evening', 'cto'].includes(currentBriefingType)) {
    currentPromptEditType = currentBriefingType;
  } else {
    currentPromptEditType = 'morning';
  }

  modal.classList.remove('hidden');
  document.body.classList.add('overflow-hidden');

  try {
    const res = await fetch('/api/briefings/prompts');
    if (res.ok) {
      cachedPromptConfigs = await res.json();
      switchPromptEditTab(currentPromptEditType);
    }
  } catch (err) {
    showToast(`Failed to load prompt configs: ${err.message}`, 'error');
  }

  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function closeBriefingPromptModal() {
  const modal = document.getElementById('briefing-prompt-modal');
  if (modal) modal.classList.add('hidden');
  document.body.classList.remove('overflow-hidden');
}

function switchPromptEditTab(type) {
  currentPromptEditType = type;

  // Update tab navigation highlight
  ['morning', 'evening', 'cto'].forEach(t => {
    const btn = document.getElementById(`prompt-edit-tab-${t}`);
    if (btn) {
      if (t === type) {
        btn.className = "pb-2.5 px-3 border-b-2 border-indigo-500 text-indigo-400 flex items-center space-x-1.5 whitespace-nowrap transition font-bold";
      } else {
        btn.className = "pb-2.5 px-3 border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center space-x-1.5 whitespace-nowrap transition";
      }
    }
  });

  const cfg = cachedPromptConfigs[type] || {};

  // Form inputs
  const toneInput = document.getElementById('prompt-tone-input');
  const contentInput = document.getElementById('prompt-content-input');
  const templateInput = document.getElementById('prompt-template-input');
  const statusDot = document.getElementById('prompt-status-dot');
  const statusText = document.getElementById('prompt-status-text');
  const lastUpdated = document.getElementById('prompt-last-updated');

  if (toneInput) toneInput.value = cfg.tone_directive || '';
  if (contentInput) contentInput.value = cfg.custom_instructions || '';
  if (templateInput) templateInput.value = cfg.full_template || '';

  if (cfg.is_customized) {
    if (statusDot) statusDot.className = "w-2 h-2 rounded-full bg-emerald-400 animate-pulse";
    if (statusText) statusText.innerHTML = `<strong class="text-emerald-300">Customized:</strong> active tone & content rules applied`;
  } else {
    if (statusDot) statusDot.className = "w-2 h-2 rounded-full bg-slate-500";
    if (statusText) statusText.innerHTML = `<span class="text-slate-400">Using standard default prompt directives</span>`;
  }

  if (lastUpdated && cfg.updated_at) {
    lastUpdated.innerText = `Updated: ${new Date(cfg.updated_at).toLocaleDateString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'})}`;
  } else if (lastUpdated) {
    lastUpdated.innerText = "";
  }
}

function insertPromptSuggestion(field, text) {
  if (field === 'tone') {
    const input = document.getElementById('prompt-tone-input');
    if (!input) return;
    const cur = input.value.trim();
    input.value = cur ? `${cur} ${text}` : text;
    input.focus();
  } else if (field === 'content') {
    const input = document.getElementById('prompt-content-input');
    if (!input) return;
    const cur = input.value.trim();
    input.value = cur ? `${cur}\n- ${text}` : `- ${text}`;
    input.focus();
  }
}

async function saveCurrentBriefingPrompt() {
  const toneInput = document.getElementById('prompt-tone-input');
  const contentInput = document.getElementById('prompt-content-input');
  const templateInput = document.getElementById('prompt-template-input');
  const saveBtn = document.getElementById('save-prompt-btn');
  const saveText = document.getElementById('save-prompt-text');

  const payload = {
    tone_directive: toneInput ? toneInput.value.trim() : "",
    custom_instructions: contentInput ? contentInput.value.trim() : "",
    full_template: templateInput && templateInput.value.trim() ? templateInput.value.trim() : null
  };

  if (saveBtn) saveBtn.disabled = true;
  if (saveText) saveText.innerText = "Saving...";

  try {
    const res = await fetch(`/api/briefings/prompts/${currentPromptEditType}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error(await res.text());
    const updated = await res.json();
    cachedPromptConfigs[currentPromptEditType] = updated;
    switchPromptEditTab(currentPromptEditType);

    const typeDisplay = currentPromptEditType === 'cto' ? 'Leadership Briefing' : (currentPromptEditType.charAt(0).toUpperCase() + currentPromptEditType.slice(1));
    showToast(`✓ ${typeDisplay} prompt directives saved! Next briefing will reflect these changes.`, 'success', 3500);
  } catch (err) {
    showToast(`Failed to save prompt: ${err.message}`, 'error', 4000);
  } finally {
    if (saveBtn) saveBtn.disabled = false;
    if (saveText) saveText.innerText = "Save Changes";
  }
}

async function resetCurrentBriefingPrompt() {
  const typeDisplay = currentPromptEditType === 'cto' ? 'Leadership Briefing' : (currentPromptEditType.charAt(0).toUpperCase() + currentPromptEditType.slice(1));
  if (!confirm(`Reset ${typeDisplay} prompt directives back to system defaults?`)) {
    return;
  }

  const resetBtn = document.getElementById('reset-prompt-btn');
  if (resetBtn) resetBtn.disabled = true;

  try {
    const res = await fetch(`/api/briefings/prompts/${currentPromptEditType}/reset`, {
      method: 'POST'
    });
    if (!res.ok) throw new Error(await res.text());
    const resetData = await res.json();
    cachedPromptConfigs[currentPromptEditType] = resetData;
    switchPromptEditTab(currentPromptEditType);
    showToast(`✓ ${typeDisplay} prompt reset to system defaults.`, 'info', 3000);
  } catch (err) {
    showToast(`Failed to reset prompt: ${err.message}`, 'error', 4000);
  } finally {
    if (resetBtn) resetBtn.disabled = false;
  }
}

// --- Prompts & Nudges ---

async function loadPrompts() {
  const list = document.getElementById('prompts-list');
  try {
    const res = await fetch('/api/prompts');
    const prompts = await res.json();

    if (prompts.length === 0) {
      list.innerHTML = `
        <div class="text-center py-12 border border-dashed border-slate-800 rounded-2xl bg-slate-900/40">
          <i data-lucide="check-circle-2" class="w-8 h-8 text-emerald-400 mx-auto mb-2 opacity-80"></i>
          <h4 class="text-sm font-semibold text-slate-300">Runway is Clear!</h4>
          <p class="text-xs text-slate-500 mt-1">No stalled projects, upcoming deadline panics, or waiting-on bottlenecks detected.</p>
        </div>
      `;
    } else {
      list.innerHTML = prompts.map(p => `
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-start justify-between space-x-4">
          <div class="space-y-1">
            <div class="flex items-center space-x-2">
              <span class="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
              <h4 class="font-bold text-slate-200 text-xs">${p.title}</h4>
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 uppercase font-mono">${p.prompt_type}</span>
            </div>
            <p class="text-xs text-slate-300">${p.message}</p>
          </div>
          <div class="flex items-center space-x-2 shrink-0">
            <button onclick="resolvePrompt('${p.id}')" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium transition">
              Resolve
            </button>
            <button onclick="dismissPrompt('${p.id}')" class="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 text-xs transition">
              Dismiss
            </button>
          </div>
        </div>
      `).join('');
    }

    loadDecisionLogs();
    lucide.createIcons();
  } catch (err) {
    console.error("Failed to load prompts:", err);
  }
}

async function runManualSweep() {
  try {
    const res = await fetch('/api/prompts/sweep', { method: 'POST' });
    const data = await res.json();
    alert(`Scan complete: ${data.created_count} new prompt(s) found.`);
    loadPrompts();
    loadPromptsBadge();
  } catch (err) {
    alert("Sweep failed.");
  }
}

async function resolvePrompt(id) {
  try {
    await fetch(`/api/prompts/${id}/resolve?status=resolved`, { method: 'POST' });
    loadPrompts();
    loadPromptsBadge();
  } catch (err) {
    alert("Failed to resolve prompt.");
  }
}

async function dismissPrompt(id) {
  try {
    await fetch(`/api/prompts/${id}/resolve?status=dismissed`, { method: 'POST' });
    loadPrompts();
    loadPromptsBadge();
  } catch (err) {
    alert("Failed to dismiss prompt.");
  }
}

async function loadPromptsBadge() {
  try {
    const res = await fetch('/api/prompts');
    const prompts = await res.json();
    const badge = document.getElementById('prompt-badge');
    if (badge) {
      if (prompts.length > 0) {
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
      }
    }
  } catch (e) {}
}

async function loadDecisionLogs() {
  const container = document.getElementById('decision-logs-list');
  if (!container) return;
  try {
    const res = await fetch('/api/prompts/decision-logs?limit=15');
    const logs = await res.json();
    if (logs.length === 0) {
      container.innerHTML = `<div class="text-xs text-slate-600 py-3 text-center">No decision logs yet.</div>`;
      return;
    }
    container.innerHTML = logs.map(l => `
      <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 text-xs font-mono space-y-1">
        <div class="flex justify-between text-indigo-400">
          <span>[DECISION] ${l.decision_type}</span>
          <span class="text-slate-500">${new Date(l.created_at).toLocaleTimeString()}</span>
        </div>
        <p class="text-slate-300 font-sans">${l.rationale}</p>
      </div>
    `).join('');
  } catch (err) {}
}

// --- Calendar & Settings ---

async function loadCalendarPill() {
  try {
    const res = await fetch('/api/calendar/status');
    const data = await res.json();
    const textEl = document.getElementById('calendar-pill-text');
    if (textEl) {
      textEl.innerText = data.authenticated ? `Cal Sync (${data.events_count_today})` : `Cal Staged (${data.events_count_today})`;
    }
  } catch (err) {}
}

async function loadSettings() {
  try {
    const [statusRes, calRes] = await Promise.all([
      fetch('/api/settings/status'),
      fetch('/api/calendar/status')
    ]);
    const status = await statusRes.json();
    const cal = await calRes.json();

    // OpenRouter Status
    const orIndicator = document.getElementById('openrouter-status-indicator');
    const orModelInput = document.getElementById('openrouter-model-input');
    const orProviderSelect = document.getElementById('llm-provider-select');
    if (orIndicator) {
      if (status.openrouter_configured) {
        orIndicator.innerHTML = `<span class="text-emerald-400 font-semibold">● Active & Configured</span> (Model: ${status.openrouter_model})`;
      } else {
        orIndicator.innerHTML = `<span class="text-slate-500">Not configured (Gemini is active)</span>`;
      }
    }
    if (orModelInput && status.openrouter_model) {
      orModelInput.value = status.openrouter_model;
    }
    if (orProviderSelect && status.llm_provider) {
      orProviderSelect.value = status.llm_provider;
    }

    const calDetails = document.getElementById('cal-details');
    if (calDetails) {
      calDetails.innerHTML = `
        <div class="space-y-1.5">
          <div class="flex justify-between">
            <span class="text-slate-500">Mode:</span>
            <span class="font-medium ${cal.authenticated ? 'text-emerald-400' : 'text-amber-400'}">${cal.mode}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-slate-500">Today's Events:</span>
            <span class="font-bold text-slate-200">${cal.events_count_today}</span>
          </div>
          <p class="text-[11px] text-slate-500 pt-2">${cal.help_text}</p>
        </div>
      `;
    }

    // Load Backup and Migration stats
    loadBackupSettings();

    // Load Android Phone Notification settings
    loadNotificationSettings();
  } catch (err) {
    console.error("Failed to load settings:", err);
  }
}

async function saveOpenRouterSettings() {
  const keyInput = document.getElementById('openrouter-key-input');
  const modelInput = document.getElementById('openrouter-model-input');
  const providerSelect = document.getElementById('llm-provider-select');
  const saveBtn = document.getElementById('save-openrouter-btn');
  const saveIcon = document.getElementById('save-openrouter-icon');
  const saveText = document.getElementById('save-openrouter-text');

  const key = keyInput?.value.trim();
  const model = modelInput?.value.trim() || 'anthropic/claude-3.5-sonnet';
  const provider = providerSelect?.value || 'auto';

  if (!key) {
    showToast("Please enter your OpenRouter API key first.", "warning", 3000);
    keyInput?.focus();
    return;
  }

  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.classList.add('opacity-80', 'cursor-not-allowed');
  }
  if (saveText) saveText.innerText = "Saving...";
  if (saveIcon) {
    saveIcon.outerHTML = `
      <svg id="save-openrouter-icon" class="animate-spin w-3.5 h-3.5 text-white shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
      </svg>
    `;
  }
  showToast("Saving OpenRouter configuration...", "info", 2000);

  try {
    const res = await fetch('/api/settings/openrouter', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        openrouter_api_key: key,
        openrouter_model: model,
        llm_provider: provider
      })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    showToast("✓ OpenRouter configuration saved successfully!", "success", 3000);
    keyInput.value = '';
    loadSettings();
  } catch (err) {
    showToast(`Failed to save OpenRouter settings: ${err.message}`, "error", 4500);
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.classList.remove('opacity-80', 'cursor-not-allowed');
    }
    const curIcon = document.getElementById('save-openrouter-icon');
    if (curIcon) {
      curIcon.outerHTML = `<i data-lucide="save" id="save-openrouter-icon" class="w-3.5 h-3.5"></i>`;
    }
    if (saveText) saveText.innerText = "Save OpenRouter Config";
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }
}

async function confirmClearAllData() {
  if (!confirm("Are you sure you want to clear all notes, graph entities, and history? This cannot be undone.")) {
    return;
  }
  try {
    const res = await fetch('/api/settings/clear-data', { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());
    showToast("✓ All database records have been purged. Clean slate ready!", "success", 4000);
    loadInitialData();
    switchTab('capture');
  } catch (err) {
    showToast(`Failed to clear data: ${err.message}`, "error", 4000);
  }
}

// --- Data Migration, Backups & Encryption ---

async function loadBackupSettings() {
  try {
    const res = await fetch('/api/settings/backup/status');
    if (!res.ok) return;
    const data = await res.json();
    const stats = data.stats || {};
    const counts = stats.record_counts || {};

    // Update count labels in UI
    const setTxt = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.innerText = val !== undefined ? val : '0';
    };
    setTxt('stat-nodes-count', counts.nodes ?? 51);
    setTxt('stat-edges-count', counts.edges ?? 54);
    setTxt('stat-notes-count', counts.raw_notes ?? 19);
    setTxt('stat-memories-count', counts.person_memories ?? 53);
    setTxt('stat-briefings-count', counts.daily_summaries ?? 12);
    setTxt('stat-decisions-count', counts.decision_logs ?? 125);

    // Update Backups list
    const backups = data.backups || [];
    const countLabel = document.getElementById('backups-count-label');
    if (countLabel) countLabel.innerText = `${backups.length} snapshot(s) available`;

    const listEl = document.getElementById('backups-list');
    if (!listEl) return;

    if (backups.length === 0) {
      listEl.innerHTML = `<div class="p-3 text-center text-slate-500 text-xs bg-slate-950/40 rounded-lg border border-slate-800/60">No backups found. Click 'Create Snapshot' to save your first backup!</div>`;
      return;
    }

    listEl.innerHTML = backups.map(b => {
      const isJson = b.file_type === 'json_export';
      const isBase = b.is_baseline;
      const typeBadge = isBase
        ? `<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-950/80 text-amber-300 border border-amber-800/80">Baseline</span>`
        : (isJson
          ? `<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-purple-950/80 text-purple-300 border border-purple-800/80">JSON Export</span>`
          : `<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-indigo-950/80 text-indigo-300 border border-indigo-800/80">SQLite DB</span>`);

      const dateStr = b.modified_at ? new Date(b.modified_at).toLocaleString() : '';
      const safeFilename = encodeURIComponent(b.filename);

      return `
        <div class="flex items-center justify-between p-2.5 rounded-lg bg-slate-950/50 hover:bg-slate-950/80 border border-slate-800/80 transition text-xs">
          <div class="flex items-center space-x-2.5 min-w-0 pr-2">
            <i data-lucide="${isJson ? 'file-json' : 'database'}" class="w-4 h-4 shrink-0 ${isJson ? 'text-purple-400' : 'text-indigo-400'}"></i>
            <div class="min-w-0">
              <div class="flex items-center space-x-2">
                <span class="font-mono text-slate-200 font-medium truncate block">${escapeHtml(b.filename)}</span>
                ${typeBadge}
              </div>
              <div class="text-[10px] text-slate-500 flex items-center space-x-2">
                <span>${b.size_formatted}</span>
                <span>•</span>
                <span>${dateStr}</span>
              </div>
            </div>
          </div>
          <div class="flex items-center space-x-1.5 shrink-0">
            <a href="/api/settings/backup/download/${safeFilename}" download="${escapeHtml(b.filename)}" 
               class="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] font-medium border border-slate-700 transition flex items-center space-x-1">
              <i data-lucide="download" class="w-3 h-3 text-slate-300"></i>
              <span>Download</span>
            </a>
            ${!isJson ? `
            <button onclick="confirmRestoreBackup('${escapeHtml(b.filename)}')" 
                    class="px-2 py-1 rounded bg-rose-950/60 hover:bg-rose-900 text-rose-300 text-[11px] font-medium border border-rose-800/60 transition flex items-center space-x-1">
              <i data-lucide="rotate-ccw" class="w-3 h-3 text-rose-400"></i>
              <span>Restore</span>
            </button>` : ''}
          </div>
        </div>
      `;
    }).join('');

    if (typeof lucide !== 'undefined') lucide.createIcons();
  } catch (err) {
    console.error("Failed to load backups:", err);
  }
}

async function triggerCreateBackup() {
  const btn = document.getElementById('create-backup-btn');
  const icon = document.getElementById('create-backup-icon');
  const text = document.getElementById('create-backup-text');
  try {
    if (btn) btn.disabled = true;
    if (icon) icon.outerHTML = `<i data-lucide="loader-2" id="create-backup-icon" class="w-3.5 h-3.5 animate-spin"></i>`;
    if (text) text.innerText = "Creating Snapshot...";
    if (typeof lucide !== 'undefined') lucide.createIcons();

    const res = await fetch('/api/settings/backup/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label: 'web_manual' })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    showToast(`✓ Database snapshot created: ${data.filename} (${data.file_size_formatted})`, "success", 4000);
    loadBackupSettings();
  } catch (err) {
    showToast(`Failed to create snapshot: ${err.message}`, "error", 4500);
  } finally {
    if (btn) btn.disabled = false;
    const curIcon = document.getElementById('create-backup-icon');
    if (curIcon) curIcon.outerHTML = `<i data-lucide="save" id="create-backup-icon" class="w-3.5 h-3.5"></i>`;
    if (text) text.innerText = "Create Snapshot";
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }
}

function downloadJsonExport() {
  showToast("Preparing decrypted portable JSON backup...", "info", 2500);
  window.location.href = '/api/settings/backup/export-json';
}

async function triggerVerifyIntegrity() {
  try {
    showToast("Running integrity and decryption validation...", "info", 2000);
    const res = await fetch('/api/settings/backup/verify', { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    if (data.healthy) {
      showToast(`✓ Integrity Verified: 100% Healthy! Tested ${data.total_records_checked} encrypted fields with 0 errors.`, "success", 5000);
      const text = document.getElementById('integrity-text');
      if (text) text.innerText = `100% Health Validated (${data.total_records_checked} fields)`;
    } else {
      showToast(`⚠️ Integrity Warning: ${data.decryption_errors_count} error(s) detected`, "error", 6000);
    }
  } catch (err) {
    showToast(`Integrity check failed: ${err.message}`, "error", 4500);
  }
}

async function handleImportJsonFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  const replace = confirm(
    `Importing "${file.name}":\n\nClick OK to REPLACE current data (A safety backup snapshot will be created automatically first).\n\nClick CANCEL to MERGE with existing data without deleting anything.`
  );

  const formData = new FormData();
  formData.append('file', file);
  formData.append('replace_existing', replace ? 'true' : 'false');

  try {
    showToast("Importing and re-encrypting data...", "info", 3000);
    const res = await fetch('/api/settings/backup/import-json', {
      method: 'POST',
      body: formData
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const counts = data.imported_counts || {};
    showToast(
      `✓ Data imported successfully! Re-encrypted ${counts.nodes || 0} nodes, ${counts.raw_notes || 0} notes, ${counts.person_memories || 0} memories.`,
      "success",
      5000
    );
    loadBackupSettings();
    loadInitialData();
  } catch (err) {
    showToast(`Failed to import JSON: ${err.message}`, "error", 5000);
  } finally {
    event.target.value = '';
  }
}

async function confirmRestoreBackup(filename) {
  if (!confirm(`Are you sure you want to restore database from "${filename}"?\n\nA safety backup of your current database will be saved automatically before restoring.`)) {
    return;
  }
  try {
    showToast(`Restoring database from ${filename}...`, "info", 3000);
    const res = await fetch(`/api/settings/backup/restore/${encodeURIComponent(filename)}`, { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    showToast(`✓ ${data.message}`, "success", 4500);
    loadBackupSettings();
    loadInitialData();
  } catch (err) {
    showToast(`Failed to restore: ${err.message}`, "error", 5000);
  }
}

// --- Android Phone (Pixel 10 XL) & Mobile Push Notifications ---

let cachedVapidPublicKey = null;

function initServiceWorker() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
      .then(reg => {
        console.log('Obrigado PWA Service Worker active with scope:', reg.scope);
      })
      .catch(err => {
        console.warn('Service Worker registration skipped:', err);
      });
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding)
    .replace(/\-/g, '+')
    .replace(/_/g, '/');

  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);

  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

async function loadNotificationSettings() {
  try {
    const res = await fetch('/api/notifications/config');
    if (!res.ok) return;
    const data = await res.json();
    const config = data.config || {};
    cachedVapidPublicKey = data.vapid_public_key;

    // Populate ntfy settings
    const ntfyInput = document.getElementById('ntfy-topic-input');
    if (ntfyInput && config.ntfy_topic) {
      ntfyInput.value = config.ntfy_topic;
    }
    updateNtfyLink();

    // Populate category checkboxes
    const setCheck = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.checked = Boolean(val);
    };
    setCheck('pref-notify-briefing', config.notify_on_briefing);
    setCheck('pref-notify-elicitation', config.notify_on_elicitation);
    setCheck('pref-notify-urgent', config.notify_on_urgent_nudge);

    // Update subscriber devices summary
    const subs = data.subscriptions || [];
    const countEl = document.getElementById('webpush-sub-count');
    if (countEl) {
      if (subs.length === 0) {
        countEl.innerText = "No devices subscribed yet. Enable below on your Pixel 10 XL.";
      } else {
        const names = subs.map(s => s.device_name || 'Device').join(', ');
        countEl.innerText = `${subs.length} active device(s): ${names}`;
      }
    }

    // Check current browser subscription status
    await updateWebPushUIState();
  } catch (err) {
    console.error("Failed to load notification settings:", err);
  }
}

async function updateWebPushUIState() {
  const btn = document.getElementById('btn-toggle-webpush');
  const btnText = document.getElementById('webpush-btn-text');
  const btnIcon = document.getElementById('webpush-btn-icon');
  const badge = document.getElementById('webpush-badge');
  const statusText = document.getElementById('webpush-status-text');
  const headerPill = document.getElementById('notification-pill');

  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    if (btn) {
      btn.disabled = true;
      btn.classList.replace('bg-emerald-600', 'bg-slate-800');
    }
    if (btnText) btnText.innerText = "Web Push Not Supported in this Browser";
    if (statusText) statusText.innerText = "Unsupported";
    return;
  }

  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();

    if (sub) {
      // Subscribed on this browser
      if (btn) {
        btn.classList.remove('bg-emerald-600', 'hover:bg-emerald-500');
        btn.classList.add('bg-slate-800', 'hover:bg-slate-700', 'border', 'border-slate-700');
      }
      if (btnText) btnText.innerText = "✓ Notifications Active on this Pixel 10 XL (Click to Disable)";
      if (btnIcon) btnIcon.setAttribute('data-lucide', 'check-circle');
      if (badge) {
        badge.className = "px-2.5 py-1 rounded-full text-[10px] font-semibold bg-emerald-950/80 text-emerald-400 border border-emerald-800/80 flex items-center space-x-1";
      }
      if (statusText) statusText.innerText = "● Pixel 10 XL Active";
      if (headerPill) {
        headerPill.classList.add('border-emerald-700/60', 'bg-emerald-950/40');
      }
    } else {
      // Not yet subscribed
      if (btn) {
        btn.classList.add('bg-emerald-600', 'hover:bg-emerald-500');
        btn.classList.remove('bg-slate-800', 'hover:bg-slate-700', 'border', 'border-slate-700');
      }
      if (btnText) btnText.innerText = "Enable Android Notifications on this Device";
      if (btnIcon) btnIcon.setAttribute('data-lucide', 'bell-ring');
      if (badge) {
        badge.className = "px-2.5 py-1 rounded-full text-[10px] font-semibold bg-slate-800 text-slate-400 border border-slate-700 flex items-center space-x-1";
      }
      if (statusText) statusText.innerText = "Ready to Enable";
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
  } catch (err) {
    console.warn("Could not check push status:", err);
  }
}

async function toggleWebPushSubscription() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    alert("Web Push is not supported in this browser. Please use Chrome on Android for native push or configure ntfy.sh below.");
    return;
  }

  const reg = await navigator.serviceWorker.ready;
  const existingSub = await reg.pushManager.getSubscription();

  if (existingSub) {
    if (confirm("Disable push notifications on this device?")) {
      try {
        await fetch('/api/notifications/unsubscribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ endpoint: existingSub.endpoint })
        });
        await existingSub.unsubscribe();
        showToast("Notifications disabled on this device.", "info", 3500);
        await loadNotificationSettings();
      } catch (err) {
        showToast(`Failed to unsubscribe: ${err.message}`, "error", 4000);
      }
    }
    return;
  }

  // Request permission
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') {
    alert("Notification permission was denied. Please allow notifications in Chrome settings for this site to receive alerts on your Pixel 10 XL.");
    return;
  }

  if (!cachedVapidPublicKey) {
    showToast("VAPID public key not loaded yet, please try again in a moment.", "error", 3500);
    return;
  }

  try {
    showToast("Subscribing your Pixel 10 XL...", "info", 2500);
    const convertedKey = urlBase64ToUint8Array(cachedVapidPublicKey);
    const newSub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: convertedKey
    });

    const keyJson = newSub.toJSON();
    const isMobile = /Android|Pixel/i.test(navigator.userAgent);
    const deviceName = isMobile ? "Pixel 10 XL" : "Desktop Browser";

    const res = await fetch('/api/notifications/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        endpoint: newSub.endpoint,
        keys: {
          p256dh: keyJson.keys.p256dh,
          auth: keyJson.keys.auth
        },
        device_name: deviceName
      })
    });

    if (!res.ok) throw new Error(await res.text());

    showToast(`✓ Push notifications enabled on ${deviceName}! Sending test ping...`, "success", 4500);
    await loadNotificationSettings();

    // Trigger test ping immediately to verify
    setTimeout(sendTestPushNotification, 1200);
  } catch (err) {
    showToast(`Failed to register push: ${err.message}`, "error", 5000);
  }
}

async function sendTestPushNotification() {
  const btn = document.getElementById('btn-send-test-push');
  const icon = document.getElementById('test-push-icon');
  const text = document.getElementById('test-push-text');

  try {
    if (btn) btn.disabled = true;
    if (icon) icon.outerHTML = `<i data-lucide="loader-2" id="test-push-icon" class="w-3.5 h-3.5 animate-spin"></i>`;
    if (text) text.innerText = "Sending Ping...";
    if (typeof lucide !== 'undefined') lucide.createIcons();

    const res = await fetch('/api/notifications/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_name: "Pixel 10 XL" })
    });

    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const wp = data.results?.webpush?.sent || 0;
    const ntfy = data.results?.ntfy?.sent;

    let msg = "✓ Test notification dispatched!";
    if (wp > 0 && ntfy) {
      msg = `✓ Alert sent to ${wp} WebPush device(s) & ntfy channel! Check your Pixel 10 XL.`;
    } else if (wp > 0) {
      msg = `✓ Alert delivered to ${wp} WebPush device(s)! Check your notification drawer.`;
    } else if (ntfy) {
      msg = "✓ Alert delivered via ntfy gateway! Check your Pixel 10 XL.";
    }

    showToast(msg, "success", 5000);
  } catch (err) {
    showToast(`Failed to send test push: ${err.message}`, "error", 4500);
  } finally {
    if (btn) btn.disabled = false;
    const curIcon = document.getElementById('test-push-icon');
    if (curIcon) curIcon.outerHTML = `<i data-lucide="send" id="test-push-icon" class="w-3.5 h-3.5"></i>`;
    if (text) text.innerText = "Send Test Ping to Pixel 10 XL";
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }
}

async function saveNotificationPreferences() {
  const topic = document.getElementById('ntfy-topic-input')?.value.trim();
  const notifyBriefing = document.getElementById('pref-notify-briefing')?.checked;
  const notifyElicitation = document.getElementById('pref-notify-elicitation')?.checked;
  const notifyUrgent = document.getElementById('pref-notify-urgent')?.checked;

  try {
    const res = await fetch('/api/notifications/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ntfy_topic: topic || "obrigado_pixel_alerts",
        ntfy_enabled: Boolean(topic),
        notify_on_briefing: notifyBriefing,
        notify_on_elicitation: notifyElicitation,
        notify_on_urgent_nudge: notifyUrgent
      })
    });
    if (!res.ok) throw new Error(await res.text());
    showToast("✓ Notification preferences saved successfully!", "success", 3500);
    loadNotificationSettings();
  } catch (err) {
    showToast(`Failed to save settings: ${err.message}`, "error", 4000);
  }
}

async function generateRandomNtfyTopic() {
  try {
    const res = await fetch('/api/notifications/generate-topic', { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const input = document.getElementById('ntfy-topic-input');
    if (input) {
      input.value = data.topic;
      updateNtfyLink();
      saveNotificationPreferences();
    }
  } catch (err) {
    showToast(`Could not generate topic: ${err.message}`, "error", 3500);
  }
}

function updateNtfyLink() {
  const input = document.getElementById('ntfy-topic-input');
  const link = document.getElementById('ntfy-subscribe-link');
  if (input && link) {
    const val = input.value.trim() || 'obrigado_pixel_alerts';
    link.href = `https://ntfy.sh/${val}`;
  }
}

function scrollToNotificationSection() {
  const el = document.getElementById('section-notifications');
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('ring-2', 'ring-amber-500/60');
    setTimeout(() => el.classList.remove('ring-2', 'ring-amber-500/60'), 2500);
  }
}

// --- People & Relationship Memory Hub ---

let allPeopleCache = [];
let currentPeopleCategory = 'all';
let selectedPersonId = null;

async function loadPeople() {
  const grid = document.getElementById('people-grid');
  if (!grid) return;
  try {
    const res = await fetch('/api/people');
    allPeopleCache = await res.json();
    renderPeopleCards(allPeopleCache);
  } catch (err) {
    grid.innerHTML = `<div class="col-span-3 text-rose-400 text-xs py-8 text-center">Failed to load people: ${err.message}</div>`;
  }
}

function filterPeopleCards() {
  const query = (document.getElementById('people-search-input')?.value || '').toLowerCase();
  const filtered = allPeopleCache.filter(p => {
    const matchesCat = currentPeopleCategory === 'all' || p.category === currentPeopleCategory || p.relationship_type === currentPeopleCategory;
    const matchesQuery = !query || 
      p.name.toLowerCase().includes(query) || 
      (p.role_or_title && p.role_or_title.toLowerCase().includes(query)) ||
      (p.organization && p.organization.toLowerCase().includes(query)) ||
      (p.memories && p.memories.some(m => m.memory_fact.toLowerCase().includes(query)));
    return matchesCat && matchesQuery;
  });
  renderPeopleCards(filtered);
}

function setPeopleCategoryFilter(cat) {
  currentPeopleCategory = cat;
  ['all', 'work', 'personal'].forEach(c => {
    const btn = document.getElementById(`people-cat-${c}`);
    if (btn) {
      if (c === cat) {
        btn.className = "px-2.5 py-1 rounded font-medium bg-indigo-600 text-white";
      } else {
        btn.className = "px-2.5 py-1 rounded text-slate-400 hover:text-white";
      }
    }
  });
  filterPeopleCards();
}

function renderPeopleCards(people) {
  const grid = document.getElementById('people-grid');
  if (!grid) return;

  if (people.length === 0) {
    grid.innerHTML = `
      <div class="col-span-3 text-center py-12 border border-dashed border-slate-800 rounded-2xl bg-slate-900/40">
        <i data-lucide="user-x" class="w-8 h-8 text-slate-600 mx-auto mb-2"></i>
        <h4 class="text-sm font-semibold text-slate-300">No contacts found</h4>
        <p class="text-xs text-slate-500 mt-1">Mention colleagues, clients, or contacts in your notes or add them to start remembering context.</p>
      </div>
    `;
    lucide.createIcons();
    return;
  }

  grid.innerHTML = people.map(p => {
    const initials = p.name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() || 'P';
    
    // Memory facts preview
    let memoriesHtml = '';
    if (p.memories && p.memories.length > 0) {
      memoriesHtml = p.memories.slice(0, 2).map(m => `
        <div class="flex items-start space-x-1.5 text-[11px] text-slate-300 bg-slate-950/60 px-2 py-1.5 rounded border border-slate-800/60">
          <span class="text-purple-400">💡</span>
          <span class="line-clamp-1">${m.memory_fact}</span>
        </div>
      `).join('');
    } else {
      memoriesHtml = `<div class="text-[11px] text-slate-600 italic">No personal memories logged yet.</div>`;
    }

    // Commitments badges
    const waitingCount = p.commitments_from_them ? p.commitments_from_them.length : 0;
    const owedCount = p.commitments_to_them ? p.commitments_to_them.length : 0;

    return `
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4 hover:border-slate-700 transition shadow-lg flex flex-col justify-between">
        <div class="space-y-3">
          <!-- Person Header -->
          <div class="flex items-start justify-between">
            <div class="flex items-center space-x-3">
              <div class="w-10 h-10 rounded-full bg-gradient-to-tr from-purple-700 to-indigo-600 flex items-center justify-center font-bold text-white text-xs shadow-md">
                ${initials}
              </div>
              <div>
                <h4 class="font-bold text-slate-100 text-sm leading-snug">${p.name}</h4>
                <p class="text-xs text-purple-400 font-medium">${p.role_or_title || 'Contact'} ${p.organization ? `· ${p.organization}` : ''}</p>
              </div>
            </div>
            <span class="text-[10px] uppercase font-semibold px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
              ${p.relationship_type || p.category}
            </span>
          </div>

          <!-- Memory Bank Snippets -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between text-[10px] uppercase font-semibold text-slate-500 tracking-wider">
              <span>Memory Bank</span>
              <span>${p.memories ? p.memories.length : 0} facts</span>
            </div>
            <div class="space-y-1">
              ${memoriesHtml}
            </div>
          </div>

          <!-- Commitments summary -->
          <div class="flex items-center space-x-2 text-[10px] pt-1">
            ${waitingCount > 0 ? `<span class="px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-800/60 font-medium">Waiting on ${waitingCount}</span>` : ''}
            ${owedCount > 0 ? `<span class="px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800/60 font-medium">${owedCount} tasks linked</span>` : ''}
            ${waitingCount === 0 && owedCount === 0 ? `<span class="text-slate-500">No pending commitments</span>` : ''}
          </div>
        </div>

        <!-- Action footer -->
        <div class="pt-3 border-t border-slate-800/80 flex items-center justify-between">
          <button onclick="openPersonModal('${p.id}')" class="text-xs font-medium text-purple-400 hover:text-purple-300 flex items-center space-x-1">
            <i data-lucide="book-open" class="w-3.5 h-3.5"></i>
            <span>Open Dossier</span>
          </button>
          <span class="text-[10px] text-slate-600">Updated: ${new Date(p.updated_at).toLocaleDateString()}</span>
        </div>
      </div>
    `;
  }).join('');

  lucide.createIcons();
}

async function openPersonModal(personId) {
  selectedPersonId = personId;
  const modal = document.getElementById('person-dossier-modal');
  modal.classList.remove('hidden');

  try {
    const res = await fetch(`/api/people/${personId}`);
    const data = await res.json();
    const p = data.person;
    const prof = data.profile;
    const initials = p.title.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() || 'P';

    document.getElementById('modal-person-avatar').innerText = initials;
    document.getElementById('modal-person-name').innerText = p.title;
    document.getElementById('modal-person-subtitle').innerText = `${prof.role_or_title || 'Contact'} ${prof.organization ? `· ${prof.organization}` : ''} (${prof.relationship_type})`;

    // Render Memories
    const memList = document.getElementById('modal-memories-list');
    if (!data.memories || data.memories.length === 0) {
      memList.innerHTML = `<div class="text-xs text-slate-500 italic py-2">No memory notes saved yet. Add one above!</div>`;
    } else {
      memList.innerHTML = data.memories.map(m => `
        <div class="flex items-center justify-between p-2 rounded-lg bg-slate-950 border border-slate-800 text-xs">
          <span class="text-slate-200">💡 ${m.memory_fact}</span>
          <button onclick="deleteMemory('${m.id}')" class="text-slate-600 hover:text-rose-400 p-1" title="Delete memory">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        </div>
      `).join('');
    }

    // Render Commitments
    const commList = document.getElementById('modal-commitments-list');
    if (!data.obligations || data.obligations.length === 0) {
      commList.innerHTML = `<div class="text-xs text-slate-500 italic py-2">No mutual obligations currently linked.</div>`;
    } else {
      commList.innerHTML = data.obligations.map(o => `
        <div class="flex items-center justify-between p-2.5 rounded-lg bg-slate-950 border border-slate-800 text-xs">
          <div class="space-y-0.5">
            <div class="flex items-center space-x-2">
              <span class="text-[10px] font-bold px-1.5 py-0.5 rounded ${o.relation_type === 'WAITING_ON' ? 'bg-amber-950 text-amber-300' : 'bg-indigo-950 text-indigo-300'}">${o.relation_type}</span>
              <span class="font-medium text-slate-200">${o.title}</span>
            </div>
            <p class="text-[10px] text-slate-500">Status: ${o.status} · Due: ${o.due_date || 'None'}</p>
          </div>
          <span class="text-[10px] px-2 py-0.5 rounded ${o.status === 'completed' ? 'bg-emerald-950 text-emerald-400' : 'bg-slate-800 text-slate-400'}">${o.status}</span>
        </div>
      `).join('');
    }

    lucide.createIcons();
  } catch (err) {
    alert(`Failed to load dossier: ${err.message}`);
  }
}

function closePersonModal() {
  document.getElementById('person-dossier-modal').classList.add('hidden');
  selectedPersonId = null;
}

async function saveNewMemory() {
  if (!selectedPersonId) return;
  const input = document.getElementById('new-memory-input');
  const addBtn = document.getElementById('save-memory-btn');
  const addIcon = document.getElementById('save-memory-icon');
  const addText = document.getElementById('save-memory-text');
  const fact = input?.value.trim();
  if (!fact) {
    input?.focus();
    return;
  }

  if (input) input.disabled = true;
  if (addBtn) {
    addBtn.disabled = true;
    addBtn.classList.add('opacity-80', 'cursor-not-allowed');
  }
  if (addText) addText.innerText = "Saving...";
  if (addIcon) {
    addIcon.outerHTML = `
      <svg id="save-memory-icon" class="animate-spin w-3.5 h-3.5 text-white shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
      </svg>
    `;
  }
  showToast("Saving memory to person bank...", "info", 2000);

  try {
    const res = await fetch(`/api/people/${selectedPersonId}/memories`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ memory_fact: fact, category: 'personal' })
    });
    if (!res.ok) throw new Error(await res.text());
    if (input) {
      input.value = '';
      input.disabled = false;
    }
    showToast("✓ Fact added to memory bank!", "success", 3000);
    openPersonModal(selectedPersonId);
    loadPeople();
  } catch (err) {
    showToast(`Failed to save memory: ${err.message}`, "error", 4000);
    if (input) input.disabled = false;
  } finally {
    if (addBtn) {
      addBtn.disabled = false;
      addBtn.classList.remove('opacity-80', 'cursor-not-allowed');
    }
    const curIcon = document.getElementById('save-memory-icon');
    if (curIcon) {
      curIcon.outerHTML = `<i data-lucide="plus" id="save-memory-icon" class="w-3.5 h-3.5"></i>`;
    }
    if (addText) addText.innerText = "Add Memory";
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }
}

async function deleteMemory(memoryId) {
  try {
    await fetch(`/api/people/memories/${memoryId}`, { method: 'DELETE' });
    showToast("Memory deleted", "info", 2000);
    if (selectedPersonId) openPersonModal(selectedPersonId);
    loadPeople();
  } catch (err) {
    showToast("Failed to delete memory", "error");
  }
}

// --- Token Consumption & Cost Intelligence ---

let currentAnalyticsTimeframe = 'day';
let currentTimelineMetric = 'tokens'; // 'tokens' or 'cost'
let timelineChartInstance = null;
let activityChartInstance = null;
let modelChartInstance = null;
let cachedAnalyticsData = null;
let cachedPricingList = [];

function setAnalyticsTimeframe(tf) {
  currentAnalyticsTimeframe = tf;
  ['day', 'week', 'month', 'year'].forEach(t => {
    const btn = document.getElementById(`analytics-tf-${t}`);
    if (btn) {
      if (t === tf) {
        btn.className = "px-2.5 py-1 rounded-lg bg-indigo-600 text-white font-semibold transition shadow-sm";
      } else {
        btn.className = "px-2.5 py-1 rounded-lg text-slate-400 hover:text-white transition";
      }
    }
  });
  loadTokenAnalytics();
}

function setTimelineChartMetric(metric) {
  currentTimelineMetric = metric;
  const btnTok = document.getElementById('timeline-metric-tokens');
  const btnCost = document.getElementById('timeline-metric-cost');
  if (metric === 'tokens') {
    if (btnTok) btnTok.className = "px-2.5 py-1 rounded-md bg-indigo-600 text-white font-medium text-[11px] transition";
    if (btnCost) btnCost.className = "px-2.5 py-1 rounded-md text-slate-400 hover:text-white font-medium text-[11px] transition";
  } else {
    if (btnTok) btnTok.className = "px-2.5 py-1 rounded-md text-slate-400 hover:text-white font-medium text-[11px] transition";
    if (btnCost) btnCost.className = "px-2.5 py-1 rounded-md bg-indigo-600 text-white font-medium text-[11px] transition";
  }
  if (cachedAnalyticsData && cachedAnalyticsData.time_series) {
    renderTimelineChart(cachedAnalyticsData.time_series);
  }
}

async function loadTokenAnalytics() {
  const refreshIcon = document.getElementById('analytics-refresh-icon');
  if (refreshIcon) refreshIcon.classList.add('animate-spin');

  const actFilter = document.getElementById('analytics-activity-filter')?.value || '';
  const url = `/api/analytics/tokens?timeframe=${currentAnalyticsTimeframe}${actFilter ? `&activity=${actFilter}` : ''}`;

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    cachedAnalyticsData = data;

    // 1. Update KPI Cards
    const kpis = data.kpis || {};
    const today = kpis.today || {};
    const week = kpis.this_week || {};
    const month = kpis.this_month || {};
    const allTime = kpis.all_time || {};

    const elTodayTok = document.getElementById('kpi-today-tokens');
    const elTodayCost = document.getElementById('kpi-today-cost');
    const elTodayReq = document.getElementById('kpi-today-requests');
    if (elTodayTok) elTodayTok.innerText = Number(today.total_tokens || 0).toLocaleString();
    if (elTodayCost) elTodayCost.innerText = `$${Number(today.total_cost || 0).toFixed(4)}`;
    if (elTodayReq) elTodayReq.innerText = `${today.request_count || 0} calls (${today.prompt_tokens || 0} in / ${today.completion_tokens || 0} out)`;

    const elWeekTok = document.getElementById('kpi-week-tokens');
    const elWeekCost = document.getElementById('kpi-week-cost');
    const elWeekReq = document.getElementById('kpi-week-requests');
    if (elWeekTok) elWeekTok.innerText = Number(week.total_tokens || 0).toLocaleString();
    if (elWeekCost) elWeekCost.innerText = `$${Number(week.total_cost || 0).toFixed(4)}`;
    if (elWeekReq) elWeekReq.innerText = `${week.request_count || 0} calls`;

    const elMonthTok = document.getElementById('kpi-month-tokens');
    const elMonthCost = document.getElementById('kpi-month-cost');
    const elMonthReq = document.getElementById('kpi-month-requests');
    if (elMonthTok) elMonthTok.innerText = Number(month.total_tokens || 0).toLocaleString();
    if (elMonthCost) elMonthCost.innerText = `$${Number(month.total_cost || 0).toFixed(4)}`;
    if (elMonthReq) elMonthReq.innerText = `${month.request_count || 0} calls`;

    const elAllCost = document.getElementById('kpi-all-cost');
    const elAllTok = document.getElementById('kpi-all-tokens');
    const elAllReq = document.getElementById('kpi-all-requests');
    if (elAllCost) elAllCost.innerText = `$${Number(allTime.total_cost || 0).toFixed(4)}`;
    if (elAllTok) elAllTok.innerText = `${Number(allTime.total_tokens || 0).toLocaleString()} tokens`;
    if (elAllReq) elAllReq.innerText = `${allTime.request_count || 0} lifetime calls`;

    // 2. Render Charts
    renderTimelineChart(data.time_series || []);
    renderActivityChart(data.activity_breakdown || []);
    renderModelChart(data.model_breakdown || []);

    // 3. Render Recent Invocations Table
    renderRecentLogsTable(data.recent_logs || []);

    // 4. Update pricing table
    loadModelPricings();

  } catch (err) {
    console.error("Failed to load token analytics:", err);
    showToast(`Failed to load token analytics: ${err.message}`, 'error');
  } finally {
    if (refreshIcon) refreshIcon.classList.remove('animate-spin');
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }
}

function renderTimelineChart(timeSeries) {
  const canvas = document.getElementById('token-timeline-chart');
  if (!canvas || typeof Chart === 'undefined') return;

  const labels = timeSeries.map(item => item.period);
  const promptTokens = timeSeries.map(item => item.prompt_tokens);
  const compTokens = timeSeries.map(item => item.completion_tokens);
  const costs = timeSeries.map(item => item.cost);

  if (timelineChartInstance) {
    timelineChartInstance.destroy();
  }

  const isCost = currentTimelineMetric === 'cost';

  const datasets = isCost ? [
    {
      label: 'Estimated Spend ($)',
      data: costs,
      borderColor: '#38bdf8',
      backgroundColor: 'rgba(56, 189, 248, 0.15)',
      fill: true,
      tension: 0.35,
      pointRadius: 4,
      pointBackgroundColor: '#38bdf8',
      pointHoverRadius: 6,
      borderWidth: 2
    }
  ] : [
    {
      label: 'Prompt / Input Tokens',
      data: promptTokens,
      backgroundColor: 'rgba(99, 102, 241, 0.8)',
      borderRadius: 4,
      stack: 'tokens'
    },
    {
      label: 'Completion / Output Tokens',
      data: compTokens,
      backgroundColor: 'rgba(168, 85, 247, 0.8)',
      borderRadius: 4,
      stack: 'tokens'
    }
  ];

  timelineChartInstance = new Chart(canvas, {
    type: isCost ? 'line' : 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: { color: '#94a3b8', font: { size: 11 } }
        },
        tooltip: {
          backgroundColor: '#0f172a',
          titleColor: '#f1f5f9',
          bodyColor: '#cbd5e1',
          borderColor: '#334155',
          borderWidth: 1,
          padding: 10,
          callbacks: {
            label: function(context) {
              const val = context.raw || 0;
              return isCost ? ` Spend: $${Number(val).toFixed(5)}` : ` ${context.dataset.label}: ${Number(val).toLocaleString()} tokens`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(51, 65, 85, 0.3)' },
          ticks: { color: '#94a3b8', font: { size: 10 } }
        },
        y: {
          grid: { color: 'rgba(51, 65, 85, 0.3)' },
          ticks: {
            color: '#94a3b8',
            font: { size: 10 },
            callback: function(val) {
              return isCost ? `$${val}` : Number(val).toLocaleString();
            }
          }
        }
      }
    }
  });
}

function renderActivityChart(activityData) {
  const canvas = document.getElementById('token-activity-chart');
  const legendContainer = document.getElementById('activity-legend');
  if (!canvas || typeof Chart === 'undefined') return;

  if (activityChartInstance) {
    activityChartInstance.destroy();
  }

  if (!activityData || activityData.length === 0) {
    if (legendContainer) legendContainer.innerHTML = '<div class="col-span-2 text-slate-500 text-center py-4 text-xs">No token usage recorded yet</div>';
    return;
  }

  const palette = {
    ingestion: '#3b82f6',
    summarisation: '#8b5cf6',
    elicitation: '#f59e0b',
    nudge: '#f43f5e',
    embedding: '#10b981',
    chat: '#06b6d4',
    custom: '#64748b'
  };

  const labels = activityData.map(a => a.activity.charAt(0).toUpperCase() + a.activity.slice(1));
  const dataValues = activityData.map(a => a.total_tokens);
  const bgColors = activityData.map(a => palette[a.activity.toLowerCase()] || '#6366f1');

  activityChartInstance = new Chart(canvas, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: dataValues,
        backgroundColor: bgColors,
        borderColor: '#0f172a',
        borderWidth: 2,
        hoverOffset: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#0f172a',
          titleColor: '#f1f5f9',
          bodyColor: '#cbd5e1',
          borderColor: '#334155',
          borderWidth: 1,
          padding: 8,
          callbacks: {
            label: function(ctx) {
              const val = ctx.raw || 0;
              const total = dataValues.reduce((a, b) => a + b, 0);
              const pct = total > 0 ? ((val / total) * 100).toFixed(1) : 0;
              return ` ${ctx.label}: ${Number(val).toLocaleString()} tokens (${pct}%)`;
            }
          }
        }
      },
      cutout: '65%'
    }
  });

  // Render HTML legend
  if (legendContainer) {
    const totalTokensAll = dataValues.reduce((a, b) => a + b, 0);
    legendContainer.innerHTML = activityData.map((a, idx) => {
      const color = bgColors[idx];
      const pct = totalTokensAll > 0 ? ((a.total_tokens / totalTokensAll) * 100).toFixed(0) : 0;
      return `
        <div class="flex items-center justify-between p-1 rounded hover:bg-slate-800/40">
          <div class="flex items-center space-x-1.5 truncate">
            <span class="w-2.5 h-2.5 rounded-full shrink-0" style="background-color: ${color}"></span>
            <span class="text-slate-300 font-medium truncate">${escapeHtml(a.activity)}</span>
          </div>
          <span class="text-slate-400 font-mono text-[10px] shrink-0 ml-1">${pct}% · $${Number(a.cost).toFixed(3)}</span>
        </div>
      `;
    }).join('');
  }
}

function renderModelChart(modelData) {
  const canvas = document.getElementById('token-model-chart');
  if (!canvas || typeof Chart === 'undefined') return;

  if (modelChartInstance) {
    modelChartInstance.destroy();
  }

  if (!modelData || modelData.length === 0) return;

  const labels = modelData.map(m => m.model);
  const dataValues = modelData.map(m => m.total_tokens);
  const costs = modelData.map(m => m.cost);

  modelChartInstance = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Total Tokens',
        data: dataValues,
        backgroundColor: 'rgba(245, 158, 11, 0.85)',
        borderRadius: 4
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#0f172a',
          titleColor: '#f1f5f9',
          bodyColor: '#cbd5e1',
          borderColor: '#334155',
          borderWidth: 1,
          padding: 8,
          callbacks: {
            label: function(ctx) {
              const val = ctx.raw || 0;
              const cost = costs[ctx.dataIndex] || 0;
              return ` ${Number(val).toLocaleString()} tokens · $${Number(cost).toFixed(4)}`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(51, 65, 85, 0.3)' },
          ticks: {
            color: '#94a3b8',
            font: { size: 10 },
            callback: function(v) { return Number(v).toLocaleString(); }
          }
        },
        y: {
          grid: { display: false },
          ticks: { color: '#cbd5e1', font: { size: 10 } }
        }
      }
    }
  });
}

function renderRecentLogsTable(logs) {
  const tbody = document.getElementById('analytics-logs-body');
  if (!tbody) return;

  if (!logs || logs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="py-8 text-center text-slate-500 font-sans">No recent LLM invocations recorded yet.</td></tr>`;
    return;
  }

  const actBadges = {
    ingestion: 'bg-blue-950 text-blue-300 border-blue-800/60',
    summarisation: 'bg-purple-950 text-purple-300 border-purple-800/60',
    elicitation: 'bg-amber-950 text-amber-300 border-amber-800/60',
    nudge: 'bg-rose-950 text-rose-300 border-rose-800/60',
    embedding: 'bg-emerald-950 text-emerald-300 border-emerald-800/60',
    chat: 'bg-sky-950 text-sky-300 border-sky-800/60'
  };

  tbody.innerHTML = logs.map(l => {
    const timeStr = new Date(l.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const dateStr = new Date(l.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' });
    const badgeCls = actBadges[l.activity_type] || 'bg-slate-800 text-slate-400 border-slate-700';

    return `
      <tr class="hover:bg-slate-800/40 transition">
        <td class="py-2.5 px-3 text-slate-400 whitespace-nowrap">${dateStr} ${timeStr}</td>
        <td class="py-2.5 px-3 font-sans">
          <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold border ${badgeCls}">
            ${escapeHtml(l.activity_type)}
          </span>
        </td>
        <td class="py-2.5 px-3">
          <div class="truncate max-w-[160px] text-slate-200" title="${escapeHtml(l.model)}">
            <span class="text-[10px] text-slate-500 uppercase font-sans">[${escapeHtml(l.provider)}]</span>
            ${escapeHtml(l.model)}
          </div>
        </td>
        <td class="py-2.5 px-3 text-right text-slate-400">${Number(l.prompt_tokens).toLocaleString()}</td>
        <td class="py-2.5 px-3 text-right text-slate-400">${Number(l.completion_tokens).toLocaleString()}</td>
        <td class="py-2.5 px-3 text-right font-bold text-slate-200">${Number(l.total_tokens).toLocaleString()}</td>
        <td class="py-2.5 px-3 text-right text-emerald-400 font-bold">$${Number(l.estimated_cost).toFixed(5)}</td>
      </tr>
    `;
  }).join('');
}

async function loadModelPricings() {
  try {
    const res = await fetch('/api/analytics/pricing');
    if (!res.ok) return;
    const pricings = await res.json();
    cachedPricingList = pricings;

    // 1. Populate summary table in analytics view
    const summaryBody = document.getElementById('pricing-summary-body');
    if (summaryBody) {
      summaryBody.innerHTML = pricings.map(p => `
        <tr class="hover:bg-slate-800/40 transition">
          <td class="py-2 px-3 font-mono font-medium text-slate-200">${escapeHtml(p.display_name || p.model_id)}</td>
          <td class="py-2 px-3 uppercase text-[10px] text-slate-400">${escapeHtml(p.provider)}</td>
          <td class="py-2 px-3 text-right font-mono text-slate-300">$${Number(p.input_cost_per_million).toFixed(3)}</td>
          <td class="py-2 px-3 text-right font-mono text-slate-300">$${Number(p.output_cost_per_million).toFixed(3)}</td>
        </tr>
      `).join('');
    }

    // 2. Populate modal table
    const modalBody = document.getElementById('modal-pricing-table-body');
    if (modalBody) {
      modalBody.innerHTML = pricings.map(p => {
        const isDefault = p.model_id === 'default';
        const escapedId = (p.model_id || '').replace(/'/g, "\\'");
        return `
          <tr class="hover:bg-slate-900 transition">
            <td class="py-2 px-3">
              <div class="font-bold text-slate-200">${escapeHtml(p.display_name || p.model_id)}</div>
              <div class="text-[10px] font-mono text-slate-500">${escapeHtml(p.model_id)}</div>
            </td>
            <td class="py-2 px-3 uppercase text-[10px] text-slate-400">
              <span>${escapeHtml(p.provider)}</span>
              ${p.is_auto_fetched ? '<span class="ml-1 text-[9px] text-emerald-400 font-semibold">(auto)</span>' : ''}
            </td>
            <td class="py-2 px-3 text-right font-mono text-slate-200">$${Number(p.input_cost_per_million).toFixed(3)}</td>
            <td class="py-2 px-3 text-right font-mono text-slate-200">$${Number(p.output_cost_per_million).toFixed(3)}</td>
            <td class="py-2 px-3 text-right">
              <div class="flex items-center justify-end space-x-1.5">
                <button onclick="editPricingItem('${escapedId}')" class="text-indigo-400 hover:text-indigo-300 p-1 rounded hover:bg-slate-800" title="Edit rates">
                  <i data-lucide="edit-3" class="w-3.5 h-3.5"></i>
                </button>
                ${!isDefault ? `
                  <button onclick="deletePricingItem('${escapedId}')" class="text-rose-400 hover:text-rose-300 p-1 rounded hover:bg-slate-800" title="Delete custom rate">
                    <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                  </button>
                ` : ''}
              </div>
            </td>
          </tr>
        `;
      }).join('');
      if (typeof lucide !== 'undefined') lucide.createIcons();
    }
  } catch (err) {
    console.error("Failed to load model pricings:", err);
  }
}

function openModelPricingModal() {
  const modal = document.getElementById('model-pricing-modal');
  if (modal) {
    modal.classList.remove('hidden');
    document.body.classList.add('overflow-hidden');
    loadModelPricings();
  }
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function closeModelPricingModal() {
  const modal = document.getElementById('model-pricing-modal');
  if (modal) {
    modal.classList.add('hidden');
    document.body.classList.remove('overflow-hidden');
  }
}

function resetPricingForm() {
  const mid = document.getElementById('pricing-input-model');
  const prov = document.getElementById('pricing-input-provider');
  const name = document.getElementById('pricing-input-name');
  const promptRate = document.getElementById('pricing-input-prompt');
  const compRate = document.getElementById('pricing-input-completion');
  const title = document.getElementById('pricing-form-title');

  if (mid) mid.value = '';
  if (prov) prov.value = 'custom';
  if (name) name.value = '';
  if (promptRate) promptRate.value = '';
  if (compRate) compRate.value = '';
  if (title) title.innerHTML = `<i data-lucide="plus-circle" class="w-3.5 h-3.5 text-indigo-400"></i><span>Add / Edit Model Pricing</span>`;
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function editPricingItem(modelId) {
  const item = cachedPricingList.find(p => p.model_id === modelId);
  if (!item) return;

  const mid = document.getElementById('pricing-input-model');
  const prov = document.getElementById('pricing-input-provider');
  const name = document.getElementById('pricing-input-name');
  const promptRate = document.getElementById('pricing-input-prompt');
  const compRate = document.getElementById('pricing-input-completion');
  const title = document.getElementById('pricing-form-title');

  if (mid) mid.value = item.model_id;
  if (prov) prov.value = item.provider || 'custom';
  if (name) name.value = item.display_name || item.model_id;
  if (promptRate) promptRate.value = item.input_cost_per_million;
  if (compRate) compRate.value = item.output_cost_per_million;
  if (title) title.innerHTML = `<i data-lucide="edit-3" class="w-3.5 h-3.5 text-amber-400"></i><span>Edit Pricing for ${escapeHtml(item.model_id)}</span>`;
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function saveCustomModelPricing() {
  const mid = document.getElementById('pricing-input-model')?.value.trim();
  const prov = document.getElementById('pricing-input-provider')?.value || 'custom';
  const name = document.getElementById('pricing-input-name')?.value.trim();
  const promptRate = parseFloat(document.getElementById('pricing-input-prompt')?.value || 0);
  const compRate = parseFloat(document.getElementById('pricing-input-completion')?.value || 0);

  if (!mid) {
    showToast("Please provide a model identifier (ID)", "error");
    return;
  }

  const saveBtn = document.getElementById('save-pricing-btn');
  if (saveBtn) saveBtn.disabled = true;

  try {
    const res = await fetch('/api/analytics/pricing', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model_id: mid,
        provider: prov,
        display_name: name || mid,
        input_cost_per_million: promptRate,
        output_cost_per_million: compRate
      })
    });

    if (!res.ok) throw new Error(await res.text());
    showToast(`✓ Pricing saved for ${mid}`, "success", 3000);
    resetPricingForm();
    loadModelPricings();
    loadTokenAnalytics();
  } catch (err) {
    showToast(`Failed to save pricing: ${err.message}`, "error");
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
}

async function deletePricingItem(modelId) {
  if (!confirm(`Delete custom pricing configuration for ${modelId}?`)) return;

  try {
    const res = await fetch(`/api/analytics/pricing/${encodeURIComponent(modelId)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    showToast(`Pricing deleted for ${modelId}`, "info", 2500);
    loadModelPricings();
    loadTokenAnalytics();
  } catch (err) {
    showToast(`Failed to delete pricing: ${err.message}`, "error");
  }
}

async function syncOpenRouterRates() {
  const btn = document.getElementById('sync-rates-btn');
  const icon = document.getElementById('sync-rates-icon');
  if (btn) btn.disabled = true;
  if (icon) icon.classList.add('animate-spin');

  showToast("Fetching live model pricing from OpenRouter API...", "info", 3000);

  try {
    const res = await fetch('/api/analytics/pricing/sync-openrouter', { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    showToast(`✓ Successfully synced ${data.models_synced} models from OpenRouter!`, "success", 4000);
    loadModelPricings();
    loadTokenAnalytics();
  } catch (err) {
    showToast(`Failed to sync OpenRouter pricing: ${err.message}`, "error", 4500);
  } finally {
    if (btn) btn.disabled = false;
    if (icon) icon.classList.remove('animate-spin');
  }
}
