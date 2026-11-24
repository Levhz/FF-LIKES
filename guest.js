#!/usr/bin/env node
'use strict';
// guest.js — single guest account creator. Prints JSON on stdout. Logs on stderr.
// exit 0 = ok | exit 2 = retryable failure | exit 1 = fatal
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

let undici = null;
try { undici = require('undici'); } catch {}

const argv = process.argv.slice(2);
const getArg = k => { const i = argv.indexOf(k); return i > -1 ? argv[i + 1] : null; };

const CFG = {
  endpoint: process.env.GUEST_ENDPOINT || 'https://100067.connect.garena.com/oauth/guest/register',
  appId: process.env.GUEST_APP_ID || '100067',
  region: (getArg('--region') || argv.find(a => !a.startsWith('--')) || process.env.GUEST_REGION || 'IND').toUpperCase(),
  count: Math.max(1, parseInt(getArg('--count') || '1', 10) || 1),
  maxRetries: parseInt(process.env.GUEST_MAX_RETRIES || '6', 10),
  baseBackoffMs: parseInt(process.env.GUEST_BACKOFF_MS || '20000', 10),
  maxBackoffMs: parseInt(process.env.GUEST_MAX_BACKOFF_MS || '240000', 10),
  proxyFile: process.env.GUEST_PROXY_FILE || path.join(__dirname, 'proxies.txt'),
};

const sleep = ms => new Promise(r => setTimeout(r, ms));
const hex = n => crypto.randomBytes(n).toString('hex');
const log = m => process.stderr.write(`[guest] ${m}\n`);

function proxies() {
  try {
    return fs.readFileSync(CFG.proxyFile, 'utf8').split(/\r?\n/)
      .map(s => s.trim()).filter(l => l && !l.startsWith('#'))
      .map(l => /^https?:\/\//i.test(l) ? l : (p => p.length === 4
        ? `http://${p[2]}:${p[3]}@${p[0]}:${p[1]}` : `http://${p[0]}:${p[1]}`)(l.split(':').map(x => x.trim())))
      .filter(Boolean);
  } catch { return []; }
}
const pickProxy = () => { const l = proxies(); return l.length ? l[Math.floor(Math.random() * l.length)] : null; };

function body(region) {
  const m = () => ['02', '00', hex(1), hex(1), hex(1), hex(1)].join(':');
  return JSON.stringify({
    app_id: CFG.appId, login_channel: 'guest', client_type: '2', client_version: '1.0.0',
    device_id: 'android-' + hex(8), android_id: hex(8), serial_number: hex(8),
    mac_address: m(), region, platform: 'android', sdk_version: '2.3.1', sdk_type: 'garena',
  });
}

async function attempt(region) {
  const proxy = pickProxy();
  const opts = {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Accept': 'application/json',
      'User-Agent': 'GarenaMSDK/2.3.1 (Android 11; en-US)',
    },
    body: body(region),
  };
  if (proxy && undici) opts.dispatcher = new undici.ProxyAgent({ uri: proxy, timeout: 20000 });

  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), 25000);
  let res;
  try { res = await fetch(CFG.endpoint, { ...opts, signal: ac.signal }); }
  finally { clearTimeout(t); }

  const text = await res.text();
  let data = {};
  try { data = JSON.parse(text); } catch {}

  if (res.status === 429 || data.code === 1006) return { retry: true, why: `429/1006 [${region}]` };
  if (!res.ok) return { retry: true, why: `HTTP ${res.status}` };
  if (data.code !== undefined && String(data.code) !== '0') return { retry: true, why: `code ${data.code}` };

  const src = data.data && typeof data.data === 'object' ? data.data : data;
  const uid = src.uid ?? src.user_id;
  if (!uid || !src.password) return { retry: true, why: 'no uid/password' };
  return { guest: { uid: String(uid), password: String(src.password), token: String(src.access_token ?? src.token ?? ''), region } };
}

async function one(region) {
  for (let i = 1; i <= CFG.maxRetries; i++) {
    let r;
    try { r = await attempt(region); }
    catch (e) { r = { retry: true, why: e.message }; }
    if (r.guest) return r.guest;
    log(`attempt ${i}/${CFG.maxRetries} failed: ${r.why}`);
    if (i < CFG.maxRetries) {
      const b = Math.min(CFG.baseBackoffMs * 2 ** (i - 1), CFG.maxBackoffMs);
      await sleep(Math.floor(b * (0.7 + Math.random() * 0.4)));
    }
  }
  return null;
}

(async () => {
  for (let n = 0; n < CFG.count; n++) {
    const g = await one(CFG.region);
    if (!g) { log('exhausted'); process.exit(2); }
    process.stdout.write(JSON.stringify(g) + '\n');
    if (n < CFG.count - 1) await sleep(3000 + Math.random() * 4000);
  }
  process.exit(0);
})();
