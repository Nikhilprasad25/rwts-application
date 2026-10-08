# Implementation assumptions

The proposal fixes the research design; it does not fix every implementation
detail. Everything below is a choice made in this application, and each should be
reported as an assumption rather than as part of the published methodology.

**What the interface lets you change.** Only: number of workers, number of tasks,
repetitions, random seed, reliability distribution (normal / uniform / skewed /
minority-unreliable) and its mean, the three WRS weights, and which algorithms run.
Every other value below is held at the stated default and shown read-only under
*Fixed settings* on the Experiment page. The backend still accepts the full
configuration through its API, so these values can be changed in code if needed.
Sensitivity sweeps exist in the backend but are not exposed in the interface.

---

## 1. Contact process

**λ estimation.** λ<sub>j</sub> = contacts<sub>j</sub> ÷ observation period — the
maximum-likelihood rate of a homogeneous Poisson contact process, consistent with the
exponential inter-meeting model of Zhang et al. (2025).
A node needs at least 2 contacts to qualify as a worker (fixed).

**Requester.** The CMS/TMS framework has one requester who must meet a worker before
a task can be handed over. The trace does not label a requester, so by default the
node with the most contacts is used, and it is removed from the worker pool.
(Fixed.)

**Contact mode.** `trace` replays the observed encounters; `exponential` samples
inter-meeting times from Exp(λ<sub>j</sub>) estimated from the same trace.
Trace mode is the default because it preserves burstiness and diurnal structure that
the analytical model discards.

**Hand-over granularity.** One task is handed over per encounter, and a worker serves
one task at a time (fixed).

---

## 2. Scheduling

**Expected occupancy.** A task *i* placed on worker *j* is assumed to occupy

&nbsp;&nbsp;&nbsp;&nbsp;p<sub>ij</sub> = 1/λ<sub>j</sub> + τ<sub>i</sub>

the expected wait for a hand-over encounter plus the service time. This is the
quantity LUCF and LRSTF balance across workers.

**LUCF.** Tasks are ordered by decreasing unit cost w<sub>i</sub>/τ<sub>i</sub> and each is
placed on the worker minimising w<sub>i</sub>·(A<sub>j</sub> + p<sub>ij</sub>), where A<sub>j</sub> is
the worker's projected available time.

**LRSTF.** Tasks are ordered by decreasing τ<sub>i</sub> and each is placed on the worker
minimising A<sub>j</sub> + p<sub>ij</sub> — standard list scheduling for the makespan objective.

**RWTS-Multiplicative.** The proposal gives the reliability-adjusted unit cost
(w<sub>i</sub>/τ<sub>i</sub>)·g(WRS<sub>j</sub>) but not the placement rule. Implemented as

&nbsp;&nbsp;&nbsp;&nbsp;score<sub>ij</sub> = w<sub>i</sub>·(A<sub>j</sub> + p<sub>ij</sub>) ÷ g(WRS<sub>j</sub>),&nbsp;&nbsp; g(x) = x<sup>γ</sup>

with γ fixed at 1.0 (γ = 0 would recover LUCF; larger γ penalises unreliable
workers harder). RWTS-M and RWTS-ER both use the CMS objective.

**RWTS-Expected-Rework.** p<sub>ij</sub> = (1/λ<sub>j</sub> + τ<sub>i</sub>) ÷ WRS<sub>j</sub>, the
expected total occupancy under geometric retries with success probability WRS<sub>j</sub>.

**Oracle.** Identical to RWTS-Expected-Rework but reads the hidden true reliability.
It is a benchmark, not a deployable scheduler — and specifically an *information*
benchmark, not a proven optimum: it is the same greedy heuristic with perfect
knowledge. An empirical approximation ratio below 1 is therefore possible, and when
it happens it says the binding constraint was the heuristic form rather than the
quality of the WRS estimate. A genuine lower bound on CMS/TMS would need the
optimal offline solution, which is outside the proposal's scope.

**Complexity.** Every scheduler is a greedy list-scheduling pass: O(n·m) for n tasks
and m workers, matching the original LUCF/LRSTF bound. A test asserts the exact
number of score evaluations.

**Rescheduling.** A failed task is re-placed online with the same rule, using the
current time and the workers' current projected loads and current WRS.

---

## 3. Worker Reliability Score

&nbsp;&nbsp;&nbsp;&nbsp;WRS = w<sub>c</sub>·completion + w<sub>d</sub>·delay + w<sub>r</sub>·rework,&nbsp;&nbsp; w<sub>c</sub>+w<sub>d</sub>+w<sub>r</sub> = 1

Weights are renormalised to sum to 1 whatever is entered.

* **completion** — Beta–Binomial posterior mean (α + successes)/(α + β + attempts)
* **rework** — the same posterior form on rework-free attempts
* **delay** — per attempt, an on-time score 1/(1 + overrun) ∈ (0, 1]; the mean is
  shrunk toward the prior mean with prior weight α + β

The neutral cold-start value is therefore α/(α + β), which is 0.5 for the default
α = β = 2. An asymmetric prior shifts it deliberately.

**Noise.** `noise_level` adds N(0, σ) to the *reported* score only, clipped to
[0, 1]; the noise-free estimate is kept for the convergence analysis, so the WRS
Analysis page can separate estimator error from injected noise.

**Floor.** The reported WRS is floored at 0.05 by default so the expected-rework
division stays bounded.

**Cold-start seeding.** `cold_start_history = k` gives each worker k synthetic prior
observations drawn from its own hidden reliability. k = 0 means the scheduler starts
from the neutral prior alone.

---

## 4. Task outcomes

* success probability = true_reliability<sup>difficulty_exponent</sup> (default exponent 1)
* service overrun ~ Gamma(shape, scale) with mean `delay_scale·(1 − reliability)`, so
  unreliable workers are also slower — this is what the delay component of the WRS
  is meant to pick up
* a failed attempt consumes `partial_effort × τ` before the failure is discovered
  (default 1.0: the full attempt is wasted)
* after `max_attempts` (default 5) a task is abandoned

None of this is specified by the proposal; it is the minimal probabilistic outcome
layer needed to make rework meaningful.

---

## 5. Metrics

* **CMS** — realised total weighted completion time Σ w<sub>i</sub>C<sub>i</sub>
* **TMS** — realised maximum completion time max C<sub>i</sub>
* **Total cost** — realised weighted service effort Σ w<sub>i</sub>·(service time consumed)
* **Rework rate** — share of tasks sent back at least once
  (**reworks per task** is reported separately)
* **Failure rate** — failed attempts ÷ total attempts
* **Approximation ratio** — algorithm metric ÷ Oracle metric, per repetition, then
  averaged with a 95% CI

**Unfinished tasks.** A task still open at the horizon is charged

&nbsp;&nbsp;&nbsp;&nbsp;C<sub>i</sub> = factor·horizon + τ<sub>i</sub>·(1 + reworks<sub>i</sub>)

so CMS and TMS stay finite, and TMS does not collapse to an exact tie between any two
algorithms that each leave one task open. `factor` is fixed at 1.0.
For a clean read on TMS, size the task count so all algorithms finish inside the
horizon — the completion-rate row on the Results page tells you whether they did.

**Confidence intervals** are Student-t at 95% over
repetitions. Every individual run is stored in `raw_runs.csv`, not only the aggregate.

**Significance tests** are paired (t-test and Wilcoxon) across repetitions, which is
valid precisely because of the common random numbers described in the README.

---

## 6. Defaults

| Setting | Default | Note |
|---|---|---|
| Repetitions | 30 | the proposal's stochastic evaluation needs this or more |
| Tasks | 100 | set the task/worker ratio deliberately |
| Deadline factor | 100 × τ | contact waiting dominates service time in MSN traces; a small factor makes every task late and the deadline metric uninformative |
| Service time | uniform 300–1800 s | the Haggle traces are in seconds |
| Reliability | normal, mean 0.75, sd 0.15 | sweep the distribution rather than trusting one shape |
| Max attempts | 5 | |
| Seed | 12345 | repetition *r* uses seed + r |
