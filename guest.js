'use strict';
// guest.js — paced, retrying, proxy-rotating guest generator
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

let undici = null;
try { undici = require('undici'); } catch { /* proxies disabled without undici */ }

const CFG = {
  endpoint: process.env.GUEST_ENDPOINT || 'https://100067.connect.garena.com/oauth/guest/register',
  appId: process.env.GUEST_APP_ID || '100067',
  regions: (process.env.GUEST_REGIONS || 'IND,BD,PK,ID,SG,TH,VN,MY,BR,US,ME,EG')
    .split(',').map(s => s.trim()).filter(Boolean),
  minGapMs: Number(process.env.GUEST_MIN_GAP_MS ?? 8000),
  maxGapMs: Number(process.env.GUEST_MAX_GAP_MS ?? 16000),
  maxRetries: Number(process.env.GUEST_MAX_RETRIES ?? 6),
  baseBackoffMs: Number(process.env.GUEST_BACKOFF_MS ?? 20000),
  maxBackoffMs: Number(process.env.GUEST_MAX_BACKOFF_MS ?? 240000),
  stormThreshold: Number(process.env.GUEST_STORM_THRESHOLD ?? 3),
  stormCooldownMs: Number(process.env.GUEST_STORM_COOLDOWN_MS ?? 300000),
  proxyFile: process.env.GUEST_PROXY_FILE || path.join(__dirname, 'proxies.txt'),
  stateFile: path.join(__dirname, 'guest_state.json'),
};

const sleep = ms => new Promise(r => setTimeout(r, ms));
const jitter = (min, max) => min + Math.floor(Math.random() * (max - min + 1));

/* ---------------- state (survives restarts) ---------------- */
function loadState() {
  try { return JSON.parse(fs.readFileSync(CFG.stateFile, 'utf8')); }
  catch { return { cooldownUntil: 0, strikes: 0, proxyIndex: 0, ok: 0, fail: 0 }; }
}
function saveState(s) {
  try { fs.writeFileSync(CFG.stateFile, JSON.stringify(s, null, 2)); } catch {}
}

/* ---------------- proxies ---------------- */
function normProxy(line) {
  if (!line) return null;
  if (/^https?:\/\//i.test(line)) return line;
  const p = line.split(':').map(x => x.trim());
  if (p.length === 2) return `http://${p[0]}:${p[1]}`;
  if (p.length === 4) return `http://${p[2]}:${p[3]}@${p[0]}:${p[1]}`;
  return null;
}
function loadProxies() {
  try {
    return fs.readFileSync(CFG.proxyFile, 'utf8')
      .split(/\r?\n/).map(s => s.trim())
      .filter(l => l && !l.startsWith('#'))
      .map(normProxy).filter(Boolean);
  } catch { return []; }
}
function pickProxy() {
  if (!undici) return null;
  const list = loadProxies();
  if (!list.length) return null;
  const s = loadState();
  s.proxyIndex = (s.proxyIndex + 1) % list.length;
  saveState(s);
  return list[s.proxyIndex];
}

/* ---------------- fingerprint ---------------- */
function hex(n) { return crypto.randomBytes(n).toString('hex'); }
function mac() {
  const b = () => crypto.randomBytes(1).toString('hex').padStart(2, '0');
  return ['02', '00', b(), b(), b(), b()].join(':');
}
function fingerprint(region) {
  return {
    app_id: CFG.appId,
    login_channel: 'guest',
    client_type: '2',
    client_version: '1.0.0',
    device_id: 'android-' + hex(8),
    android_id: hex(8),
    serial_number: hex(8),
    mac_address: mac(),
    region,
    platform: 'android',
    sdk_version: '2.3.1',
    sdk_type: 'garena',
  };
}
function headers() {
  return {
    'Content-Type': 'application/json; charset=utf-8',
    'Accept': 'application/json',
    'User-Agent': 'GarenaMSDK/2.3.1 (Android 11; en-US)',
    'Connection': 'keep-alive',
  };
}

/* ---------------- http ---------------- */
async function post(url, body, hdrs, proxy) {
  const opts = { method: 'POST', headers: hdrs, body };
  if (proxy && undici) {
    const { ProxyAgent, fetch: uFetch } = undici;
    return uFetch(url, { ...opts, dispatcher: new ProxyAgent({ uri: proxy, timeout: 20000 }) });
  }
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), 25000);
  try { return await fetch(url, { ...opts, signal: ac.signal }); }
  finally { clearTimeout(t); }
}

function retryable(msg) { const e = new Error(msg); e.retryable = true; return e; }

/* ---------------- one attempt ---------------- */
async function attemptCreate(region, proxy) {
  let res;
  try {
    res = await post(CFG.endpoint, JSON.stringify(fingerprint(region)), headers(), proxy);
  } catch (e) {
    throw retryable(`network: ${e.message}`);
  }
  const text = await res.text();
  let data = {};
  try { data = JSON.parse(text); } catch {}

  if (res.status === 429 || data.code === 1006) throw retryable(`429/1006 rate limited [${region}]`);
  if (!res.ok) throw retryable(`HTTP ${res.status}: ${text.slice(0, 140)}`);
  if (data.code !== undefined && String(data.code) !== '0') {
    throw retryable(`api code ${data.code}: ${data.error || 'unknown'}`);
  }

  const src = data.data && typeof data.data === 'object' ? data.data : data;
  const uid = src.uid ?? src.user_id;
  const password = src.password;
  const token = src.access_token ?? src.token;
  if (!uid || !password) throw retryable('no uid/password returned');

  return {
    uid: String(uid),
    password: String(password),
    token: token ? String(token) : null,
    region,
    created_at: Date.now(),
  };
}

/* ---------------- public: single guest, fully retried ---------------- */
async function generateOne() {
  const s = loadState();
  const wait = s.cooldownUntil - Date.now();
  if (wait > 0) await sleep(wait);

  let lastErr;
  for (let attempt = 1; attempt <= CFG.maxRetries; attempt++) {
    const region = CFG.regions[Math.floor(Math.random() * CFG.regions.length)];
    const proxy = pickProxy();
    try {
      const guest = await attemptCreate(region, proxy);
      const st = loadState();
      st.strikes = 0; st.ok++;
      saveState(st);
      return guest;
    } catch (e) {
      lastErr = e;
      const st = loadState();
      st.fail++;
      if (e.retryable) {
        st.strikes = (st.strikes || 0) + 1;
        if (st.strikes >= CFG.stormThreshold) {
          st.strikes = 0;
          st.cooldownUntil = Date.now() + CFG.stormCooldownMs;
          saveState(st);
          console.warn(`[guest] storm detected -> cooldown ${CFG.stormCooldownMs / 1000}s`);
          await sleep(CFG.stormCooldownMs);
        } else {
          saveState(st);
          const back = Math.min(CFG.baseBackoffMs * 2 ** (attempt - 1), CFG.maxBackoffMs);
          await sleep(Math.floor(back * (0.7 + Math.random() * 0.4)));
        }
      } else {
        saveState(st);
        await sleep(2000);
      }
    }
  }
  throw lastErr;
}

/* ---------------- public: background auto-fill ---------------- */
const auto = { running: false, stop: false };

async function startAutoFill({ target, current, onGuest, onError, log = console.log }) {
  if (auto.running) return;
  auto.running = true;
  auto.stop = false;
  let made = 0;
  log(`[guest] auto-fill started -> target ${target} (have ${current})`);

  try {
    while (!auto.stop && made < target) {
      try {
        const guest = await generateOne();
        made++;
        if (onGuest) await onGuest(guest);
        log(`[guest] ${made}/${target} ok uid=${guest.uid} region=${guest.region}`);
      } catch (e) {
        if (onError) await onError(e);
        console.error(`[guest] ${made}/${target} failed: ${e.message}`);
      }
      if (!auto.stop && made < target) await sleep(jitter(CFG.minGapMs, CFG.maxGapMs));
    }
  } finally {
    auto.running = false;
    log(`[guest] auto-fill done (${made} created)`);
  }
}

function stopAutoFill() { auto.stop = true; }
function isRunning() { return auto.running; }
function stats() { const s = loadState(); return { ok: s.ok || 0, fail: s.fail || 0, cooldownUntil: s.cooldownUntil || 0 }; }

module.exports = { generateOne, startAutoFill, stopAutoFill, isRunning, stats, CFG };
