# RWTS - Reliability-Weighted Task Scheduling
### Research simulation platform · CS427 project

A local web application for evaluating **Reliability-Weighted Task Scheduling (RWTS)**
against the reliability-agnostic **LUCF** / **LRSTF** baselines of Zhang et al. (2025)
and an **Oracle** benchmark, on real mobile-social-network contact traces.

```
Excel dataset → import → mapping → cleaning → validation → processed dataset
   → contact parameters (λ) → synthetic reliability → tasks → scheduling
   → discrete-event simulation → metrics → comparison → charts → export
```

---

## Quick start

**Windows**

```
start.bat
```

**macOS / Linux**

```
./start.sh
```

Either script creates a virtual environment, installs the dependencies and serves
the application at <http://127.0.0.1:8000>. The browser opens **by itself once the
server is actually listening** — on the very first run the dependency install takes
one to three minutes, so give it a moment. Leave the console window open while you
work; closing it stops the server. The dashboard and the REST API are on the same
origin, so nothing else needs to run.

Manual equivalent:

```
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
python run.py
```

Requires Python 3.11+.

### If the browser says ERR_CONNECTION_REFUSED

The page was opened before the server finished starting, or the server is not
running. In order:

1. **Is the console window still open?** `start.bat` must stay running. If it
   closed instantly, run it from a Command Prompt so you can read the error:
   `cd Desktop\CS427\Application` then `start.bat`.
2. **First run?** Dependency installation takes one to three minutes. Wait for the
   line `RWTS platform ready at http://127.0.0.1:8000`, then refresh the browser.
3. **Is Python installed and on PATH?** `python --version` in a Command Prompt
   should print 3.11 or newer. If it opens the Microsoft Store instead, install
   Python from <https://www.python.org/downloads/> with *Add python.exe to PATH*
   ticked.
4. **Port 8000 already taken?** The launcher moves to the next free port and prints
   it — use the URL the console shows. To force one: `set RWTS_PORT=8010` then
   `start.bat`.
5. **Corporate proxy interfering?** Make sure the browser is not routing localhost
   through a proxy (Windows → Settings → Network → Proxy → *Don't use the proxy
   server for local addresses*).
6. **`pip install` blocked?** On a restricted network, install once with your
   institution's index, e.g.
   `backend\.venv\Scripts\python -m pip install -r backend\requirements.txt --proxy http://your.proxy:port`.

Nothing is sent anywhere: the server binds to `127.0.0.1` only and is reachable
solely from your own computer.

---

## The five-minute walkthrough

1. **Dataset** → *Load bundled sample* → `contacts.Exp1.xls`
   (the Cambridge Haggle Experiment 1 trace shipped in `sample_data/`), or drag in
   your own workbook.
2. Check the **workbook inspection** panel, then the **column mapping** — the
   CRAWDAD/Haggle layout is recognised automatically, and every row can be changed.
3. Adjust the **cleaning rules** if needed and press **Prepare Dataset**.
4. **Transformation** shows the record count at every stage and the validation report.
5. **Experiment** → set the number of workers and tasks, repetitions, seed, the
   synthetic reliability distribution (and mean) and the three WRS weights; tick the
   algorithms; press **Run Experiment**. Everything else is held fixed and listed
   under **Fixed settings** on the same page.
6. **Simulation** shows live per-algorithm progress; the app jumps to **Results**
   when the run finishes.
7. **Results**, **Worker Reliability**, **WRS Analysis** and **Algorithm Comparison**
   present the analysis; **Export** produces CSV, Excel, JSON,
   PNG, PDF and a full ZIP bundle.

---

## Layout

```
Application/
├── backend/
│   ├── app/
│   │   ├── main.py                 FastAPI app; also serves the dashboard
│   │   ├── config.py               storage paths and upload limits
│   │   ├── api/                    dataset / experiment / result routes
│   │   ├── data/                   excel_reader, mapper, validator,
│   │   │                           transformer, dataset_manager
│   │   ├── models/                 contact, task, worker (canonical models)
│   │   ├── reliability/            wrs, bayesian, distributions
│   │   ├── algorithms/             base, lucf, lrstf, rwts, oracle, registry
│   │   ├── simulation/             engine, events, contact_model,
│   │   │                           task_model, outcome_model
│   │   ├── evaluation/             metrics, statistics, comparison
│   │   └── experiments/            runner, configuration, reproducibility, export
│   ├── tests/                      68 tests
│   ├── storage/                    raw / processed / experiments / exports
│   ├── requirements.txt
│   └── run.py
├── frontend/                       index.html, css/, js/, assets/ (Chart.js vendored)
├── sample_data/                    the supplied Haggle Exp1 files
├── ASSUMPTIONS.md                  every choice the proposal does not fix
├── start.bat / start.sh
└── README.md
```

All research logic is Python. The frontend never implements a scheduling rule or a
statistic — it renders what the API returns.

---

## Data handling

**The supplied files are not really Excel.** `contacts.Exp1.xls`, `table.Exp1.xls`
and `MAC3Btable.Exp1.xls` are tab-separated text with an `.xls` extension and no
header row — the standard CRAWDAD / Cambridge Haggle format. The reader inspects
file *content*, never the declared extension, and handles:

* OOXML workbooks (`.xlsx`, `.xlsm`) via openpyxl, `data_only=True`, macros never run
* legacy BIFF workbooks (`.xls`) via xlrd
* delimited text with a sniffed delimiter, generating `col_1 … col_n` when there is
  no header row

`contacts.Exp1` columns, as mapped by default:

| Column  | Meaning                                    | Canonical field      |
|---------|--------------------------------------------|----------------------|
| `col_1` | observing iMote id (1 = stationary kitchen node) | `source_worker` |
| `col_2` | peer device id (2–9 mobile, 10–128 external)     | `destination_worker` |
| `col_3` | contact start time (seconds)               | `timestamp`          |
| `col_4` | contact end time (seconds)                 | `end_time`           |
| `col_5` | sequence number of this pair's contact     | — (unused)           |
| `col_6` | inter-contact gap since the pair's previous contact | — (unused)  |

Contact duration is derived as `end_time − timestamp`. λ<sub>j</sub> is estimated as
contacts<sub>j</sub> ÷ observation period.

The raw upload is stored untouched under `storage/raw/`; the processed dataset is
written separately to `storage/processed/<id>/` and can be exported for
reproducibility.

### Where working files live

By default: `backend/storage/`.

**Exception — cloud-synced folders.** If the application sits inside OneDrive,
Dropbox or Google Drive, the sync client holds transient locks on files the
simulator rewrites several times a second, which produces
`[WinError 5] Access is denied` mid-experiment; it would also upload every
intermediate result. The app detects this and stores working files locally
instead:

| Platform | Location |
|---|---|
| Windows | `%LOCALAPPDATA%\RWTS\storage` |
| macOS | `~/Library/Application Support/RWTS/storage` |
| Linux | `~/.local/share/RWTS/storage` |

Anything already produced in `backend/storage/` is copied across once. The Home
page and the startup console both state the location in use. Override it with:

```
set RWTS_STORAGE=D:\rwts-storage
start.bat
```

Independently of this, every write retries the rename with backoff and falls back
to an in-place write, so a slow scanner or sync client can no longer abort a run.

---

## Methodological separation

| Layer | Origin | Visible to |
|---|---|---|
| Contacts, timestamps, λ | uploaded dataset — **REAL** | every algorithm |
| True worker reliability, task success/failure, delay, rework | generated — **SYNTHETIC** | the simulator, and the Oracle only |
| Worker Reliability Score | estimated from observed outcomes | RWTS-M and RWTS-ER only |

This is enforced in code: the engine builds a `WorkerView` per scheduler whose
`reliability` field is `None` for LUCF/LRSTF, the WRS for RWTS, and the hidden truth
for the Oracle. A reliability-aware scheduler handed a blind view raises rather than
silently falling back — there is a test for it.

---

## Fair comparison

Per repetition the runner builds **one** scenario — workers, hidden reliability,
tasks, contact events, seed — and replays it for every selected algorithm. Task
outcomes are drawn from a stream keyed by `(seed, task_id, attempt)`, so the same
task on the same attempt meets the same random draw whichever scheduler placed it.
That is what makes the paired t-test and Wilcoxon test on the Results page valid.

---

## Testing

```
cd backend
python -m pytest tests -q
```

68 tests cover format detection, mapping suggestions, validation rules, the
transformation funnel, λ estimation, WRS convergence and cold start, every
distribution, the knowledge separation, the O(nm) greedy bound, scenario
determinism, the task lifecycle, metric consistency, the runner's fairness and
sweeps (backend only), and the whole REST surface.

---

## References

Zhang, J., Yi, L., Gao, X., Bhatti, S. S., Yuan, T., & Chen, G. (2025). Task
scheduling mechanism for crowdsourcing in mobile social networks. *IEEE Transactions
on Mobile Computing, 24*(9), 8714–8728.

Chen, C.-Y. (2026). Approximation algorithms for scheduling crowdsourcing tasks in
mobile social networks. *IEEE Transactions on Mobile Computing, 25*(5), 7308–7322.
