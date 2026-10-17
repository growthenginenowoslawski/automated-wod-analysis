// WOD Tracker — week-1 tracking test.
// Tracks the body on the phone with the same MediaPipe model and settings as the desktop tool,
// and saves the result in the same pose.json format, so the Python engine can analyze it unchanged.
import { CONFIG } from './config.js';

const $ = id => document.getElementById(id);
const params = new URLSearchParams(location.search);

// The tracking library and model are big (30 MB), so the live site loads them from public CDNs
// (pinned to the same version the desktop tool uses); a local test server uses its own copies.
const MP_VERSION = '0.10.32';
const SELF = (CONFIG.assets || 'self') === 'self';
const MP_BASE = SELF ? new URL('vendor/', location.href).href : `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}/`;
const MODEL_URLS = [
  ...(SELF ? [new URL('models/pose_landmarker_full.task', location.href).href] : []),
  'https://raw.githubusercontent.com/growthenginenowoslawski/automated-wod-analysis/main/models/pose_landmarker_full.task',
];
const { FilesetResolver, PoseLandmarker } = await import(`${MP_BASE}vision_bundle.mjs`);
let modelBuffer = null;
async function loadModel() {
  if (modelBuffer) return modelBuffer;
  let lastErr;
  for (const url of MODEL_URLS) {
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`${r.status}`);
      modelBuffer = new Uint8Array(await r.arrayBuffer());
      return modelBuffer;
    } catch (e) { lastErr = e; console.warn('model', url, e); }
  }
  throw new Error(`Couldn't download the tracking model (${lastErr && lastErr.message}). Check your connection.`);
}
const FPS = 15;
const STEP_MS = 1000 / FPS;
const VERSION = 'test-1';

// ---------- body tracking ----------
let fileset = null;
let delegateUsed = null;

async function newLandmarker() {
  // A fresh tracker per session: its timestamps must only ever go up.
  fileset = fileset || await FilesetResolver.forVisionTasks(`${MP_BASE}wasm`);
  const model = await loadModel();
  const opts = delegate => ({
    baseOptions: { modelAssetBuffer: model.slice(), delegate },
    runningMode: 'VIDEO', numPoses: 1,
    minPoseDetectionConfidence: 0.4, minTrackingConfidence: 0.4,   // same as the desktop tool
  });
  const order = params.get('cpu') ? ['CPU'] : ['GPU', 'CPU'];
  let lastErr;
  for (const d of order) {
    try {
      const lm = await PoseLandmarker.createFromOptions(fileset, opts(d));
      delegateUsed = d === 'GPU' ? 'graphics chip' : 'processor';
      return lm;
    } catch (e) { lastErr = e; console.warn('tracker', d, e); }
  }
  throw lastErr || new Error('Body tracking could not start on this phone.');
}

// ---------- one recording ----------
class Session {
  constructor(kind) {
    this.kind = kind;
    this.frames = [];          // {t, p: Float32Array(99) | null}
    this.minutes = [];         // per minute: {n, body, ms}
    this.gaps = [];            // [start, end] seconds when the app was in the background
    this.aspect = 1;
    this.duration = 0;
    this.started = new Date().toISOString();
    this.wakeLock = false;
    this.audio = null;
  }
  add(t, res, ms) {
    const lm = res && res.landmarks && res.landmarks[0];
    let p = null;
    if (lm) {
      p = new Float32Array(99);
      for (let i = 0; i < 33; i++) {
        p[i * 3] = lm[i].x; p[i * 3 + 1] = lm[i].y; p[i * 3 + 2] = lm[i].visibility ?? 0;
      }
    }
    this.frames.push({ t, p });
    const m = Math.floor(t / 60);
    while (this.minutes.length <= m) this.minutes.push({ n: 0, body: 0, ms: 0 });
    const mm = this.minutes[m];
    mm.n++; mm.ms += ms; if (p) mm.body++;
  }
  summary() {
    const n = this.frames.length;
    const body = this.frames.filter(f => f.p).length;
    const gapS = this.gaps.reduce((a, [s, e]) => a + (e - s), 0);
    const tracked = Math.max(1, this.duration - gapS);
    const perMin = this.minutes.map((m, i) => {
      const secs = i === this.minutes.length - 1 ? Math.max(1, this.duration - 60 * i) : 60;
      return { fps: m.n / secs, ms: m.n ? m.ms / m.n : 0, body: m.n ? m.body / m.n : 0 };
    });
    const full = perMin.slice(0, Math.max(1, perMin.length - (this.duration % 60 > 5 ? 1 : 0)));
    const avg = (a, k) => a.length ? a.reduce((s, x) => s + x[k], 0) / a.length : 0;
    return {
      kind: this.kind, version: VERSION, started: this.started,
      duration_s: +this.duration.toFixed(1),
      frames: n,
      avg_fps: +(n / tracked).toFixed(2),
      slowest_minute_fps: +Math.min(...full.map(m => m.fps)).toFixed(2),
      body_pct: n ? +(100 * body / n).toFixed(1) : 0,
      ms_first5: +avg(perMin.slice(0, 5), 'ms').toFixed(1),
      ms_last5: +avg(perMin.slice(-5), 'ms').toFixed(1),
      pauses: this.gaps.length, paused_s: +gapS.toFixed(1),
      wake_lock: this.wakeLock, tracker: delegateUsed,
      aspect: +this.aspect.toFixed(4),
      per_minute_fps: perMin.map(m => +m.fps.toFixed(2)),
      per_minute_ms: perMin.map(m => +m.ms.toFixed(1)),
      speed_x: this.speedX ? +this.speedX.toFixed(2) : undefined,
      took_s: this.tookS ? +this.tookS.toFixed(1) : undefined,
      device: navigator.userAgent,
      audio: this.audio ? { type: this.audio.type, bytes: this.audio.size } : null,
    };
  }
  // Same layout as the desktop tool's pose.json: 15 frames a second, t = int(i*1000/15)/1000.
  // Live frames arrive at uneven times, so each grid slot takes the nearest tracked frame.
  poseParts() {
    const r4 = x => Math.round(x * 1e4) / 1e4, r3 = x => Math.round(x * 1e3) / 1e3;
    const fmt = p => {
      if (!p) return 'null';
      const out = [];
      for (let i = 0; i < 33; i++) out.push(`[${r4(p[i * 3])},${r4(p[i * 3 + 1])},${r3(p[i * 3 + 2])}]`);
      return `[${out.join(',')}]`;
    };
    const parts = [`{"fps":15.0,"aspect":${r4(this.aspect)},"source":"browser","version":"${VERSION}","frames":[`];
    const F = this.frames;
    if (this.kind === 'video') {
      F.forEach((f, i) => parts.push(`${i ? ',' : ''}{"t":${f.t},"p":${fmt(f.p)}}`));
    } else {
      const n = Math.floor(this.duration * FPS);
      let j = 0;
      for (let i = 0; i < n; i++) {
        const t = Math.floor(i * 1000 / FPS) / 1000;
        while (j + 1 < F.length && Math.abs(F[j + 1].t - t) <= Math.abs(F[j].t - t)) j++;
        const f = F[j];
        const p = f && Math.abs(f.t - t) <= 0.12 ? f.p : null;
        parts.push(`${i ? ',' : ''}{"t":${t},"p":${fmt(p)}}`);
      }
    }
    parts.push(']}');
    return parts;
  }
  async poseGz() {
    const blob = new Blob(this.poseParts(), { type: 'application/json' });
    if (!('CompressionStream' in window)) return { blob, gz: false };
    const gz = await new Response(blob.stream().pipeThrough(new CompressionStream('gzip'))).blob();
    return { blob: gz, gz: true };
  }
}

// ---------- drawing ----------
const BONES = [[11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24],
  [23, 25], [25, 27], [24, 26], [26, 28], [27, 31], [28, 32]];

function drawPose(canvas, video, res) {
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  if (canvas.width !== Math.round(W * dpr)) { canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const lm = res && res.landmarks && res.landmarks[0];
  if (!lm || !video.videoWidth) return;
  const s = Math.min(W / video.videoWidth, H / video.videoHeight);
  const w = video.videoWidth * s, h = video.videoHeight * s, ox = (W - w) / 2, oy = (H - h) / 2;
  const P = i => [ox + lm[i].x * w, oy + lm[i].y * h];
  ctx.lineWidth = 3; ctx.strokeStyle = '#E8480C'; ctx.lineCap = 'round';
  for (const [a, b] of BONES) {
    const [x1, y1] = P(a), [x2, y2] = P(b);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  }
  ctx.fillStyle = '#121614';
  for (const i of [0, 15, 16, 27, 28]) { const [x, y] = P(i); ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 7); ctx.fill(); }
}

// ---------- screens ----------
function show(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.toggle('active', s.id === id));
  window.scrollTo(0, 0);
}
const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

// ---------- live test ----------
const live = { stream: null, lm: null, rec: null, running: false, last: 0, recorder: null, chunks: [], wake: null, hiddenAt: null, recent: [] };

async function openLive() {
  show('live');
  $('live-msg').textContent = 'Starting camera…';
  $('live-start').disabled = true;
  try {
    try {
      live.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } },
        audio: true,
      });
    } catch (e) {
      live.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } } });
    }
    const cam = $('cam');
    cam.srcObject = live.stream;
    await cam.play();
    $('live-msg').textContent = 'Loading body tracking…';
    live.lm = await newLandmarker();
    $('live-msg').textContent = 'Frame yourself: your whole body should light up in orange.';
    $('live-start').disabled = false;
    live.running = true;
    tick();
  } catch (e) {
    $('live-msg').textContent = `Camera didn't start: ${e.message || e}. Allow camera access and try again.`;
  }
}

function schedule() {
  const cam = $('cam');
  if (cam.requestVideoFrameCallback) cam.requestVideoFrameCallback(tick); else requestAnimationFrame(tick);
}

function tick() {
  if (!live.running) return;
  const cam = $('cam');
  const now = performance.now();
  if (now - live.last >= STEP_MS - 8 && cam.readyState >= 2 && !document.hidden) {
    live.last = now;
    const a = performance.now();
    let res = null;
    try { res = live.lm.detectForVideo(cam, now); } catch (e) { console.warn(e); }
    const ms = performance.now() - a;
    drawPose($('overlay'), cam, res);
    if (live.rec) {
      live.rec.add((now - live.t0) / 1000, res, ms);
      live.recent.push([now, ms, !!(res && res.landmarks && res.landmarks[0])]);
    } else {
      const found = res && res.landmarks && res.landmarks[0];
      $('live-msg').textContent = found ? 'Body found. Press Start when you’re ready.' : 'No body found yet. Step back so your whole body is in frame.';
    }
  }
  schedule();
}

async function keepAwake() {
  try {
    if ('wakeLock' in navigator) { live.wake = await navigator.wakeLock.request('screen'); return true; }
  } catch (e) { console.warn('wake lock', e); }
  return false;
}

async function startLive() {
  const cam = $('cam');
  live.rec = new Session('live');
  live.rec.aspect = cam.videoWidth / cam.videoHeight;
  live.t0 = performance.now();
  live.recent = [];
  live.rec.wakeLock = await keepAwake();
  const audio = live.stream.getAudioTracks();
  if (audio.length && 'MediaRecorder' in window) {
    const type = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm'].find(t => MediaRecorder.isTypeSupported(t));
    try {
      live.recorder = new MediaRecorder(new MediaStream(audio), type ? { mimeType: type, audioBitsPerSecond: 64000 } : undefined);
      live.chunks = [];
      live.recorder.ondataavailable = e => e.data.size && live.chunks.push(e.data);
      live.recorder.start(10000);
    } catch (e) { console.warn('audio', e); live.recorder = null; }
  }
  $('live-msg').textContent = '';
  $('live-start').hidden = true; $('live-back').hidden = true; $('live-stop').hidden = false;
  live.timer = setInterval(updateLiveStats, 1000);
}

function updateLiveStats() {
  const r = live.rec; if (!r) return;
  const now = performance.now();
  live.recent = live.recent.filter(x => now - x[0] < 5000);
  const n = live.recent.length;
  $('s-time').textContent = mmss((now - live.t0) / 1000);
  const fps = n / 5;
  $('s-fps').textContent = fps.toFixed(1);
  $('s-fps').parentElement.classList.toggle('warn', (now - live.t0) > 6000 && fps < 13);
  $('s-ms').textContent = n ? Math.round(live.recent.reduce((s, x) => s + x[1], 0) / n) : '–';
  const all = r.frames.length, body = r.frames.filter(f => f.p).length;
  $('s-body').textContent = all ? `${Math.round(100 * body / all)}%` : '–';
}

async function stopLive() {
  const r = live.rec; if (!r) return;
  r.duration = (performance.now() - live.t0) / 1000;
  if (live.hiddenAt != null) { r.gaps.push([live.hiddenAt, r.duration]); live.hiddenAt = null; }
  clearInterval(live.timer);
  if (live.recorder && live.recorder.state !== 'inactive') {
    await new Promise(res => { live.recorder.onstop = res; live.recorder.stop(); });
    r.audio = new Blob(live.chunks, { type: live.recorder.mimeType || 'audio/mp4' });
  }
  closeLive();
  showResults(r);
}

function closeLive() {
  live.running = false;
  if (live.stream) live.stream.getTracks().forEach(t => t.stop());
  live.stream = null;
  try { live.lm && live.lm.close(); } catch (e) {}
  live.lm = null;
  if (live.wake) { live.wake.release().catch(() => {}); live.wake = null; }
  live.rec = null;
  $('live-start').hidden = false; $('live-back').hidden = false; $('live-stop').hidden = true;
}

document.addEventListener('visibilitychange', async () => {
  if (!live.rec) return;
  const t = (performance.now() - live.t0) / 1000;
  if (document.hidden) live.hiddenAt = t;
  else {
    if (live.hiddenAt != null) live.rec.gaps.push([live.hiddenAt, t]);
    live.hiddenAt = null;
    await keepAwake();
  }
});

// ---------- video test ----------
const vt = { stop: false, running: false };

function seekTo(v, t) {
  return new Promise(resolve => {
    const done = () => { v.removeEventListener('seeked', done); resolve(); };
    v.addEventListener('seeked', done);
    v.currentTime = t;
  });
}

async function runVideo(file) {
  const v = $('vid');
  vt.stop = false; vt.running = true;
  $('vstage').hidden = false; $('vprog').hidden = false; $('vstats').hidden = false; $('v-stop').hidden = false;
  v.src = URL.createObjectURL(file);
  await new Promise((res, rej) => { v.onloadeddata = res; v.onerror = () => rej(new Error('This video can’t be opened here.')); });
  const lm = await newLandmarker();
  const rec = new Session('video');
  rec.aspect = v.videoWidth / v.videoHeight;
  rec.fileName = file.name;
  const dur = v.duration;
  const n = Math.floor(dur * FPS);
  const t0 = performance.now();
  let body = 0;
  for (let i = 0; i < n && !vt.stop; i++) {
    const ts = Math.floor(i * 1000 / FPS);
    await seekTo(v, i / FPS + 0.002);
    const a = performance.now();
    let res = null;
    try { res = lm.detectForVideo(v, ts); } catch (e) { console.warn(e); }
    rec.add(ts / 1000, res, performance.now() - a);
    if (res && res.landmarks && res.landmarks[0]) body++;
    if (i % 15 === 0 || i === n - 1) {
      drawPose($('voverlay'), v, res);
      const el = (performance.now() - t0) / 1000;
      const doneS = (i + 1) / FPS;
      const speed = doneS / el;
      $('vbar').style.width = `${(100 * (i + 1) / n).toFixed(1)}%`;
      $('v-done').textContent = `${Math.floor(100 * (i + 1) / n)}%`;
      $('v-speed').textContent = speed.toFixed(2);
      $('v-eta').textContent = mmss((dur - doneS) / speed);
      $('v-body').textContent = `${Math.round(100 * body / (i + 1))}%`;
      window.__progress = (i + 1) / n;
      await new Promise(r => setTimeout(r, 0));
    }
  }
  rec.tookS = (performance.now() - t0) / 1000;
  rec.duration = rec.frames.length / FPS;
  rec.speedX = rec.duration / rec.tookS;
  try { lm.close(); } catch (e) {}
  vt.running = false;
  $('v-stop').hidden = true;
  window.__session = rec;
  showResults(rec);
  return rec;
}

// ---------- results ----------
let current = null;

function showResults(rec) {
  current = rec;
  const s = rec.summary();
  window.__summary = s;
  show('results');
  const rows = [];
  if (s.kind === 'live') {
    const pass = s.avg_fps >= 14 && s.slowest_minute_fps >= 12 && s.pauses === 0 && s.duration_s >= 600;
    $('r-title').textContent = pass ? 'Your phone kept up' : 'Test finished';
    $('r-verdict').innerHTML = pass
      ? '<span class="ok">Passed.</span> Tracking held its speed for the whole workout. Send the results to Claude.'
      : verdictText(s);
    rows.push(['Workout length', mmss(s.duration_s)]);
    rows.push(['Average tracking speed (target 15)', `${s.avg_fps} frames/s`]);
    rows.push(['Slowest full minute', `${s.slowest_minute_fps} frames/s`]);
  } else {
    $('r-title').textContent = 'Video tracked';
    $('r-verdict').textContent = `Your phone tracked ${mmss(s.duration_s)} of video in ${mmss(s.took_s)}, ${s.speed_x}× real time.`;
    rows.push(['Video length', mmss(s.duration_s)]);
    rows.push(['Time it took', mmss(s.took_s)]);
    rows.push(['Speed', `${s.speed_x}× real time`]);
  }
  rows.push(['Body found', `${s.body_pct}% of frames`]);
  rows.push(['Time per frame, first 5 min → last 5 min', `${s.ms_first5} → ${s.ms_last5} ms`]);
  if (s.kind === 'live') {
    rows.push(['Times the app was left', s.pauses ? `${s.pauses} (${Math.round(s.paused_s)}s)` : '0']);
    rows.push(['Screen kept on', s.wake_lock ? 'Yes' : 'No']);
    rows.push(['Sound recorded (for rope counting)', s.audio ? `${(s.audio.bytes / 1e6).toFixed(1)} MB` : 'No']);
  }
  rows.push(['Tracking ran on', s.tracker || '–']);
  $('r-table').innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
  drawChart($('r-chart'), s.per_minute_fps);
  $('r-send').hidden = !CONFIG.supabaseUrl;
  $('r-status').textContent = CONFIG.supabaseUrl ? '' : 'Save the file and send it to Claude.';
}

function verdictText(s) {
  const why = [];
  if (s.duration_s < 600) why.push('it ran for under 10 minutes (try a full workout)');
  if (s.avg_fps < 14) why.push(`tracking averaged ${s.avg_fps} frames a second, below the 15 we want`);
  if (s.slowest_minute_fps < 12) why.push(`one minute dropped to ${s.slowest_minute_fps} frames a second`);
  if (s.pauses) why.push(`the app was left ${s.pauses} time${s.pauses > 1 ? 's' : ''}`);
  return `Worth a look: ${why.join('; ')}. Send the results to Claude either way.`;
}

function drawChart(canvas, vals) {
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth || 600, H = 140;
  canvas.width = W * dpr; canvas.height = H * dpr; canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const L = 34, R = 12, T = 12, B = 24, max = 20;
  const x = i => L + (vals.length < 2 ? 0 : i * (W - L - R) / (vals.length - 1));
  const y = v => T + (1 - Math.min(v, max) / max) * (H - T - B);
  ctx.font = '11px -apple-system, sans-serif'; ctx.fillStyle = '#5A615C'; ctx.strokeStyle = '#ECEEE9'; ctx.lineWidth = 1;
  for (const v of [0, 5, 10, 15, 20]) { ctx.beginPath(); ctx.moveTo(L, y(v)); ctx.lineTo(W - R, y(v)); ctx.stroke(); ctx.fillText(String(v), 8, y(v) + 4); }
  ctx.strokeStyle = '#0E7C4A'; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(L, y(15)); ctx.lineTo(W - R, y(15)); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = '#5A615C'; ctx.fillText('min 1', L, H - 6); if (vals.length > 1) { ctx.textAlign = 'right'; ctx.fillText(`min ${vals.length}`, W - R, H - 6); ctx.textAlign = 'left'; }
  ctx.strokeStyle = '#E8480C'; ctx.lineWidth = 2.5; ctx.beginPath();
  vals.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
  ctx.stroke();
  if (vals.length === 1) { ctx.fillStyle = '#E8480C'; ctx.beginPath(); ctx.arc(x(0), y(vals[0]), 4, 0, 7); ctx.fill(); }
}

async function saveFile() {
  if (!current) return;
  $('r-status').textContent = 'Preparing the file…';
  const { blob, gz } = await current.poseGz();
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
  const files = [new File([blob], `wod-test-${stamp}.pose.json${gz ? '.gz' : ''}`, { type: gz ? 'application/gzip' : 'application/json' })];
  files.push(new File([JSON.stringify(current.summary(), null, 1)], `wod-test-${stamp}.summary.json`, { type: 'application/json' }));
  if (current.audio) files.push(new File([current.audio], `wod-test-${stamp}.audio.${current.audio.type.includes('mp4') ? 'm4a' : 'webm'}`, { type: current.audio.type }));
  if (navigator.canShare && navigator.canShare({ files })) {
    try { await navigator.share({ files }); $('r-status').textContent = ''; return; } catch (e) { if (e.name === 'AbortError') { $('r-status').textContent = ''; return; } }
  }
  for (const f of files) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(f); a.download = f.name; a.click();
  }
  $('r-status').textContent = 'Saved.';
}

async function sendResults() {
  if (!current || !CONFIG.supabaseUrl) return;
  const btn = $('r-send');
  btn.disabled = true;
  $('r-status').textContent = 'Sending…';
  try {
    const code = Math.random().toString(36).slice(2, 8).toUpperCase();
    const s = current.summary();
    const { blob, gz } = await current.poseGz();
    const up = async (name, body, type) => {
      const r = await fetch(`${CONFIG.supabaseUrl}/storage/v1/object/test-runs/${code}/${name}`, {
        method: 'POST',
        headers: { apikey: CONFIG.supabaseKey, Authorization: `Bearer ${CONFIG.supabaseKey}`, 'Content-Type': type, 'x-upsert': 'false' },
        body,
      });
      if (!r.ok) throw new Error(`upload ${name}: ${r.status} ${await r.text()}`);
    };
    await up(`pose.json${gz ? '.gz' : ''}`, blob, gz ? 'application/gzip' : 'application/json');
    if (current.audio) await up(`audio.${current.audio.type.includes('mp4') ? 'm4a' : 'webm'}`, current.audio, current.audio.type.split(';')[0]);
    const r = await fetch(`${CONFIG.supabaseUrl}/rest/v1/test_runs`, {
      method: 'POST',
      headers: { apikey: CONFIG.supabaseKey, Authorization: `Bearer ${CONFIG.supabaseKey}`, 'Content-Type': 'application/json', Prefer: 'return=minimal' },
      body: JSON.stringify({ code, kind: s.kind, summary: s }),
    });
    if (!r.ok) throw new Error(`save: ${r.status} ${await r.text()}`);
    $('r-status').innerHTML = `Sent. Tell Claude your code: <b>${code}</b>`;
  } catch (e) {
    console.error(e);
    $('r-status').textContent = `Couldn't send (${e.message}). Use "Save the file" instead.`;
    btn.disabled = false;
  }
}

// ---------- wiring ----------
$('go-live').onclick = openLive;
$('live-start').onclick = startLive;
$('live-stop').onclick = stopLive;
$('live-back').onclick = () => { closeLive(); show('home'); };
$('go-video').onclick = () => show('video');
$('video-back').onclick = () => { vt.stop = true; show('home'); };
$('v-stop').onclick = () => { vt.stop = true; };
$('file').onchange = e => { const f = e.target.files[0]; if (f) runVideo(f).catch(err => { $('v-eta').textContent = '–'; alertBox(err); }); };
$('r-save').onclick = saveFile;
$('r-send').onclick = sendResults;
$('r-home').onclick = () => show('home');

function alertBox(err) {
  const p = document.createElement('p');
  p.className = 'fine no';
  p.textContent = err.message || String(err);
  $('video').appendChild(p);
}

if (window.matchMedia('(display-mode: standalone)').matches || navigator.standalone) $('install-hint').hidden = true;

// For automated testing on a computer: export the tracked data as text.
window.__runVideo = runVideo;
window.__poseText = async () => { const b = new Blob(window.__session.poseParts()); return await b.text(); };
