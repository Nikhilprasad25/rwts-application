/* Experiment configuration + run/progress control.
 *
 * Simplified page: only the settings the research question varies are editable.
 * Everything else is sent as the backend default and listed, read-only, under
 * "Fixed settings" so the method can still be explained from the page.
 */
const Experiment = (() => {
  const state = { options: null, defaults: null, currentId: null, poll: null, log: [] };

  // Reliability distributions offered on the page (others stay backend-only).
  const DISTRIBUTIONS = [
    ['normal', 'Normal (mean ± 0.15)'],
    ['uniform', 'Uniform (0.05 – 1.0)'],
    ['skewed', 'Skewed toward reliable'],
    ['minority_unreliable', 'Minority unreliable (20% weak workers)']
  ];
  const USES_MEAN = ['normal', 'skewed'];

  async function init() {
    state.options = await API.options();
    state.defaults = state.options.defaults;
    renderAll();
    UI.$('#btn-run').onclick = run;
    UI.$('#btn-reset-config').onclick = renderAll;
    UI.$('#btn-cancel').onclick = async () => {
      if (state.currentId) { await API.cancelExp(state.currentId); UI.toast('Cancellation requested'); }
    };
    UI.$('#btn-view-results').onclick = () => {
      if (state.currentId) { App.go('results'); Results.load(state.currentId); }
    };
  }

  function renderAll() {
    renderScenario();
    renderReliability();
    renderWRS();
    renderAlgorithms();
    renderFixed();
  }

  /* ----------------------------- editable ------------------------------ */
  function renderScenario() {
    const d = state.defaults;
    const box = UI.clear(UI.$('#cfg-scenario'));
    const workers = UI.input('cfg-n-workers', '', 'number', '1');
    workers.placeholder = 'All';
    workers.min = 1;
    box.append(
      UI.field('Number of workers', workers,
        'Leave blank to use every worker in the dataset; otherwise the N most-connected.'),
      UI.field('Number of tasks', UI.input('cfg-n-tasks', d.tasks.n_tasks, 'number', '1')),
      UI.field('Repetitions', UI.input('cfg-repetitions', d.repetitions, 'number', '1'),
        'Independent runs averaged for the results (30 or more recommended).'),
      UI.field('Random seed', UI.input('cfg-seed', d.simulation.seed, 'number', '1'),
        'Same seed gives the same results.'));
  }

  function renderReliability() {
    const r = state.defaults.reliability;
    const box = UI.clear(UI.$('#cfg-rel'));
    const dist = UI.select('cfg-rel-distribution', DISTRIBUTIONS, r.distribution);
    const meanField = UI.field('Mean reliability',
      UI.input('cfg-rel-mean', r.mean, 'number', '0.05'), 'Between 0 and 1.');
    const sync = () => { meanField.style.display = USES_MEAN.includes(dist.value) ? '' : 'none'; };
    dist.onchange = sync;
    box.append(UI.field('Distribution', dist), meanField,
      UI.el('div', { class: 'note synthetic' },
        'Reliability values are SYNTHETIC. No public MSN dataset records task '
        + 'outcomes, so behaviour is layered on the real contact rates.'));
    sync();
  }

  function renderWRS() {
    const w = state.defaults.wrs;
    const box = UI.clear(UI.$('#cfg-wrs'));
    box.append(
      UI.field('Completion weight', UI.input('cfg-wrs-completion', w.completion_weight, 'number', '0.05')),
      UI.field('Delay weight', UI.input('cfg-wrs-delay', w.delay_weight, 'number', '0.05')),
      UI.field('Rework weight', UI.input('cfg-wrs-rework', w.rework_weight, 'number', '0.05'),
        'Rescaled to sum to 1 if they don\'t already.'));
  }

  function renderAlgorithms() {
    const box = UI.clear(UI.$('#cfg-algos'));
    state.options.algorithms.forEach(a => {
      const wrap = UI.el('div', { class: 'card', style: 'margin:0' });
      wrap.appendChild(UI.checkbox('algo-' + a.name, a.label, true));
      wrap.appendChild(UI.el('div', { class: 'card-sub', style: 'margin:6px 0 4px' }, a.doc));
      wrap.appendChild(UI.el('span', {
        class: 'badge ' + (a.knowledge === 'network_only' ? '' :
          a.knowledge === 'network_plus_wrs' ? 'brand' : 'synthetic')
      }, a.knowledge.replace(/_/g, ' ')));
      box.appendChild(wrap);
    });
  }

  /* ------------------------------ fixed -------------------------------- */
  function renderFixed() {
    const d = state.defaults, t = d.tasks, r = d.reliability, w = d.wrs,
          s = d.simulation, o = d.outcome;
    const groups = [
      ['Statistics', [
        ['Confidence level', `${Math.round(d.confidence * 100)}%`]]],
      ['Tasks', [
        ['Task weight', `${t.weight_min} – ${t.weight_max}`],
        ['Service time', `uniform ${t.service_min} – ${t.service_max} s`],
        ['Arrival', t.arrival_window ? `over ${t.arrival_window} s` : 'all at t = 0'],
        ['Deadline', `creation + ${t.deadline_factor} × service time`],
        ['Priority levels', t.priority_levels]]],
      ['Workers & contacts', [
        ['Minimum contacts to qualify', d.workers.min_contacts],
        ['Contact process', s.contact_mode === 'trace' ? 'replay observed trace' : 'Exp(λ) sampling'],
        ['Requester', s.requester_id || 'busiest node'],
        ['Tasks handed over per contact', s.tasks_per_contact],
        ['Simulation length', s.duration ? `${s.duration} s` : 'full trace span']]],
      ['Reliability', [
        ['Standard deviation', r.std],
        ['Range', `${r.minimum} – ${r.maximum}`],
        ['Minority case', `${Math.round(r.unreliable_fraction * 100)}% at ${r.unreliable_mean}, rest at ${r.reliable_mean}`]]],
      ['WRS estimator', [
        ['Bayesian prior', `α = ${w.alpha}, β = ${w.beta} (cold start ${(w.alpha / (w.alpha + w.beta)).toFixed(2)})`],
        ['Estimation noise', w.noise_level],
        ['WRS floor', w.floor],
        ['Pre-seeded history', `${s.cold_start_history} observations`]]],
      ['Task outcomes', [
        ['Success probability', o.difficulty_exponent === 1 ? 'true reliability' : `reliability^${o.difficulty_exponent}`],
        ['Overrun', `Gamma, shape ${o.delay_shape}, scale ${o.delay_scale} × (1 − reliability)`],
        ['Failed attempt costs', `${o.partial_effort} × service time`],
        ['Failed tasks', o.rework_on_failure ? `rescheduled, up to ${o.max_attempts} attempts` : 'not rescheduled'],
        ['Unfinished-task penalty', `${s.unassigned_penalty_factor} × horizon`]]],
      ['Algorithms', [
        ['RWTS objective', 'CMS'],
        ['RWTS-M exponent γ', 1]]]
    ];
    const box = UI.clear(UI.$('#cfg-fixed'));
    const grid = UI.el('div', { class: 'grid cols-2' });
    groups.forEach(([title, rows]) => {
      const dl = UI.el('dl', { class: 'kv' });
      rows.forEach(([k, v]) => dl.append(UI.el('dt', {}, k), UI.el('dd', {}, String(v))));
      grid.appendChild(UI.el('div', {}, UI.el('h3', {}, title), dl));
    });
    box.appendChild(grid);
  }

  /* ------------------------------ config ------------------------------- */
  function num(id, fallback) { return UI.val(id, fallback); }

  function buildConfig() {
    const d = state.defaults;
    const algorithms = state.options.algorithms
      .filter(a => UI.val('algo-' + a.name, false)).map(a => a.name);
    const nWorkers = num('cfg-n-workers', null);
    return {
      dataset_id: App.state.datasetId,
      name: `Experiment on ${App.state.datasetMeta?.original_filename || 'dataset'}`,
      repetitions: Math.max(1, Math.round(num('cfg-repetitions', d.repetitions))),
      algorithms,
      workers: nWorkers && nWorkers > 0
        ? { mode: 'top_n', count: Math.round(nWorkers) }
        : { mode: 'all' },
      tasks: { n_tasks: Math.max(1, Math.round(num('cfg-n-tasks', d.tasks.n_tasks))) },
      reliability: {
        distribution: UI.val('cfg-rel-distribution', d.reliability.distribution),
        mean: num('cfg-rel-mean', d.reliability.mean)
      },
      wrs: {
        completion_weight: num('cfg-wrs-completion', d.wrs.completion_weight),
        delay_weight: num('cfg-wrs-delay', d.wrs.delay_weight),
        rework_weight: num('cfg-wrs-rework', d.wrs.rework_weight)
      },
      simulation: { seed: Math.round(num('cfg-seed', d.simulation.seed)) }
    };
  }

  function validate(cfg) {
    const m = cfg.reliability.mean;
    if (!(m >= 0 && m <= 1)) return 'Mean reliability must be between 0 and 1';
    const ws = [cfg.wrs.completion_weight, cfg.wrs.delay_weight, cfg.wrs.rework_weight];
    if (ws.some(x => !(x >= 0))) return 'WRS weights cannot be negative';
    if (ws.reduce((a, b) => a + b, 0) <= 0) return 'At least one WRS weight must be above 0';
    if (!cfg.algorithms.length) return 'Select at least one algorithm';
    return null;
  }

  async function run() {
    if (!App.state.datasetId) { UI.toast('Prepare a dataset first', 'warn'); return; }
    if (!App.state.datasetMeta?.prepared) { UI.toast('Dataset is not prepared yet', 'warn'); return; }
    const cfg = buildConfig();
    const err = validate(cfg);
    if (err) { UI.toast(err, 'warn'); return; }
    try {
      const rec = await API.createExp(cfg);
      state.currentId = rec.experiment_id;
      state.log = [];
      await API.runExp(rec.experiment_id);
      UI.toast(`${rec.experiment_id} started`, 'ok');
      App.go('progress');
      startPolling(rec.experiment_id, cfg);
    } catch (e) { UI.toast('Could not start: ' + e.message, 'bad'); }
  }

  function startPolling(id, cfg) {
    clearInterval(state.poll);
    UI.$('#prog-title').textContent = id;
    UI.$('#prog-subtitle').textContent =
      `${cfg.algorithms.length} algorithms × ${cfg.repetitions} repetitions`;
    const bars = UI.clear(UI.$('#prog-bars'));
    cfg.algorithms.forEach(a => {
      bars.appendChild(UI.el('div', { class: 'progress-row' },
        UI.el('span', {}, a),
        UI.el('div', { class: 'progress' }, UI.el('i', { id: 'bar-' + a })),
        UI.el('span', { class: 'mono', id: 'pct-' + a }, '0%')));
    });
    const tick = async () => {
      try {
        const s = await API.expStatus(id);
        const badge = UI.$('#prog-status');
        badge.textContent = s.status;
        badge.className = 'badge ' + ({ running: 'brand', completed: 'ok',
          failed: 'bad', cancelled: 'warn' }[s.status] || '');
        UI.$('#prog-message').textContent = s.message || '';
        Object.entries(s.per_algorithm || {}).forEach(([a, v]) => {
          const bar = document.getElementById('bar-' + a);
          if (bar) bar.style.width = (v * 100).toFixed(1) + '%';
          const p = document.getElementById('pct-' + a);
          if (p) p.textContent = (v * 100).toFixed(0) + '%';
        });
        UI.clear(UI.$('#prog-stats')).append(
          UI.stat('Overall', UI.pct(s.progress || 0, 1)),
          UI.stat('Condition', s.condition || '—'),
          UI.stat('Started', (s.started_at || '—').replace('T', ' ').replace('+00:00', '')),
          UI.stat('Updated', (s.updated_at || '—').replace('T', ' ').replace('+00:00', '')));
        const line = `[${new Date().toLocaleTimeString()}] ${s.status} ${(100 * (s.progress || 0)).toFixed(1)}% — ${s.message || ''}`;
        if (state.log[state.log.length - 1] !== line) {
          state.log.push(line);
          UI.$('#prog-log').textContent = state.log.slice(-200).join('\n');
        }
        if (['completed', 'failed', 'cancelled'].includes(s.status)) {
          clearInterval(state.poll);
          if (s.status === 'completed') {
            UI.toast(`${id} finished`, 'ok');
            await App.refreshHistory();
            Results.load(id);
            App.go('results');
          } else UI.toast(`${id}: ${s.status} — ${s.message || ''}`, 'bad');
        }
      } catch (e) { /* keep polling */ }
    };
    tick();
    state.poll = setInterval(tick, 700);
  }

  return { init, state, buildConfig };
})();
