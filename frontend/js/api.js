/* Thin REST client + shared UI helpers. All research logic lives in Python. */
const API = (() => {
  const base = '';

  async function req(path, opts = {}) {
    const res = await fetch(base + path, opts);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    const ct = res.headers.get('content-type') || '';
    return ct.includes('application/json') ? res.json() : res.text();
  }
  const get  = p => req(p);
  const post = (p, body) => req(p, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const del = p => req(p, { method: 'DELETE' });

  return {
    get, post, del,
    home:            () => get('/api/home'),
    fields:          () => get('/api/dataset/fields'),
    datasets:        () => get('/api/dataset'),
    samples:         () => get('/api/dataset/samples'),
    loadSample:      n => post(`/api/dataset/sample?name=${encodeURIComponent(n)}`),
    dataset:         id => get(`/api/dataset/${id}`),
    deleteDataset:   id => del(`/api/dataset/${id}`),
    mapping:         (id, sheet) => get(`/api/dataset/${id}/mapping` + (sheet ? `?sheet=${encodeURIComponent(sheet)}` : '')),
    preview:         (id, rows) => get(`/api/dataset/${id}/preview?rows=${rows || 100}`),
    prepare:         (id, body) => post(`/api/dataset/${id}/prepare`, body),
    validation:      id => get(`/api/dataset/${id}/validation`),
    datasetConfig:   id => get(`/api/dataset/${id}/configuration`),
    applyConfig:     (id, c) => post(`/api/dataset/${id}/configuration`, { configuration: c }),
    options:         () => get('/api/experiment/options'),
    experiments:     () => get('/api/experiment'),
    createExp:       cfg => post('/api/experiment', cfg),
    runExp:          id => post(`/api/experiment/${id}/run?background=true`),
    expStatus:       id => get(`/api/experiment/${id}/status`),
    cancelExp:       id => post(`/api/experiment/${id}/cancel`),
    expResults:      id => get(`/api/experiment/${id}/results`),
    expMetrics:      id => get(`/api/experiment/${id}/metrics`),
    expWorkers:      (id, a) => get(`/api/experiment/${id}/workers` + (a ? `?algorithm=${a}` : '')),
    expTasks:        (id, a) => get(`/api/experiment/${id}/tasks` + (a ? `?algorithm=${a}` : '')),
    exportUrl:       (id, kind, fmt, metric) =>
      `/api/results/${id}/export?kind=${kind}&fmt=${fmt}` + (metric ? `&metric=${metric}` : ''),
    datasetExportUrl: (id, fmt) => `/api/dataset/${id}/export?fmt=${fmt}`,
    async upload(file) {
      const fd = new FormData();
      fd.append('file', file);
      return req('/api/dataset/upload', { method: 'POST', body: fd });
    }
  };
})();

/* ------------------------------ UI helpers ------------------------------ */
const UI = {
  el(tag, attrs = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') n.className = v;
      else if (k === 'html') n.innerHTML = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) n.setAttribute(k, v);
    }
    kids.flat().forEach(k => k !== null && k !== undefined &&
      n.appendChild(typeof k === 'string' || typeof k === 'number'
        ? document.createTextNode(String(k)) : k));
    return n;
  },
  $(sel) { return document.querySelector(sel); },
  clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; },
  toast(msg, kind = '') {
    const t = UI.el('div', { class: `toast ${kind}` }, msg);
    UI.$('#toasts').appendChild(t);
    setTimeout(() => t.remove(), kind === 'bad' ? 8000 : 4200);
  },
  modal(title, contentNode) {
    const box = UI.$('#modal');
    UI.clear(box);
    box.appendChild(UI.el('div', { class: 'card-head' },
      UI.el('h2', {}, title),
      UI.el('button', { class: 'btn sm', onclick: UI.closeModal }, 'Close')));
    box.appendChild(contentNode);
    UI.$('#modal-backdrop').classList.add('open');
  },
  closeModal() { UI.$('#modal-backdrop').classList.remove('open'); },

  num(v, digits = 4) {
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    const a = Math.abs(v);
    if (a !== 0 && (a >= 1e6 || a < 1e-3)) return v.toExponential(2);
    return Number(v.toFixed(digits)).toLocaleString();
  },
  int(v) { return (v === null || v === undefined) ? '—' : Math.round(v).toLocaleString(); },
  pct(v, d = 1) { return v === null || v === undefined ? '—' : (100 * v).toFixed(d) + '%'; },
  bytes(b) {
    if (b < 1024) return b + ' B';
    if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
    return (b / 1048576).toFixed(2) + ' MB';
  },
  duration(sec) {
    if (sec === null || sec === undefined) return '—';
    const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600),
          m = Math.floor(sec % 3600 / 60);
    return `${d ? d + 'd ' : ''}${h}h ${m}m`;
  },
  stat(label, value, hint) {
    return UI.el('div', { class: 'stat' },
      UI.el('div', { class: 'label' }, label),
      UI.el('div', { class: 'value' }, value),
      hint ? UI.el('div', { class: 'hint' }, hint) : null);
  },
  table(columns, rows, opts = {}) {
    const thead = UI.el('thead', {}, UI.el('tr', {}, columns.map(c =>
      UI.el('th', { class: c.num ? 'num' : '' }, c.label))));
    const tbody = UI.el('tbody', {}, rows.map(r => {
      const tr = UI.el('tr', { class: opts.rowClass ? opts.rowClass(r) : '' },
        columns.map(c => {
          const v = c.render ? c.render(r) : r[c.key];
          const td = UI.el('td', { class: c.num ? 'num' : '' });
          if (v instanceof Node) td.appendChild(v); else td.textContent = v ?? '—';
          return td;
        }));
      return tr;
    }));
    return UI.el('table', {}, thead, tbody);
  },
  field(label, control, help) {
    return UI.el('div', { class: 'field' },
      UI.el('label', {}, label), control,
      help ? UI.el('div', { class: 'help' }, help) : null);
  },
  input(id, value, type = 'number', step) {
    const i = UI.el('input', { id, type, value: value ?? '' });
    if (step) i.step = step;
    return i;
  },
  select(id, options, value) {
    const s = UI.el('select', { id });
    options.forEach(o => {
      const [val, lbl] = Array.isArray(o) ? o : [o, o];
      const opt = UI.el('option', { value: val }, lbl);
      if (String(val) === String(value)) opt.selected = true;
      s.appendChild(opt);
    });
    return s;
  },
  checkbox(id, label, checked) {
    const c = UI.el('input', { id, type: 'checkbox' });
    c.checked = !!checked;
    return UI.el('label', { class: 'checkline' }, c, UI.el('span', {}, label));
  },
  val(id, fallback) {
    const n = document.getElementById(id);
    if (!n) return fallback;
    if (n.type === 'checkbox') return n.checked;
    if (n.type === 'number') { const v = parseFloat(n.value); return Number.isNaN(v) ? fallback : v; }
    return n.value;
  }
};
