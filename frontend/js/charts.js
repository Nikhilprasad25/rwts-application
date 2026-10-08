/* Chart.js wrappers. Palette is theme-aware and consistent across the app. */
const Charts = (() => {
  const registry = {};
  const ALGO_COLORS = {
    'LUCF':    '#94a3b8',
    'LRSTF':   '#64748b',
    'RWTS-M':  '#2563eb',
    'RWTS-ER': '#0ea5e9',
    'Oracle':  '#16a34a'
  };
  const SERIES = ['#2563eb', '#0ea5e9', '#7c3aed', '#16a34a', '#d97706',
                  '#dc2626', '#0891b2', '#64748b'];

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function baseOptions(extra = {}) {
    const grid = css('--border') || '#e2e8f0';
    const text = css('--muted') || '#64748b';
    return Object.assign({
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: false },
      plugins: {
        legend: { labels: { color: text, boxWidth: 12, font: { size: 11 } } },
        tooltip: { backgroundColor: 'rgba(15,23,42,.92)', padding: 10, cornerRadius: 6 }
      },
      scales: {
        x: { grid: { color: grid, drawBorder: false }, ticks: { color: text, font: { size: 11 } } },
        y: { grid: { color: grid, drawBorder: false }, ticks: { color: text, font: { size: 11 } },
             beginAtZero: true }
      }
    }, extra);
  }
  function color(algo, i) { return ALGO_COLORS[algo] || SERIES[i % SERIES.length]; }

  function render(id, config) {
    const canvas = document.getElementById(id);
    if (!canvas) return null;
    if (registry[id]) registry[id].destroy();
    registry[id] = new Chart(canvas.getContext('2d'), config);
    return registry[id];
  }

  /* ---- specific chart builders ---------------------------------------- */
  function algoBar(id, algos, means, errs, label) {
    // 95% CI drawn as a thin overlay bar via a custom plugin-free approach:
    // an extra scatter dataset marking the interval endpoints.
    const points = [];
    algos.forEach((a, i) => {
      if (errs && errs[i]) {
        points.push({ x: a, y: means[i] - errs[i] });
        points.push({ x: a, y: means[i] + errs[i] });
      }
    });
    return render(id, {
      type: 'bar',
      data: {
        labels: algos,
        datasets: [
          { label, data: means, backgroundColor: algos.map(color), borderRadius: 5,
            maxBarThickness: 68 },
          { type: 'scatter', label: '95% CI', data: points,
            backgroundColor: css('--text') || '#0f172a', pointRadius: 3,
            pointStyle: 'line', rotation: 90, showLine: false }
        ]
      },
      options: baseOptions()
    });
  }

  function groupedBar(id, labels, series) {
    return render(id, {
      type: 'bar',
      data: {
        labels,
        datasets: series.map((s, i) => ({
          label: s.label, data: s.data,
          backgroundColor: color(s.label, i), borderRadius: 4, maxBarThickness: 42
        }))
      },
      options: baseOptions()
    });
  }

  function lines(id, labels, series, xTitle, yTitle) {
    const opts = baseOptions();
    opts.scales.x.title = { display: !!xTitle, text: xTitle, color: css('--muted') };
    opts.scales.y.title = { display: !!yTitle, text: yTitle, color: css('--muted') };
    return render(id, {
      type: 'line',
      data: {
        labels,
        datasets: series.map((s, i) => ({
          label: s.label, data: s.data, borderColor: color(s.label, i),
          backgroundColor: color(s.label, i) + '22', tension: .25,
          pointRadius: s.data.length > 40 ? 0 : 2.5, borderWidth: 2, fill: false,
          spanGaps: true
        }))
      },
      options: opts
    });
  }

  function scatter(id, datasets, xTitle, yTitle, extra = {}) {
    const opts = baseOptions();
    opts.scales.x.title = { display: true, text: xTitle, color: css('--muted') };
    opts.scales.y.title = { display: true, text: yTitle, color: css('--muted') };
    Object.assign(opts.scales.x, extra.x || {});
    Object.assign(opts.scales.y, extra.y || {});
    return render(id, {
      type: 'scatter',
      data: {
        datasets: datasets.map((d, i) => ({
          label: d.label, data: d.data,
          backgroundColor: d.color || color(d.label, i),
          borderColor: d.color || color(d.label, i),
          pointRadius: d.pointRadius ?? 4, showLine: !!d.showLine,
          borderWidth: d.showLine ? 2 : 0, borderDash: d.dash || []
        }))
      },
      options: opts
    });
  }

  function histogram(id, values, bins, label) {
    const n = bins || 12;
    const lo = Math.min(...values), hi = Math.max(...values);
    const width = (hi - lo) / n || 1;
    const counts = new Array(n).fill(0);
    values.forEach(v => {
      let k = Math.floor((v - lo) / width);
      if (k >= n) k = n - 1; if (k < 0) k = 0;
      counts[k]++;
    });
    const labels = counts.map((_, i) => (lo + i * width).toFixed(2));
    return render(id, {
      type: 'bar',
      data: { labels, datasets: [{ label, data: counts, backgroundColor: '#7c3aed',
              borderRadius: 3 }] },
      options: baseOptions()
    });
  }

  return { render, algoBar, groupedBar, lines, scatter, histogram, color, ALGO_COLORS };
})();
