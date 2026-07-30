/* UI helpers — escaping (XSS safety), toasts, modal, formatting. */
(function () {
  'use strict';

  /* Every value rendered into HTML must pass through esc(). */
  function esc(v) {
    if (v === null || v === undefined) return '';
    return String(v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function toast(title, msg, kind) {
    const box = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = 'toast ' + (kind || 'info');
    el.innerHTML = '<b>' + esc(title) + '</b>' + (msg ? esc(msg) : '');
    box.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; }, 4200);
    setTimeout(() => el.remove(), 4600);
  }

  /* Modal — bodyHTML must already be escaped by the caller where dynamic. */
  function modal(title, bodyHTML) {
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalBody').innerHTML = bodyHTML;
    document.getElementById('modalBack').classList.add('open');
  }
  function closeModal() { document.getElementById('modalBack').classList.remove('open'); }

  function fmtDate(v) {
    if (!v) return '—';
    const d = new Date(v);
    if (isNaN(d)) return esc(v);
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  }
  function fmtDateTime(v) {
    if (!v) return '—';
    const d = new Date(v);
    if (isNaN(d)) return esc(v);
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) + ', ' +
           d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  }
  function fmtTime(v) {
    if (!v) return '';
    const d = new Date(v);
    return isNaN(d) ? '' : d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  }
  function ago(v) {
    if (!v) return '—';
    const d = new Date(v); if (isNaN(d)) return esc(v);
    const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return Math.floor(s / 86400) + 'd ago';
  }
  function fmtDuration(sec) {
    if (sec === null || sec === undefined) return '—';
    if (sec < 60) return sec + 's';
    const m = Math.floor(sec / 60), s = sec % 60;
    if (m < 60) return m + 'm ' + s + 's';
    return Math.floor(m / 60) + 'h ' + (m % 60) + 'm';
  }
  function num(v) { return (v === null || v === undefined) ? '—' : Number(v).toLocaleString(); }

  /* Human labels for internal status keys. Keys stay as they are in the
     database; only what the user reads changes. */
  const STATUS_LABEL = {
    partially_paid: 'Half Paid',
    fully_paid: 'Fully Paid',
    unpaid: 'Unpaid',
    dropped_out: 'Drop Out',
    on_hold: 'On Hold',
    not_admitted: 'Not Admitted'
  };
  function statusLabel(status) {
    const k = String(status || '').toLowerCase();
    return STATUS_LABEL[k] || String(status || '').replace(/_/g, ' ');
  }
  function badge(status) {
    if (!status) return '<span class="badge b-neutral">—</span>';
    const cls = 'b-' + String(status).toLowerCase().replace(/\s+/g, '_');
    return '<span class="badge ' + esc(cls) + '">' + esc(statusLabel(status)) + '</span>';
  }

  /* pager({total,page,pages}, fnName) → HTML; fnName is a global callback(page) */
  function pager(res, fnName) {
    if (!res || res.pages <= 1) {
      return res && res.total ? '<div class="pager"><span>' + num(res.total) + ' total</span></div>' : '';
    }
    return '<div class="pager">' +
      '<span>' + num(res.total) + ' total · page ' + res.page + ' of ' + res.pages + '</span>' +
      '<button ' + (res.page <= 1 ? 'disabled' : '') + ' onclick="' + fnName + '(' + (res.page - 1) + ')">‹ Prev</button>' +
      '<button ' + (res.page >= res.pages ? 'disabled' : '') + ' onclick="' + fnName + '(' + (res.page + 1) + ')">Next ›</button>' +
      '</div>';
  }

  function spinner(msg) {
    return '<div class="skeleton"><div class="spinner"></div>' + esc(msg || 'Loading…') + '</div>';
  }
  function emptyState(big, small) {
    return '<div class="empty"><div class="big">' + esc(big) + '</div>' + esc(small || '') + '</div>';
  }

  function debounce(fn, ms) {
    let t;
    return function () {
      clearTimeout(t);
      const args = arguments, self = this;
      t = setTimeout(() => fn.apply(self, args), ms);
    };
  }

  document.getElementById('modalClose').addEventListener('click', closeModal);
  document.getElementById('modalBack').addEventListener('click', function (e) {
    if (e.target === this) closeModal();
  });

  window.UI = {
    esc, toast, modal, closeModal, fmtDate, fmtDateTime, fmtTime, ago,
    fmtDuration, num, badge, pager, spinner, emptyState, debounce
  };
})();
