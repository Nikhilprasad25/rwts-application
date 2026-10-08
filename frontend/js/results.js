/* Results, worker reliability, WRS analysis and comparison views. */
const Results = (() => {
  const state = { id: null, results: null, metrics: null, workers: {}, condition: 'baseline' };
  const CMS = 'total_weighted_completion_time';
  const TMS = 'maximum_completion_time';

  function init() {
    UI.$('#btn-reload-results').onclick = () => state.id && load(state.id);
    UI.$('#results-exp-select').onchange = e => e.target.value && load(e.target.value);
    UI.$('#workers-algo-select').onchange = () => renderWorkers();
    UI.$('#wrs-algo-select').onchange = () => renderWRS();
    UI.$('#cmp-condition').onchange = renderComparison;
    UI.$('#cmp-metric').onchange = renderComparison;
    UI.$('#export-exp-select').onchange = e => e.target.value && loadExport(e.target.value);
  }

  async function load(id) {
    state.id = id;
    try {
      state.results = await API.expResults(id);
      state.metrics = await API.expMetrics(id);
    } catch (e) { UI.toast('No results yet for ' + id, 'warn'); return; }
    UI.$('#results-exp-select').value = id;
    UI.$('#export-exp-select').value = id;
    renderResults();
    renderWorkerSelectors();
    renderWorkers();
    renderWRS();
    renderComparisonControls();
    renderComparison();
    loadExport(id);
  }

  /* --------------------------- results page --------------------------- */
  function renderResults() {
    const r = state.results, comp = r.comparison;
    UI.$('#results-subtitle').textContent =
      `${r.experiment_id} · ${r.dataset.filename} · ${r.n_workers} workers · `
      + `${r.config.tasks.n_tasks} tasks · ${r.config.repetitions} repetitions · seed ${r.config.simulation.seed}`;

    const best = comp.best || {};
    const orc = (comp.approximation_ratios || {})[CMS] || {};
    UI.clear(UI.$('#results-tiles')).append(
      UI.stat('Best (CMS)', best[CMS] || '—', 'lowest total weighted completion time'),
      UI.stat('Best (TMS)', best[TMS] || '—', 'lowest maximum completion time'),
      UI.stat('Lowest rework', best.rework_rate || '—'),
      UI.stat('Best approx. ratio',
        (() => {
          const cand = Object.entries(orc).filter(([a]) => a !== 'Oracle');
          if (!cand.length) return '—';
          const b = cand.reduce((x, y) => (y[1].mean < x[1].mean ? y : x));
          return `${b[0]} ${b[1].mean.toFixed(3)}`;
        })(), 'vs Oracle, CMS objective'));

    const algos = comp.algorithms;
    const metricRows = [CMS, TMS, 'total_cost', 'average_completion_time', 'rework_rate',
      'reworks_per_task', 'failure_rate', 'deadline_violation_rate', 'average_attempts',
      'completion_rate', 'worker_utilisation', 'expired_tasks', 'runtime_seconds']
      .filter(m => comp.metrics.includes(m));

    const cols = [{ label: 'Metric', render: r0 => r0.label }].concat(
      algos.map(a => ({
        label: a, num: true,
        render: r0 => {
          const s = comp.aggregate[a][r0.metric];
          const el = UI.el('span', {},
            UI.num(s.mean, 4),
            UI.el('span', { style: 'color:var(--faint);font-size:.75em' },
              ` ±${UI.num(Math.max(s.ci_high - s.mean, 0), 3)}`));
          if (comp.best[r0.metric] === a) el.style.fontWeight = '700';
          return el;
        }
      })));
    const rows = metricRows.map(m => ({ metric: m, label: comp.metric_labels[m] || m }));
    UI.clear(UI.$('#results-table')).appendChild(UI.table(cols, rows));

    const mean = m => algos.map(a => comp.aggregate[a][m].mean);
    const err = m => algos.map(a => Math.max(comp.aggregate[a][m].ci_high - comp.aggregate[a][m].mean, 0));
    Charts.algoBar('chart-cms', algos, mean(CMS), err(CMS), comp.metric_labels[CMS]);
    Charts.algoBar('chart-tms', algos, mean(TMS), err(TMS), comp.metric_labels[TMS]);
    if (Object.keys(orc).length) {
      Charts.algoBar('chart-ratio', algos, algos.map(a => (orc[a] || {}).mean ?? null),
        algos.map(a => Math.max(((orc[a] || {}).ci_high ?? 0) - ((orc[a] || {}).mean ?? 0), 0)),
        'Approximation ratio (CMS)');
    }
    Charts.groupedBar('chart-rates', algos.map(a => a), [
      { label: 'Rework rate', data: mean('rework_rate') },
      { label: 'Failure rate', data: mean('failure_rate') },
      { label: 'Deadline violations', data: mean('deadline_violation_rate') }
    ]);

    const sig = (comp.significance || {})[CMS] || {};
    const sigRows = Object.entries(sig).map(([k, v]) => ({
      pair: k, diff: v.mean_difference, p: v.t_p_value, d: v.cohens_d,
      w: v.wilcoxon_p_value, n: v.n
    }));
    UI.clear(UI.$('#results-significance')).appendChild(sigRows.length
      ? UI.table([
          { label: 'Comparison', key: 'pair' },
          { label: 'Mean difference', num: true, render: r0 => UI.num(r0.diff, 4) },
          { label: 't-test p', num: true, render: r0 => UI.num(r0.p, 5) },
          { label: 'Wilcoxon p', num: true, render: r0 => UI.num(r0.w, 5) },
          { label: "Cohen's d", num: true, render: r0 => UI.num(r0.d, 3) },
          { label: 'n', num: true, key: 'n' }
        ], sigRows)
      : UI.el('div', { class: 'empty' }, 'Needs at least one RWTS variant and one baseline.'));
  }

  /* --------------------------- workers page --------------------------- */
  function renderWorkerSelectors() {
    const algos = Object.keys(state.results.details || {});
    [['#workers-algo-select', renderWorkers], ['#wrs-algo-select', renderWRS]]
      .forEach(([sel]) => {
        const s = UI.clear(UI.$(sel));
        algos.forEach(a => s.appendChild(UI.el('option', { value: a }, a)));
      });
  }

  function currentDetail(selectId) {
    const algo = UI.$(selectId).value || Object.keys(state.results.details || {})[0];
    return [algo, (state.results.details || {})[algo]];
  }

  function renderWorkers() {
    if (!state.results) return;
    const [algo, d] = currentDetail('#workers-algo-select');
    if (!d) return;
    const ws = d.workers;
    Charts.histogram('chart-rel-hist', ws.map(w => w.true_reliability), 12,
      'Workers per true-reliability bin (synthetic)');
    Charts.scatter('chart-util', [{
      label: 'Worker', color: '#2563eb',
      data: ws.map(w => ({ x: w.true_reliability, y: w.busy_time }))
    }], 'True reliability (synthetic)', 'Busy time');

    UI.clear(UI.$('#workers-table')).appendChild(UI.table([
      { label: 'Worker', key: 'worker_id' },
      { label: 'λ', num: true, render: w => w.lam.toExponential(3) },
      { label: 'True reliability', num: true, render: w => UI.num(w.true_reliability, 3) },
      { label: 'WRS', num: true, render: w => UI.num(w.wrs, 3) },
      { label: 'Error', num: true, render: w => UI.num(w.estimation_error, 3) },
      { label: 'Observations', num: true, key: 'observed_attempts' },
      { label: 'Completed', num: true, key: 'completed' },
      { label: 'Failed', num: true, key: 'failed' },
      { label: 'Rework', num: true, key: 'reworked' },
      { label: 'Busy time', num: true, render: w => UI.num(w.busy_time, 0) }
    ], ws));
  }

  /* --------------------------- WRS analysis --------------------------- */
  function renderWRS() {
    if (!state.results) return;
    const [algo, d] = currentDetail('#wrs-algo-select');
    if (!d) return;
    const ws = d.workers;
    Charts.scatter('chart-scatter', [
      { label: 'Workers', color: '#7c3aed',
        data: ws.map(w => ({ x: w.true_reliability, y: w.wrs })) },
      { label: 'Perfect estimation', color: '#94a3b8', showLine: true, pointRadius: 0,
        dash: [6, 4], data: [{ x: 0, y: 0 }, { x: 1, y: 1 }] }
    ], 'True reliability (synthetic ground truth)', 'Estimated WRS',
       { x: { min: 0, max: 1 }, y: { min: 0, max: 1 } });

    const errs = ws.map(w => w.estimation_error);
    const mae = errs.reduce((a, b) => a + Math.abs(b), 0) / (errs.length || 1);
    const bias = errs.reduce((a, b) => a + b, 0) / (errs.length || 1);
    const corr = pearson(ws.map(w => w.true_reliability), ws.map(w => w.wrs));
    UI.$('#wrs-fit').textContent =
      `n = ${ws.length}   MAE = ${mae.toFixed(4)}   bias (true − WRS) = ${bias.toFixed(4)}   Pearson r = ${corr.toFixed(4)}`;
    Charts.histogram('chart-error', errs, 12, 'Estimation error (true − WRS)');

    // convergence: mean |error| against observation count, pooled over workers
    const buckets = new Map();
    Object.values(d.wrs_history || {}).forEach(hist => {
      hist.forEach(h => {
        const k = Math.round(h.observations);
        if (!buckets.has(k)) buckets.set(k, []);
        buckets.get(k).push(Math.abs(h.true_reliability - h.wrs_noise_free));
      });
    });
    const xs = [...buckets.keys()].sort((a, b) => a - b);
    const ys = xs.map(k => {
      const v = buckets.get(k); return v.reduce((a, b) => a + b, 0) / v.length;
    });
    Charts.lines('chart-convergence', xs, [{ label: 'Mean |true − WRS|', data: ys }],
      'Observed task outcomes for the worker', 'Mean absolute estimation error');
  }

  function pearson(a, b) {
    const n = a.length; if (!n) return NaN;
    const ma = a.reduce((x, y) => x + y, 0) / n, mb = b.reduce((x, y) => x + y, 0) / n;
    let num = 0, da = 0, db = 0;
    for (let i = 0; i < n; i++) { const x = a[i] - ma, y = b[i] - mb; num += x * y; da += x * x; db += y * y; }
    return da && db ? num / Math.sqrt(da * db) : NaN;
  }

  /* --------------------------- comparison ----------------------------- */
  function renderComparisonControls() {
    const conds = state.metrics.conditions.map(c => c.label);
    const cs = UI.clear(UI.$('#cmp-condition'));
    conds.forEach(c => cs.appendChild(UI.el('option', { value: c }, c)));
    const comp = state.results.comparison;
    const ms = UI.clear(UI.$('#cmp-metric'));
    comp.metrics.forEach(m => ms.appendChild(
      UI.el('option', { value: m }, comp.metric_labels[m] || m)));
    ms.value = CMS;
    const ab = UI.clear(UI.$('#cmp-algos'));
    comp.algorithms.forEach(a => {
      const c = UI.checkbox('cmp-algo-' + a, a, true);
      c.querySelector('input').onchange = renderComparison;
      ab.appendChild(c);
    });
  }

  function renderComparison() {
    if (!state.metrics) return;
    const cond = UI.$('#cmp-condition').value;
    const metric = UI.$('#cmp-metric').value;
    const entry = state.metrics.conditions.find(c => c.label === cond);
    if (!entry) return;
    const comp = entry.comparison;
    const algos = comp.algorithms.filter(a => UI.val('cmp-algo-' + a, true));
    const means = algos.map(a => comp.aggregate[a][metric].mean);
    const errs = algos.map(a => Math.max(comp.aggregate[a][metric].ci_high - comp.aggregate[a][metric].mean, 0));
    Charts.algoBar('chart-cmp', algos, means, errs, comp.metric_labels[metric] || metric);

    const small = UI.clear(UI.$('#cmp-small-multiples'));
    ['total_cost', 'average_completion_time', 'rework_rate', 'reworks_per_task',
     'failure_rate', 'average_attempts']
      .filter(m => comp.metrics.includes(m))
      .forEach(m => {
        const id = 'sm-' + m;
        small.appendChild(UI.el('div', { class: 'card' },
          UI.el('div', { class: 'card-head' }, UI.el('h3', {}, comp.metric_labels[m] || m)),
          UI.el('div', { class: 'chart-box' }, UI.el('canvas', { id }))));
        setTimeout(() => Charts.algoBar(id, algos,
          algos.map(a => comp.aggregate[a][m].mean),
          algos.map(a => Math.max(comp.aggregate[a][m].ci_high - comp.aggregate[a][m].mean, 0)),
          comp.metric_labels[m] || m), 0);
      });
  }

  /* --------------------------- export --------------------------------- */
  function loadExport(id) {
    const b = UI.clear(UI.$('#export-buttons'));
    const items = [
      ['Aggregated results (CSV)', 'aggregated', 'csv'],
      ['Aggregated results (Excel)', 'aggregated', 'xlsx'],
      ['Raw simulation runs (CSV)', 'raw', 'csv'],
      ['Raw simulation runs (JSON)', 'raw', 'json'],
      ['Experiment configuration (JSON)', 'config', 'json'],
      ['Research summary (Markdown)', 'summary', 'md'],
      ['Charts (PDF)', 'charts', 'pdf'],
      ['Primary chart (PNG)', 'chart', 'png'],
      ['Full bundle (ZIP)', 'bundle', 'zip']
    ];
    items.forEach(([label, kind, fmt]) => b.appendChild(UI.el('a', {
      class: 'btn', href: API.exportUrl(id, kind, fmt), download: ''
    }, label)));

    const db = UI.clear(UI.$('#export-dataset-buttons'));
    const dsid = state.results?.config?.dataset_id || App.state.datasetId;
    if (dsid) {
      [['CSV', 'csv'], ['Excel', 'xlsx'], ['JSON', 'json']].forEach(([l, f]) =>
        db.appendChild(UI.el('a', { class: 'btn', href: API.datasetExportUrl(dsid, f),
          download: '' }, `Processed dataset (${l})`)));
    }
    fetch(API.exportUrl(id, 'summary', 'md')).then(r => r.text())
      .then(t => { UI.$('#export-preview').textContent = t; })
      .catch(() => {});
  }

  return { init, load, state };
})();
