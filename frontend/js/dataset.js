/* Dataset page: upload -> inspect -> map -> clean -> validate -> prepare. */
const Dataset = (() => {
  const state = {
    datasetId: null, meta: null, sheet: null, columns: [], fields: [],
    mapping: {}, prepared: null, suggestions: []
  };

  const CLEANING_FIELDS = [
    ['missing_strategy', 'Missing values', 'select',
     [['remove_row', 'Remove row'], ['default', 'Replace with default'],
      ['forward_fill', 'Forward fill'], ['ignore', 'Ignore field']],
     'Records are never dropped silently — the funnel reports every removal.'],
    ['remove_duplicates', 'Remove duplicate records', 'check', null, null],
    ['remove_invalid', 'Remove invalid records', 'check', null, null],
    ['remove_self_contacts', 'Remove self-contacts (source = destination)', 'check', null, null],
    ['min_duration', 'Minimum contact duration', 'number', null,
     'Contacts shorter than this are discarded.'],
    ['normalise_time_origin', 'Shift first contact to t = 0', 'check', null, null],
    ['treat_as_undirected', 'Treat contacts as undirected', 'check', null,
     'A contact a–b counts toward both nodes when estimating λ.'],
    ['time_unit', 'Time unit label', 'text', null, 'Documentation only.']
  ];
  const CLEAN_DEFAULTS = {
    missing_strategy: 'remove_row', remove_duplicates: true, remove_invalid: true,
    remove_self_contacts: true, min_duration: 0, normalise_time_origin: true,
    treat_as_undirected: true, time_unit: 'seconds'
  };

  /* ---------------------------------------------------------------- */
  async function init() {
    const f = await API.fields();
    state.fields = f.fields;
    UI.$('#ds-formats').textContent = f.allowed_extensions.join(' · ');

    const dz = UI.$('#dropzone'), fi = UI.$('#file-input');
    dz.addEventListener('click', () => fi.click());
    dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('drag'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('drag'));
    dz.addEventListener('drop', e => {
      e.preventDefault(); dz.classList.remove('drag');
      if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]);
    });
    fi.addEventListener('change', () => fi.files[0] && upload(fi.files[0]));

    UI.$('#btn-load-sample').onclick = async () => {
      const name = UI.$('#sample-select').value;
      if (!name) return;
      try {
        const meta = await API.loadSample(name);
        UI.toast(`Loaded sample ${name}`, 'ok');
        await refreshDatasets(); await open(meta.dataset_id);
      } catch (e) { UI.toast(e.message, 'bad'); }
    };
    UI.$('#btn-open-dataset').onclick = () => {
      const id = UI.$('#dataset-select').value; if (id) open(id);
    };
    UI.$('#btn-delete-dataset').onclick = async () => {
      const id = UI.$('#dataset-select').value; if (!id) return;
      await API.deleteDataset(id); UI.toast('Dataset deleted', 'ok');
      state.datasetId = null; await refreshDatasets(); renderStepper();
    };
    UI.$('#sheet-select').onchange = () => loadSheet(UI.$('#sheet-select').value);
    UI.$('#btn-resuggest').onclick = () => loadSheet(state.sheet, true);
    UI.$('#btn-prepare').onclick = prepare;
    UI.$('#btn-save-config').onclick = saveConfig;
    UI.$('#btn-load-config').onclick = loadConfig;
    UI.$('#prep-tabs').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      [...UI.$('#prep-tabs').children].forEach(x => x.classList.toggle('active', x === b));
      ['summary', 'quality', 'workers', 'records'].forEach(t =>
        UI.$('#prep-' + t).style.display = (t === b.dataset.tab ? '' : 'none'));
    });

    renderCleaningForm();
    await refreshSamples();
    await refreshDatasets();
    renderStepper();
  }

  async function refreshSamples() {
    const { samples } = await API.samples();
    const sel = UI.clear(UI.$('#sample-select'));
    if (!samples.length) sel.appendChild(UI.el('option', { value: '' }, 'no bundled samples'));
    samples.forEach(s => sel.appendChild(UI.el('option', { value: s }, s)));
  }

  async function refreshDatasets() {
    const { datasets } = await API.datasets();
    const sel = UI.clear(UI.$('#dataset-select'));
    sel.appendChild(UI.el('option', { value: '' }, `${datasets.length} dataset(s) available…`));
    datasets.forEach(d => sel.appendChild(UI.el('option', { value: d.dataset_id },
      `${d.original_filename} ${d.prepared ? '✓ prepared' : '· raw'}`)));
    App.state.datasets = datasets;
    return datasets;
  }

  async function upload(file) {
    const s = UI.$('#upload-status');
    s.innerHTML = `<span class="spinner"></span> Uploading ${file.name} (${UI.bytes(file.size)})…`;
    try {
      const meta = await API.upload(file);
      s.innerHTML = '';
      UI.toast(`${meta.original_filename} uploaded`, 'ok');
      await refreshDatasets();
      await open(meta.dataset_id);
    } catch (e) {
      s.innerHTML = '';
      UI.toast('Upload failed: ' + e.message, 'bad');
    }
  }

  /* ---------------------------------------------------------------- */
  async function open(datasetId) {
    state.datasetId = datasetId;
    state.meta = await API.dataset(datasetId);
    App.state.datasetId = datasetId;
    App.state.datasetMeta = state.meta;
    UI.$('#dataset-select').value = datasetId;

    const wb = state.meta.workbook;
    UI.$('#card-workbook').style.display = '';
    UI.$('#wb-format').textContent =
      `${wb.physical_format}${wb.delimiter ? ' · delimiter "' + (wb.delimiter === '\t' ? '\\t' : wb.delimiter) + '"' : ''}`;

    const sel = UI.clear(UI.$('#sheet-select'));
    wb.sheet_names.forEach(n => sel.appendChild(UI.el('option', { value: n }, n)));
    sel.value = state.meta.sheet || wb.sheet_names[0];
    await loadSheet(sel.value);

    if (state.meta.prepared) await showPrepared(await API.preview(datasetId, 100), true);
    else { UI.$('#card-prepared').style.display = 'none'; }
    renderStepper();
    App.refreshHome();
  }

  async function loadSheet(sheet, resuggest) {
    state.sheet = sheet;
    const wb = state.meta.workbook;
    const info = wb.sheets.find(s => s.name === sheet) || wb.sheets[0];
    if (!info) return;

    UI.clear(UI.$('#wb-stats')).append(
      UI.stat('Rows', UI.int(info.rows)),
      UI.stat('Columns', UI.int(info.columns)),
      UI.stat('Duplicate rows', UI.int(info.duplicate_rows)),
      UI.stat('Header', info.synthetic_header ? 'generated' : 'present',
              info.synthetic_header ? 'no header row found in the source' : ''));

    UI.clear(UI.$('#wb-columns')).appendChild(UI.table(
      [{ label: 'Column', key: 'c' }, { label: 'Type', key: 't' },
       { label: 'Missing', key: 'm', num: true }],
      info.column_names.map(c => ({ c, t: info.dtypes[c], m: info.missing_values[c] }))));

    const cols = info.column_names;
    UI.clear(UI.$('#wb-sample')).appendChild(UI.table(
      cols.map(c => ({ label: c, key: c })), info.sample));

    const m = await API.mapping(state.datasetId, sheet);
    state.columns = m.columns;
    state.suggestions = m.suggestions;
    const saved = (!resuggest && state.meta.mapping) ? state.meta.mapping : null;
    state.mapping = {};
    m.suggestions.forEach(s => {
      state.mapping[s.field] = saved && saved[s.field] !== undefined
        ? saved[s.field] : s.suggested_column;
    });
    renderMapping();
    UI.$('#card-mapping').style.display = '';
    UI.$('#card-cleaning').style.display = '';
  }

  function renderMapping() {
    const box = UI.clear(UI.$('#mapping-rows'));
    state.suggestions.forEach(s => {
      const sel = UI.select('map-' + s.field,
        [['', '— not mapped —']].concat(state.columns.map(c => [c, c])),
        state.mapping[s.field] || '');
      sel.onchange = () => { state.mapping[s.field] = sel.value || null; };
      box.appendChild(UI.el('div', { class: 'map-row' },
        UI.el('div', { class: 'fld' }, s.label,
          UI.el('small', {}, `${s.field}${s.required ? ' · required' : ' · optional'}`)),
        sel,
        UI.el('span', { class: 'badge ' + (s.confidence > .8 ? 'ok' : s.confidence > .5 ? 'warn' : '') },
          s.suggested_column ? `${s.reason} (${(s.confidence * 100).toFixed(0)}%)` : s.reason)));
    });
  }

  function renderCleaningForm() {
    const box = UI.clear(UI.$('#cleaning-form'));
    CLEANING_FIELDS.forEach(([key, label, type, options, help]) => {
      const id = 'clean-' + key;
      let control;
      if (type === 'select') control = UI.select(id, options, CLEAN_DEFAULTS[key]);
      else if (type === 'check') { box.appendChild(UI.checkbox(id, label, CLEAN_DEFAULTS[key])); return; }
      else control = UI.input(id, CLEAN_DEFAULTS[key], type === 'text' ? 'text' : 'number');
      box.appendChild(UI.field(label, control, help));
    });
  }

  function cleaningOptions() {
    const o = {};
    CLEANING_FIELDS.forEach(([key]) => { o[key] = UI.val('clean-' + key, CLEAN_DEFAULTS[key]); });
    return o;
  }

  /* ---------------------------------------------------------------- */
  async function prepare() {
    const s = UI.$('#prepare-status');
    s.innerHTML = '<span class="spinner"></span> Preparing…';
    try {
      const res = await API.prepare(state.datasetId, {
        sheet: state.sheet, mapping: state.mapping, cleaning: cleaningOptions()
      });
      s.innerHTML = '';
      UI.toast('Dataset prepared', 'ok');
      state.meta = await API.dataset(state.datasetId);
      App.state.datasetMeta = state.meta;
      await showPrepared({ ...res, records: res.preview,
                           worker_parameters: res.worker_parameters }, false);
      await refreshDatasets();
      renderStepper();
      App.renderTransform(state.meta, res.worker_parameters);
      App.refreshHome();
    } catch (e) {
      s.innerHTML = '';
      UI.toast('Preparation failed: ' + e.message, 'bad');
    }
  }

  async function showPrepared(res, fromPreview) {
    state.prepared = res;
    UI.$('#card-prepared').style.display = '';
    const sm = res.summary;
    UI.clear(UI.$('#prep-summary')).append(
      UI.el('div', { class: 'grid cols-4' },
        UI.stat('Workers', UI.int(sm.workers)),
        UI.stat('Contacts', UI.int(sm.contacts)),
        UI.stat('Time period', UI.duration(sm.duration), `${sm.time_unit}`),
        UI.stat('Total records', UI.int(sm.total_records)),
        UI.stat('Avg contacts / worker', UI.num(sm.average_contacts_per_worker, 2)),
        UI.stat('Avg inter-contact time', UI.num(sm.average_inter_contact_time, 1)),
        UI.stat('Avg contact duration', UI.num(sm.average_contact_duration, 1)),
        UI.stat('Time origin', UI.num(sm.time_start, 0))));

    const v = res.validation || (await API.validation(state.datasetId)).validation;
    UI.clear(UI.$('#prep-quality')).append(
      UI.el('div', { class: 'grid cols-4' },
        UI.stat('Valid records', UI.int(v.valid_rows)),
        UI.stat('Invalid records', UI.int(v.invalid_rows)),
        UI.stat('Duplicates', UI.int(v.duplicate_rows)),
        UI.stat('Missing values',
                UI.int(Object.values(v.missing_values || {}).reduce((a, b) => a + b, 0)))),
      UI.el('h3', { style: 'margin-top:14px' }, 'Rule breakdown'),
      UI.el('div', { class: 'table-wrap' }, UI.table(
        [{ label: 'Rule', key: 'r' }, { label: 'Description', key: 'd' },
         { label: 'Rows', key: 'n', num: true }],
        Object.entries(v.rule_counts || {}).map(([r, n]) =>
          ({ r, n, d: (v.rule_descriptions || {})[r] || '—' })))));

    const wp = res.worker_parameters ||
      (await API.preview(state.datasetId, 1)).worker_parameters;
    UI.clear(UI.$('#prep-workers')).appendChild(
      UI.el('div', { class: 'table-wrap table-scroll' }, UI.table([
        { label: 'Worker', key: 'worker_id' },
        { label: 'Contacts', key: 'contact_count', num: true },
        { label: 'Distinct peers', key: 'distinct_peers', num: true },
        { label: 'Observation period', num: true,
          render: r => UI.num(r.observation_period, 0) },
        { label: 'Mean inter-contact', num: true,
          render: r => UI.num(r.mean_inter_contact_time, 1) },
        { label: 'λ (per unit time)', num: true,
          render: r => (r['lambda'] ?? r.lam).toExponential(3) }
      ], wp)));

    const recs = res.records || res.preview || [];
    const cols = recs.length ? Object.keys(recs[0]) : [];
    UI.clear(UI.$('#prep-records')).append(
      UI.el('div', { class: 'card-sub' }, `First ${recs.length} processed records`),
      UI.el('div', { class: 'table-wrap table-scroll' },
        UI.table(cols.map(c => ({ label: c, key: c, num: c !== 'source_worker' && c !== 'destination_worker' })), recs)));

    App.state.workerParameters = wp;
    if (!fromPreview) UI.$('#prep-tabs').children[0].click();
  }

  async function saveConfig() {
    try {
      const cfg = await API.datasetConfig(state.datasetId);
      const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: 'application/json' });
      const a = UI.el('a', { href: URL.createObjectURL(blob),
        download: `dataset_config_${state.datasetId}.json` });
      document.body.appendChild(a); a.click(); a.remove();
      UI.toast('Configuration downloaded', 'ok');
    } catch (e) { UI.toast(e.message, 'bad'); }
  }

  function loadConfig() {
    const inp = UI.el('input', { type: 'file', accept: '.json' });
    inp.onchange = async () => {
      const text = await inp.files[0].text();
      try {
        const cfg = JSON.parse(text);
        const res = await API.applyConfig(state.datasetId, cfg);
        UI.toast('Configuration applied and dataset re-prepared', 'ok');
        state.meta = await API.dataset(state.datasetId);
        await showPrepared({ ...res, records: res.preview }, false);
        App.renderTransform(state.meta, res.worker_parameters);
      } catch (e) { UI.toast('Could not apply configuration: ' + e.message, 'bad'); }
    };
    inp.click();
  }

  function renderStepper() {
    const steps = ['Select', 'Inspect', 'Map', 'Clean', 'Validate', 'Prepared'];
    let reached = 0;
    if (state.datasetId) reached = 2;
    if (state.mapping && Object.values(state.mapping || {}).some(Boolean)) reached = 3;
    if (state.meta && state.meta.prepared) reached = 6;
    const box = UI.clear(UI.$('#ds-stepper'));
    steps.forEach((s, i) => box.appendChild(UI.el('div', {
      class: 'step ' + (i < reached ? 'done' : i === reached ? 'current' : '')
    }, UI.el('i', {}, i < reached ? '✓' : String(i + 1)), s)));
    App.renderHomeStepper(reached);
  }

  return { init, open, refreshDatasets, state };
})();
