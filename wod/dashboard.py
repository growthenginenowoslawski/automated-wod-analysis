"""A self-contained HTML dashboard built from the local database (no internet, no accounts)."""
import json
from pathlib import Path

from .db import query


def _rows(con, sql, params=()):
    cols, rows = query(con, sql, params)
    return [dict(zip(cols, r)) for r in rows]


def build(con, out_path):
    data = {
        "workouts": _rows(con, """SELECT id, date, name, format, score, rounds_complete, total_reps, elapsed_s, moving_s,
                                   between_pct, notes FROM workouts ORDER BY date"""),
        "movements": _rows(con, "SELECT * FROM v_movement_summary ORDER BY total_reps DESC"),
        "fresh": _rows(con, """SELECT f.movement_key, m.name AS movement, f.date, f.time_for_10_s, f.estimated, f.reps_per_sec
                               FROM fresh_benchmarks f JOIN movements m ON m.key = f.movement_key ORDER BY f.date"""),
        "blocks": _rows(con, """SELECT workout_id, round, movement_name, duration_s, transition_after_s, reps, sets,
                                sec_per_rep FROM blocks ORDER BY workout_id, seq"""),
        "transitions": _rows(con, "SELECT * FROM v_transitions ORDER BY avg_s DESC"),
        "fatigue": _rows(con, "SELECT * FROM v_fatigue ORDER BY date DESC"),
    }
    html = TEMPLATE.replace("__DATA__", json.dumps(data, default=str).replace("</", "<\\/"))
    Path(out_path).write_text(html)
    return Path(out_path)


TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WOD Log</title>
<style>
  :root { --bg:#f7f8f6; --panel:#ffffff; --fg:#1d2420; --muted:#66706a; --line:#dfe4e0; --accent:#2f6f5e;
          --s1:#2f6f5e; --s2:#c46a2b; --s3:#4a63b8; --s4:#a8475f; --s5:#7a8c2e; --gap:#c9cfca; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  main { max-width:1100px; margin:0 auto; padding:24px max(16px, env(safe-area-inset-left)); display:grid; gap:20px; }
  h1 { font-size:28px; margin:0; letter-spacing:-.01em; }
  h2 { font-size:16px; margin:0 0 4px; }
  .sub { color:var(--muted); margin:4px 0 0; }
  .note { color:var(--muted); font-size:13px; margin:0 0 12px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:18px; min-width:0; }
  .tiles { display:grid; gap:12px; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); }
  .tile .k { color:var(--muted); font-size:13px; } .tile .v { font-size:26px; margin-top:4px; font-variant-numeric:tabular-nums; }
  .grid2 { display:grid; gap:20px; grid-template-columns:repeat(auto-fit, minmax(min(100%, 460px), 1fr)); }
  table { width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; font-size:14px; }
  th { text-align:left; color:var(--muted); font-weight:500; font-size:12px; border-bottom:1px solid var(--line); padding:6px 8px; white-space:nowrap; }
  td { border-bottom:1px solid var(--line); padding:6px 8px; } td.n, th.n { text-align:right; }
  .wrap { overflow-x:auto; }
  .legend { display:flex; flex-wrap:wrap; gap:6px 14px; font-size:12px; color:var(--muted); margin-bottom:8px; }
  .legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; vertical-align:-1px; }
  svg text { fill:var(--muted); font-size:11px; }
  select { font:inherit; padding:4px 6px; border:1px solid var(--line); border-radius:6px; background:var(--panel); }
  .pill { display:inline-block; padding:1px 7px; border-radius:99px; background:#eef3f0; color:var(--accent); font-size:12px; }
</style></head><body><main>
<header><h1>WOD Log</h1><p class="sub" id="headline"></p></header>
<section class="tiles" id="tiles"></section>

<section class="card">
  <h2>Fresh speed by movement</h2>
  <p class="note">Fresh 10 = how long 10 reps take in round 1, before fatigue (estimated when round 1 had fewer than 10). Reps/sec is the average across every round.</p>
  <div class="wrap"><table id="moves"></table></div>
</section>

<section class="card">
  <h2>Where the time went</h2>
  <p class="note">Colored bars are movements, grey is time between them. <select id="pick" aria-label="Workout"></select></p>
  <div class="legend" id="legend"></div><div id="rounds"></div>
</section>

<div class="grid2">
  <section class="card"><h2>Fresh 10 over time</h2><p class="note">Lower is faster. One point per workout that included the movement.</p>
    <div class="legend" id="flegend"></div><div id="freshchart"></div></section>
  <section class="card"><h2>Time between movements</h2><p class="note">Share of first rep to last rep spent in transitions and rest.</p>
    <div id="between"></div></section>
</div>

<div class="grid2">
  <section class="card"><h2>Slowest transitions</h2><div class="wrap"><table id="trans"></table></div></section>
  <section class="card"><h2>Pace from first to last round</h2><p class="note">Negative means you slowed down.</p><div class="wrap"><table id="fatigue"></table></div></section>
</div>

<section class="card"><h2>All workouts</h2><div class="wrap"><table id="hist"></table></div></section>
</main>
<script>
const D = __DATA__;
const C = ['--s1','--s2','--s3','--s4','--s5'].map(v => getComputedStyle(document.documentElement).getPropertyValue(v).trim());
const mmss = s => { if (s == null) return '—'; s = Math.round(s); return Math.floor(s/60) + ':' + String(s%60).padStart(2,'0'); };
const el = (t, a = {}, ...kids) => { const e = document.createElementNS(t === 'svg' || ['rect','text','line','circle','path','g'].includes(t) ? 'http://www.w3.org/2000/svg' : 'http://www.w3.org/1999/xhtml', t);
  for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); for (const k of kids) e.append(k); return e; };
const table = (id, cols, rows) => { const t = document.getElementById(id); t.replaceChildren(
  el('thead', {}, el('tr', {}, ...cols.map(c => el('th', {class: c.n ? 'n' : ''}, c.h)))),
  el('tbody', {}, ...rows.map(r => el('tr', {}, ...cols.map(c => el('td', {class: c.n ? 'n' : ''}, c.f ? c.f(r) : (r[c.k] ?? '—'))))))); };
const moves = [...new Set(D.blocks.map(b => b.movement_name))];
const color = m => C[moves.indexOf(m) % C.length];

const W = D.workouts, last = W[W.length - 1];
document.getElementById('headline').textContent = W.length
  ? `${W.length} workout${W.length > 1 ? 's' : ''} analyzed. Latest: ${last.name || 'workout'} on ${last.date}, ${last.score || ''}.`
  : 'No workouts yet. Run: wod analyze VIDEO --workout "..."';
const tot = (k) => W.reduce((s, w) => s + (w[k] || 0), 0);
document.getElementById('tiles').replaceChildren(...[
  ['Workouts', W.length], ['Total reps', tot('total_reps').toLocaleString()], ['Time analyzed', mmss(tot('elapsed_s'))],
  ['Movements tracked', D.movements.length], ['Latest between-movements', last ? Math.round(last.between_pct) + '%' : '—']
].map(([k, v]) => el('div', {class: 'card tile'}, el('div', {class: 'k'}, k), el('div', {class: 'v'}, String(v)))));

table('moves', [
  {h: 'Movement', k: 'movement'}, {h: 'First seen', k: 'first_seen_date'}, {h: 'Workouts', k: 'workouts', n: 1},
  {h: 'Total reps', k: 'total_reps', n: 1}, {h: 'Best fresh 10', n: 1, f: r => r.best_fresh_10_s == null ? '—' : r.best_fresh_10_s + 's'},
  {h: 'Latest fresh 10', n: 1, f: r => r.latest_fresh_10_s == null ? '—' : r.latest_fresh_10_s + 's'},
  {h: 'Avg reps/sec', k: 'avg_reps_per_sec', n: 1}, {h: 'Avg sec/rep', k: 'avg_sec_per_rep', n: 1},
  {h: 'Biggest unbroken set', k: 'biggest_unbroken_set', n: 1}], D.movements);

function drawRounds(wid) {
  const bs = D.blocks.filter(b => b.workout_id === wid), rounds = [...new Set(bs.map(b => b.round))];
  const ms = [...new Set(bs.map(b => b.movement_name))];
  document.getElementById('legend').replaceChildren(...ms.map(m => el('span', {}, el('i', {style: `background:${color(m)}`}), m)),
    el('span', {}, el('i', {style: 'background:var(--gap)'}), 'Between movements'));
  const box = document.getElementById('rounds'), w = box.clientWidth || 600, lw = 64, rh = 28, h = rounds.length * rh + 24;
  const rows = rounds.map(r => { let x = 0; return bs.filter(b => b.round === r).flatMap(b => { const o = [{r, x, w: b.duration_s, b, mv: 1}]; x += b.duration_s;
    if (b.transition_after_s != null) { o.push({r, x, w: b.transition_after_s, b}); x += b.transition_after_s; } return o; }); });
  const max = Math.max(1, ...rows.map(r => r.length ? r[r.length-1].x + r[r.length-1].w : 0)), sx = v => lw + v / max * (w - lw - 8);
  const svg = el('svg', {viewBox: `0 0 ${w} ${h}`, width: '100%', height: h});
  rows.forEach((segs, i) => { svg.append(el('text', {x: 0, y: i*rh + 18}, 'Round ' + rounds[i]));
    segs.forEach(s => { const r = el('rect', {x: sx(s.x), y: i*rh + 4, width: Math.max(1, sx(s.x + s.w) - sx(s.x) - 1), height: rh - 8, rx: 3,
      fill: s.mv ? color(s.b.movement_name) : 'var(--gap)'});
      r.append(el('title', {}, s.mv ? `${s.b.movement_name}: ${Math.round(s.w)}s, ${s.b.reps} reps (${s.b.sets}), ${s.b.sec_per_rep} s/rep` : `Between movements: ${Math.round(s.w)}s`));
      svg.append(r); }); });
  for (let t = 0; t <= max; t += Math.max(15, Math.ceil(max / 6 / 15) * 15)) svg.append(el('text', {x: sx(t), y: h - 4, 'text-anchor': 'middle'}, mmss(t)));
  box.replaceChildren(svg);
}
const pick = document.getElementById('pick');
pick.replaceChildren(...[...W].reverse().map(w => el('option', {value: w.id}, `${w.date} · ${w.name || w.id}`)));
pick.addEventListener('change', () => drawRounds(pick.value));
if (W.length) drawRounds(last.id);

(function freshChart() {
  const box = document.getElementById('freshchart'), w = box.clientWidth || 460, h = 220, m = {l: 40, r: 12, t: 10, b: 24};
  const dates = [...new Set(D.fresh.map(f => f.date))].sort(), ms = [...new Set(D.fresh.map(f => f.movement))];
  document.getElementById('flegend').replaceChildren(...ms.map(mv => el('span', {}, el('i', {style: `background:${color(mv)}`}), mv)));
  const step = Math.max(1, Math.ceil(Math.max(1, ...D.fresh.map(f => f.time_for_10_s)) * 1.1 / 4 / 5) * 5), ymax = step * 4;
  const sx = d => dates.length < 2 ? (m.l + w - m.r) / 2 : m.l + dates.indexOf(d) / (dates.length - 1) * (w - m.l - m.r);
  const sy = v => h - m.b - v / ymax * (h - m.t - m.b);
  const svg = el('svg', {viewBox: `0 0 ${w} ${h}`, width: '100%', height: h});
  for (let i = 0; i <= 4; i++) { const v = ymax / 4 * i; svg.append(el('line', {x1: m.l, x2: w - m.r, y1: sy(v), y2: sy(v), stroke: 'var(--line)'}), el('text', {x: m.l - 6, y: sy(v) + 4, 'text-anchor': 'end'}, Math.round(v) + 's')); }
  dates.forEach(d => svg.append(el('text', {x: sx(d), y: h - 6, 'text-anchor': 'middle'}, d.slice(5))));
  ms.forEach(mv => { const pts = D.fresh.filter(f => f.movement === mv);
    if (pts.length > 1) svg.append(el('path', {d: pts.map((p, i) => (i ? 'L' : 'M') + sx(p.date) + ',' + sy(p.time_for_10_s)).join(''), fill: 'none', stroke: color(mv), 'stroke-width': 2}));
    pts.forEach(p => { const c = el('circle', {cx: sx(p.date), cy: sy(p.time_for_10_s), r: 5, fill: color(mv)}); c.append(el('title', {}, `${mv} ${p.date}: ${p.time_for_10_s}s for 10${p.estimated ? ' (estimated)' : ''}`)); svg.append(c); }); });
  box.replaceChildren(svg);
})();

(function betweenChart() {
  const box = document.getElementById('between'), w = box.clientWidth || 460, h = 200, m = {l: 36, b: 24, t: 14};
  const bw = Math.min(36, (w - m.l) / Math.max(W.length, 1) * .6), step = (w - m.l) / Math.max(W.length, 1);
  const sy = v => h - m.b - v / 100 * (h - m.t - m.b);
  const svg = el('svg', {viewBox: `0 0 ${w} ${h}`, width: '100%', height: h});
  [0, 50, 100].forEach(v => svg.append(el('line', {x1: m.l, x2: w, y1: sy(v), y2: sy(v), stroke: 'var(--line)'}), el('text', {x: m.l - 6, y: sy(v) + 4, 'text-anchor': 'end'}, v + '%')));
  W.forEach((wk, i) => { const x = m.l + i * step + (step - bw) / 2;
    svg.append(el('rect', {x, y: sy(wk.between_pct), width: bw, height: sy(0) - sy(wk.between_pct), rx: 4, fill: 'var(--accent)'}),
      el('text', {x: x + bw/2, y: sy(wk.between_pct) - 4, 'text-anchor': 'middle'}, Math.round(wk.between_pct) + '%'),
      el('text', {x: x + bw/2, y: h - 6, 'text-anchor': 'middle'}, wk.date.slice(5))); });
  box.replaceChildren(svg);
})();

table('trans', [{h: 'From', k: 'from_movement'}, {h: 'To', k: 'to_movement'}, {h: 'Times', k: 'times', n: 1},
  {h: 'Average', n: 1, f: r => r.avg_s + 's'}, {h: 'Best', n: 1, f: r => r.best_s + 's'}], D.transitions.slice(0, 8));
table('fatigue', [{h: 'Date', k: 'date'}, {h: 'Movement', k: 'movement'}, {h: 'Round 1 reps/sec', k: 'first_round_reps_per_sec', n: 1},
  {h: 'Last round', k: 'last_round_reps_per_sec', n: 1}, {h: 'Change', n: 1, f: r => r.pace_change_pct == null ? '—' : (r.pace_change_pct > 0 ? '+' : '') + r.pace_change_pct + '%'}], D.fatigue.slice(0, 12));
table('hist', [{h: 'Date', k: 'date'}, {h: 'Workout', k: 'name'}, {h: 'Score', k: 'score'}, {h: 'Time', n: 1, f: r => mmss(r.elapsed_s)},
  {h: 'Reps', k: 'total_reps', n: 1}, {h: 'Between', n: 1, f: r => Math.round(r.between_pct) + '%'}, {h: 'Notes', k: 'notes'}], [...W].reverse());
</script></body></html>
"""
