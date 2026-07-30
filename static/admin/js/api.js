/* API client — Bearer-token fetch wrapper for the Brains College dashboard. */
(function () {
  'use strict';

  function token() { return localStorage.getItem('bc_token'); }

  function logout() {
    localStorage.removeItem('bc_token');
    localStorage.removeItem('bc_admin');
    location.href = '/admin/login';
  }

  async function request(method, path, body) {
    const headers = { 'Authorization': 'Bearer ' + token() };
    if (body !== undefined) headers['Content-Type'] = 'application/json';

    let res;
    try {
      res = await fetch(path, {
        method: method,
        headers: headers,
        body: body !== undefined ? JSON.stringify(body) : undefined
      });
    } catch (e) {
      throw new Error('Network error — is the server reachable?');
    }

    if (res.status === 401) { logout(); throw new Error('Session expired'); }

    let data = null;
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('application/json')) data = await res.json().catch(() => null);

    if (!res.ok) {
      let msg = (data && data.detail) || res.statusText || 'Request failed';
      if (Array.isArray(msg)) msg = msg.map(e => e.msg || JSON.stringify(e)).join('; ');
      const err = new Error(msg);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function qs(params) {
    const clean = {};
    Object.keys(params || {}).forEach(k => {
      const v = params[k];
      if (v !== undefined && v !== null && v !== '') clean[k] = v;
    });
    const s = new URLSearchParams(clean).toString();
    return s ? '?' + s : '';
  }

  /* Authenticated file download (exports, PDFs) via blob. */
  async function download(path, filename) {
    const res = await fetch(path, { headers: { 'Authorization': 'Bearer ' + token() } });
    if (res.status === 401) { logout(); return; }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || 'Download failed');
    }
    const blob = await res.blob();
    const cd = res.headers.get('content-disposition') || '';
    const m = cd.match(/filename="?([^";]+)"?/);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (m && m[1]) || filename || 'download';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }

  window.API = {
    token: token,
    logout: logout,
    qs: qs,
    download: download,
    get: (path) => request('GET', path),
    post: (path, body) => request('POST', path, body),
    patch: (path, body) => request('PATCH', path, body),
    del: (path) => request('DELETE', path)
  };
})();
