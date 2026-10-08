/* Application shell: navigation, home dashboard, transformation view, history. */
const App = (() => {
  const state = { datasetId: null, datasetMeta: null, datasets: [], experiments: [],
                  workerParameters: [] };

  function go(page) {
    document.querySelectorAll('.page').forEach(p =>
      p.classList.toggle('active', p.id === 'page-' + page));
    document.querySelectorAll('#nav button').forEach(b =>
      b.classList.toggle('active', b.dataset.page === page));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function refreshHome() {
    const h = await API.home();
    UI.clear(UI.$('#home-stats')).append(
      UI.stat('Dataset status', h.dataset_status,
              h.active_dataset ? h.active_dataset.original_filename : 'no dataset yet'),
      UI.stat('Workers', h.dataset_summary ? UI.int(h.dataset_summary.workers) : '—'),
      UI.stat('Contacts', h.dataset_summary ? UI.int(h.dataset_summary.contacts) : '—'),
      UI.stat('Experiments', UI.int(h.n_experiments),
              h.best_algorithm ? `best (CMS): ${h.best_algorithm}` : ''));

    const notices = UI.clear(UI.$('#home-notices'));
    if (h.storage_notice) {
      notices.appendChild(UI.el('div', { class: 'note', style: 'margin-bottom:16px' },
        h.storage_notice));
    }

    const box = UI.clear(UI.$('#home-dataset'));
    if (h.active_dataset) {
      const d = h.active_dataset;
      box.appendChild(UI.el('dl', { class: 'kv' },
        UI.el('dt', {}, 'File'), UI.el('dd', {}, d.original_filename),
        UI.el('dt', {}, 'Uploaded'), UI.el('dd', {}, (d.uploaded_at || '').replace('T', ' ')),
        UI.el('dt', {}, 'Sheets'), UI.el('dd', {}, (d.sheet_names || []).join(', ')),
        UI.el('dt', {}, 'Rows'), UI.el('dd', {}, UI.int(d.rows)),
        UI.el('dt', {}, 'Prepared'), UI.el('dd', {}, d.prepared ? 'yes' : 'no')));
      if (!state.datasetId && d.prepared) {
        state.datasetId = d.dataset_id;
        state.datasetMeta = await API.dataset(d.dataset_id);
      }
    } else {
      box.appendChild(UI.el('div', { class: 'empty' }, 'No dataset loaded yet.'));
    }

    const last = UI.clear(UI.$('#home-last'));
    if (h.last_experiment) {
      const e = h.last_experiment;
      last.appendChild(UI.el('dl', { class: 'kv' },
        UI.el('dt', {}, 'ID'), UI.el('dd', {}, e.experiment_id),
        UI.el('dt', {}, 'Status'), UI.el('dd', {}, e.status),
        UI.el('dt', {}, 'Algorithms'), UI.el('dd', {}, (e.algorithms || []).join(', ')),
        UI.el('dt', {}, 'Tasks'), UI.el('dd', {}, UI.int(e.tasks)),
        UI.el('dt', {}, 'Repetitions'), UI.el('dd', {}, UI.int(e.repetitions)),
        UI.el('dt', {}, 'Best (CMS)'), UI.el('dd', {}, e.best_algorithm || '—')));
      last.appendChild(UI.el('button', { class: 'btn primary sm', style: 'margin-top:10px',
        onclick: () => { go('results'); Results.load(e.experiment_id); } }, 'Open results'));
    } else last.appendChild(UI.el('div', { class: 'empty' }, 'No experiments run yet.'));
  }

  function renderHomeStepper(reached) {
    const steps = ['Dataset', 'Mapping', 'Preparation', 'Configuration', 'Simulation', 'Analysis'];
    const done = state.datasetMeta?.prepared ? 3 : Math.min(reached, 2);
    const box = UI.clear(UI.$('#home-stepper'));
    steps.forEach((s, i) => box.appendChild(UI.el('div', {
      class: 'step ' + (i < done ? 'done' : i === done ? 'current' : '')
    }, UI.el('i', {}, i < done ? '✓' : String(i + 1)), s)));
  }

  /* ---- transformation page ---- */
  function renderTransform(meta, workerParams) {
    const funnel = meta.funnel || [];
    const box = UI.clear(UI.$('#funnel'));
    funnel.forEach((f, i) => {
      if (i) box.appendChild(UI.el('div', { class: 'funnel-arrow' }));
      box.appendChild(UI.el('div', { class: 'funnel-step' },
        UI.el('div', {}, UI.el('div', { class: 'name' }, f.stage),
          f.note ? UI.el('div', { class: 'note' }, f.note) : null),
        UI.el('div', { class: 'count' }, UI.int(f.rows)),
        UI.el('div', { class: 'delta ' + (f.removed ? '' : 'zero') },
          f.removed ? `−${UI.int(f.removed)}` : '—')));
    });

    const v = meta.validation || {};
    const rep = UI.clear(UI.$('#validation-report'));
    rep.append(UI.el('div', { class: 'grid cols-2' },
      UI.stat('Valid', UI.int(v.valid_rows)),
      UI.stat('Invalid', UI.int(v.invalid_rows)),
      UI.stat('Duplicates', UI.int(v.duplicate_rows)),
      UI.stat('Missing cells',
        UI.int(Object.values(v.missing_values || {}).reduce((a, b) => a + b, 0)))));
    (meta.warnings || []).forEach(w =>
      rep.appendChild(UI.el('div', { class: 'note', style: 'margin-top:10px' }, w)));
    if (v.examples && v.examples.length) {
      rep.appendChild(UI.el('h3', { style: 'margin-top:14px' }, 'Example invalid rows'));
      rep.appendChild(UI.el('div', { class: 'table-wrap table-scroll' }, UI.table(
        [{ label: 'Row', key: '_row', num: true },
         { label: 'Reasons', render: r => (r._reasons || []).join(', ') }],
        v.examples)));
    }

    const wp = workerParams || state.workerParameters || [];
    if (wp.length) {
      const top = wp.slice(0, 30);
      Charts.groupedBar('chart-lambda', top.map(w => w.worker_id),
        [{ label: 'λ × 1000', data: top.map(w => 1000 * (w['lambda'] ?? w.lam)) }]);
      state.workerParameters = wp;
    }
  }

  /* ---- history ---- */
  async function refreshHistory() {
    const { experiments } = await API.experiments();
    state.experiments = experiments;
    UI.clear(UI.$('#history-table')).appendChild(experiments.length ? UI.table([
      { label: 'Experiment', key: 'experiment_id' },
      { label: 'Date', render: e => (e.created_at || '').replace('T', ' ').replace('+00:00', '') },
      { label: 'Dataset', key: 'dataset_id' },
      { label: 'Algorithms', render: e => (e.algorithms || []).join(', ') },
      { label: 'Workers', key: 'workers' },
      { label: 'Tasks', key: 'tasks', num: true },
      { label: 'Reliability', key: 'reliability_distribution' },
      { label: 'Seed', key: 'seed', num: true },
      { label: 'Reps', key: 'repetitions', num: true },
      { label: 'Status', render: e => UI.el('span', {
          class: 'badge ' + ({ completed: 'ok', failed: 'bad', running: 'brand' }[e.status] || '')
        }, e.status) },
      { label: 'Best (CMS)', key: 'best_algorithm' },
      { label: '', render: e => UI.el('button', { class: 'btn sm',
          onclick: () => { go('results'); Results.load(e.experiment_id); } }, 'Open') }
    ], experiments) : UI.el('div', { class: 'empty' }, 'No experiments yet.'));

    ['#results-exp-select', '#export-exp-select'].forEach(sel => {
      const s = UI.clear(UI.$(sel));
      s.appendChild(UI.el('option', { value: '' }, 'Select an experiment…'));
      experiments.filter(e => e.status === 'completed').forEach(e =>
        s.appendChild(UI.el('option', { value: e.experiment_id },
          `${e.experiment_id} · ${(e.created_at || '').slice(0, 16).replace('T', ' ')}`)));
    });
  }

  /* ---- about ---- */
  function renderAbout() {
    const html = `
<div class="card"><h2>What the application implements</h2>
<p>The pipeline follows the CS427 proposal: a Worker Reliability Score built from
completion, delay and rework history with Bayesian shrinkage; two RWTS variants
layered on the LUCF/LRSTF scheduling rules of Zhang et al. (2025); a discrete-event
simulator that adds a probabilistic task-outcome step on top of the real
inter-contact process; and an evaluation against both reliability-agnostic
baselines and an oracle that knows true reliability.</p></div>

<div class="card"><h2>Information separation</h2>
<div class="table-wrap"><table>
<thead><tr><th>Layer</th><th>Source</th><th>Who may read it</th></tr></thead>
<tbody>
<tr><td>Contacts, timestamps, λ</td><td>Uploaded dataset (REAL)</td><td>every algorithm</td></tr>
<tr><td>True worker reliability, outcomes, delay, rework</td><td>Generated (SYNTHETIC)</td><td>simulator, and the Oracle only</td></tr>
<tr><td>Worker Reliability Score</td><td>Estimated from observed outcomes</td><td>RWTS-M and RWTS-ER only</td></tr>
</tbody></table></div></div>

<div class="card"><h2>Assumptions made where the proposal is silent</h2>
<p>These are implementation choices, held fixed in this version (see <em>Fixed settings</em>
on the Experiment page), and should be reported as assumptions rather than as part of
the published methodology.</p>
<ul>
<li><strong>λ estimation.</strong> λ<sub>j</sub> = contacts<sub>j</sub> / observation period, the maximum-likelihood
rate of a homogeneous Poisson contact process.</li>
<li><strong>Expected occupancy.</strong> A task placed on worker <em>j</em> is assumed to occupy
1/λ<sub>j</sub> + τ<sub>i</sub>: the expected wait for a hand-over encounter plus the service time.</li>
<li><strong>RWTS-Multiplicative placement rule.</strong> The proposal gives the adjusted unit cost
(w<sub>i</sub>/τ<sub>i</sub>)·g(WRS<sub>j</sub>); here the weighted completion cost is divided by
g(WRS<sub>j</sub>) = WRS<sub>j</sub><sup>γ</sup>, with γ = 1.</li>
<li><strong>WRS components.</strong> Completion and rework use Beta–Binomial posterior means; the
delay component shrinks a per-task on-time score toward the same prior mean.</li>
<li><strong>Outcome model.</strong> Success probability = true reliability<sup>difficulty</sup>; service
overrun is Gamma-distributed with mean scaling in (1 − reliability); a failed attempt
consumes the full τ before the failure is discovered.</li>
<li><strong>Unfinished tasks.</strong> Tasks still open at the horizon are charged a completion time
of the horizon plus the task's service time, so CMS/TMS stay finite and comparable.</li>
<li><strong>Hand-over granularity.</strong> One task is handed over per encounter and a worker
serves one task at a time.</li>
</ul></div>

<div class="card"><h2>Fair comparison</h2>
<p>Per repetition the platform builds one scenario — workers, hidden reliability,
tasks, contact events and seed — and replays it for every selected algorithm.
Task outcomes are drawn from a stream keyed by (seed, task, attempt), so the same
task on the same attempt faces the same random draw regardless of scheduler:
common random numbers, which is what makes the paired tests on the Results page valid.</p></div>

<div class="card"><h2>Reference</h2>
<p>Zhang, J., Yi, L., Gao, X., Bhatti, S. S., Yuan, T., &amp; Chen, G. (2025).
Task scheduling mechanism for crowdsourcing in mobile social networks.
<em>IEEE Transactions on Mobile Computing, 24</em>(9), 8714–8728.<br>
Chen, C.-Y. (2026). Approximation algorithms for scheduling crowdsourcing tasks in
mobile social networks. <em>IEEE TMC, 25</em>(5), 7308–7322.</p></div>`;
    UI.$('#about-content').innerHTML = html;
  }

  async function init() {
    document.getElementById('nav').addEventListener('click', e => {
      const b = e.target.closest('button'); if (b) go(b.dataset.page);
    });
    document.querySelectorAll('[data-goto]').forEach(b =>
      b.addEventListener('click', () => go(b.dataset.goto)));
    UI.$('#modal-backdrop').addEventListener('click', e => {
      if (e.target.id === 'modal-backdrop') UI.closeModal();
    });
    UI.$('#home-refresh').onclick = () => { refreshHome(); refreshHistory(); };
    UI.$('#btn-reload-history').onclick = refreshHistory;

    renderAbout();
    Results.init();
    await Dataset.init();
    await Experiment.init();
    await refreshHome();
    await refreshHistory();

    if (state.datasetId) {
      try {
        await Dataset.open(state.datasetId);
        if (state.datasetMeta?.prepared) {
          const p = await API.preview(state.datasetId, 100);
          renderTransform(state.datasetMeta, p.worker_parameters);
        }
      } catch (_) {}
    }
    const banner = UI.$('#exp-dataset-banner');
    UI.clear(banner).appendChild(UI.el('div', { class: 'card' },
      UI.el('div', { class: 'row' },
        UI.el('span', { class: 'badge ' + (state.datasetMeta?.prepared ? 'ok' : 'warn') },
          state.datasetMeta?.prepared ? 'Dataset ready' : 'No prepared dataset'),
        UI.el('strong', {}, state.datasetMeta?.original_filename || '—'),
        UI.el('span', { class: 'mono' },
          state.datasetMeta?.summary
            ? `${UI.int(state.datasetMeta.summary.workers)} workers · ${UI.int(state.datasetMeta.summary.contacts)} contacts`
            : ''))));
  }

  return { init, go, state, refreshHome, refreshHistory, renderTransform,
           renderHomeStepper };
})();

document.addEventListener('DOMContentLoaded', () => App.init().catch(e => {
  console.error(e); UI.toast('Startup error: ' + e.message, 'bad');
}));
