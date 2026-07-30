/* ═══════════════════════════════════════════════════════════════════════
   Brains College Admin — single-page dashboard.
   Hash router + live WebSocket updates. All server values pass UI.esc().
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  const { esc, toast, modal, closeModal, fmtDate, fmtDateTime, fmtTime, ago,
          fmtDuration, num, badge, pager, spinner, emptyState, debounce } = UI;

  if (!API.token()) { location.href = '/admin/login'; return; }

  const content = document.getElementById('content');
  const charts = {};              // chart-id → Chart instance
  let ME = {};                    // current admin
  let FORM_OPTIONS = null;        // {campuses, departments, courses}
  let ws = null, wsRetry = 0;

  /* ── Theme ─────────────────────────────────────────────────────────── */
  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem('bc_theme', t);
  }
  applyTheme(localStorage.getItem('bc_theme') || 'light');
  document.getElementById('themeBtn').addEventListener('click', () => {
    applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
    // re-render current page so charts pick up new colours
    router();
  });

  function chartColors() {
    const dark = document.documentElement.getAttribute('data-theme') === 'dark';
    return {
      brand: dark ? '#6FCB94' : '#123A4B',
      brass: '#D6A94A',
      grid: dark ? 'rgba(255,255,255,.07)' : 'rgba(23,36,43,.08)',
      tick: dark ? '#96A69E' : '#566771',
      fill: dark ? 'rgba(111,203,148,.15)' : 'rgba(18,58,75,.10)',
      palette: ['#123A4B', '#D6A94A', '#1C6EA4', '#6B4FA1', '#C0392B', '#1F8A54', '#B0740A', '#566771']
    };
  }
  function makeChart(id, cfg) {
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
    const el = document.getElementById(id);
    if (!el) return;
    if (typeof Chart === 'undefined') {   // CDN not loaded — fail soft
      const box = el.closest('.chart-box');
      if (box) box.innerHTML = '<div class="chart-fallback">Chart unavailable (offline).</div>';
      return;
    }
    try {
      const c = chartColors();
      Chart.defaults.color = c.tick;
      Chart.defaults.borderColor = c.grid;
      Chart.defaults.font.family = "'Inter', sans-serif";
      charts[id] = new Chart(el, cfg);
    } catch (e) { /* never let a chart error blank the page */ }
  }

  /* ── Shell: me, logout, sidebar ────────────────────────────────────── */
  try { ME = JSON.parse(localStorage.getItem('bc_admin') || '{}'); } catch (e) { ME = {}; }
  function paintMe() {
    document.getElementById('meName').textContent = ME.name || 'Admin';
    document.getElementById('meRole').textContent = (ME.role || '').replace('_', ' ')
      + (ME.campus ? ' · ' + ME.campus : '');
    document.getElementById('meAvatar').textContent = (ME.name || 'A').trim()[0].toUpperCase();
    // Only the super admin manages other admins; everything else is visible to
    // campus admins too (their data is automatically scoped to their campus).
    document.getElementById('adminsLink').style.display = ME.role === 'super_admin' ? '' : 'none';
  }
  // A campus admin is a non-super admin tied to a specific campus. They get the
  // FULL menu — every page — but all data they see and edit is limited to
  // their own campus by the backend. This flag is used only to filter the live
  // activity feed so they don't get pop-ups for other campuses.
  function isCampusAdmin() { return ME.role === 'admin' && !!(ME.campus || '').trim(); }
  paintMe();
  API.get('/api/auth/me').then(me => { ME = me; localStorage.setItem('bc_admin', JSON.stringify(me)); paintMe(); }).catch(() => {});

  document.getElementById('logoutBtn').addEventListener('click', API.logout);

  // Chatbot launcher — loads the deployed bot on first open
  (function () {
    const fab = document.getElementById('bcChatFab');
    const panel = document.getElementById('bcChatPanel');
    const frame = document.getElementById('bcChatFrame');
    if (!fab) return;
    fab.addEventListener('click', () => {
      const open = panel.classList.toggle('open');
      if (open && frame.src === 'about:blank') frame.src = frame.dataset.src;
    });
    document.getElementById('bcChatClose').addEventListener('click', () => panel.classList.remove('open'));
  })();
  const sidebar = document.getElementById('sidebar');
  const scrim = document.getElementById('scrim');
  document.getElementById('hamburger').addEventListener('click', () => {
    sidebar.classList.toggle('open'); scrim.classList.toggle('open');
  });
  scrim.addEventListener('click', () => { sidebar.classList.remove('open'); scrim.classList.remove('open'); });
  document.getElementById('nav').addEventListener('click', e => {
    if (e.target.closest('a')) { sidebar.classList.remove('open'); scrim.classList.remove('open'); }
  });

  /* ── Global search ─────────────────────────────────────────────────── */
  const searchInput = document.getElementById('globalSearch');
  const searchDrop = document.getElementById('searchDrop');
  searchInput.addEventListener('input', debounce(async () => {
    const q = searchInput.value.trim();
    if (q.length < 2) { searchDrop.classList.remove('open'); return; }
    try {
      const r = await API.get('/api/admin/search' + API.qs({ q }));
      let html = '';
      if (r.applications.length) {
        html += '<div class="sd-group">Applications</div>' + r.applications.map(a =>
          `<a class="sd-item" href="#/applications/${a.id}"><b>${esc(a.full_name)} · ${esc(a.application_no)}</b><span>${esc(a.course || '—')} · ${badge(a.application_status)}</span></a>`).join('');
      }
      if (r.chats.length) {
        html += '<div class="sd-group">Conversations</div>' + r.chats.map(s =>
          `<a class="sd-item" href="#/chats/${esc(s.id)}"><b>${esc(s.title || 'Untitled chat')}</b><span>${esc(s.visitor_name || 'Anonymous')} · ${s.message_count} messages</span></a>`).join('');
      }
      if (r.leads.length) {
        html += '<div class="sd-group">Leads</div>' + r.leads.map(l =>
          `<a class="sd-item" href="#/leads"><b>${esc(l.name)}</b><span>${esc(l.phone)} · ${esc(l.campus)}</span></a>`).join('');
      }
      searchDrop.innerHTML = html || '<div class="sd-item"><span>No matches found</span></div>';
      searchDrop.classList.add('open');
    } catch (e) { /* ignore */ }
  }, 300));
  document.addEventListener('click', e => {
    if (!e.target.closest('.global-search')) searchDrop.classList.remove('open');
  });
  searchDrop.addEventListener('click', () => { searchDrop.classList.remove('open'); searchInput.value = ''; });

  /* ── Notifications badge ───────────────────────────────────────────── */
  async function refreshUnread() {
    try {
      const r = await API.get('/api/admin/notifications/unread-count');
      const n = r.unread || 0;
      const b1 = document.getElementById('notifCount');
      const b2 = document.getElementById('notifBadgeNav');
      b1.style.display = n ? '' : 'none'; b1.textContent = n > 99 ? '99+' : n;
      b2.style.display = n ? '' : 'none'; b2.textContent = n > 99 ? '99+' : n;
    } catch (e) { /* ignore */ }
  }
  refreshUnread();
  document.getElementById('notifBtn').addEventListener('click', () => { location.hash = '#/notifications'; });

  /* ── WebSocket (live updates) ──────────────────────────────────────── */
  const liveFeed = [];   // recent events kept in memory for the Live page
  function pushFeed(item) {
    liveFeed.unshift(item);
    if (liveFeed.length > 200) liveFeed.pop();
    const feedEl = document.getElementById('liveFeed') || document.getElementById('dashFeed');
    if (feedEl) feedEl.insertAdjacentHTML('afterbegin', feedItemHTML(item));
  }
  function feedItemHTML(it) {
    return `<div class="feed-item"><time>${fmtTime(it.at)}</time><b>${esc(it.title)}</b>` +
           (it.msg ? `<div class="f-msg">${esc(it.msg)}</div>` : '') + '</div>';
  }
  function setWs(on) {
    document.getElementById('wsDot').classList.toggle('on', on);
    document.getElementById('wsLabel').textContent = on ? 'Live · connected' : 'Live · reconnecting…';
  }
  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    try { ws = new WebSocket(`${proto}://${location.host}/ws/admin?token=${encodeURIComponent(API.token())}`); }
    catch (e) { setWs(false); return; }
    ws.onopen = () => { setWs(true); wsRetry = 0; };
    ws.onclose = () => {
      setWs(false);
      const wait = Math.min(15000, 1000 * Math.pow(2, wsRetry++));
      setTimeout(connectWS, wait);
    };
    ws.onmessage = e => {
      let payload; try { payload = JSON.parse(e.data); } catch (err) { return; }
      handleEvent(payload.event, payload.data || {});
    };
  }
  function handleEvent(event, d) {
    const at = new Date().toISOString();
    // Campus admins only receive live events for their own campus.
    // Events that carry a campus and don't match are ignored.
    if (isCampusAdmin() && d && d.campus && d.campus !== ME.campus) return;
    switch (event) {
      case 'chat_message':
        pushFeed({ at, title: (d.role === 'user' ? '💬 Visitor' : '🤖 Assistant') + (d.title ? ' · ' + d.title : ''), msg: d.content });
        break;
      case 'chat_session_started':
        pushFeed({ at, title: '✨ New conversation started', msg: (d.device || '') + ' · ' + (d.browser || '') });
        toast('New chatbot conversation', 'A visitor just started chatting.', 'gold');
        break;
      case 'new_application':
        pushFeed({ at, title: '📄 New application', msg: (d.full_name || '') + ' — ' + (d.course || '') });
        toast('New application received', d.full_name || '', 'ok');
        if (location.hash.startsWith('#/applications') && !location.hash.match(/\d/)) pages.applications();
        if (location.hash === '' || location.hash === '#/dashboard') pages.dashboard();
        break;
      case 'application_updated':
        pushFeed({ at, title: '✏️ Application updated', msg: d.application_no || '' });
        break;
      case 'new_lead':
        pushFeed({ at, title: '📞 New lead', msg: (d.name || '') + ' · ' + (d.phone || '') });
        toast('New lead received', (d.name || '') + ' — ' + (d.campus || ''), 'gold');
        if (location.hash === '#/leads') pages.leads();
        break;
      case 'receipt_uploaded':
        pushFeed({ at, title: '🧾 Payment receipt uploaded', msg: (d.challan_no || '') + ' · Rs ' + (d.amount || '') + ' · ' + (d.method || '') });
        toast('Receipt uploaded', (d.challan_no || '') + ' — needs verification', 'gold');
        break;
      case 'payment_decision':
        pushFeed({ at, title: '💳 Payment ' + (d.action || ''), msg: d.challan_no || '' });
        break;
      case 'notification':
        refreshUnread();
        break;
    }
  }
  connectWS();

  /* ── Form options (departments / courses / campuses) ───────────────── */
  async function formOptions() {
    if (!FORM_OPTIONS) FORM_OPTIONS = await API.get('/api/meta/form-options');
    return FORM_OPTIONS;
  }
  function optionList(items, selected, labelKey) {
    return items.map(i =>
      `<option value="${i.id}" ${String(selected) === String(i.id) ? 'selected' : ''}>${esc(i[labelKey || 'name'])}</option>`).join('');
  }

  /* ══ Router ═══════════════════════════════════════════════════════ */
  const pages = {};
  function router() {
    const hash = location.hash || '#/dashboard';
    const parts = hash.slice(2).split('/');
    let page = parts[0] || 'dashboard';
    const arg = parts[1];

    document.querySelectorAll('.nav a').forEach(a =>
      a.classList.toggle('active', a.dataset.page === page));

    Object.keys(charts).forEach(k => { charts[k].destroy(); delete charts[k]; });

    if (page === 'applications' && arg) return pages.applicationDetail(parseInt(arg, 10));
    if (page === 'chats' && arg) return pages.chatDetail(arg);
    (pages[page] || pages.dashboard)();
  }
  window.addEventListener('hashchange', router);

  /* ══ Dashboard ═══════════════════════════════════════════════════ */
  const dashRange = { date_from: '', date_to: '' };
  pages.dashboard = async function () {
    content.innerHTML = spinner();
    try {
      const qs = API.qs({ date_from: dashRange.date_from, date_to: dashRange.date_to });
      const [ov, appStats, recent, fee, exp] = await Promise.all([
        API.get('/api/admin/analytics/overview' + qs),
        API.get('/api/admin/analytics/applications' + API.qs({ days: 30, date_from: dashRange.date_from, date_to: dashRange.date_to })),
        API.get('/api/admin/applications?page=1&page_size=6'),
        API.get('/api/admin/analytics/fees' + qs).catch(() => null),
        API.get('/api/admin/expenses-dashboard' + qs).catch(() => null)
      ]);

      const ranged = !!(dashRange.date_from || dashRange.date_to);
      const rangeLabel = ranged
        ? `${dashRange.date_from || '…'} → ${dashRange.date_to || '…'}`
        : 'All time';

      content.innerHTML = `
        <div class="page-head">
          <div><h1>Dashboard</h1><p>What's happening at Brains College${ME.campus ? ' — ' + esc(ME.campus) : ''}.</p></div>
          <div class="spacer"></div>
          <div class="filters" style="margin:0">
            <input type="date" id="dashFrom" value="${esc(dashRange.date_from)}" title="From date">
            <span style="align-self:center;color:var(--ink-faint)">→</span>
            <input type="date" id="dashTo" value="${esc(dashRange.date_to)}" title="To date">
            <button class="btn btn-primary btn-sm" id="dashApply">Apply</button>
            <button class="btn btn-outline btn-sm" id="dashClear">Clear</button>
          </div>
        </div>
        <div class="range-note">Showing: <b>${esc(rangeLabel)}</b></div>

        <div class="stat-grid">
          <div class="stat"><div class="label">${ranged ? 'Applications in range' : 'Total applications'}</div><div class="value">${num(ov.total_applications)}</div><div class="sub">${num(ov.applications_this_year)} this year</div></div>
          <div class="stat gold"><div class="label">${ranged ? 'In range' : 'Today'}</div><div class="value">${num(ov.applications_today)}</div><div class="sub">${num(ov.applications_this_month)} this month</div></div>
          <div class="stat amber"><div class="label">Pending</div><div class="value">${num(ov.pending)}</div><div class="sub">${num(ov.on_hold)} on hold</div></div>
          <div class="stat green"><div class="label">Approved</div><div class="value">${num(ov.approved)}</div><div class="sub">${num(ov.rejected)} rejected</div></div>
          <div class="stat blue"><div class="label">Chat sessions</div><div class="value">${num(ov.total_chat_sessions)}</div><div class="sub">${num(ov.chats_today)} today · ${num(ov.total_chat_messages)} messages</div></div>
          <div class="stat violet"><div class="label">Leads</div><div class="value">${num(ov.total_leads)}</div><div class="sub">${num(ov.new_leads)} awaiting contact</div></div>
        </div>

        ${fee ? `<h2 class="section">Fees &amp; eligibility${ranged ? ' — ' + esc(rangeLabel) : ''}</h2>
        <div class="stat-grid">
          <div class="stat green"><div class="label">Fee collected</div><div class="value">Rs ${num(fee.collected)}</div><div class="sub">${esc(fee.collection_rate)}% of Rs ${num(fee.total_fee)}</div></div>
          <div class="stat red"><div class="label">Remaining Fee</div><div class="value">Rs ${num(fee.outstanding)}</div><div class="sub">${num(fee.installments_due)} installments due</div></div>
          <div class="stat amber"><div class="label">Overdue payments</div><div class="value">${num(fee.installments_overdue)}</div><div class="sub">past due date</div></div>
          <div class="stat green"><div class="label">Fully paid</div><div class="value">${num(fee.fully_paid)}</div><div class="sub">students</div></div>
          <div class="stat amber"><div class="label">Half Paid</div><div class="value">${num(fee.partially_paid)}</div></div>
          <div class="stat red"><div class="label">Unpaid</div><div class="value">${num(fee.unpaid)}</div></div>
          <div class="stat blue"><div class="label">Eligible for classes</div><div class="value">${num(fee.eligible)}</div><div class="sub">paid ≥ 75%</div></div>
          <div class="stat"><div class="label">Not yet eligible</div><div class="value">${num(fee.not_eligible)}</div><div class="sub">below 75%</div></div>
        </div>` : ''}

        ${exp ? `<h2 class="section">Expenses${ranged ? ' — ' + esc(rangeLabel) : ''}</h2>
        <div class="stat-grid">
          <div class="stat red"><div class="label">${ranged ? 'Expenses in range' : 'Total expenses'}</div><div class="value">Rs ${num(exp.total_expenses)}</div></div>
          <div class="stat amber"><div class="label">This month</div><div class="value">Rs ${num(exp.monthly_expenses)}</div></div>
          <div class="stat blue"><div class="label">Records</div><div class="value">${num(exp.expense_count || 0)}</div></div>
        </div>` : ''}

        <div class="grid-main-side">
          <div class="card">
            <div class="card-title"><h2>Application growth${ranged ? '' : ' — last 30 days'}</h2></div>
            <div class="chart-box"><canvas id="growthChart"></canvas></div>
          </div>
          <div class="card">
            <div class="card-title"><h2>Live activity</h2><span class="badge b-active">live</span></div>
            <div class="feed" id="dashFeed">${liveFeed.slice(0, 30).map(feedItemHTML).join('') || emptyState('Quiet for now', 'Chatbot and form activity will appear here in real time.')}</div>
          </div>
        </div>

        <div style="height:16px"></div>
        <div class="grid-main-side">
          <div class="card">
            <div class="card-title"><h2>Recent applications</h2><a class="btn btn-sm btn-outline" href="#/applications">View all</a></div>
            <div class="table-wrap"><table class="data"><thead><tr>
              <th>Applicant</th><th>Course</th><th>Campus</th><th>Status</th><th>Submitted</th>
            </tr></thead><tbody>
              ${recent.items.map(a => `<tr onclick="location.hash='#/applications/${a.id}'">
                <td class="td-main"><b>${esc(a.full_name)}</b><small>${esc(a.roll_number || a.application_no)}</small></td>
                <td>${esc(a.course_name || a.course || '—')}</td><td>${esc(a.campus || '—')}</td>
                <td>${badge(a.application_status)}</td>
                <td class="mono">${fmtDateTime(a.submitted_at)}</td></tr>`).join('') ||
              '<tr><td colspan="5">' + emptyState('No applications yet', 'They will appear here as students apply.') + '</td></tr>'}
            </tbody></table></div>
          </div>
          <div class="card">
            <div class="card-title"><h2>Popular courses</h2></div>
            <div class="chart-box"><canvas id="coursesChart"></canvas></div>
          </div>
        </div>`;

      // wire date range
      document.getElementById('dashApply').addEventListener('click', () => {
        dashRange.date_from = document.getElementById('dashFrom').value;
        dashRange.date_to = document.getElementById('dashTo').value;
        pages.dashboard();
      });
      document.getElementById('dashClear').addEventListener('click', () => {
        dashRange.date_from = ''; dashRange.date_to = ''; pages.dashboard();
      });

      const c = chartColors();
      makeChart('growthChart', {
        type: 'line',
        data: {
          labels: appStats.growth.map(d => d.date.slice(5)),
          datasets: [{ data: appStats.growth.map(d => d.count), borderColor: c.brand,
            backgroundColor: c.fill, fill: true, tension: .35, pointRadius: 0, borderWidth: 2.5 }]
        },
        options: { plugins: { legend: { display: false } }, maintainAspectRatio: false,
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }
      });
      makeChart('coursesChart', {
        type: 'doughnut',
        data: { labels: appStats.by_course.map(d => d.course),
          datasets: [{ data: appStats.by_course.map(d => d.count), backgroundColor: c.palette, borderWidth: 0 }] },
        options: { maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { boxWidth: 11 } } },
          cutout: '62%' }
      });
    } catch (e) { content.innerHTML = emptyState('Could not load dashboard', e.message); }
  };

  /* ══ Applications list ═══════════════════════════════════════════ */
  const appState = { page: 1, sort_by: 'submitted_at', sort_dir: 'desc' };

  pages.applications = async function () {
    content.innerHTML = spinner();
    const fo = await formOptions().catch(() => ({ campuses: [], departments: [], courses: [], programme_categories: [], lead_sources: [], sessions: [] }));
    const canWrite = ME.role !== 'staff';
    content.innerHTML = `
      <div class="page-head">
        <div><h1>Applications</h1><p>Search by Roll Number · create and manage admissions.</p></div>
        <div class="spacer"></div>
        ${canWrite ? `<button class="btn btn-primary" onclick="newApplication()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
          Create New Application</button>` : ''}
        <button class="btn btn-outline" onclick="exportData('applications')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
          Export</button>
      </div>

      <div class="filters">
        <input class="grow" id="fQ" placeholder="🔍 Search by Roll Number…" value="${esc(appState.q || '')}">
        <select id="fCat"><option value="">Programme: all</option>
          ${(fo.programme_categories || []).map(c => `<option ${appState.programme_category===c?'selected':''}>${esc(c)}</option>`).join('')}
        </select>
        <select id="fStatus">
          <option value="">Status: all</option>
          ${[['pending','Pending'],['approved','Approved'],['on_hold','On Hold'],['dropped_out','Drop Out']].map(([v,l]) => `<option value="${v}" ${appState.status===v?'selected':''}>${l}</option>`).join('')}
        </select>
        <select id="fPay">
          <option value="">Payment: all</option>
          ${[['unpaid','Unpaid'],['partially_paid','Half Paid'],['fully_paid','Fully Paid']].map(([v,l]) => `<option value="${v}" ${appState.payment_status===v?'selected':''}>${l}</option>`).join('')}
        </select>
        <select id="fAdm">
          <option value="">Admission: all</option>
          ${['not_admitted','admitted','enrolled'].map(s => `<option value="${s}" ${appState.admission_status===s?'selected':''}>${s.replace('_',' ')}</option>`).join('')}
        </select>
        <select id="fSource"><option value="">Lead source: all</option>
          ${(fo.lead_sources || []).map(s => `<option ${appState.lead_source===s?'selected':''}>${esc(s)}</option>`).join('')}
        </select>
        <select id="fTransfer">
          <option value="">Transfer: all</option>
          <option value="active" ${appState.transfer_filter==='active'?'selected':''}>Active Students</option>
          <option value="transferred_out" ${appState.transfer_filter==='transferred_out'?'selected':''}>Transferred Out</option>
          <option value="transferred_in" ${appState.transfer_filter==='transferred_in'?'selected':''}>Transferred In</option>
        </select>
        <input type="date" id="fFrom" value="${esc(appState.date_from || '')}" title="From date">
        <input type="date" id="fTo" value="${esc(appState.date_to || '')}" title="To date">
        <button class="btn btn-primary btn-sm" id="fGo">Apply</button>
        <button class="btn btn-outline btn-sm" id="fClear">Clear</button>
      </div>

      <div class="card" id="appsTable">${spinner()}</div>`;

    document.getElementById('fGo').addEventListener('click', () => {
      Object.assign(appState, {
        q: document.getElementById('fQ').value.trim(),
        programme_category: document.getElementById('fCat').value,
        status: document.getElementById('fStatus').value,
        payment_status: document.getElementById('fPay').value,
        admission_status: document.getElementById('fAdm').value,
        lead_source: document.getElementById('fSource').value,
        transfer_filter: document.getElementById('fTransfer').value,
        date_from: document.getElementById('fFrom').value,
        date_to: document.getElementById('fTo').value,
        page: 1
      });
      loadApps();
    });
    document.getElementById('fClear').addEventListener('click', () => {
      Object.keys(appState).forEach(k => delete appState[k]);
      Object.assign(appState, { page: 1, sort_by: 'submitted_at', sort_dir: 'desc' });
      pages.applications();
    });
    document.getElementById('fQ').addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('fGo').click(); });
    loadApps();
  };

  window.appsPage = function (p) { appState.page = p; loadApps(); };
  window.appsSort = function (col) {
    if (appState.sort_by === col) appState.sort_dir = appState.sort_dir === 'desc' ? 'asc' : 'desc';
    else { appState.sort_by = col; appState.sort_dir = 'desc'; }
    appState.page = 1; loadApps();
  };

  async function loadApps() {
    const box = document.getElementById('appsTable');
    if (!box) return;
    box.innerHTML = spinner();
    try {
      const r = await API.get('/api/admin/applications' + API.qs(appState));
      const arrow = col => appState.sort_by === col ? (appState.sort_dir === 'desc' ? ' ↓' : ' ↑') : '';
      const canWrite = ME.role !== 'staff';
      box.innerHTML = `
        <div class="table-wrap"><table class="data"><thead><tr>
          <th>Roll Number</th>
          <th class="sortable" onclick="appsSort('full_name')">Student${arrow('full_name')}</th>
          <th>Programme</th><th>Course</th><th>Lead source</th>
          <th class="sortable" onclick="appsSort('application_status')">Status${arrow('application_status')}</th>
          <th>Payment</th>
          <th class="num">Pending Payment</th>
          <th class="sortable" onclick="appsSort('submitted_at')">Submitted${arrow('submitted_at')}</th>
          <th></th>
        </tr></thead><tbody>
        ${r.items.map(a => {
          let trBadge = badge(a.application_status);
          let trSub = '';
          if (a.is_transferred) {
            const scope = ME.campus ? ME.campus.trim() : '';
            if (scope && scope === a.transferred_from) {
              trBadge = `<span class="badge b-transferred">Transferred</span>`;
              trSub = `<span class="transfer-sub">Currently in <b>${esc(a.current_campus || a.campus)} Campus</b></span>`;
            } else if (scope && scope === a.campus) {
              trSub = `<span class="transfer-sub">Transferred from <b>${esc(a.transferred_from)} Campus</b></span>`;
            } else {
              trSub = `<span class="transfer-sub">Transferred: ${esc(a.transferred_from)} → ${esc(a.campus)}</span>`;
            }
          }
          const displayRoll = (ME.campus && ME.campus === a.transferred_from && a.previous_roll_number) ? a.previous_roll_number : (a.roll_number || '—');
          return `<tr onclick="location.hash='#/applications/${a.id}'">
            <td class="td-main"><b>${esc(displayRoll)}</b><small>${esc(a.application_no || '')}</small></td>
            <td class="td-main"><b>${esc(a.full_name)}</b><small>${esc(a.phone || '')}</small>${trSub}</td>
            <td>${esc(a.programme_category || '—')}</td>
            <td>${esc(a.course_name || a.course || '—')}</td>
            <td>${a.lead_source ? badge(a.lead_source) : '—'}</td>
            <td>${trBadge}</td>
            <td>${badge(a.payment_status)}</td>
            <td class="num mono ${(a.pending_payment || 0) > 0 ? 'pend-pos' : 'pend-zero'}">Rs ${num(a.pending_payment || 0)}</td>
            <td class="mono">${fmtDateTime(a.submitted_at)}</td>
            <td onclick="event.stopPropagation()">${canWrite ? `<button class="btn btn-bad btn-sm" title="Delete application" onclick="deleteApp(${a.id}, '${esc(a.roll_number || '')}')">✕</button>` : ''}</td>
          </tr>`;
        }).join('') || '<tr><td colspan="10">' + emptyState('No applications match', 'Try adjusting the filters or create a new application.') + '</td></tr>'}
        </tbody></table></div>
        ${pager(r, 'appsPage')}`;
    } catch (e) { box.innerHTML = emptyState('Could not load applications', e.message); }
  }


  /* ── Receipt number: live uniqueness check ──────────────────────── */
  function attachReceiptCheck(inputId) {
    const el = document.getElementById(inputId);
    if (!el) return;
    const msg = document.createElement('div');
    msg.className = 'rc-msg';
    msg.id = inputId + 'Msg';
    el.parentNode.appendChild(msg);
    let t = null;
    el.addEventListener('input', () => {
      clearTimeout(t);
      const val = el.value.trim();
      el.classList.remove('rc-bad', 'rc-ok');
      msg.className = 'rc-msg'; msg.textContent = '';
      if (!val) return;
      t = setTimeout(async () => {
        try {
          const r = await API.get('/api/admin/receipts/check' + API.qs({ receipt_number: val }));
          if (r.available) {
            el.classList.add('rc-ok'); msg.className = 'rc-msg ok';
            msg.textContent = '✓ Receipt number is available.';
          } else {
            el.classList.add('rc-bad'); msg.className = 'rc-msg bad';
            msg.textContent = '❌ ' + r.message;
          }
        } catch (e) { /* ignore transient errors while typing */ }
      }, 350);
    });
  }
  function receiptIsBlocked(inputId) {
    const el = document.getElementById(inputId);
    return !!(el && el.classList.contains('rc-bad'));
  }

  window.exportExpenses = async function (fmt) {
    // Must go through API.download() so the Bearer token is sent — a plain
    // window.open() has no token and the server answers "Not authenticated".
    const p = API.qs({
      format: fmt, q: expState.q || '', category: expState.category || '',
      payment_method: expState.payment_method || '',
      date_from: expState.date_from || '', date_to: expState.date_to || ''
    });
    toast('Preparing export…', 'Expenses → ' + fmt.toUpperCase(), 'info');
    try { await API.download('/api/admin/exports/expenses' + p); }
    catch (e) { toast('Export failed', e.message, 'err'); }
  };

  /* Open an authenticated HTML page (attendance card / receipt) in a new tab.
     window.open() can't send the Bearer token, so we fetch the HTML with the
     token first and then write it into the new tab. Relative /static paths are
     rewritten to absolute so images and CSS still resolve. */
  async function openAuthedHtml(url, label) {
    const w = window.open('', '_blank');   // opened synchronously → not blocked
    if (!w) { toast('Popup blocked', 'Allow popups for this site, then try again.', 'err'); return; }
    w.document.write('<!DOCTYPE html><title>Loading…</title>'
      + '<body style="font-family:Inter,Arial,sans-serif;display:grid;place-items:center;'
      + 'height:100vh;margin:0;color:#5b6b64">Preparing ' + label + '…</body>');
    try {
      const res = await fetch(url, {
        headers: { 'Authorization': 'Bearer ' + localStorage.getItem('bc_token') }
      });
      if (!res.ok) {
        let msg = 'Request failed';
        try { msg = (await res.json()).detail || msg; } catch (e) {}
        throw new Error(msg);
      }
      let html = await res.text();
      html = html.replace(/(src|href)="\/static/g, '$1="' + location.origin + '/static');
      w.document.open();
      w.document.write(html);
      w.document.close();
    } catch (e) {
      w.document.open();
      w.document.write('<body style="font-family:Inter,Arial,sans-serif;padding:40px;color:#b02a1c">'
        + '<h2>Could not open ' + label + '</h2><p>' + esc(e.message) + '</p></body>');
      w.document.close();
      toast('Could not open ' + label, e.message, 'err');
    }
  }

  window.printAttendanceCard = function (id) {
    openAuthedHtml('/api/admin/applications/' + id + '/attendance-card', 'attendance card');
  };

  window.openReceipt = function (id) {
    openAuthedHtml('/api/admin/applications/' + id + '/receipt', 'receipt');
  };

  window.deleteApp = function (id, roll) {
    modal('Delete application', `
      <p style="margin-top:0">Are you sure you want to delete the application for
      <b>Roll ${esc(roll || id)}</b>? This permanently removes the application and
      its fee records and cannot be undone.</p>
      <div class="status-row" style="justify-content:flex-end">
        <button class="btn btn-outline" onclick="UI.closeModal()">Cancel</button>
        <button class="btn btn-bad" onclick="confirmDeleteApp(${id})">Delete</button>
      </div>`);
  };
  window.confirmDeleteApp = async function (id) {
    try {
      const r = await API.del('/api/admin/applications/' + id);
      closeModal(); toast('Application deleted', r.message || '', 'ok');
      if (location.hash.startsWith('#/applications/')) location.hash = '#/applications';
      else loadApps();
    } catch (e) { toast('Delete failed', e.message, 'err'); }
  };

  /* ══ Application detail ═══════════════════════════════════════════ */
  pages.applicationDetail = async function (id) {
    content.innerHTML = spinner();
    try {
      const [a, chats, fee] = await Promise.all([
        API.get('/api/admin/applications/' + id),
        API.get('/api/admin/applications/' + id + '/chats').catch(() => ({ linked: [], possible_matches: [] })),
        API.get('/api/admin/applications/' + id + '/fees').catch(() => null)
      ]);
      const canWrite = ME.role !== 'staff';
      const dl = (t, v) => `<div class="dl"><dt>${t}</dt><dd>${v || '—'}</dd></div>`;

      let transferBanner = '';
      if (a.is_transferred) {
        const scope = ME.campus ? ME.campus.trim() : '';
        if (scope && scope === a.transferred_from) {
          transferBanner = `<div class="transfer-banner source">
            <b>⚠️ Transferred Student (Source Campus Record)</b>
            <p>This student was transferred from <b>${esc(a.transferred_from)} Campus</b> to <b>${esc(a.campus)} Campus</b> on ${fmtDateTime(a.transferred_at)}. Historical records, fees, and attendance cards are preserved here in read-only view. <b>Currently in: ${esc(a.campus)} Campus.</b></p>
          </div>`;
        } else {
          transferBanner = `<div class="transfer-banner dest">
            <b>✓ Transferred Student (Active Record)</b>
            <p>Transferred from <b>${esc(a.transferred_from)} Campus</b> (Previous Roll Number: <code>${esc(a.previous_roll_number || '—')}</code>) on ${fmtDateTime(a.transferred_at)}. <b>Current Campus: ${esc(a.campus)} Campus.</b></p>
          </div>`;
        }
      }

      content.innerHTML = `
        ${transferBanner}
        <div class="page-head">
          <div>
            <p><a href="#/applications" style="text-decoration:none;color:var(--ink-soft)">← Applications</a></p>
            <h1>${esc(a.full_name)}</h1>
            <p>Roll <b>${esc(a.roll_number || '—')}</b> · ${esc(a.course_name || a.course || '')} · submitted ${fmtDateTime(a.submitted_at)}</p>
          </div>
          <div class="spacer"></div>
          ${canWrite ? '<button class="btn btn-outline" onclick="editApp(' + id + ')">Edit</button>' : ''}
          <button class="btn btn-green" onclick="printAttendanceCard(${id})">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v8H6z"/></svg>
            Print Attendance Card</button>
          <button class="btn btn-gold" onclick="openReceipt(${id})">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
            Download Receipt</button>
          ${canWrite ? '<button class="btn btn-bad" onclick="deleteApp(' + id + ', \'' + esc(a.roll_number || '') + '\')">Delete</button>' : ''}
        </div>

        <div class="grid-main-side">
          <div>
            <div class="card"><div class="card-pad">
              <h2 class="section">Status</h2>
              <div class="status-row" style="margin-bottom:14px">
                ${badge(a.application_status)} ${badge(a.payment_status)} ${badge(a.eligibility_status)} ${badge(a.admission_status)}
                ${a.is_referral ? refPill(a.referral_status) : ''}
              </div>
              ${canWrite ? `<div class="status-row">
                <button class="btn btn-ok btn-sm" onclick="setStatus(${id},{application_status:'approved'})">✓ Approve</button>
                <button class="btn btn-bad btn-sm" onclick="setStatus(${id},{application_status:'rejected'})">✕ Reject</button>
                <button class="btn btn-hold btn-sm" onclick="setStatus(${id},{application_status:'on_hold'})">⏸ Hold</button>
                <button class="btn btn-outline btn-sm" onclick="setStatus(${id},{application_status:'pending'})">↺ Pending</button>
                <span style="flex:1"></span>
                <select id="admSel" style="width:auto" onchange="setStatus(${id},{admission_status:this.value})">
                  <option value="">Admission…</option><option value="not_admitted">not admitted</option>
                  <option value="admitted">admitted</option><option value="enrolled">enrolled</option>
                </select>
                ${a.is_referral ? `
                <select id="refSel" style="width:auto;margin-left:6px" onchange="setStatus(${id},{referral_status:this.value})">
                  <option value="">Referral Status…</option>
                  <option value="accepted">Accepted / Approved</option>
                  <option value="rejected">Rejected</option>
                  <option value="pending">Pending</option>
                </select>` : ''}
              </div>
              <p style="color:var(--ink-faint);font-size:12px;margin:8px 0 0">Payment status &amp; class eligibility update automatically from the fee panel below.</p>` : '<p style="color:var(--ink-faint);font-size:12.5px">Read-only access — ask an admin to change statuses.</p>'}
            </div></div>

            <div style="height:16px"></div>
            <div class="card"><div class="card-pad" id="feePanel">
              ${feePanelHTML(id, a, fee, canWrite)}
            </div></div>

            <div style="height:16px"></div>
            <div class="card"><div class="card-pad">
              <h2 class="section">Student information</h2>
              <div class="detail-grid">
                ${dl('Roll Number', esc(a.roll_number))}
                ${dl('Student name', esc(a.full_name))}
                ${dl('Father name', esc(a.father_name))}
                ${dl('CNIC', esc(a.cnic))}
                ${dl('Phone', esc(a.phone))}
                ${dl('Guardian Phone', esc(a.guardian_phone || '—'))}
                ${dl('Email', esc(a.email))}
                ${dl('City', esc(a.city))}
                ${dl('Address', esc(a.address))}
              </div>
              <h2 class="section" style="margin-top:20px">Academic information</h2>
              <div class="detail-grid">
                ${dl('Programme category', esc(a.programme_category))}
                ${dl('Course', esc(a.course_name || a.course))}
                ${dl('Class timing', esc(a.class_timing))}
                ${dl('Admission date', a.admission_date ? esc(a.admission_date) : '—')}
                ${dl('Duration', esc(a.duration))}
                ${dl('Marks', a.percentage != null ? esc(a.percentage) + '%' : (a.extra_fields && a.extra_fields.marks != null ? esc(a.extra_fields.marks) : '—'))}
              </div>
              <h2 class="section" style="margin-top:20px">Application information</h2>
              <div class="detail-grid">
                ${dl('Current status', badge(a.application_status))}
                ${dl('Admission status', badge(a.admission_status))}
                ${dl('Lead source', a.lead_source ? (badge(a.lead_source) + (a.lead_source === 'Others' && a.lead_source_detail ? ' ' + esc(a.lead_source_detail) : '')) : '—')}
                ${dl('Assigned staff', esc(a.assigned_staff_name))}
                ${dl('Last updated', fmtDateTime(a.updated_at))}
              </div>
              ${a.remarks ? '<h2 class="section" style="margin-top:20px">Remarks</h2><p style="font-size:14px">' + esc(a.remarks) + '</p>' : ''}
            </div></div>
          </div>

          <div>
            <div class="card"><div class="card-pad">
              <h2 class="section">Notes</h2>
              <div id="notesBox">
                ${(a.notes || []).map(n => `<div class="note"><small>${esc(n.admin_name)} · ${fmtDateTime(n.created_at)}</small><p>${esc(n.note)}</p></div>`).join('') || '<p style="color:var(--ink-faint);font-size:13px">No notes yet.</p>'}
              </div>
              ${canWrite ? `<textarea id="noteText" placeholder="Add a note about this application…"></textarea>
              <div style="margin-top:8px;text-align:right"><button class="btn btn-primary btn-sm" onclick="addNote(${id})">Add note</button></div>` : ''}
            </div></div>

            <div style="height:16px"></div>
            <div class="card"><div class="card-pad">
              <h2 class="section">Chatbot history</h2>
              ${chats.linked.length ? chats.linked.map(s =>
                `<div class="session-row" style="padding:10px 0" onclick="location.hash='#/chats/${esc(s.id)}'">
                   <div class="session-ic">💬</div>
                   <div class="s-body"><b>${esc(s.title || 'Untitled chat')}</b><small>${s.message_count} messages · ${ago(s.last_activity_at)}</small></div>
                 </div>`).join('')
                : '<p style="color:var(--ink-faint);font-size:13px">No linked conversations. When this student chats with the bot (or a chat lead matches their phone), it appears here.</p>'}
              ${chats.possible_matches.length ? `<h2 class="section" style="margin-top:14px;font-size:14px">Possible matches</h2>` +
                chats.possible_matches.map(s =>
                `<div class="session-row" style="padding:10px 0">
                   <div class="session-ic">❓</div>
                   <div class="s-body"><b>${esc(s.title || 'Untitled chat')}</b><small>same phone · ${s.message_count} messages</small></div>
                   ${canWrite ? `<button class="btn btn-outline btn-sm" onclick="linkChat('${esc(s.id)}', ${a.student_id}, ${id})">Link</button>` : ''}
                 </div>`).join('') : ''}
              ${(a.payments && a.payments.length) ? `<h2 class="section" style="margin-top:16px">Payments</h2>` +
                a.payments.map(p => `<div class="note" style="border-left-color:var(--ok)"><small>${fmtDateTime(p.created_at)}</small><p>${badge(p.status)} ${p.amount ? 'Rs ' + num(p.amount) : ''} ${esc(p.method || '')}</p></div>`).join('') : ''}
            </div></div>
          </div>
        </div>`;
      loadSchedule(id, canWrite);
    } catch (e) { content.innerHTML = emptyState('Could not load application', e.message); }
  };

  window.openChallanPrint = async function (challanId) {
    try {
      const r = await API.get('/api/admin/challans/' + challanId + '/print-url');
      window.open(r.url, '_blank');
    } catch (e) { toast('Could not open challan', e.message, 'err'); }
  };

  window.deleteApp = async function (appId, rollNumber) {
    if (!confirm('Are you sure you want to delete application ' + (rollNumber || ('#' + appId)) + '? This will also remove associated fee payments and student records.')) return;
    try {
      await API.del('/api/admin/applications/' + appId);
      toast('Application deleted', '', 'ok');
      location.hash = '#/applications';
    } catch (e) { toast('Could not delete application', e.message, 'err'); }
  };

  function feePanelHTML(appId, a, fee, canWrite) {
    if (!fee) return '<h2 class="section">Fees</h2><p style="color:var(--ink-faint)">No fee data.</p>';
    const pct = fee.percent_paid || 0;
    const instRows = (fee.installments || []).map(i => `
      <div class="inst-row">
        <div class="inum">${i.number}</div>
        <div class="ibody">
          <b>${esc(i.label)} — Rs ${num(i.amount)}</b>
          <small>${i.due_date ? 'due ' + fmtDate(i.due_date) : 'no due date'}${i.paid_amount ? ' · paid Rs ' + num(i.paid_amount) : ''}${i.recorded_by ? ' · by ' + esc(i.recorded_by) : ''}</small>
        </div>
        ${badge(i.status)}
        ${canWrite ? `<div class="status-row" style="gap:5px" onclick="event.stopPropagation()">
          ${i.status !== 'paid' ? `<button class="btn btn-ok btn-sm" onclick="payInstallment(${appId},${i.id})">Mark paid</button>
            <button class="btn btn-outline btn-sm" onclick="extendDue(${appId},${i.id},'${esc(i.due_date || '')}')">Extend</button>
            <button class="btn btn-outline btn-sm" onclick="editInstallment(${appId},${i.id},${i.amount})">Edit</button>
            <button class="btn btn-bad btn-sm" onclick="deleteInstallment(${appId},${i.id})">✕</button>`
          : `<button class="btn btn-outline btn-sm" onclick="unpayInstallment(${appId},${i.id})">Undo</button>`}
        </div>` : ''}
      </div>`).join('');

    return `
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <h2 class="section" style="margin:0">Fee management</h2>
        ${badge(fee.payment_status)} ${badge(a.eligibility_status)}
        <span class="spacer" style="flex:1"></span>
        ${canWrite ? `<button class="btn btn-outline btn-sm" onclick="setTotalFee(${appId}, ${fee.total_fee})">Set total fee</button>
        <button class="btn btn-outline btn-sm" onclick="addInstallment(${appId})">+ Installment</button>
        <button class="btn btn-primary btn-sm" onclick="recordPayment(${appId})">Record payment</button>` : ''}
      </div>
      <div class="fee-mini">
        <div><b>Total fee</b><span>Rs ${num(fee.total_fee)}</span></div>
        <div><b>Paid</b><span style="color:var(--ok)">Rs ${num(fee.paid)}</span></div>
        <div><b>Remaining</b><span style="color:var(--bad)">Rs ${num(fee.remaining)}</span></div>
        <div><b>Progress</b><span>${esc(pct)}%</span></div>
      </div>
      <div class="fee-bar"><span style="width:${Math.min(100, pct)}%"></span></div>
      <p style="font-size:12.5px;color:var(--ink-soft);margin:4px 0 10px">
        ${fee.installments_completed}/${fee.installments_total} installments paid ·
        ${fee.installments_overdue ? '<b style="color:var(--bad)">' + fee.installments_overdue + ' overdue</b> · ' : ''}
        next due: <b>${fee.next_due_date ? fmtDate(fee.next_due_date) : '—'}</b> ·
        eligible for classes at 75% paid</p>

      <h2 class="section" style="margin:14px 0 8px">Payment schedule</h2>
      <div id="scheduleBox" data-app="${appId}" data-canwrite="${canWrite ? 1 : 0}">${spinner()}</div>

      <div>${instRows || ''}</div>`;
  }

  const SCHED_LABELS = { admission_fee: 'Admission Fee', first_installment: '1st Installment', second_installment: '2nd Installment', test_session: 'Test Session' };
  const STATE_CLS = { paid: 'st-paid', paid_late: 'st-late', overdue: 'st-overdue', pending: 'st-pending' };

  async function loadSchedule(appId, canWrite) {
    const box = document.getElementById('scheduleBox');
    if (!box) return;
    try {
      const s = await API.get('/api/admin/applications/' + appId + '/schedule');
      const anyOverdue = s.rows.some(r => r.state === 'overdue' && (r.amount || 0) > 0);
      const rows = s.rows.map(r => {
        const late = r.days_late || 0;
        const note = r.state === 'overdue'
          ? `<small class="sch-note bad">${late} day${late === 1 ? '' : 's'} overdue — extend to accept payment</small>`
          : r.state === 'paid_late'
            ? `<small class="sch-note warn">paid ${late} day${late === 1 ? '' : 's'} late</small>`
            : '';
        return `
        <tr class="${r.state === 'overdue' ? 'row-overdue' : ''}">
          <td class="td-main"><b>${esc(r.schedule)}</b>${note}</td>
          <td>${canWrite
            ? `<input class="sch-amt" data-stage="${r.stage}" type="number" min="0" value="${r.amount || 0}">`
            : 'Rs ' + num(r.amount)}</td>
          <td>${canWrite
            ? `<input class="sch-due" data-stage="${r.stage}" type="date" value="${esc(r.due_date || '')}">`
            : (r.due_date ? fmtDate(r.due_date) : '—')}</td>
          <td class="mono">${r.paid_amount ? '<span style="color:var(--ok);font-weight:700">Rs ' + num(r.paid_amount) + '</span>' : '—'}</td>
          <td><span class="pill ${STATE_CLS[r.state] || 'st-pending'}">${esc(r.state_label)}</span></td>
          <td class="mono">${esc(r.receipt_number || '—')}</td>
          <td>${canWrite && r.state === 'overdue'
            ? `<button class="btn btn-outline btn-sm" onclick="quickExtend(${appId},'${r.stage}','${esc(r.schedule)}')">Extend</button>` : ''}</td>
        </tr>`; }).join('');
      const over = s.unscheduled;
      box.innerHTML = `
        ${anyOverdue ? `<div class="alert-bar">
          <b>Payment blocked.</b> A due date has passed. Extend it before recording any payment.
        </div>` : ''}
        <div class="table-wrap"><table class="data sched"><thead><tr>
          <th>Schedule</th><th>Amount</th><th>Due Date</th><th>Paid</th><th>Status</th><th>Receipt</th><th></th>
        </tr></thead><tbody>${rows}</tbody></table></div>
        <div class="sched-foot">
          <span>Scheduled <b>Rs ${num(s.scheduled_total)}</b> of total <b>Rs ${num(s.total_fee)}</b>${
            over > 0 ? ' · <span class="muted">Rs ' + num(over) + ' unscheduled</span>'
            : over < 0 ? ' · <span style="color:var(--bad);font-weight:700">over by Rs ' + num(-over) + '</span>' : ' · <span style="color:var(--ok);font-weight:700">fully scheduled</span>'}</span>
          ${canWrite ? `<button class="btn btn-primary btn-sm" onclick="saveSchedule(${appId})">Save schedule</button>` : ''}
        </div>`;
    } catch (e) { box.innerHTML = emptyState('Could not load schedule', e.message); }
  }

  window.quickExtend = function (appId, stage, label) {
    const today = new Date(); today.setDate(today.getDate() + 7);
    modal('Extend due date — ' + label, `
      <p style="margin-top:0;color:var(--ink-soft);font-size:13.5px">
        This deadline has passed, so payment is blocked. Set a new due date to accept payment.</p>
      <label class="field"><span>New due date</span>
        <input type="date" id="qeDate" value="${today.toISOString().slice(0, 10)}"></label>
      <div style="text-align:right"><button class="btn btn-primary" onclick="doQuickExtend(${appId},'${stage}')">Extend</button></div>`);
  };
  window.doQuickExtend = async function (appId, stage) {
    const d = document.getElementById('qeDate').value;
    if (!d) { toast('Pick a date', '', 'err'); return; }
    try {
      await API.put('/api/admin/applications/' + appId + '/schedule', { rows: [{ stage, due_date: d }] });
      UI.closeModal();
      toast('Due date extended', 'Payment can now be recorded.', 'ok');
      reloadFeePanel(appId);
    } catch (e) { toast('Could not extend', e.message, 'err'); }
  };

  window.saveSchedule = async function (appId) {
    const rows = [];
    document.querySelectorAll('#scheduleBox .sch-amt').forEach(el => {
      const stage = el.dataset.stage;
      const due = document.querySelector('#scheduleBox .sch-due[data-stage="' + stage + '"]');
      rows.push({ stage, amount: parseFloat(el.value || '0'), due_date: due ? due.value : '' });
    });
    try {
      await API.put('/api/admin/applications/' + appId + '/schedule', { rows });
      toast('Schedule saved', 'Payment schedule updated.', 'ok');
      reloadFeePanel(appId);
    } catch (e) { toast('Could not save', e.message, 'err'); }
  };

  async function reloadFeePanel(appId) {
    try {
      const [a, fee] = await Promise.all([
        API.get('/api/admin/applications/' + appId),
        API.get('/api/admin/applications/' + appId + '/fees')
      ]);
      const el = document.getElementById('feePanel');
      if (el) {
        el.innerHTML = feePanelHTML(appId, a, fee, ME.role !== 'staff');
        loadSchedule(appId, ME.role !== 'staff');
      }
    } catch (e) { /* ignore */ }
  }

  window.setTotalFee = function (appId, current) {
    modal('Set total fee', `
      <label class="field"><span>Total fee (Rs)</span><input id="tfAmount" type="number" min="0" value="${esc(current || 0)}"></label>
      <label class="field"><span>Fee category</span><input id="tfCat" placeholder="Admission Fee" value="Admission Fee"></label>
      <div style="text-align:right"><button class="btn btn-primary" onclick="saveTotalFee(${appId})">Save</button></div>`);
  };
  window.saveTotalFee = async function (appId) {
    try {
      await API.patch('/api/admin/applications/' + appId + '/fee', {
        total_fee: parseFloat(document.getElementById('tfAmount').value) || 0,
        fee_category: document.getElementById('tfCat').value.trim()
      });
      closeModal(); toast('Fee updated', '', 'ok'); reloadFeePanel(appId);
    } catch (e) { toast('Failed', e.message, 'err'); }
  };
  window.addInstallment = function (appId) {
    const today = new Date().toISOString().slice(0, 10);
    modal('Add installment', `
      <div class="grid-2">
        <label class="field"><span>Amount (Rs)</span><input id="inAmt" type="number" min="1"></label>
        <label class="field"><span>Due date</span><input id="inDue" type="date" value="${today}"></label>
      </div>
      <label class="field"><span>Label (optional)</span><input id="inLabel" placeholder="e.g. 2nd Installment"></label>
      <div style="text-align:right"><button class="btn btn-primary" onclick="saveInstallment(${appId})">Add</button></div>`);
  };
  window.saveInstallment = async function (appId) {
    const amt = parseFloat(document.getElementById('inAmt').value);
    if (!amt || amt <= 0) { toast('Enter an amount', '', 'err'); return; }
    try {
      await API.post('/api/admin/applications/' + appId + '/installments', {
        amount: amt, due_date: document.getElementById('inDue').value,
        label: document.getElementById('inLabel').value.trim() || null
      });
      closeModal(); toast('Installment added', '', 'ok'); reloadFeePanel(appId);
    } catch (e) { toast('Failed', e.message, 'err'); }
  };
  window.extendDue = function (appId, instId, current) {
    modal('Extend due date', `
      <p style="margin-top:0;color:var(--ink-soft)">The new date appears on the student's challan immediately.</p>
      <label class="field"><span>New due date</span><input id="edDate" type="date" value="${esc(current)}"></label>
      <div style="text-align:right"><button class="btn btn-primary" onclick="saveExtend(${appId},${instId})">Update</button></div>`);
  };
  window.saveExtend = async function (appId, instId) {
    try {
      await API.patch('/api/admin/installments/' + instId, { due_date: document.getElementById('edDate').value });
      closeModal(); toast('Due date extended', '', 'ok'); reloadFeePanel(appId);
    } catch (e) { toast('Failed', e.message, 'err'); }
  };
  window.editInstallment = function (appId, instId, amount) {
    modal('Edit installment', `
      <label class="field"><span>Amount (Rs)</span><input id="eiAmt" type="number" min="1" value="${esc(amount)}"></label>
      <div style="text-align:right"><button class="btn btn-primary" onclick="saveEditInstallment(${appId},${instId})">Save</button></div>`);
  };
  window.saveEditInstallment = async function (appId, instId) {
    try {
      await API.patch('/api/admin/installments/' + instId, { amount: parseFloat(document.getElementById('eiAmt').value) });
      closeModal(); toast('Installment updated', '', 'ok'); reloadFeePanel(appId);
    } catch (e) { toast('Failed', e.message, 'err'); }
  };
  window.deleteInstallment = async function (appId, instId) {
    if (!confirm('Delete this installment?')) return;
    try { await API.del('/api/admin/installments/' + instId); toast('Deleted', '', 'ok'); reloadFeePanel(appId); }
    catch (e) { toast('Failed', e.message, 'err'); }
  };
  window.payInstallment = function (appId, instId) {
    modal('Mark installment paid', `
      <p style="margin-top:0;color:var(--ink-soft)">A Receipt Number is required to approve the payment.</p>
      <div class="grid-2">
        <label class="field"><span>Payment method</span><select id="piMethod">
          <option value="cash">Cash</option><option value="jazzcash">JazzCash</option>
          <option value="bank">Bank</option><option value="other">Other</option>
        </select></label>
        <label class="field"><span>Receipt Number <b style="color:var(--bad)">*</b></span><input id="piReceipt" placeholder="e.g. RCPT-00123"></label>
      </div>
      <div style="text-align:right"><button class="btn btn-ok" onclick="savePay(${appId},${instId})">Confirm paid</button></div>`);
    attachReceiptCheck('piReceipt');
  };
  window.savePay = async function (appId, instId) {
    const receipt = document.getElementById('piReceipt').value.trim();
    if (!receipt) { toast('Receipt Number required', 'Enter the receipt number to approve.', 'err'); return; }
    if (receiptIsBlocked('piReceipt')) { toast('Duplicate receipt number', 'Please enter a unique receipt number.', 'err'); return; }
    try {
      await API.post('/api/admin/installments/' + instId + '/pay', { method: document.getElementById('piMethod').value, receipt_number: receipt });
      closeModal(); toast('Payment recorded', 'Receipt ' + receipt, 'ok'); reloadFeePanel(appId);
    } catch (e) { toast('Failed', e.message, 'err'); }
  };
  window.unpayInstallment = async function (appId, instId) {
    if (!confirm('Undo this payment?')) return;
    try { await API.post('/api/admin/installments/' + instId + '/unpay'); toast('Payment undone', '', 'ok'); reloadFeePanel(appId); }
    catch (e) { toast('Failed', e.message, 'err'); }
  };
  window.recordPayment = function (appId) {
    modal('Record a payment', `
      <p style="margin-top:0;color:var(--ink-soft)">Applied to the oldest unpaid installments automatically. A Receipt Number is required.</p>
      <div class="grid-2">
        <label class="field"><span>Amount received (Rs)</span><input id="rpAmt" type="number" min="1"></label>
        <label class="field"><span>Method</span><select id="rpMethod">
          <option value="cash">Cash</option><option value="jazzcash">JazzCash</option>
          <option value="bank">Bank</option><option value="other">Other</option>
        </select></label>
      </div>
      <label class="field"><span>Receipt Number <b style="color:var(--bad)">*</b></span><input id="rpReceipt" placeholder="e.g. RCPT-00123"></label>
      <div style="text-align:right"><button class="btn btn-primary" onclick="saveRecordPayment(${appId})">Record</button></div>`);
    attachReceiptCheck('rpReceipt');
  };
  window.saveRecordPayment = async function (appId) {
    const amt = parseFloat(document.getElementById('rpAmt').value);
    const receipt = document.getElementById('rpReceipt').value.trim();
    if (!amt || amt <= 0) { toast('Enter an amount', '', 'err'); return; }
    if (!receipt) { toast('Receipt Number required', '', 'err'); return; }
    if (receiptIsBlocked('rpReceipt')) { toast('Duplicate receipt number', 'Please enter a unique receipt number.', 'err'); return; }
    try {
      await API.post('/api/admin/applications/' + appId + '/payments', { amount: amt, method: document.getElementById('rpMethod').value, receipt_number: receipt });
      closeModal(); toast('Payment recorded', 'Receipt ' + receipt, 'ok'); reloadFeePanel(appId);
    } catch (e) { toast('Failed', e.message, 'err'); }
  };

  window.setStatus = async function (id, patch) {
    try {
      await API.patch('/api/admin/applications/' + id + '/status', patch);
      toast('Status updated', '', 'ok');
      pages.applicationDetail(id);
    } catch (e) { toast('Update failed', e.message, 'err'); }
  };
  window.addNote = async function (id) {
    const t = document.getElementById('noteText');
    if (!t.value.trim()) return;
    try {
      await API.post('/api/admin/applications/' + id + '/notes', { note: t.value.trim() });
      toast('Note added', '', 'ok');
      pages.applicationDetail(id);
    } catch (e) { toast('Could not add note', e.message, 'err'); }
  };
  window.linkChat = async function (sessionId, studentId, appId) {
    try {
      const r = await API.post('/api/admin/chats/' + sessionId + '/link/' + studentId);
      toast('Chat linked', r.message || '', 'ok');
      pages.applicationDetail(appId);
    } catch (e) { toast('Link failed', e.message, 'err'); }
  };

  /* ══ Create / edit application form ═══════════════════════════════ */
  function courseOptionsFor(fo, category, selected) {
    const cat = (fo.programme_catalog || {})[category];
    if (!cat) return '<option value="">Select programme first…</option>';
    let html = '<option value="">Select course…</option>';
    if (cat.grouped) {
      Object.entries(cat.groups).forEach(([g, list]) => {
        html += `<optgroup label="${esc(g)}">` +
          list.map(c => `<option ${selected === c ? 'selected' : ''}>${esc(c)}</option>`).join('') +
          '</optgroup>';
      });
    } else {
      html += cat.courses.map(c => `<option ${selected === c ? 'selected' : ''}>${esc(c)}</option>`).join('');
    }
    return html;
  }

  window.newApplication = async function () {
    const fo = await formOptions();
    // The next roll number in this campus's sequence — pre-filled so the admin
    // never has to work it out by hand.
    let nextRoll = { next_roll: '', prefix: '', campus: '' };
    try { nextRoll = await API.get('/api/admin/next-roll'); } catch (e) {}
    const today = new Date().toISOString().slice(0, 10);
    const f = (label, id, req, type) =>
      `<label class="field"><span>${label} ${req ? '<b style="color:var(--bad)">*</b>' : '<small style="color:var(--ink-faint)">(optional)</small>'}</span><input id="${id}" type="${type || 'text'}"></label>`;
    modal('Create New Application', `
      <h2 class="section" style="margin-top:0">Student information</h2>
      <div class="grid-2">
        ${f('Student Name', 'naFull', true)}
        ${f('Father Name', 'naFather', false)}
        <label class="field"><span>Roll Number <b style="color:var(--bad)">*</b></span>
          <input id="naRoll" value="${esc(nextRoll.next_roll || '')}">
          ${nextRoll.next_roll ? `<div class="roll-hint">Next in sequence for ${esc(nextRoll.campus)} — roll numbers must run consecutively.</div>` : ''}
        </label>
        ${f('Phone Number', 'naPhone', true)}
        ${f('Guardian Phone Number', 'naGuardian')}
        ${f('Email Address', 'naEmail', false, 'email')}
        ${f('CNIC', 'naCnic', false)}
      </div>
      <label class="field"><span>Address <small style="color:var(--ink-faint)">(optional)</small></span><textarea id="naAddr"></textarea></label>

      <h2 class="section">Academic information</h2>
      <div class="grid-2">
        <label class="field"><span>Programme Category <b style="color:var(--bad)">*</b></span>
          <select id="naCat"><option value="">Select…</option>
            ${(fo.programme_categories || []).map(c => `<option>${esc(c)}</option>`).join('')}
          </select></label>
        <label class="field"><span>Course <b style="color:var(--bad)">*</b></span>
          <select id="naCourse"><option value="">Select programme first…</option></select></label>
        <label class="field"><span>Class Timing <b style="color:var(--bad)">*</b></span>
          <select id="naTiming"><option value="">Select…</option>
            <option>Morning</option><option>Afternoon</option><option>Evening</option><option>Weekend</option>
          </select></label>
        <label class="field"><span>Admission Date <b style="color:var(--bad)">*</b></span><input id="naAdmDate" type="date" value="${today}"></label>
        ${f('Marks', 'naMarks', false, 'number')}
        ${f('Duration', 'naDuration', false)}
      </div>

      <h2 class="section">How did you hear about us?</h2>
      <div class="grid-2">
        <label class="field"><span>Lead Source <b style="color:var(--bad)">*</b></span>
          <select id="naSource" onchange="document.getElementById('naSpecifyWrap').style.display=this.value==='Others'?'block':'none'">
            <option value="">Select…</option>
            ${(fo.lead_sources || []).map(s => `<option>${esc(s)}</option>`).join('')}
          </select></label>
        <div id="naSpecifyWrap" style="display:none">
          <label class="field"><span>Please specify <b style="color:var(--bad)">*</b></span><input id="naSpecify"></label>
        </div>
      </div>

      <div class="acad-card">
        <div class="acad-head">
          <h2>Academic Information</h2>
          <span class="opt-pill">All optional</span>
        </div>
        <p class="acad-note">Used on the student's Attendance Card. You can add or change these later.</p>
        <div class="grid-2">
          <label class="field"><span>Class Time</span><input id="naClassTime" placeholder="e.g. 2:00 PM – 4:00 PM"></label>
          <label class="field"><span>Lab Time</span><input id="naLabTime" placeholder="e.g. 4:00 PM – 5:00 PM"></label>
          <label class="field"><span>Instructor Name</span><input id="naInstructor" placeholder="e.g. Muhammad Bilal"></label>
          <label class="field"><span>Course Duration (months)</span>
            <select id="naDurMonths">
              ${[1,2,3,4,5,6,9,12,18,24].map(m => `<option value="${m}"${m === 3 ? ' selected' : ''}>${m} month${m > 1 ? 's' : ''}</option>`).join('')}
            </select></label>
        </div>
      </div>

      <div style="text-align:right;margin-top:8px"><button class="btn btn-primary" id="naSubmit">Create Application</button></div>`);

    document.getElementById('naCat').addEventListener('change', function () {
      document.getElementById('naCourse').innerHTML = courseOptionsFor(fo, this.value, '');
    });
    document.getElementById('naSubmit').addEventListener('click', submitNewApplication);
  };

  async function submitNewApplication() {
    const v = id => (document.getElementById(id) || {}).value || '';
    const body = {
      full_name: v('naFull').trim(), father_name: v('naFather').trim(),
      roll_number: v('naRoll').trim(), phone: v('naPhone').trim(),
      guardian_phone: v('naGuardian').trim(),
      email: v('naEmail').trim() || null, cnic: v('naCnic').trim() || null,
      address: v('naAddr').trim(),
      programme_category: v('naCat'), course_name: v('naCourse'),
      session: '', class_timing: v('naTiming'),
      admission_date: v('naAdmDate') || null,
      marks: v('naMarks') !== '' ? parseFloat(v('naMarks')) : null,
      duration: v('naDuration').trim() || null,
      lead_source: v('naSource'), lead_source_detail: v('naSpecify').trim(),
      class_time: v('naClassTime').trim(),
      lab_time: v('naLabTime').trim(),
      instructor_name: v('naInstructor').trim(),
      course_duration_months: parseInt(v('naDurMonths') || '3', 10)
    };
    // client-side required checks
    const need = { full_name: 'Student Name', roll_number: 'Roll Number', phone: 'Phone Number', programme_category: 'Programme Category', course_name: 'Course', class_timing: 'Class Timing', lead_source: 'Lead Source' };
    for (const k in need) if (!body[k]) { toast('Missing field', need[k] + ' is required.', 'err'); return; }
    if (body.lead_source === 'Others' && !body.lead_source_detail) { toast('Missing field', 'Please specify how you heard about us.', 'err'); return; }

    const btn = document.getElementById('naSubmit');
    btn.disabled = true; btn.textContent = 'Creating…';
    try {
      const r = await API.post('/api/admin/applications', body);
      closeModal();
      toast('Application created', r.message || '', 'ok');
      location.hash = '#/applications/' + r.id;
    } catch (e) {
      toast('Could not create application', e.message, 'err');
      btn.disabled = false; btn.textContent = 'Create Application';
    }
  }

  window.editApp = async function (id) {
    const a = await API.get('/api/admin/applications/' + id);
    const fo = await formOptions();
    let admins = [];
    if (ME.role === 'super_admin') { try { admins = (await API.get('/api/auth/admins')).items; } catch (e) {} }
    const f = (label, id_, val, type) =>
      `<label class="field"><span>${label}</span><input id="${id_}" type="${type || 'text'}" value="${esc(val ?? '')}"></label>`;
    modal('Edit application — Roll ' + esc(a.roll_number || ''), `
      <h2 class="section" style="margin-top:0">Student</h2>
      <div class="grid-2">
        ${f('Roll Number', 'eRoll', a.roll_number)}
        ${f('Student name', 'eFull', a.full_name)}
        ${f('Father name', 'eFather', a.father_name)}
        ${f('CNIC', 'eCnic', a.cnic)}
        ${f('Phone', 'ePhone', a.phone)}
        ${f('Guardian Phone', 'eGuardian', a.guardian_phone)}
        ${f('Email', 'eEmail', a.email)}
        ${f('City', 'eCity', a.city)}
      </div>
      <label class="field"><span>Address</span><textarea id="eAddr">${esc(a.address || '')}</textarea></label>

      <h2 class="section">Academic</h2>
      <div class="grid-2">
        <label class="field"><span>Programme Category</span>
          <select id="eCat"><option value="">—</option>${(fo.programme_categories || []).map(c => `<option ${a.programme_category === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label>
        <label class="field"><span>Course</span><select id="eCourseName">${courseOptionsFor(fo, a.programme_category, a.course_name || a.course)}</select></label>
        <label class="field"><span>Session</span><select id="eSession"><option value="">—</option>${(fo.sessions || []).map(s => `<option ${a.session === s ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></label>
        <label class="field"><span>Class timing</span><select id="eTiming">${['', 'Morning', 'Afternoon', 'Evening', 'Weekend'].map(t => `<option ${a.class_timing === t ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
        ${f('Marks', 'ePct', a.percentage, 'number')}
      </div>

      <h2 class="section">Application</h2>
      <div class="grid-2">
        <label class="field"><span>Lead source</span>
          <select id="eSource" onchange="document.getElementById('eSpecWrap').style.display=this.value==='Others'?'block':'none'">
            <option value="">—</option>${(fo.lead_sources || []).map(s => `<option ${a.lead_source === s ? 'selected' : ''}>${esc(s)}</option>`).join('')}
          </select></label>
        <div id="eSpecWrap" style="display:${a.lead_source === 'Others' ? 'block' : 'none'}">
          <label class="field"><span>Please specify</span><input id="eSpec" value="${esc(a.lead_source_detail || '')}"></label>
        </div>
        ${admins.length ? `<label class="field"><span>Assigned staff</span><select id="eStaff"><option value="0">— Unassigned —</option>${admins.map(ad => `<option value="${ad.id}" ${a.assigned_staff_id === ad.id ? 'selected' : ''}>${esc(ad.name)}</option>`).join('')}</select></label>` : ''}
      </div>

      <div class="acad-card">
        <div class="acad-head">
          <h2>Academic Information</h2>
          <span class="opt-pill">All optional · shown on the Attendance Card</span>
        </div>
        <div class="grid-2">
          <label class="field"><span>Class Time</span><input id="eClassTime" value="${esc(a.class_time || '')}" placeholder="e.g. 2:00 PM – 4:00 PM"></label>
          <label class="field"><span>Lab Time</span><input id="eLabTime" value="${esc(a.lab_time || '')}" placeholder="e.g. 4:00 PM – 5:00 PM"></label>
          <label class="field"><span>Instructor Name</span><input id="eInstructor" value="${esc(a.instructor_name || '')}" placeholder="e.g. Muhammad Bilal"></label>
          <label class="field"><span>Course Duration (months)</span>
            <select id="eDurMonths">
              ${[1,2,3,4,5,6,9,12,18,24].map(m => `<option value="${m}"${(a.course_duration_months || 3) === m ? ' selected' : ''}>${m} month${m > 1 ? 's' : ''}</option>`).join('')}
            </select></label>
        </div>
      </div>

      <label class="field"><span>Remarks</span><textarea id="eRemarks">${esc(a.remarks || '')}</textarea></label>
      <div style="text-align:right"><button class="btn btn-primary" onclick="saveApp(${id})">Save changes</button></div>`);

    document.getElementById('eCat').addEventListener('change', function () {
      document.getElementById('eCourseName').innerHTML = courseOptionsFor(fo, this.value, '');
    });
  };
  window.saveApp = async function (id) {
    const v = id_ => (document.getElementById(id_) || {}).value;
    const body = {
      roll_number: v('eRoll'), full_name: v('eFull'), father_name: v('eFather'),
      cnic: v('eCnic') || null, phone: v('ePhone'),
      guardian_phone: v('eGuardian') || '', email: v('eEmail') || null,
      city: v('eCity'), address: v('eAddr'),
      programme_category: v('eCat') || null, course_name: v('eCourseName') || null,
      session: v('eSession') || null, class_timing: v('eTiming'),
      lead_source: v('eSource') || null, lead_source_detail: v('eSpec') || '',
      remarks: v('eRemarks'),
      class_time: v('eClassTime') || '',
      lab_time: v('eLabTime') || '',
      instructor_name: v('eInstructor') || '',
      course_duration_months: parseInt(v('eDurMonths') || '3', 10),
      percentage: v('ePct') !== '' && v('ePct') != null ? parseFloat(v('ePct')) : null
    };
    const staff = document.getElementById('eStaff');
    if (staff) body.assigned_staff_id = parseInt(staff.value) || 0;
    try {
      await API.patch('/api/admin/applications/' + id, body);
      closeModal(); toast('Application updated', '', 'ok');
      pages.applicationDetail(id);
    } catch (e) { toast('Save failed', e.message, 'err'); }
  };

  /* ══ Conversations list ════════════════════════════════════════════ */
  const chatState = { page: 1 };
  pages.chats = async function () {
    content.innerHTML = `
      <div class="page-head">
        <div><h1>Conversations</h1><p>Every chatbot conversation, saved permanently — like a ChatGPT history for your visitors.</p></div>
        <div class="spacer"></div>
        <button class="btn btn-outline" onclick="exportData('chats')">Export</button>
      </div>
      <div class="filters">
        <input class="grow" id="cQ" placeholder="Search titles, messages, visitor names, phone, IP…" value="${esc(chatState.q || '')}">
        <select id="cDevice">
          <option value="">Device: all</option>
          ${['Desktop','Mobile','Tablet'].map(d => `<option ${chatState.device===d?'selected':''}>${d}</option>`).join('')}
        </select>
        <select id="cLinked">
          <option value="">All conversations</option>
          <option value="true" ${chatState.linked==='true'?'selected':''}>Linked to a student</option>
        </select>
        <select id="cStatus">
          <option value="">Active + archived</option>
          <option value="active" ${chatState.status==='active'?'selected':''}>Active only</option>
          <option value="archived" ${chatState.status==='archived'?'selected':''}>Archived only</option>
        </select>
        <input type="date" id="cFrom" value="${esc(chatState.date_from || '')}">
        <input type="date" id="cTo" value="${esc(chatState.date_to || '')}">
        <button class="btn btn-primary btn-sm" id="cGo">Apply</button>
      </div>
      <div class="card" id="chatsBox">${spinner()}</div>`;
    document.getElementById('cGo').addEventListener('click', () => {
      Object.assign(chatState, {
        q: document.getElementById('cQ').value.trim(),
        device: document.getElementById('cDevice').value,
        linked: document.getElementById('cLinked').value,
        status: document.getElementById('cStatus').value,
        date_from: document.getElementById('cFrom').value,
        date_to: document.getElementById('cTo').value,
        page: 1
      });
      loadChats();
    });
    document.getElementById('cQ').addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('cGo').click(); });
    loadChats();
  };
  window.chatsPage = function (p) { chatState.page = p; loadChats(); };

  async function loadChats() {
    const box = document.getElementById('chatsBox');
    if (!box) return;
    box.innerHTML = spinner();
    try {
      const r = await API.get('/api/admin/chats' + API.qs(chatState));
      const icon = d => d === 'Mobile' ? '📱' : d === 'Tablet' ? '📲' : '💻';
      box.innerHTML = (r.items.map(s => `
        <div class="session-row" onclick="location.hash='#/chats/${esc(s.id)}'">
          <div class="session-ic">${icon(s.device)}</div>
          <div class="s-body">
            <b>${esc(s.title || 'Untitled conversation')}</b>
            <small>${esc(s.visitor_name || 'Anonymous visitor')}${s.student_name ? ' · linked to <b>' + esc(s.student_name) + '</b>' : ''} · ${esc(s.browser || '')} ${esc(s.os ? '· ' + s.os : '')}</small>
          </div>
          <div class="s-side">${s.message_count} messages<br>${ago(s.last_activity_at)}</div>
        </div>`).join('') || emptyState('No conversations yet', 'Chats from the website widget will appear here.')) +
        pager(r, 'chatsPage');
    } catch (e) { box.innerHTML = emptyState('Could not load conversations', e.message); }
  }

  /* ══ Conversation viewer ═══════════════════════════════════════════ */
  pages.chatDetail = async function (sessionId) {
    content.innerHTML = spinner();
    try {
      const s = await API.get('/api/admin/chats/' + sessionId);
      content.innerHTML = `
        <div class="page-head">
          <div>
            <p><a href="#/chats" style="text-decoration:none;color:var(--ink-soft)">← Conversations</a></p>
            <h1 style="font-size:21px">${esc(s.title || 'Untitled conversation')}</h1>
          </div>
          <div class="spacer"></div>
          ${s.student_id ? `<a class="btn btn-outline btn-sm" href="#/applications" onclick="appState.q='${esc(s.visitor_phone || s.student_name || '')}'">View student</a>` : ''}
          <button class="btn btn-gold btn-sm" onclick="API.download('/api/admin/chats/${esc(s.id)}/pdf').catch(e=>UI.toast('PDF failed',e.message,'err'))">⬇ PDF / Print</button>
          ${ME.role !== 'staff' ? `<button class="btn btn-outline btn-sm" onclick="archiveChat('${esc(s.id)}')">${s.status === 'archived' ? 'Unarchive' : 'Archive'}</button>` : ''}
          ${ME.role === 'super_admin' ? `<button class="btn btn-bad btn-sm" onclick="deleteChat('${esc(s.id)}')">Delete</button>` : ''}
        </div>
        <div class="card">
          <div class="chat-meta">
            <span>Visitor: <b>${esc(s.visitor_name || 'Anonymous')}</b></span>
            ${s.visitor_phone ? `<span>Phone: <b>${esc(s.visitor_phone)}</b></span>` : ''}
            ${s.student_name ? `<span>Student: <b>${esc(s.student_name)}</b></span>` : ''}
            <span>Device: <b>${esc(s.device || '—')}</b></span>
            <span>Browser: <b>${esc(s.browser || '—')}</b></span>
            <span>OS: <b>${esc(s.os || '—')}</b></span>
            <span>IP: <b>${esc(s.ip_address || '—')}</b></span>
            ${s.country ? `<span>Country: <b>${esc(s.country)}</b></span>` : ''}
            <span>Started: <b>${fmtDateTime(s.started_at)}</b></span>
            <span>Duration: <b>${fmtDuration(s.duration_seconds)}</b></span>
            <span>Messages: <b>${s.message_count}</b></span>
            ${s.page_url ? `<span>Page: <b>${esc(s.page_url)}</b></span>` : ''}
            ${s.status === 'archived' ? `<span>${badge('archived')}</span>` : ''}
          </div>
          <div class="chat-scroll" id="chatScroll">
            ${(s.messages || []).map(m => `
              <div class="bubble ${m.role === 'user' ? 'user' : 'assistant'}">${esc(m.content)}
                <span class="b-time">${fmtDateTime(m.created_at)}${m.response_time_ms ? ' · replied in ' + (m.response_time_ms / 1000).toFixed(1) + 's' : ''}</span>
              </div>`).join('') || emptyState('No messages', '')}
          </div>
        </div>`;
      const sc = document.getElementById('chatScroll');
      if (sc) sc.scrollTop = sc.scrollHeight;
    } catch (e) { content.innerHTML = emptyState('Could not load conversation', e.message); }
  };
  window.archiveChat = async function (id) {
    try {
      const r = await API.patch('/api/admin/chats/' + id + '/archive');
      toast('Conversation ' + r.status, '', 'ok');
      pages.chatDetail(id);
    } catch (e) { toast('Archive failed', e.message, 'err'); }
  };
  window.deleteChat = async function (id) {
    if (!confirm('Delete this conversation permanently?')) return;
    try {
      await API.del('/api/admin/chats/' + id);
      toast('Conversation deleted', '', 'ok');
      location.hash = '#/chats';
    } catch (e) { toast('Delete failed', e.message, 'err'); }
  };

  /* ══ Live monitor ══════════════════════════════════════════════════ */
  pages.live = async function () {
    content.innerHTML = `
      <div class="page-head">
        <div><h1>Live Monitor</h1><p>Visitor messages stream in here the moment they're sent — no refresh needed.</p></div>
        <div class="spacer"></div>
        <span class="badge b-active" id="liveBadge">listening</span>
      </div>
      <div class="grid-main-side">
        <div class="card">
          <div class="card-title"><h2>Real-time feed</h2></div>
          <div class="feed" id="liveFeed" style="max-height:70vh">
            ${liveFeed.map(feedItemHTML).join('') || emptyState('Waiting for activity…', 'Chat messages, new applications and leads appear instantly.')}
          </div>
        </div>
        <div class="card">
          <div class="card-title"><h2>Active today</h2></div>
          <div id="activeToday">${spinner()}</div>
        </div>
      </div>`;
    try {
      const today = new Date().toISOString().slice(0, 10);
      const r = await API.get('/api/admin/chats' + API.qs({ date_from: today, page_size: 15 }));
      document.getElementById('activeToday').innerHTML =
        r.items.map(s => `
          <div class="session-row" onclick="location.hash='#/chats/${esc(s.id)}'">
            <div class="session-ic">💬</div>
            <div class="s-body"><b>${esc(s.title || 'Untitled')}</b><small>${s.message_count} messages · ${ago(s.last_activity_at)}</small></div>
          </div>`).join('') || emptyState('No chats today yet', '');
    } catch (e) { document.getElementById('activeToday').innerHTML = emptyState('Could not load', e.message); }
  };

  /* ══ Leads ═════════════════════════════════════════════════════════ */
  const leadState = { page: 1 };
  pages.leads = async function () {
    const fo = await formOptions().catch(() => ({ campuses: [] }));
    content.innerHTML = `
      <div class="page-head">
        <div><h1>Leads</h1><p>Quick enquiries captured by the chatbot — these used to go to Google Sheets.</p></div>
        <div class="spacer"></div>
        <button class="btn btn-outline" onclick="exportData('leads')">Export</button>
      </div>
      <div class="stat-grid" id="leadStats"></div>
      <div class="filters">
        <input class="grow" id="lQ" placeholder="Search name, phone, email, city, course…" value="${esc(leadState.q || '')}">
        <select id="lSource"><option value="">Source: all</option>
          ${['chatbot','admission_form','contact_form','course_inquiry','newsletter','website_popup','other'].map(s => `<option value="${s}" ${leadState.source===s?'selected':''}>${s.replace(/_/g,' ')}</option>`).join('')}
        </select>
        <select id="lStatus"><option value="">Status: all</option>
          ${['new','contacted','interested','follow_up','documents_pending','application_submitted','converted','rejected','lost'].map(s => `<option value="${s}" ${leadState.status===s?'selected':''}>${s.replace(/_/g,' ')}</option>`).join('')}
        </select>
        <select id="lCampus"><option value="">Campus: all</option>${fo.campuses.map(cp => `<option ${leadState.campus===cp?'selected':''}>${esc(cp)}</option>`).join('')}</select>
        <button class="btn btn-primary btn-sm" id="lGo">Apply</button>
      </div>
      <div class="card" id="leadsBox">${spinner()}</div>`;
    document.getElementById('lGo').addEventListener('click', () => {
      Object.assign(leadState, {
        q: document.getElementById('lQ').value.trim(),
        status: document.getElementById('lStatus').value,
        campus: document.getElementById('lCampus').value,
        source: document.getElementById('lSource').value,
        page: 1
      });
      loadLeads();
    });
    API.get('/api/admin/analytics/leads').then(st => {
      const el = document.getElementById('leadStats');
      if (!el) return;
      el.innerHTML = `
        <div class="stat"><div class="label">Total leads</div><div class="value">${num(st.total)}</div><div class="sub">${num(st.today)} today · ${num(st.this_week)} this week</div></div>
        <div class="stat gold"><div class="label">This month</div><div class="value">${num(st.this_month)}</div></div>
        <div class="stat green"><div class="label">Conversion rate</div><div class="value">${esc(st.conversion_rate)}%</div><div class="sub">became applications</div></div>
        <div class="stat blue"><div class="label">Top source</div><div class="value" style="font-size:20px;text-transform:capitalize">${esc((st.by_source[0] || {}).source || '—').replace(/_/g,' ')}</div><div class="sub">${st.by_source.map(x => x.source.replace(/_/g,' ') + ' ' + x.count).slice(0,3).join(' · ')}</div></div>`;
    }).catch(() => {});
    document.getElementById('lQ').addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('lGo').click(); });
    loadLeads();
  };
  window.leadsPage = function (p) { leadState.page = p; loadLeads(); };

  async function loadLeads() {
    const box = document.getElementById('leadsBox');
    if (!box) return;
    box.innerHTML = spinner();
    const canWrite = ME.role !== 'staff';
    try {
      const r = await API.get('/api/admin/leads' + API.qs(leadState));
      box.innerHTML = `
        <div class="table-wrap"><table class="data"><thead><tr>
          <th>Name</th><th>Contact</th><th>Interest</th><th>Source</th><th>Assigned</th><th>Received</th><th>Status</th><th></th>
        </tr></thead><tbody>
        ${r.items.map(l => `<tr onclick="openLead(${l.id})">
          <td class="td-main"><b>${esc(l.name)}</b><small>${esc(l.city || '')}</small></td>
          <td class="td-main"><b style="font-weight:500">${esc(l.phone)}</b><small>${esc(l.email || '')}</small></td>
          <td class="td-main"><b style="font-weight:500">${esc(l.interested_course || l.campus || '—')}</b><small>${esc(l.campus || '')}</small></td>
          <td>${badge(l.source || 'chatbot')}</td>
          <td>${esc(l.assigned_to_name || '—')}${l.follow_up_at ? '<br><small style="color:var(--warn)">⏰ ' + fmtDateTime(l.follow_up_at) + '</small>' : ''}</td>
          <td class="mono">${fmtDateTime(l.created_at)}</td>
          <td onclick="event.stopPropagation()">${canWrite ? `<select style="width:auto" onchange="setLeadStatus(${l.id}, this.value)">
            ${['new','contacted','interested','follow_up','documents_pending','application_submitted','converted','rejected','lost'].map(st => `<option value="${st}" ${l.status===st?'selected':''}>${st.replace(/_/g,' ')}</option>`).join('')}
          </select>` : badge(l.status)}</td>
          <td onclick="event.stopPropagation()">${l.session_id ? `<a class="btn btn-outline btn-sm" href="#/chats/${esc(l.session_id)}">Chat</a>` : ''}</td>
        </tr>`).join('') || '<tr><td colspan="8">' + emptyState('No leads yet', 'Chatbot, form and website enquiries will appear here.') + '</td></tr>'}
        </tbody></table></div>${pager(r, 'leadsPage')}`;
    } catch (e) { box.innerHTML = emptyState('Could not load leads', e.message); }
  }
  window.setLeadStatus = async function (id, status) {
    try { await API.patch('/api/admin/leads/' + id, { status }); toast('Lead updated', '', 'ok'); }
    catch (e) { toast('Update failed', e.message, 'err'); loadLeads(); }
  };

  window.openLead = async function (id) {
    try {
      const l = await API.get('/api/admin/leads/' + id);
      let admins = [];
      if (ME.role === 'super_admin') {
        try { admins = (await API.get('/api/auth/admins')).items; } catch (e) {}
      }
      const canWrite = ME.role !== 'staff';
      modal('Lead — ' + l.name, `
        <div class="detail-grid" style="grid-template-columns:1fr 1fr">
          <div class="dl"><dt>Phone</dt><dd><a href="tel:${esc(l.phone)}">${esc(l.phone)}</a></dd></div>
          <div class="dl"><dt>Email</dt><dd>${l.email ? '<a href="mailto:' + esc(l.email) + '">' + esc(l.email) + '</a>' : '—'}</dd></div>
          <div class="dl"><dt>City</dt><dd>${esc(l.city) || '—'}</dd></div>
          <div class="dl"><dt>Campus</dt><dd>${esc(l.campus) || '—'}</dd></div>
          <div class="dl"><dt>Interested course</dt><dd>${esc(l.interested_course) || '—'}</dd></div>
          <div class="dl"><dt>Source</dt><dd>${badge(l.source)}</dd></div>
          <div class="dl"><dt>Status</dt><dd>${badge(l.status)}</dd></div>
          <div class="dl"><dt>Received</dt><dd>${fmtDateTime(l.created_at)}</dd></div>
        </div>
        ${canWrite ? `
        <div class="grid-2" style="margin-top:12px">
          <label class="field"><span>Assign to staff</span>
            <select id="ldAssign" ${admins.length ? '' : 'disabled title="Super admin can assign"'}>
              <option value="0">— Unassigned —</option>
              ${admins.map(a => `<option value="${a.id}" ${l.assigned_to === a.id ? 'selected' : ''}>${esc(a.name)}</option>`).join('')}
              ${!admins.length && l.assigned_to_name ? `<option selected>${esc(l.assigned_to_name)}</option>` : ''}
            </select></label>
          <label class="field"><span>Schedule follow-up</span>
            <input type="datetime-local" id="ldFollow" value="${l.follow_up_at ? esc(String(l.follow_up_at).slice(0, 16)) : ''}"></label>
        </div>
        <div style="text-align:right;margin-bottom:14px"><button class="btn btn-primary btn-sm" onclick="saveLead(${l.id})">Save</button></div>` : ''}
        <h2 class="section" style="font-size:15px">Notes</h2>
        <div style="max-height:180px;overflow-y:auto">
          ${(l.notes || []).map(n => `<div class="note"><small>${esc(n.admin_name)} · ${fmtDateTime(n.created_at)}</small><p>${esc(n.note)}</p></div>`).join('') || '<p style="color:var(--ink-faint);font-size:13px">No notes yet.</p>'}
        </div>
        ${canWrite ? `<textarea id="ldNote" placeholder="Add a note (call summary, next step…)"></textarea>
        <div style="text-align:right;margin-top:8px"><button class="btn btn-primary btn-sm" onclick="addLeadNote(${l.id})">Add note</button></div>` : ''}`);
    } catch (e) { toast('Could not load lead', e.message, 'err'); }
  };
  window.saveLead = async function (id) {
    const sel = document.getElementById('ldAssign');
    const body = { follow_up_at: document.getElementById('ldFollow').value || '' };
    if (sel && !sel.disabled) body.assigned_to = parseInt(sel.value) || 0;
    try { await API.patch('/api/admin/leads/' + id, body); toast('Lead saved', '', 'ok'); closeModal(); loadLeads(); }
    catch (e) { toast('Save failed', e.message, 'err'); }
  };
  window.addLeadNote = async function (id) {
    const t = document.getElementById('ldNote');
    if (!t.value.trim()) return;
    try { await API.post('/api/admin/leads/' + id + '/notes', { note: t.value.trim() }); toast('Note added', '', 'ok'); openLead(id); }
    catch (e) { toast('Could not add note', e.message, 'err'); }
  };




  /* ══ Challans — all challans (Module 1) ═════════════════════════════ */

  window.challansPage = function (p) { chalState.page = p; loadChallans(); };

  /* ══ Expense Management (Module 16-17) ═════════════════════════════ */
  const expState = { page: 1 };
  /* ══ Transfer Students ════════════════════════════════════════════ */
  /* ══ Money Transfer — inter-campus fee movement ═══════════════════ */
  const mtState = { status: '', q: '', found: null };

  pages['money-transfers'] = async function () {
    content.innerHTML = `
      <div class="page-head">
        <div><h1>Money Transfer</h1>
        <p>Move a student's paid fee from your campus to another. The destination
           campus verifies the roll number and approves — nothing changes until then.</p></div>
      </div>
      <div id="mtReqBox">${spinner()}</div>
      <div style="height:18px"></div>
      <h2 class="section">New money transfer</h2>
      <div class="card"><div class="card-pad">
        <div class="mt-form">
          <label class="field"><span>Source campus</span>
            <input id="mtSource" value="${esc(ME.campus || 'Your campus')}" disabled></label>
          <label class="field"><span>Destination campus <b style="color:var(--bad)">*</b></span>
            <select id="mtDest"><option value="">Select…</option>
              ${(window.OPTS && OPTS.campuses ? OPTS.campuses : ['Walton Road','Queen Road','Darogwala','Bhagbanpura'])
                .filter(c => c !== ME.campus).map(c => `<option>${esc(c)}</option>`).join('')}
            </select></label>
          <label class="field"><span>Student roll number <b style="color:var(--bad)">*</b></span>
            <div class="mt-roll"><input id="mtRoll" placeholder="e.g. ${esc((ME.campus||'W')[0])}-15">
              <button class="btn btn-outline" id="mtFind">Find</button></div></label>
        </div>
        <div id="mtStudent"></div>
        <div class="mt-form" id="mtAmtRow" style="display:none">
          <label class="field"><span>Transfer amount (Rs) <b style="color:var(--bad)">*</b></span>
            <input id="mtAmount" type="number" min="1" placeholder="0"></label>
          <label class="field" style="grid-column:span 2"><span>Remarks (optional)</span>
            <input id="mtRemarks" placeholder="Reason for transfer"></label>
        </div>
        <div id="mtSubmitRow" style="display:none;text-align:right;margin-top:6px">
          <button class="btn btn-primary" id="mtSubmit">Send transfer request</button>
        </div>
      </div></div>`;
    document.getElementById('mtFind').addEventListener('click', mtFindStudent);
    document.getElementById('mtRoll').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); mtFindStudent(); } });
    document.getElementById('mtSubmit').addEventListener('click', mtSubmit);
    loadMoneyTransfers();
  };

  async function mtFindStudent() {
    const roll = document.getElementById('mtRoll').value.trim();
    const box = document.getElementById('mtStudent');
    mtState.found = null;
    document.getElementById('mtAmtRow').style.display = 'none';
    document.getElementById('mtSubmitRow').style.display = 'none';
    if (!roll) { toast('Enter a roll number', '', 'err'); return; }
    box.innerHTML = spinner();
    try {
      const s = await API.get('/api/admin/money-transfers/lookup' + API.qs({ roll }));
      mtState.found = s;
      box.innerHTML = `
        <div class="mt-student">
          <div class="mt-s-grid">
            <div><span>Student</span><b>${esc(s.student_name)}</b></div>
            <div><span>Father</span><b>${esc(s.father_name || '—')}</b></div>
            <div><span>Course</span><b>${esc(s.course || '—')}</b></div>
            <div><span>Campus</span><b>${esc(s.campus)}</b></div>
            <div><span>Total paid</span><b>Rs ${num(s.total_paid)}</b></div>
            <div><span>Remaining fee</span><b>Rs ${num(s.remaining_fee)}</b></div>
            <div class="hl"><span>Transferable balance</span><b>Rs ${num(s.transferable)}</b></div>
          </div>
        </div>`;
      document.getElementById('mtAmtRow').style.display = '';
      document.getElementById('mtSubmitRow').style.display = '';
      document.getElementById('mtAmount').max = s.transferable;
    } catch (e) {
      box.innerHTML = `<div class="mt-err">${esc(e.message)}</div>`;
    }
  }

  async function mtSubmit() {
    if (!mtState.found) { toast('Find a student first', '', 'err'); return; }
    const dest = document.getElementById('mtDest').value;
    const amount = parseFloat(document.getElementById('mtAmount').value || '0');
    const remarks = document.getElementById('mtRemarks').value.trim();
    if (!dest) { toast('Select destination campus', '', 'err'); return; }
    if (!(amount > 0)) { toast('Enter a valid amount', '', 'err'); return; }
    if (amount > mtState.found.transferable + 0.01) {
      toast('Too much', 'Amount exceeds the transferable balance.', 'err'); return;
    }
    try {
      const r = await API.post('/api/admin/money-transfers', {
        dest_campus: dest, roll: mtState.found.roll_number, amount, remarks });
      toast('Request sent', `${r.transfer_no} → ${dest} for approval.`, 'ok');
      document.getElementById('mtRoll').value = '';
      document.getElementById('mtStudent').innerHTML = '';
      document.getElementById('mtAmtRow').style.display = 'none';
      document.getElementById('mtSubmitRow').style.display = 'none';
      mtState.found = null;
      loadMoneyTransfers();
    } catch (e) { toast('Could not send', e.message, 'err'); }
  }

  const MT_CLS = { pending: 'st-pending', approved: 'st-paid', rejected: 'st-overdue', cancelled: 'st-pending' };

  async function loadMoneyTransfers() {
    const box = document.getElementById('mtReqBox');
    if (!box) return;
    try {
      const r = await API.get('/api/admin/money-transfers');
      const c = r.counts || {};
      const canWrite = ME.role !== 'staff';
      const pending = r.items.filter(x => x.status === 'pending');
      const incoming = pending.filter(x => x.can_decide);
      const outgoing = pending.filter(x => !x.can_decide);
      const done = r.items.filter(x => x.status !== 'pending').slice(0, 12);

      const widget = `
        <div class="stat-grid mt-widget">
          <div class="stat"><div class="label">Today's transfers</div><div class="value">${num(c.today || 0)}</div></div>
          <div class="stat amber"><div class="label">Pending</div><div class="value">${num(c.pending || 0)}</div></div>
          <div class="stat green"><div class="label">Incoming (approved)</div><div class="value">Rs ${num(c.incoming_amount || 0)}</div></div>
          <div class="stat red"><div class="label">Outgoing (approved)</div><div class="value">Rs ${num(c.outgoing_amount || 0)}</div></div>
        </div>`;

      const card = (x, actions) => `
        <div class="tr-req ${x.status}">
          <div class="tr-req-main">
            <div class="tr-req-top">
              <span class="tr-roll">${esc(x.transfer_no)}</span>
              <b>${esc(x.student_name)}</b>
              <span class="tr-roll">${esc(x.source_roll)}</span>
              <span class="tr-arrow">${esc(x.source_campus)} → <b>${esc(x.dest_campus)}</b></span>
              <span class="pill ${MT_CLS[x.status] || 'st-pending'}">${x.status.charAt(0).toUpperCase() + x.status.slice(1)}</span>
            </div>
            <div class="tr-req-sub">
              <b style="color:var(--brand)">Rs ${num(x.amount)}</b> · ${esc(x.course || '—')}
              · by ${esc(x.requested_by)} ${x.requested_at ? '· ' + fmtDate(x.requested_at) : ''}
              ${x.remarks ? '· ' + esc(x.remarks) : ''}
              ${x.reject_reason ? '· <span style="color:var(--bad)">Rejected: ' + esc(x.reject_reason) + '</span>' : ''}
            </div>
          </div>
          ${actions}
        </div>`;

      let html = widget;
      if (incoming.length) {
        html += `<div class="card tr-incoming"><div class="card-pad">
          <div class="card-title"><h2>Pending money transfers — your approval needed
            <span class="count-chip">${incoming.length}</span></h2></div>
          ${incoming.map(x => card(x, `
            <div class="tr-actions">
              <button class="btn btn-ok btn-sm" onclick="mtApprove(${x.id},'${esc(x.source_roll)}','${esc(x.student_name)}',${x.amount})">Approve</button>
              <button class="btn btn-bad btn-sm" onclick="mtReject(${x.id},'${esc(x.student_name)}')">Reject</button>
            </div>`)).join('')}
        </div></div><div style="height:14px"></div>`;
      }
      if (outgoing.length) {
        html += `<div class="card"><div class="card-pad">
          <div class="card-title"><h2>Awaiting the other campus's approval
            <span class="count-chip amber">${outgoing.length}</span></h2></div>
          ${outgoing.map(x => card(x, canWrite
            ? `<div class="tr-actions"><button class="btn btn-outline btn-sm" onclick="mtCancel(${x.id})">Cancel</button></div>`
            : '<span class="tr-wait">Waiting…</span>')).join('')}
        </div></div><div style="height:14px"></div>`;
      }
      if (done.length) {
        html += `<details class="card tr-history"><summary>Recent transfers (${done.length})</summary>
          <div class="card-pad" style="padding-top:0">
          ${done.map(x => card(x, '')).join('')}</div></details>`;
      }
      box.innerHTML = html;
    } catch (e) { box.innerHTML = ''; }
  }

  window.mtApprove = function (id, sourceRoll, name, amount) {
    modal('Approve money transfer — ' + name, `
      <p style="margin-top:0;color:var(--ink-soft);font-size:13.5px">
        You are about to accept <b>Rs ${num(amount)}</b> for <b>${esc(name)}</b>.
        To confirm this is the right student, re-enter their roll number.</p>
      <label class="field"><span>Student roll number <b style="color:var(--bad)">*</b></span>
        <input id="mtVerifyRoll" placeholder="e.g. ${esc(sourceRoll)}"></label>
      <div style="text-align:right"><button class="btn btn-ok" onclick="doMtApprove(${id})">Verify &amp; approve</button></div>`);
  };
  window.doMtApprove = async function (id) {
    const roll = (document.getElementById('mtVerifyRoll') || {}).value || '';
    try {
      const r = await API.post('/api/admin/money-transfers/' + id + '/approve', { dest_roll: roll.trim() });
      closeModal();
      toast('Transfer approved', `Rs ${num(r.amount)} received from ${r.source_campus}.`, 'ok');
      loadMoneyTransfers();
    } catch (e) { toast('Could not approve', e.message, 'err'); }
  };
  window.mtReject = function (id, name) {
    modal('Reject money transfer — ' + name, `
      <p style="margin-top:0;color:var(--ink-soft);font-size:13.5px">Give a reason. The requesting campus will see it.</p>
      <label class="field"><span>Reject reason <b style="color:var(--bad)">*</b></span>
        <select id="mtRejReason">
          <option value="">Select…</option>
          <option>Incorrect Roll Number</option>
          <option>Wrong Student</option>
          <option>Invalid Amount</option>
          <option>Duplicate Request</option>
          <option value="__other">Other…</option>
        </select></label>
      <label class="field" id="mtRejOtherWrap" style="display:none"><span>Details</span>
        <input id="mtRejOther" placeholder="Reason"></label>
      <div style="text-align:right"><button class="btn btn-bad" onclick="doMtReject(${id})">Reject transfer</button></div>`);
    setTimeout(() => {
      const sel = document.getElementById('mtRejReason');
      if (sel) sel.addEventListener('change', () => {
        document.getElementById('mtRejOtherWrap').style.display = sel.value === '__other' ? '' : 'none';
      });
    }, 50);
  };
  window.doMtReject = async function (id) {
    const sel = document.getElementById('mtRejReason');
    let reason = sel ? sel.value : '';
    if (reason === '__other') reason = (document.getElementById('mtRejOther') || {}).value || '';
    if (!reason) { toast('Pick a reason', '', 'err'); return; }
    try {
      await API.post('/api/admin/money-transfers/' + id + '/reject', { reason });
      closeModal();
      toast('Transfer rejected', '', 'err');
      loadMoneyTransfers();
    } catch (e) { toast('Could not reject', e.message, 'err'); }
  };
  window.mtCancel = async function (id) {
    if (!confirm('Cancel this pending transfer request?')) return;
    try {
      await API.post('/api/admin/money-transfers/' + id + '/cancel', {});
      toast('Cancelled', '', 'ok');
      loadMoneyTransfers();
    } catch (e) { toast('Could not cancel', e.message, 'err'); }
  };

  pages.transfers = async function () {
    content.innerHTML = `
      <div class="page-head">
        <div><h1>Transfer Students</h1>
        <p>Request a transfer to another campus. The destination campus must approve
           it before the student moves — nothing changes until then.</p></div>
      </div>
      <div id="trReqBox">${spinner()}</div>
      <div style="height:18px"></div>
      <h2 class="section">Start a new transfer</h2>
      <div class="card"><div class="card-pad">
        <div class="due-toolbar">
          <label class="field" style="margin:0;flex:1;min-width:220px"><span>Find student</span>
            <input id="trQ" placeholder="Roll number or name…"></label>
          <button class="btn btn-primary" id="trGo">Search</button>
        </div>
      </div></div>
      <div style="height:14px"></div>
      <div class="card" id="trBox"><div class="card-pad">${emptyState('Search for a student', 'Type a roll number or name to begin a transfer.')}</div></div>`;
    document.getElementById('trGo').addEventListener('click', loadTransferList);
    document.getElementById('trQ').addEventListener('keydown', e => { if (e.key === 'Enter') loadTransferList(); });
    loadTransferRequests();
  };

  async function loadTransferRequests() {
    const box = document.getElementById('trReqBox');
    if (!box) return;
    try {
      const r = await API.get('/api/admin/transfer-requests');
      const pending = r.items.filter(x => x.status === 'pending');
      const incoming = pending.filter(x => x.can_decide);
      const outgoing = pending.filter(x => !x.can_decide);
      const decided = r.items.filter(x => x.status !== 'pending').slice(0, 8);

      const reqCard = (x, actions) => `
        <div class="tr-req ${x.status}">
          <div class="tr-req-main">
            <div class="tr-req-top">
              <b>${esc(x.student_name)}</b>
              <span class="tr-roll">${esc(x.current_roll)}</span>
              <span class="tr-arrow">${esc(x.from_campus)} → <b>${esc(x.to_campus)}</b></span>
              <span class="pill ${x.status === 'pending' ? 'st-pending' : x.status === 'approved' ? 'st-paid' : 'st-overdue'}">${x.status === 'approved' ? 'Approved' + (x.new_roll ? ' · ' + esc(x.new_roll) : '') : x.status === 'rejected' ? 'Rejected' : 'Pending'}</span>
            </div>
            <div class="tr-req-sub">
              ${esc(x.course || '—')} · ${badge(x.payment_status)} · Remaining <b>Rs ${num(x.remaining_fee)}</b>
              · requested by ${esc(x.requested_by)} ${x.requested_at ? '· ' + fmtDate(x.requested_at) : ''}
              ${x.decided_by ? '· decided by ' + esc(x.decided_by) : ''}
            </div>
          </div>
          ${actions}
        </div>`;

      let html = '';
      if (incoming.length) {
        html += `<div class="card tr-incoming"><div class="card-pad">
          <div class="card-title"><h2>Pending transfer requests — your approval needed
            <span class="count-chip">${incoming.length}</span></h2></div>
          ${incoming.map(x => reqCard(x, `
            <div class="tr-actions">
              <button class="btn btn-ok btn-sm" onclick="decideTransfer(${x.id},'approve','${esc(x.student_name)}')">Approve</button>
              <button class="btn btn-bad btn-sm" onclick="decideTransfer(${x.id},'reject','${esc(x.student_name)}')">Reject</button>
            </div>`)).join('')}
        </div></div><div style="height:14px"></div>`;
      }
      if (outgoing.length) {
        html += `<div class="card"><div class="card-pad">
          <div class="card-title"><h2>Awaiting the other campus's approval
            <span class="count-chip amber">${outgoing.length}</span></h2></div>
          ${outgoing.map(x => reqCard(x, '<span class="tr-wait">Waiting…</span>')).join('')}
        </div></div><div style="height:14px"></div>`;
      }
      if (decided.length) {
        html += `<details class="card tr-history"><summary>Recent decisions (${decided.length})</summary>
          <div class="card-pad" style="padding-top:0">
          ${decided.map(x => reqCard(x, '')).join('')}</div></details>`;
      }
      if (!html) {
        html = `<div class="card"><div class="card-pad">${emptyState('No transfer requests', 'Pending and past transfer requests will appear here.')}</div></div>`;
      }
      box.innerHTML = html;
    } catch (e) { box.innerHTML = ''; }
  }

  window.decideTransfer = async function (reqId, action, name) {
    const verb = action === 'approve' ? 'Approve' : 'Reject';
    if (!confirm(verb + ' the transfer of ' + name + '?')) return;
    try {
      const r = await API.post('/api/admin/transfer-requests/' + reqId + '/decide', { action });
      toast(verb + 'd', r.message || '', 'ok');
      loadTransferRequests();
    } catch (e) { toast('Could not ' + action, e.message, 'err'); }
  };

  async function loadTransferList() {
    const box = document.getElementById('trBox');
    const q = document.getElementById('trQ').value.trim();
    if (!q) { toast('Enter a roll number or name', '', 'err'); return; }
    box.innerHTML = '<div class="card-pad">' + spinner() + '</div>';
    try {
      const r = await API.get('/api/admin/applications' + API.qs({ q, page_size: 25 }));
      if (!r.items.length) {
        box.innerHTML = '<div class="card-pad">' + emptyState('No student found', 'Try a different roll number or name.') + '</div>';
        return;
      }
      box.innerHTML = `
        <div class="table-wrap"><table class="data"><thead><tr>
          <th>Roll Number</th><th>Student</th><th>Course</th><th>Campus</th><th>Payment</th><th></th>
        </tr></thead><tbody>
        ${r.items.map(a => `<tr>
          <td class="td-main"><b>${esc(a.roll_number || '—')}</b></td>
          <td>${esc(a.full_name)}</td>
          <td>${esc(a.course_name || '—')}</td>
          <td>${esc(a.campus || '—')}</td>
          <td>${badge(a.payment_status)}</td>
          <td><button class="btn btn-primary btn-sm" onclick="transferModal(${a.id}, '${esc(a.full_name)}', '${esc(a.roll_number || '')}', '${esc(a.campus || '')}')">Transfer</button></td>
        </tr>`).join('')}
        </tbody></table></div>`;
    } catch (e) {
      box.innerHTML = '<div class="card-pad">' + emptyState('Could not load', e.message) + '</div>';
    }
  }

  window.transferModal = async function (id, name, roll, campus) {
    const all = ['Walton Road', 'Queen Road', 'Darogwala', 'Bhagbanpura'].filter(c => c !== campus);
    modal('Transfer ' + name, `
      <p style="margin-top:0;color:var(--ink-soft)">
        You are requesting a transfer for <b>${esc(name)}</b> (${esc(roll)}) from <b>${esc(campus)} Campus</b>.
        The student's historical record will remain fully available in <b>${esc(campus)} Campus</b>.
        Upon approval by the destination campus, the student will become active there with a new roll number.</p>
      <label class="field"><span>Transfer to <b style="color:var(--bad)">*</b></span>
        <select id="trTo" onchange="previewTransfer(${id})">
          <option value="">Select destination campus…</option>
          ${all.map(c => `<option>${esc(c)}</option>`).join('')}
        </select></label>
      <div id="trPreview" class="roll-hint"></div>
      <label class="field"><span>Reason (optional)</span>
        <textarea id="trReason" placeholder="e.g. Student relocated to new branch area"></textarea></label>
      <div style="text-align:right"><button class="btn btn-primary" onclick="doTransfer(${id})">Send transfer request</button></div>`);
  };

  window.previewTransfer = async function (id) {
    const to = document.getElementById('trTo').value;
    const box = document.getElementById('trPreview');
    if (!to) { box.textContent = ''; return; }
    try {
      const p = await API.get('/api/admin/transfer/preview' + API.qs({ app_id: id, to_campus: to }));
      box.innerHTML = `On approval by <b>${esc(p.to_campus)}</b>: New Roll Number: <b>${esc(p.new_roll)}</b>. <span style="color:var(--ok)">Source campus historical record remains preserved as <b>${esc(p.current_roll)}</b>.</span>`;
    } catch (e) { box.textContent = e.message; }
  };

  window.doTransfer = async function (id) {
    const to = document.getElementById('trTo').value;
    if (!to) { toast('Pick a destination campus', '', 'err'); return; }
    try {
      const r = await API.post('/api/admin/transfer', {
        application_id: id, to_campus: to,
        reason: document.getElementById('trReason').value.trim()
      });
      closeModal();
      toast('Transfer request sent', r.message ||
            `Sent to ${r.to_campus} for approval.`, 'ok');
      loadTransferRequests();
    } catch (e) { toast('Could not send request', e.message, 'err'); }
  };

  /* ══ Referrals ════════════════════════════════════════════════════ */
  /* ══ Referral Applications — accept / reject ══════════════════════ */
  const REF_PILL = { pending: 'st-pending', accepted: 'st-paid', rejected: 'st-overdue' };
  const REF_LABEL = { pending: 'Pending', accepted: 'Accepted', rejected: 'Rejected' };
  function refPill(st) {
    const k = st || 'pending';
    return `<span class="pill ${REF_PILL[k] || 'st-pending'}">${esc(REF_LABEL[k] || k)}</span>`;
  }

  const refAppState = { status: '', q: '' };

  pages['referral-applications'] = async function () {
    content.innerHTML = spinner();
    try {
      const r = await API.get('/api/admin/referral-applications' + API.qs(refAppState));
      const scope = ME.campus ? ME.campus + ' campus' : 'all campuses';
      const tab = (v, label, n) => `<button class="ref-tab ${refAppState.status === v ? 'on' : ''}"
        onclick="refAppFilter('${v}')">${label}${n != null ? ` <span class="count-chip ${v === 'pending' ? '' : 'quiet'}">${n}</span>` : ''}</button>`;

      content.innerHTML = `
        <div class="page-head">
          <div><h1>Referral Applications</h1>
          <p>Applications sent to <b>${esc(scope)}</b> from the Referral Portal.
             Accept or reject them here — they never appear in the normal Applications list.</p></div>
        </div>

        <div class="stat-grid">
          <div class="stat amber"><div class="label">Awaiting your decision</div><div class="value">${num(r.counts.pending)}</div></div>
          <div class="stat green"><div class="label">Accepted</div><div class="value">${num(r.counts.accepted)}</div></div>
          <div class="stat red"><div class="label">Rejected</div><div class="value">${num(r.counts.rejected)}</div></div>
        </div>

        <div class="card"><div class="card-pad" style="padding-bottom:12px">
          <div class="ref-tabs">
            ${tab('', 'All', r.total)}
            ${tab('pending', 'Pending', r.counts.pending)}
            ${tab('accepted', 'Accepted', r.counts.accepted)}
            ${tab('rejected', 'Rejected', r.counts.rejected)}
            <input id="refQ" class="ref-search" placeholder="Search name, roll or phone…" value="${esc(refAppState.q)}">
          </div>
        </div>

        ${r.items.length ? `<div class="table-wrap"><table class="data"><thead><tr>
          <th>Referral Roll</th><th>Student Name</th><th>Phone</th><th>Course</th>
          <th class="num">Total Fee</th><th class="num">Remaining</th>
          <th>Payment</th><th>Status</th><th>Submitted</th>${canWrite ? '<th></th>' : ''}
        </tr></thead><tbody>
        ${r.items.map(x => `<tr onclick="location.hash='#/applications/${x.id}'">
          <td class="td-main"><span class="roll">${esc(x.roll_number)}</span></td>
          <td><b>${esc(x.student_name)}</b>${x.remarks ? `<small class="sch-note warn">${esc(x.remarks)}</small>` : ''}</td>
          <td class="mono">${esc(x.phone || '—')}</td>
          <td>${esc(x.course || '—')}</td>
          <td class="num mono">Rs ${num(x.total_fee)}</td>
          <td class="num mono ${x.remaining_fee > 0 ? 'pend-pos' : 'pend-zero'}">Rs ${num(x.remaining_fee)}</td>
          <td>${badge(x.payment_status)}</td>
          <td>${refPill(x.referral_status)}${x.decided_by ? `<small class="sch-note">by ${esc(x.decided_by)}</small>` : ''}</td>
          <td class="mono">${fmtDateTime(x.submitted_at)}</td>
          ${canWrite ? `<td onclick="event.stopPropagation()">${x.referral_status === 'pending'
            ? `<div class="tr-actions">
                 <button class="btn btn-ok btn-sm" onclick="decideReferralApp(${x.id},'accept','${esc(x.student_name)}')">Accept</button>
                 <button class="btn btn-bad btn-sm" onclick="decideReferralApp(${x.id},'reject','${esc(x.student_name)}')">Reject</button>
               </div>` : '—'}</td>` : ''}
        </tr>`).join('')}
        </tbody></table></div>` : '<div class="card-pad">' + emptyState(
          refAppState.status ? 'No ' + refAppState.status + ' referrals' : 'No referral applications',
          'Applications submitted from the Referral Portal for your campus appear here.') + '</div>'}
        </div>`;

      const q = document.getElementById('refQ');
      if (q) q.addEventListener('keydown', e => {
        if (e.key === 'Enter') { refAppState.q = q.value.trim(); pages['referral-applications'](); }
      });
    } catch (e) { content.innerHTML = emptyState('Could not load referral applications', e.message); }
  };

  window.refAppFilter = function (status) {
    refAppState.status = status;
    pages['referral-applications']();
  };

  window.decideReferralApp = function (id, action, name) {
    const isAccept = action === 'accept';
    modal((isAccept ? 'Accept' : 'Reject') + ' referral — ' + name, `
      <p style="margin-top:0;color:var(--ink-soft);font-size:13.5px">
        ${isAccept
          ? 'This student will be enrolled at your campus and marked as an accepted referral.'
          : 'This referral will be marked rejected. The student is not enrolled at your campus.'}</p>
      <label class="field"><span>Remarks (optional)</span>
        <textarea id="raRemarks" placeholder="${isAccept ? 'e.g. Seat confirmed for evening batch' : 'e.g. Seats full for this course'}"></textarea></label>
      <div style="text-align:right">
        <button class="btn ${isAccept ? 'btn-ok' : 'btn-bad'}" onclick="doDecideReferralApp(${id},'${action}')">
          ${isAccept ? 'Accept referral' : 'Reject referral'}</button>
      </div>`);
  };

  window.doDecideReferralApp = async function (id, action) {
    try {
      const r = await API.post('/api/admin/referral-applications/' + id + '/decide', {
        action, remarks: (document.getElementById('raRemarks').value || '').trim()
      });
      closeModal();
      toast(action === 'accept' ? 'Referral accepted' : 'Referral rejected', r.message || '', 'ok');
      pages['referral-applications']();
    } catch (e) { toast('Could not ' + action, e.message, 'err'); }
  };

  pages.referrals = async function () {
    content.innerHTML = spinner();
    try {
      const r = await API.get('/api/admin/referrals');
      const scope = ME.campus ? ME.campus + ' campus' : 'all campuses';
      content.innerHTML = `
        <div class="page-head">
          <div><h1>Referrals</h1>
          <p>Referral students at <b>${esc(scope)}</b> — brought in through the Referral Portal.</p></div>
        </div>
        <div class="stat-grid">
          <div class="stat"><div class="label">Total referrals</div><div class="value">${num(r.total)}</div></div>
          <div class="stat green"><div class="label">Accepted / Enrolled</div><div class="value">${num(r.enrolled)}</div></div>
          <div class="stat amber"><div class="label">Awaiting decision</div><div class="value">${num(r.pending || 0)}</div></div>
          <div class="stat red"><div class="label">Rejected</div><div class="value">${num(r.rejected || 0)}</div></div>
          <div class="stat blue"><div class="label">Fee collected</div><div class="value">Rs ${num(r.collected || 0)}</div></div>
        </div>
        <div class="card">
          ${r.items.length ? `<div class="table-wrap"><table class="data"><thead><tr>
            <th>Student Name</th><th>Referral Roll</th><th>Campus</th><th>Course</th><th>Phone</th>
            <th class="num">Total Fee</th><th class="num">Paid</th><th class="num">Remaining</th>
            <th>Status</th><th>Date</th>
          </tr></thead><tbody>
          ${r.items.map(x => `<tr onclick="location.hash='#/applications/${x.id}'">
            <td class="td-main"><b>${esc(x.student_name)}</b></td>
            <td><span class="roll">${esc(x.roll_number)}</span></td>
            <td>${esc(x.campus)}</td>
            <td>${esc(x.course || '—')}</td>
            <td class="mono">${esc(x.phone || '—')}</td>
            <td class="num mono">Rs ${num(x.total_fee)}</td>
            <td class="num mono">Rs ${num(x.paid)}</td>
            <td class="num mono ${x.remaining_fee > 0 ? 'pend-pos' : 'pend-zero'}">Rs ${num(x.remaining_fee)}</td>
            <td>${refPill(x.referral_status)}</td>
            <td class="mono">${fmtDateTime(x.enrollment_date)}</td>
          </tr>`).join('')}
          </tbody></table></div>` : '<div class="card-pad">' + emptyState('No referrals yet', 'Referral partners submit students from the Referral Portal.') + '</div>'}
        </div>`;
    } catch (e) { content.innerHTML = emptyState('Could not load referrals', e.message); }
  };

  window.enrollReferral = async function (id) {
    try {
      await API.post('/api/admin/referrals/' + id + '/enroll', {});
      toast('Referral enrolled', '', 'ok');
      pages.referrals();
    } catch (e) { toast('Could not enroll', e.message, 'err'); }
  };

  /* ══ Installment Due Students ═════════════════════════════════════ */
  const dueState = { date: '', q: '', course: '', status: '' };

  pages['installments-due'] = async function () {
    content.innerHTML = spinner();
    const fo = await formOptions().catch(() => ({ courses: [] }));
    content.innerHTML = `
      <div class="page-head">
        <div><h1>Installment Due Students</h1>
        <p>Pick a date to see every student whose installment falls due that day.</p></div>
      </div>

      <div class="card"><div class="card-pad">
        <div class="due-toolbar">
          <label class="field" style="margin:0"><span>Select Date</span>
            <input type="date" id="dueDate" value="${esc(dueState.date)}"></label>
          <label class="field" style="margin:0;flex:1;min-width:180px"><span>Search</span>
            <input id="dueQ" placeholder="Roll number or student name…" value="${esc(dueState.q)}"></label>
          <label class="field" style="margin:0"><span>Course</span>
            <select id="dueCourse"><option value="">All courses</option>
              ${(fo.courses || []).map(c => {
                const n = typeof c === 'string' ? c : (c.name || '');
                return `<option ${dueState.course === n ? 'selected' : ''}>${esc(n)}</option>`;
              }).join('')}
            </select></label>
          <label class="field" style="margin:0"><span>Status</span>
            <select id="dueStatus">
              <option value="">All statuses</option>
              <option value="fully_paid" ${dueState.status === 'fully_paid' ? 'selected' : ''}>Paid</option>
              <option value="partially_paid" ${dueState.status === 'partially_paid' ? 'selected' : ''}>Half Paid</option>
              <option value="unpaid" ${dueState.status === 'unpaid' ? 'selected' : ''}>Pending</option>
            </select></label>
          <button class="btn btn-primary" id="dueSearch">Search</button>
          <button class="btn btn-outline" id="dueReset">Reset</button>
        </div>
      </div></div>

      <div style="height:14px"></div>
      <div class="card" id="dueBox"><div class="card-pad">${spinner()}</div></div>`;

    document.getElementById('dueSearch').addEventListener('click', () => {
      dueState.date = document.getElementById('dueDate').value;
      dueState.q = document.getElementById('dueQ').value.trim();
      dueState.course = document.getElementById('dueCourse').value;
      dueState.status = document.getElementById('dueStatus').value;
      loadDue();
    });
    document.getElementById('dueReset').addEventListener('click', () => {
      dueState.date = ''; dueState.q = ''; dueState.course = ''; dueState.status = '';
      document.getElementById('dueDate').value = '';
      document.getElementById('dueQ').value = '';
      document.getElementById('dueCourse').value = '';
      document.getElementById('dueStatus').value = '';
      loadDue();
    });
    document.getElementById('dueQ').addEventListener('keydown', e => {
      if (e.key === 'Enter') document.getElementById('dueSearch').click();
    });
    loadDue();
  };

  const PAY_LABEL = { fully_paid: 'Paid', partially_paid: 'Half Paid', unpaid: 'Pending' };
  const PAY_CLASS = { fully_paid: 'paid', partially_paid: 'partial', unpaid: 'pending' };

  async function loadDue() {
    const box = document.getElementById('dueBox');
    if (!box) return;
    box.innerHTML = '<div class="card-pad">' + spinner() + '</div>';
    try {
      const r = await API.get('/api/admin/installments-due' + API.qs({
        date: dueState.date, q: dueState.q,
        course: dueState.course, status: dueState.status
      }));
      if (!r.items.length) {
        box.innerHTML = '<div class="card-pad">' + emptyState(
          'No students due',
          dueState.date ? 'No installments fall due on ' + esc(dueState.date) + '.'
                        : 'No pending installments match these filters.') + '</div>';
        return;
      }
      box.innerHTML = `
        <div class="card-title" style="padding:16px 18px 0">
          <h2>${r.total} student${r.total === 1 ? '' : 's'}${dueState.date ? ' due on ' + esc(dueState.date) : ' with pending installments'}</h2>
        </div>
        <div class="table-wrap"><table class="data"><thead><tr>
          <th>Roll Number</th><th>Student Name</th><th>Phone</th><th>Guardian Phone</th>
          <th>Course</th><th>Campus</th>
          <th class="num">Due Amount</th><th>Due Date</th>
          <th class="num">Remaining Fee</th>
          <th>Current Installment</th>
          <th>Payment Status</th><th>Student Status</th><th>Receipt (Latest)</th>
        </tr></thead><tbody>
        ${r.items.map(s => `<tr onclick="location.hash='#/applications/${s.id}'">
          <td class="td-main"><b>${esc(s.roll_number || '—')}</b></td>
          <td>${esc(s.student_name)}</td>
          <td class="mono">${s.phone ? `<a href="tel:${esc(s.phone)}" onclick="event.stopPropagation()">${esc(s.phone)}</a>` : '—'}</td>
          <td class="mono">${s.guardian_phone ? `<a href="tel:${esc(s.guardian_phone)}" onclick="event.stopPropagation()">${esc(s.guardian_phone)}</a>` : '—'}</td>
          <td>${esc(s.course)}</td>
          <td>${esc(s.campus || '—')}</td>
          <td class="num mono"><b>Rs ${num(s.installment_amount)}</b></td>
          <td class="mono">${esc(s.due_date || '—')}</td>
          <td class="num mono ${s.pending_fee > 0 ? 'pend-pos' : 'pend-zero'}">Rs ${num(s.pending_fee)}</td>
          <td>${esc(s.current_installment)}</td>
          <td><span class="pay-pill ${PAY_CLASS[s.payment_status] || 'pending'}">${esc(PAY_LABEL[s.payment_status] || 'Pending')}</span></td>
          <td>${badge(s.student_status)}</td>
          <td class="mono">${esc(s.latest_receipt || '—')}</td>
        </tr>`).join('')}
        </tbody></table></div>`;
    } catch (e) {
      box.innerHTML = '<div class="card-pad">' + emptyState('Could not load', e.message) + '</div>';
    }
  }

  pages.expenses = async function () {
    content.innerHTML = spinner('Loading expenses…');
    const canWrite = ME.role !== 'staff';
    try {
      const dash = await API.get('/api/admin/expenses-dashboard' + API.qs({
        date_from: expState.date_from || '', date_to: expState.date_to || ''
      }));
      content.innerHTML = `
        <div class="page-head">
          <div><h1>Expense Management</h1><p>Record, search and report institutional spending.</p></div>
          <div class="spacer"></div>
          <button class="btn btn-outline" onclick="exportExpenses('xlsx')">Export Excel</button>
          <button class="btn btn-outline" onclick="exportExpenses('csv')">CSV</button>
          <button class="btn btn-outline" onclick="exportExpenses('pdf')">PDF</button>
          ${canWrite ? `<button class="btn btn-primary" onclick="newExpense()">+ Record Expense</button>` : ''}
        </div>

        <div class="stat-grid">
          <div class="stat red"><div class="label">Total expenses</div><div class="value">Rs ${num(dash.total_expenses)}</div></div>
          <div class="stat amber"><div class="label">This month</div><div class="value">Rs ${num(dash.monthly_expenses)}</div></div>
          <div class="stat blue"><div class="label">Records</div><div class="value">${num(dash.expense_count || 0)}</div></div>
        </div>

        <div class="grid-2">
          <div class="card"><div class="card-title"><h2>Spending by category</h2></div><div class="chart-box"><canvas id="expCat"></canvas></div></div>
          <div class="card"><div class="card-title"><h2>Monthly trend</h2></div><div class="chart-box"><canvas id="expTrend"></canvas></div></div>
        </div>

        <div style="height:16px"></div>
        <div class="page-head" style="margin-bottom:12px"><div><h2 class="section" style="margin:0">Expenses</h2></div></div>
        <div class="filters">
          <input class="grow" id="exQ" placeholder="Search title, vendor…" value="${esc(expState.q || '')}">
          <input id="exCat" placeholder="Category" value="${esc(expState.category || '')}">
          <select id="exMethod">
            <option value="">All methods</option>
            <option value="cash" ${expState.payment_method === 'cash' ? 'selected' : ''}>Cash</option>
            <option value="bank" ${expState.payment_method === 'bank' ? 'selected' : ''}>Bank Transfer</option>
            <option value="jazzcash" ${expState.payment_method === 'jazzcash' ? 'selected' : ''}>JazzCash / EasyPaisa</option>
            <option value="other" ${expState.payment_method === 'other' ? 'selected' : ''}>Other</option>
          </select>
          <input type="date" id="exFrom" value="${esc(expState.date_from || '')}">
          <input type="date" id="exTo" value="${esc(expState.date_to || '')}">
          <button class="btn btn-primary btn-sm" id="exGo">Apply</button>
          <button class="btn btn-outline btn-sm" id="exClear">Clear</button>
        </div>
        <div class="card" id="expBox">${spinner()}</div>`;

      const c = chartColors();
      makeChart('expCat', { type: 'doughnut',
        data: { labels: dash.by_category.map(x => x.category), datasets: [{ data: dash.by_category.map(x => x.amount), backgroundColor: c.palette, borderWidth: 0 }] },
        options: { maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { boxWidth: 11 } } }, cutout: '60%' } });
      makeChart('expTrend', { type: 'bar',
        data: { labels: (dash.trend || []).map(t => t.month), datasets: [{ data: (dash.trend || []).map(t => t.amount), backgroundColor: c.brand, borderRadius: 4 }] },
        options: { plugins: { legend: { display: false } }, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } } });

      document.getElementById('exGo').addEventListener('click', () => {
        Object.assign(expState, {
          q: document.getElementById('exQ').value.trim(),
          category: document.getElementById('exCat').value.trim(),
          payment_method: document.getElementById('exMethod').value,
          date_from: document.getElementById('exFrom').value,
          date_to: document.getElementById('exTo').value, page: 1
        });
        pages.expenses();
      });
      document.getElementById('exClear').addEventListener('click', () => {
        Object.assign(expState, { q: '', category: '', payment_method: '', date_from: '', date_to: '', page: 1 });
        pages.expenses();
      });
      document.getElementById('exQ').addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('exGo').click(); });
      loadExpenses();
    } catch (e) { content.innerHTML = emptyState('Could not load expenses', e.message); }
  };
  window.expensesPage = function (p) { expState.page = p; loadExpenses(); };



  async function loadExpenses() {
    const box = document.getElementById('expBox');
    if (!box) return;
    box.innerHTML = spinner();
    const canWrite = ME.role !== 'staff';
    try {
      const r = await API.get('/api/admin/expenses' + API.qs(expState));
      box.innerHTML = `<div class="table-wrap"><table class="data"><thead><tr>
        <th>Title</th><th>Category</th><th>Vendor</th><th>Date</th><th>Amount</th>${canWrite ? '<th></th>' : ''}
      </tr></thead><tbody>
      ${r.items.map(e => `<tr style="cursor:default">
        <td class="td-main"><b>${esc(e.title)}</b><small>${esc(e.description || '')}</small></td>
        <td>${e.category ? badge(e.category) : '—'}</td>
        <td>${esc(e.vendor || '—')}</td>
        <td class="mono">${esc(e.purchase_date || '—')}</td>
        <td class="mono">Rs ${num(e.amount)}</td>
        ${canWrite ? `<td><button class="btn btn-outline btn-sm" onclick='editExpense(${JSON.stringify(e)})'>Edit</button> <button class="btn btn-bad btn-sm" onclick="delExpense(${e.id})">✕</button></td>` : ''}
      </tr>`).join('') || '<tr><td colspan="6">' + emptyState('No expenses recorded', '') + '</td></tr>'}
      </tbody></table></div>${pager(r, 'expensesPage')}`;
    } catch (e) { box.innerHTML = emptyState('Could not load expenses', e.message); }
  }

  function expenseForm(e) {
    e = e || {};
    const today = new Date().toISOString().slice(0, 10);
    return `<div class="grid-2">
        <label class="field"><span>Title <b style="color:var(--bad)">*</b></span><input id="exTitle" value="${esc(e.title || '')}"></label>
        <label class="field"><span>Category</span><input id="exCategory" value="${esc(e.category || '')}" placeholder="e.g. Equipment, Utilities"></label>
        <label class="field"><span>Amount (Rs) <b style="color:var(--bad)">*</b></span><input id="exAmount" type="number" min="1" value="${esc(e.amount || '')}"></label>
        <label class="field"><span>Purchase date</span><input id="exDate" type="date" value="${esc(e.purchase_date || today)}"></label>
        <label class="field"><span>Vendor / Supplier</span><input id="exVendor" value="${esc(e.vendor || '')}"></label>
        <label class="field"><span>Payment Method</span>
          <select id="exPayMethod">
            ${[['cash','Cash'],['bank','Bank Transfer'],['jazzcash','JazzCash / EasyPaisa'],['other','Other']]
              .map(([v,l]) => `<option value="${v}"${(e.payment_method || 'cash') === v ? ' selected' : ''}>${l}</option>`).join('')}
          </select></label>
      </div>
      <label class="field"><span>Description</span><textarea id="exDesc">${esc(e.description || '')}</textarea></label>
      <label class="field"><span>Remarks</span><input id="exRemarks" value="${esc(e.remarks || '')}"></label>`;
  }
  function expenseBody() {
    return {
      title: document.getElementById('exTitle').value.trim(),
      category: document.getElementById('exCategory').value.trim(),
      amount: parseFloat(document.getElementById('exAmount').value),
      purchase_date: document.getElementById('exDate').value || null,
      vendor: document.getElementById('exVendor').value.trim(),
      payment_method: document.getElementById('exPayMethod').value,
      description: document.getElementById('exDesc').value.trim(),
      remarks: document.getElementById('exRemarks').value.trim()
    };
  }
  window.newExpense = function () {
    modal('Record Expense', expenseForm() + `<div style="text-align:right"><button class="btn btn-primary" onclick="saveExpense()">Save</button></div>`);
  };
  window.editExpense = function (e) {
    modal('Edit Expense', expenseForm(e) + `<div style="text-align:right"><button class="btn btn-primary" onclick="saveExpense(${e.id})">Save</button></div>`);
  };
  window.saveExpense = async function (id) {
    const body = expenseBody();
    if (!body.title || !body.amount || body.amount <= 0) { toast('Title and amount are required', '', 'err'); return; }
    try {
      if (id) await API.patch('/api/admin/expenses/' + id, body);
      else await API.post('/api/admin/expenses', body);
      closeModal(); toast('Expense saved', '', 'ok'); pages.expenses();
    } catch (e) { toast('Failed', e.message, 'err'); }
  };
  window.delExpense = async function (id) {
    if (!confirm('Delete this expense?')) return;
    try { await API.del('/api/admin/expenses/' + id); toast('Deleted', '', 'ok'); pages.expenses(); }
    catch (e) { toast('Failed', e.message, 'err'); }
  };
  /* ══ Analytics ═════════════════════════════════════════════════════ */
  pages.analytics = async function () {
    content.innerHTML = spinner('Crunching the numbers…');
    try {
      const days = 30;
      const [ov, fee, apps, chats, sources] = await Promise.all([
        API.get('/api/admin/analytics/overview'),
        API.get('/api/admin/analytics/fees').catch(() => null),
        API.get('/api/admin/analytics/applications?days=' + days),
        API.get('/api/admin/analytics/chats?days=' + days),
        API.get('/api/admin/analytics/lead-sources').catch(() => null)
      ]);
      content.innerHTML = `
        <div class="page-head">
          <div><h1>Analytics</h1><p>Admissions, fees and chatbot performance${ME.campus ? ' — ' + esc(ME.campus) : ''}.</p></div>
          <div class="spacer"></div>
          <button class="btn btn-outline" onclick="exportData('analytics')">Export summary</button>
        </div>

        <h2 class="section">Admissions overview</h2>
        <div class="stat-grid">
          <div class="stat"><div class="label">Total applications</div><div class="value">${num(ov.total_applications)}</div><div class="sub">${num(ov.applications_this_month)} this month</div></div>
          <div class="stat amber"><div class="label">Pending</div><div class="value">${num(ov.pending)}</div><div class="sub">${num(ov.on_hold)} on hold</div></div>
          <div class="stat green"><div class="label">Approved</div><div class="value">${num(ov.approved)}</div></div>
          <div class="stat red"><div class="label">Drop Out</div><div class="value">${num(ov.dropped_out || 0)}</div></div>
        </div>
        <div class="grid-2">
          <div class="card"><div class="card-title"><h2>Application status</h2></div><div class="chart-box"><canvas id="chStatus"></canvas></div></div>
          <div class="card"><div class="card-title"><h2>Application growth — ${days} days</h2></div><div class="chart-box"><canvas id="chGrowth"></canvas></div></div>
        </div>
        <div style="height:16px"></div>
        <div class="grid-2">
          <div class="card"><div class="card-title"><h2>Applications by programme</h2></div><div class="chart-box"><canvas id="chDept"></canvas></div></div>
          <div class="card"><div class="card-title"><h2>Top courses</h2></div><div class="chart-box"><canvas id="chCourse"></canvas></div></div>
        </div>

        ${fee ? `<h2 class="section">Fees &amp; eligibility</h2>
        <div class="stat-grid">
          <div class="stat green"><div class="label">Collected</div><div class="value">Rs ${num(fee.collected)}</div><div class="sub">${esc(fee.collection_rate)}% of Rs ${num(fee.total_fee)}</div></div>
          <div class="stat red"><div class="label">Remaining Fee</div><div class="value">Rs ${num(fee.outstanding)}</div></div>
          <div class="stat blue"><div class="label">Eligible for classes</div><div class="value">${num(fee.eligible)}</div><div class="sub">paid ≥ 75%</div></div>
          <div class="stat amber"><div class="label">Overdue payments</div><div class="value">${num(fee.installments_overdue)}</div></div>
        </div>
        <div class="grid-2">
          <div class="card"><div class="card-title"><h2>Payment status</h2></div><div class="chart-box"><canvas id="chPay"></canvas></div></div>
          <div class="card"><div class="card-title"><h2>Fee collection</h2></div><div class="chart-box"><canvas id="chCollect"></canvas></div></div>
        </div>` : ''}

        ${sources ? `<h2 class="section">Marketing</h2>
        <div class="grid-2">
          <div class="card"><div class="card-title"><h2>Where students heard about us</h2></div><div class="chart-box"><canvas id="chSource"></canvas></div></div>
          <div class="card"><div class="card-title"><h2>Lead source breakdown</h2></div>
            <ul class="qlist">${sources.by_source.map(s => `<li><span>${esc(s.source)}</span><span class="q-count">${s.count} · ${esc(s.percent)}%</span></li>`).join('')}</ul>
          </div>
        </div>` : ''}

        <h2 class="section">Chatbot performance — ${days} days</h2>
        <div class="stat-grid">
          <div class="stat blue"><div class="label">Avg AI response</div><div class="value">${(chats.avg_response_time_ms / 1000).toFixed(1)}s</div><div class="sub">per assistant reply</div></div>
          <div class="stat"><div class="label">Avg conversation</div><div class="value">${esc(chats.avg_conversation_length)}</div><div class="sub">messages per session</div></div>
          <div class="stat green"><div class="label">Active users</div><div class="value">${num(chats.active_users_7d)}</div><div class="sub">last 7 days</div></div>
          <div class="stat gold"><div class="label">Returning users</div><div class="value">${num(chats.returning_users)}</div><div class="sub">visited more than once</div></div>
        </div>

        <div class="grid-2">
          <div class="card"><div class="card-title"><h2>Daily chats</h2></div><div class="chart-box"><canvas id="chDaily"></canvas></div></div>
          <div class="card"><div class="card-title"><h2>Weekly chats — 12 weeks</h2></div><div class="chart-box"><canvas id="chWeekly"></canvas></div></div>
        </div>
        <div style="height:16px"></div>
        <div class="grid-2">
          <div class="card"><div class="card-title"><h2>Monthly chats — 12 months</h2></div><div class="chart-box"><canvas id="chMonthly"></canvas></div></div>
          <div class="card"><div class="card-title"><h2>Peak hours</h2></div><div class="chart-box"><canvas id="chPeak"></canvas></div></div>
        </div>
        <div style="height:16px"></div>
        <div class="grid-2">
          <div class="card">
            <div class="card-title"><h2>Top questions</h2></div>
            <ul class="qlist">${chats.top_questions.map(q => `<li><span>${esc(q.question)}</span><span class="q-count">${q.count}×</span></li>`).join('') || '<li>No questions recorded yet.</li>'}</ul>
          </div>
          <div class="card"><div class="card-title"><h2>Frequently asked topics</h2></div><div class="chart-box"><canvas id="chTopics"></canvas></div></div>
        </div>
        <div style="height:16px"></div>
        <div class="card">
          <div class="card-title"><h2>Unanswered questions</h2><span class="badge b-on_hold">needs prompt improvement</span></div>
          <ul class="qlist">${(chats.unanswered_questions || []).map(q => `<li><span>${esc(q.question)}</span><span class="q-count">${q.count}×</span></li>`).join('') || '<li>None detected — the bot answered everything it was asked. 🎉</li>'}</ul>
        </div>`;

      const c = chartColors();

      // ── Dashboard-driven charts ──
      makeChart('chStatus', { type: 'doughnut',
        data: { labels: ['Pending', 'Approved', 'Drop Out', 'On hold'],
          datasets: [{ data: [ov.pending, ov.approved, ov.dropped_out || 0, ov.on_hold],
            backgroundColor: ['#d99a2b', '#1f8a4c', '#c23b2e', '#8a8f8c'], borderWidth: 0 }] },
        options: { maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { boxWidth: 11 } } }, cutout: '58%' } });
      makeChart('chGrowth', { type: 'line',
        data: { labels: apps.growth.map(d => d.date.slice(5)), datasets: [{ data: apps.growth.map(d => d.count), borderColor: c.brand, backgroundColor: c.fill, fill: true, tension: .35, pointRadius: 0, borderWidth: 2.5 }] },
        options: { plugins: { legend: { display: false } }, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
      makeChart('chDept', { type: 'pie',
        data: { labels: apps.by_department.map(d => d.department), datasets: [{ data: apps.by_department.map(d => d.count), backgroundColor: c.palette, borderWidth: 0 }] },
        options: { maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { boxWidth: 11 } } } } });
      makeChart('chCourse', { type: 'bar',
        data: { labels: apps.by_course.map(d => d.course), datasets: [{ data: apps.by_course.map(d => d.count), backgroundColor: c.brand, borderRadius: 4 }] },
        options: { indexAxis: 'y', plugins: { legend: { display: false } }, maintainAspectRatio: false, scales: { x: { beginAtZero: true, ticks: { precision: 0 } } } } });

      if (fee) {
        makeChart('chPay', { type: 'doughnut',
          data: { labels: ['Fully paid', 'Half Paid', 'Unpaid'],
            datasets: [{ data: [fee.fully_paid, fee.partially_paid, fee.unpaid],
              backgroundColor: ['#1f8a4c', '#d99a2b', '#c23b2e'], borderWidth: 0 }] },
          options: { maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { boxWidth: 11 } } }, cutout: '58%' } });
        makeChart('chCollect', { type: 'bar',
          data: { labels: ['Collected', 'Remaining Fee'],
            datasets: [{ data: [fee.collected, fee.outstanding], backgroundColor: ['#1f8a4c', '#c23b2e'], borderRadius: 6 }] },
          options: { plugins: { legend: { display: false } }, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } } });
      }
      if (sources) makeChart('chSource', { type: 'doughnut',
        data: { labels: sources.by_source.map(s => s.source), datasets: [{ data: sources.by_source.map(s => s.count), backgroundColor: c.palette, borderWidth: 0 }] },
        options: { maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { boxWidth: 11 } } }, cutout: '55%' } });

      // ── Chatbot charts ──
      makeChart('chDaily', { type: 'bar',
        data: { labels: chats.daily.map(d => d.date.slice(5)), datasets: [{ data: chats.daily.map(d => d.count), backgroundColor: c.brand, borderRadius: 4 }] },
        options: { plugins: { legend: { display: false } }, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
      makeChart('chWeekly', { type: 'bar',
        data: { labels: chats.weekly.map(d => d.week_of.slice(5)), datasets: [{ data: chats.weekly.map(d => d.count), backgroundColor: c.brand, borderRadius: 4 }] },
        options: { plugins: { legend: { display: false } }, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
      makeChart('chMonthly', { type: 'line',
        data: { labels: chats.monthly.map(d => d.month), datasets: [{ data: chats.monthly.map(d => d.count), borderColor: c.brand, backgroundColor: c.fill, fill: true, tension: .3, borderWidth: 2.5 }] },
        options: { plugins: { legend: { display: false } }, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
      makeChart('chPeak', { type: 'bar',
        data: { labels: chats.peak_hours.map(h => h.hour + ':00'), datasets: [{ data: chats.peak_hours.map(h => h.count), backgroundColor: chats.peak_hours.map(h => h.count === Math.max(...chats.peak_hours.map(x => x.count)) && h.count > 0 ? c.brass : c.brand), borderRadius: 3 }] },
        options: { plugins: { legend: { display: false } }, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
      makeChart('chTopics', { type: 'bar',
        data: { labels: chats.topics.map(t => t.topic), datasets: [{ data: chats.topics.map(t => t.count), backgroundColor: c.palette, borderRadius: 4 }] },
        options: { indexAxis: 'y', plugins: { legend: { display: false } }, maintainAspectRatio: false, scales: { x: { beginAtZero: true, ticks: { precision: 0 } } } } });
    } catch (e) { content.innerHTML = emptyState('Could not load analytics', e.message); }
  };

  /* ══ Notifications page ════════════════════════════════════════════ */
  const notifState = { page: 1 };
  pages.notifications = async function () {
    content.innerHTML = `
      <div class="page-head">
        <div><h1>Notifications</h1><p>New applications, conversations, leads and status changes.</p></div>
        <div class="spacer"></div>
        <button class="btn btn-outline" onclick="markAllRead()">Mark all as read</button>
      </div>
      <div class="stat-grid" id="notifStats"></div>
      <div class="card" id="notifBox">${spinner()}</div>`;
    API.get('/api/admin/notifications/analytics').then(st => {
      const el = document.getElementById('notifStats');
      if (!el) return;
      el.innerHTML = `
        <div class="stat"><div class="label">Sent / delivered</div><div class="value">${num(st.sent)}</div><div class="sub">in-app channel</div></div>
        <div class="stat green"><div class="label">Read</div><div class="value">${num(st.read)}</div><div class="sub">${esc(st.open_rate)}% open rate</div></div>
        <div class="stat amber"><div class="label">Unread</div><div class="value">${num(st.unread)}</div></div>
        <div class="stat violet"><div class="label">Duplicates prevented</div><div class="value">${num(st.duplicates_prevented)}</div><div class="sub">smart engine blocked repeats</div></div>`;
    }).catch(() => {});
    loadNotifs();
  };
  window.notifsPage = function (p) { notifState.page = p; loadNotifs(); };
  async function loadNotifs() {
    const box = document.getElementById('notifBox');
    if (!box) return;
    try {
      const r = await API.get('/api/admin/notifications' + API.qs(notifState));
      const icon = t => ({ new_application: '📄', chat_started: '💬', new_lead: '📞',
        payment_verified: '💳', admission_approved: '🎓', application_approved: '✅' }[t] || '🔔');
      box.innerHTML = (r.items.map(n => `
        <div class="notif ${n.is_read ? '' : 'unread'}" onclick="openNotif(${n.id}, '${esc(n.type)}', '${esc(n.related_id || '')}')">
          <span class="n-dot"></span>
          <div><b>${icon(n.type)} ${esc(n.title)}</b><p>${esc(n.message)}</p>
            <p style="margin-top:5px">${badge(n.category || 'general')} ${n.priority && n.priority !== 'normal' ? badge(n.priority) : ''} ${n.occurrences > 1 ? '<span class="badge b-neutral">×' + n.occurrences + ' merged</span>' : ''}</p></div>
          <time>${ago(n.created_at)}</time>
        </div>`).join('') || emptyState('All caught up', 'No notifications yet.')) +
        pager(r, 'notifsPage');
    } catch (e) { box.innerHTML = emptyState('Could not load notifications', e.message); }
  }
  window.openNotif = async function (id, type, relatedId) {
    try { await API.patch('/api/admin/notifications/' + id + '/read'); } catch (e) {}
    refreshUnread();
    if (relatedId) {
      if (type === 'new_application' || type.includes('application') || type.includes('admission') || type.includes('payment')) {
        location.hash = '#/applications/' + relatedId; return;
      }
      if (type.includes('chat')) { location.hash = '#/chats/' + relatedId; return; }
      if (type.includes('lead')) { location.hash = '#/leads'; return; }
    }
    loadNotifs();
  };
  window.markAllRead = async function () {
    try { await API.post('/api/admin/notifications/read-all'); toast('All notifications marked as read', '', 'ok'); refreshUnread(); loadNotifs(); }
    catch (e) { toast('Failed', e.message, 'err'); }
  };

  /* ══ Admin accounts (super admin) ══════════════════════════════════ */
  async function loadRollSettings() {
    const box = document.getElementById('rollBox');
    if (!box) return;
    try {
      const r = await API.get('/api/admin/roll-settings');
      const canWrite = ME.role !== 'staff';
      box.innerHTML = `
        <div class="table-wrap"><table class="data"><thead><tr>
          <th>Campus</th><th>Prefix</th><th>Starting number</th>
          <th>Highest assigned</th><th>Next roll number</th>${canWrite ? '<th></th>' : ''}
        </tr></thead><tbody>
        ${r.items.map(x => `<tr>
          <td class="td-main"><b>${esc(x.campus)}</b></td>
          <td><span class="roll-prefix">${esc(x.prefix)}-</span></td>
          <td><input class="roll-start" id="rs_${esc(x.campus).replace(/\s/g,'_')}" type="number" min="1"
                value="${x.start_number}" ${canWrite ? '' : 'disabled'}></td>
          <td class="mono">${x.highest_assigned == null ? '—' : esc(x.prefix + '-' + x.highest_assigned)}</td>
          <td class="mono"><b>${esc(x.next_roll)}</b></td>
          ${canWrite ? `<td><button class="btn btn-primary btn-sm"
             onclick="saveRollStart('${esc(x.campus)}')">Save</button></td>` : ''}
        </tr>`).join('')}
        </tbody></table></div>`;
    } catch (e) { box.innerHTML = emptyState('Could not load', e.message); }
  }
  window.saveRollStart = async function (campus) {
    const el = document.getElementById('rs_' + campus.replace(/\s/g, '_'));
    const n = parseInt(el.value, 10);
    if (!n || n < 1) { toast('Invalid number', 'Enter 1 or more.', 'err'); return; }
    try {
      const r = await API.patch('/api/admin/roll-settings', { campus, start_number: n });
      toast('Starting roll number saved', campus + ' → next is ' + r.next_roll, 'ok');
      loadRollSettings();
    } catch (e) { toast('Could not save', e.message, 'err'); }
  };

  pages.admins = async function () {
    if (ME.role !== 'super_admin') { content.innerHTML = emptyState('Super admin only', 'You do not have permission to manage admin accounts.'); return; }
    content.innerHTML = `
      <div class="page-head">
        <div><h1>Admin Accounts</h1><p>Manage who can access this dashboard and what they can do.</p></div>
        <div class="spacer"></div>
        <button class="btn btn-primary" onclick="newAdmin()">+ New account</button>
      </div>
      <div class="card" id="adminsBox">${spinner()}</div>
      <div style="height:14px"></div>
      <div class="card"><div class="card-pad" style="font-size:13px;color:var(--ink-soft)">
        <b style="color:var(--ink)">Roles:</b>
        <span class="badge b-approved">super_admin</span> full control, manages accounts &amp; deletes data ·
        <span class="badge b-contacted">admin</span> manages applications, leads &amp; statuses ·
        <span class="badge b-neutral">staff</span> read-only access to everything.
      </div></div>`;
    loadAdmins();
  };
  async function loadAdmins() {
    const box = document.getElementById('adminsBox');
    if (!box) return;
    try {
      const r = await API.get('/api/auth/admins');
      box.innerHTML = `<div class="table-wrap"><table class="data"><thead><tr>
        <th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Last login</th><th></th>
      </tr></thead><tbody>
      ${r.items.map(a => `<tr style="cursor:default">
        <td><b>${esc(a.name)}</b>${a.id === ME.id ? ' <span class="badge b-neutral">you</span>' : ''}</td>
        <td>${esc(a.email)}</td>
        <td><select style="width:auto" ${a.id === ME.id ? 'disabled' : ''} onchange="patchAdmin(${a.id},{role:this.value})">
          ${['super_admin','admin','staff'].map(role => `<option ${a.role===role?'selected':''}>${role}</option>`).join('')}
        </select></td>
        <td>${badge(a.is_active ? 'active' : 'disabled')}</td>
        <td class="mono">${a.last_login ? fmtDateTime(a.last_login) : 'never'}</td>
        <td>${a.id !== ME.id ? `<button class="btn ${a.is_active ? 'btn-bad' : 'btn-ok'} btn-sm" onclick="patchAdmin(${a.id},{is_active:${!a.is_active}})">${a.is_active ? 'Disable' : 'Enable'}</button>` : ''}</td>
      </tr>`).join('')}
      </tbody></table></div>`;
    } catch (e) { box.innerHTML = emptyState('Could not load accounts', e.message); }
  }
  window.patchAdmin = async function (id, patch) {
    try { await API.patch('/api/auth/admins/' + id, patch); toast('Account updated', '', 'ok'); loadAdmins(); }
    catch (e) { toast('Update failed', e.message, 'err'); loadAdmins(); }
  };
  window.newAdmin = function () {
    modal('New admin account', `
      <label class="field"><span>Full name</span><input id="naName" placeholder="e.g. Ayesha Khan"></label>
      <label class="field"><span>Email</span><input id="naEmail" type="email" placeholder="name@brainscollege.edu.pk"></label>
      <label class="field"><span>Password (min 8 characters)</span><input id="naPass" type="password"></label>
      <label class="field"><span>Role</span><select id="naRole">
        <option value="staff">staff — read only</option>
        <option value="admin">admin — can manage</option>
        <option value="super_admin">super_admin — full control</option>
      </select></label>
      <div style="text-align:right"><button class="btn btn-primary" onclick="createAdmin()">Create account</button></div>`);
  };
  window.createAdmin = async function () {
    try {
      await API.post('/api/auth/admins', {
        name: document.getElementById('naName').value.trim(),
        email: document.getElementById('naEmail').value.trim(),
        password: document.getElementById('naPass').value,
        role: document.getElementById('naRole').value
      });
      closeModal(); toast('Account created', '', 'ok'); loadAdmins();
    } catch (e) { toast('Could not create account', e.message, 'err'); }
  };

  /* ══ Settings ══════════════════════════════════════════════════════ */
  pages.settings = function () {
    content.innerHTML = `
      <div class="page-head"><div><h1>Settings</h1><p>Admissions, your account and data exports.</p></div></div>

      <div class="card" id="rollCard"><div class="card-pad">
        <h2 class="section">Admissions — roll numbers</h2>
        <p style="color:var(--ink-soft);font-size:13.5px;margin:-4px 0 12px">
          Each campus has a fixed prefix. Set the starting number; the system then issues
          roll numbers in sequence with no gaps.</p>
        <div id="rollBox">${spinner()}</div>
      </div></div>
      <div style="height:16px"></div>

      <div class="grid-2">
        <div class="card"><div class="card-pad">
          <h2 class="section">Change password</h2>
          <label class="field"><span>Current password</span><input type="password" id="cpCur"></label>
          <label class="field"><span>New password (min 8 characters)</span><input type="password" id="cpNew"></label>
          <label class="field"><span>Confirm new password</span><input type="password" id="cpNew2"></label>
          <button class="btn btn-primary" onclick="changePassword()">Update password</button>
        </div></div>

        <div>
          <div class="card"><div class="card-pad">
            <h2 class="section">Appearance</h2>
            <p style="color:var(--ink-soft);font-size:13px;margin-top:0">Switch between the light and dark theme. Your choice is remembered on this device.</p>
            <button class="btn btn-outline" id="settingsTheme">Toggle dark mode</button>
          </div></div>
          <div style="height:16px"></div>
          <div class="card"><div class="card-pad">
            <h2 class="section">Export data</h2>
            <p style="color:var(--ink-soft);font-size:13px;margin-top:0">Download your data as CSV, Excel or PDF.</p>
            <div class="status-row">
              ${['applications','challans','chats','leads','analytics'].map(w => `<div style="display:flex;gap:6px;align-items:center;border:1px solid var(--line);border-radius:10px;padding:6px 6px 6px 12px">
                <b style="font-size:13px;text-transform:capitalize">${w}</b>
                <button class="btn btn-outline btn-sm" onclick="doExport('${w}','csv')">CSV</button>
                <button class="btn btn-outline btn-sm" onclick="doExport('${w}','xlsx')">Excel</button>
                <button class="btn btn-outline btn-sm" onclick="doExport('${w}','pdf')">PDF</button>
              </div>`).join('')}
            </div>
          </div></div>
        </div>
      </div>`;
    document.getElementById('settingsTheme').addEventListener('click', () => document.getElementById('themeBtn').click());
    loadRollSettings();
  };
  window.changePassword = async function () {
    const cur = document.getElementById('cpCur').value;
    const n1 = document.getElementById('cpNew').value;
    const n2 = document.getElementById('cpNew2').value;
    if (n1 !== n2) { toast('Passwords do not match', '', 'err'); return; }
    if (n1.length < 8) { toast('New password must be at least 8 characters', '', 'err'); return; }
    try {
      await API.post('/api/auth/change-password', { current_password: cur, new_password: n1 });
      toast('Password updated', '', 'ok');
      ['cpCur', 'cpNew', 'cpNew2'].forEach(id => document.getElementById(id).value = '');
    } catch (e) { toast('Could not update password', e.message, 'err'); }
  };

  /* ══ Exports ═══════════════════════════════════════════════════════ */
  window.doExport = async function (what, fmt) {
    let qs = '?format=' + fmt;
    if (what === 'applications') {
      const dEl = document.getElementById('expDate');
      const p = new URLSearchParams();
      p.set('format', fmt);
      if (dEl && dEl.value) p.set('date', dEl.value);
      // carry the same filters the Applications page is showing
      if (appState.q) p.set('q', appState.q);
      if (appState.status) p.set('status', appState.status);
      if (appState.payment_status) p.set('payment_status', appState.payment_status);
      if (appState.admission_status) p.set('admission_status', appState.admission_status);
      if (appState.course) p.set('course', appState.course);
      if (appState.lead_source) p.set('lead_source', appState.lead_source);
      if (appState.campus) p.set('campus', appState.campus);
      qs = '?' + p.toString();
    }
    toast('Preparing export…', what + ' → ' + fmt.toUpperCase(), 'info');
    try { UI.closeModal(); } catch (e) {}
    try { await API.download('/api/admin/exports/' + what + qs); }
    catch (e) { toast('Export failed', e.message, 'err'); }
  };
  window.exportData = function (what) {
    const dateField = what === 'applications' ? `
      <label class="field"><span>Report date <small style="color:var(--ink-faint)">(Recoveries = payments taken that day · Admissions = created that day)</small></span>
        <input type="date" id="expDate" value="${new Date().toISOString().slice(0,10)}"></label>
      <p style="font-size:12.5px;color:var(--ink-faint);margin:2px 0 12px">Leave blank to include all dates. Current page filters are applied automatically.</p>` : '';
    modal('Export ' + what, `
      <p style="margin-top:0;color:var(--ink-soft)">${what === 'applications'
        ? 'A professional report with two sections — <b>Recoveries</b> (payments taken on the date, split by stage) and <b>Admissions</b> (created that date, with the agreed schedule).'
        : 'Choose a format. Up to 10,000 rows are included.'}</p>
      ${dateField}
      <div class="status-row">
        <button class="btn btn-primary" onclick="doExport('${what}','csv')">CSV</button>
        <button class="btn btn-primary" onclick="doExport('${what}','xlsx')">Excel (.xlsx)</button>
        <button class="btn btn-primary" onclick="doExport('${what}','pdf')">PDF</button>
      </div>`);
  };

  /* boot */
  router();
  setInterval(refreshUnread, 60000);
})();
