#!/usr/bin/env python3
"""
ffapi.py — Free Fire guest account client. Indian server only.

Library:  guest_register / activate / profile / send_like / like_report / create_account
CLI:      python ffapi.py -n 10
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import random
import socket
import string
import sys
import threading
import time
from datetime import datetime, timezone

try:
    import requests
    from requests.adapters import HTTPAdapter
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
except ImportError as e:
    sys.exit(f"Missing dependency: {e}\nRun: pip install requests pycryptodome")

import urllib3
urllib3.disable_warnings()

_ORIG_GAI = socket.getaddrinfo

def _force_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _ORIG_GAI(host, port, socket.AF_INET, type, proto, flags)

socket.getaddrinfo = _force_ipv4

# ------------------------------------------------------------------ constants
AUTH_HOST    = "100067.connect.garena.com"
APP_ID       = "100067"
CLIENT_TYPE  = "2"
RELEASE      = "OB55"
CLIENT_VER   = "2.132.4"
GA_SV        = "1789534056"
TIMEOUT      = 12
RETRIES      = 2
USE_DOH      = True
MAX_IPS      = 6
DEBUG        = False
QUIET        = False
ROUTE_TRIES  = 6

SPOOF_OVERRIDE = None

DEFAULT_NAME   = "LatencyZ"
DEFAULT_DIGITS = 3
MAX_NAME       = 12
TARGET_REGION  = "IND"
PASSWORD_LEN   = 64

# --- rate limiting / pacing -----------------------------------------------
MIN_GAP      = float(os.getenv("GUEST_MIN_GAP_MS", "9000")) / 1000
MAX_GAP      = float(os.getenv("GUEST_MAX_GAP_MS", "18000")) / 1000
MAX_RL_TRIES = int(os.getenv("GUEST_MAX_RETRIES", "6"))
RL_BASE      = float(os.getenv("GUEST_BACKOFF_MS", "20000")) / 1000
RL_MAX       = float(os.getenv("GUEST_MAX_BACKOFF_MS", "240000")) / 1000
STORM_HITS   = int(os.getenv("GUEST_STORM_THRESHOLD", "3"))
STORM_COOL   = float(os.getenv("GUEST_STORM_COOLDOWN_MS", "300000")) / 1000
ROUTE_DELAY  = float(os.getenv("ROUTE_RETRY_DELAY_MS", "15000")) / 1000
PROXY_FILE   = os.getenv("GUEST_PROXY_FILE", "proxies.txt")

SUP_MAP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
RETRYABLE = {408, 500, 502, 503, 504}

LOGIN_HOSTS = ("loginbp.ppmainecoonghj.com", "loginbp.ggblueshark.com")

HEX_KEY = bytes.fromhex(
    "32656534343831396539623435393838343531343130363762323831363231383734"
    "643064356437616639643866376530306331653534373135623764316533")

AES_KEY = bytes([89,103,38,116,99,37,68,69,117,104,54,37,90,99,94,56])
AES_IV  = bytes([54,111,121,90,68,114,50,50,69,51,121,99,104,106,77,37])

REGION_LANG = {
    "ME": "ar", "IND": "hi", "ID": "id", "VN": "vi", "TH": "th",
    "BD": "bn", "PK": "ur", "TW": "zh", "CIS": "ru", "RU": "ru",
    "SAC": "es", "BR": "pt", "SG": "en", "MY": "ms", "PH": "en", "US": "en",
}

SPOOF_PREFIX = {
    "ID":  ("36.66","36.68","36.72","36.85","36.88","36.90","110.136","110.137",
            "114.122","114.124","180.241","180.244","202.152","103.10"),
    "IND": ("49.36","49.37","49.44","49.207","59.144","103.87","106.51",
            "115.114","117.192","122.161","157.32","182.68"),
    "SG":  ("116.12","118.189","175.156","219.74","128.199","139.59","165.22"),
    "MY":  ("115.164","175.139","60.48","118.100","124.13","202.186"),
    "PH":  ("112.198","112.201","120.28","49.145","110.54","122.2","203.177"),
    "TH":  ("49.228","49.237","171.100","184.22","110.164","203.150","27.55"),
    "VN":  ("113.161","113.171","171.244","27.72","116.96","42.112","14.161"),
    "BD":  ("103.230","103.108","119.30","103.4","202.134","27.147"),
    "PK":  ("39.40","39.57","103.255","119.73","202.83","39.32"),
    "TW":  ("1.34","1.161","36.226","111.250","114.32","61.216"),
    "CIS": ("95.24","95.108","178.176","188.170","31.173","46.188","5.16"),
    "RU":  ("95.24","95.108","178.176","188.170","31.173","46.188","5.16"),
    "SAC": ("190.60","181.48","200.87","190.14","186.84","181.64"),
    "ME":  ("37.9","37.236","5.156","94.200","185.93","213.158"),
    "BR":  ("45.112","177.54","177.129","189.34","191.6","201.17","187.17","179.108"),
    "US":  ("3.80","3.208","4.14","20.0","34.192","52.0","54.208","104.28","172.58","173.245"),
}

SPOOF_COUNTRY      = {"BR": "SG", "BD": "SG", "PK": "SG", "IND": "SG"}
FALLBACK_COUNTRIES = ("SG", "US")

IP_HEADER_KEYS = ("X-Forwarded-For", "X-Real-IP", "X-Client-IP",
                  "CF-Connecting-IP", "True-Client-IP")

F14_KS = bytes([
    0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,0x37,
    0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30,
])

FIELD_22 = bytes.fromhex(
    "4747524501010100620200001052aa0d669c6a368f08338060d2ee0690053af84a41edcd3558556ec10f24f4"
    "6c93ac64ca41a16732c46a2cb071246a79b8929032f9e1b6f4ef331bd53cabf29b09b97349a46e9863c0314e"
    "1a0d80819fef8aabf03876b3d037db354a7ccb5c1bce96411fb3753f6f50e44c69c4ed617fa30efb8ffc0517"
    "ff2f636739be1f304d999cfd6fd48bf69454199794c3dc88f55a4bdbd66534d5a061359cdfd1fb680cd37918"
    "df9fdb3cf7d80067b0a3506c90063cf62b2ccec11e23913a2fd7c4ef091331967bb518a5ad1e551146b90821"
    "be800883abadde39d6c80a5d798611466c748f075481806c5842ce45e6bd4e3368ec08fe2ec41ceb880cd862"
    "49eb71693f79f0bccf9e590c3fae12519fe08c7a1905d0927690109e0df28574bb14847225db1a59230e6662"
    "ed7730e15ff9a6c815cb41b420edeada735a4b03e181037c37c2c850257311df2f07b0a56e759372cbd0268e"
    "3f13a292ee4373e38ab5096e0342a5e0d7fec6da2bbc265d74baadd2b24ee4f74862f82c21d6694bac53f8ce"
    "80312a30068a6276a641c19b11d0305c6fe2f531ac7de578b29f543697f5c73663e6f23aa15277b6122dcd4d"
    "4171e38f9ac0b173f39c58416a16c5c1f4a35acd065ce78f449cf538a249339e763272d458e4ed86c976591a"
    "9c066b3a37111e44091eb6b5a795249f3e5145db022a6055f2cc675936391312f688f89627845df222a91156"
    "555225be36f9714a0ba50246d0f003bda3c9c1292ab73b4f79635ddd023218eda93a302d79e023404c143965"
    "44a930b98ed54771aca7fec10d095587685b473e81a9619764fad9256529dcd6e911f4f4629612287d4ee3ec"
    "5389f6ec4ec020b0e2aac017232a9197be9e46239ce690fe5d4872b2e98e651510c971667f3aca8b59f3e9d5"
    "0e43")

APK_DIR = ("/data/app/~~iw-K-GR3srU7dLE-UxJ4bg==/com.dts.freefiremax-"
           "kbPhw3SUYautW0I_oayB_A==")

FIELD_94 = (b"KqsHT2gyPt7vUCc9SCjv2ioi3WEZSEL86ErvXB38suVVK/Z4IVt78ESl/"
            b"r2S15C1pqu/j6ZmgFL7HbwoFiiVconX08ooKiisQffvEAPCo/C+Lahr")

FIELD_106 = (b"https://dl.cdn.freefiremobile.com/live/ABHotUpdates/"
             b"|https://dl-core.cdn.freefiremobile.com/live/ABHotUpdates/"
             b"|6b2078db9d22dd98f8e9386a39af8462")

FIELD_107 = b"c8e41b7a93f02d56e1a94c7b8203f5d1"

CLIENT_BASE = {
    "IND": "https://client.ind.freefiremobile.com",
    "BR":  "https://client.us.freefiremobile.com",
    "US":  "https://client.us.freefiremobile.com",
    "SAC": "https://client.us.freefiremobile.com",
}
CLIENT_DEFAULT = "https://clientbp.ggblueshark.com"

def client_base(region):
    return CLIENT_BASE.get(region.upper(), CLIENT_DEFAULT)

STATIC_FALLBACK = {
    AUTH_HOST: ["34.124.234.158", "43.205.19.48"],
    "loginbp.ggblueshark.com": ["202.81.97.33", "202.81.97.46", "148.222.66.1"],
    "loginbp.ppmainecoonghj.com": ["202.81.97.46", "202.81.97.33", "148.222.66.1"],
    "clientbp.ggblueshark.com": ["202.81.97.33", "202.81.97.46"],
    "clientbp.ggpolarbear.com": ["202.81.97.46", "202.81.97.33"],
    "client.ind.freefiremobile.com": ["202.81.97.33", "202.81.97.46"],
    "client.us.freefiremobile.com": ["202.81.97.33", "148.222.66.1"],
}

DOH_ENDPOINTS = [
    ("https://cloudflare-dns.com/dns-query", {"type": "A"}, {"accept": "application/dns-json"}),
    ("https://dns.google/resolve", {"type": "A"}, {"accept": "application/dns-json"}),
    ("http://1.1.1.1/dns-query", {"type": "A"}, {"accept": "application/dns-json"}),
]

SESSION = requests.Session()
SESSION.mount("https://", HTTPAdapter(pool_connections=30, pool_maxsize=80, max_retries=0))

_ip_cache = {}
_dead = set()
_route_cache = {}
_used_names = set()
_save_lock = threading.Lock()

# ------------------------------------------------------------------ rate limit
class RateLimited(RuntimeError):
    pass

_GEN_LOCK = threading.RLock()
_RL_LOCK = threading.Lock()
_RL = {"last": 0.0, "strikes": 0, "until": 0.0}


def is_rate(r):
    if not isinstance(r, requests.Response):
        return False
    if r.status_code == 429:
        return True
    if r.status_code == 400 and b"1006" in (r.content or b""):
        return True
    return False


def _rl_cool():
    with _RL_LOCK:
        wait = _RL["until"] - time.time()
    if wait > 0:
        say(f"      cooling down {wait:.0f}s")
        time.sleep(wait)


def _rl_pace():
    with _RL_LOCK:
        wait = _RL["last"] + random.uniform(MIN_GAP, MAX_GAP) - time.time()
    if wait > 0:
        time.sleep(wait)
    with _RL_LOCK:
        _RL["last"] = time.time()


def _rl_ok():
    with _RL_LOCK:
        _RL["strikes"] = 0


def _rl_hit():
    """Register a rate-limit hit. Returns seconds slept if a storm cooldown fired."""
    with _RL_LOCK:
        _RL["strikes"] += 1
        storm = _RL["strikes"] >= STORM_HITS
        if storm:
            _RL["strikes"] = 0
            _RL["until"] = time.time() + STORM_COOL
    if storm:
        say(f"\n      rate-limit storm -> pause {STORM_COOL:.0f}s")
        time.sleep(STORM_COOL)
        return STORM_COOL
    return 0.0


def _rl_wait(attempt, retry_after=None):
    if retry_after and str(retry_after).strip().isdigit():
        time.sleep(min(float(retry_after), 120.0))
        return
    delay = min(RL_BASE * 2 ** (attempt - 1), RL_MAX) * random.uniform(0.7, 1.3)
    time.sleep(delay)


def rate_guard(fn, tries=None):
    """Run fn() with pacing + backoff until it stops returning a 429."""
    tries = tries or MAX_RL_TRIES
    r = None
    for attempt in range(1, tries + 1):
        _rl_cool()
        _rl_pace()
        r = fn()
        if not is_rate(r):
            _rl_ok()
            return r
        cooled = _rl_hit()
        if attempt < tries and not cooled:
            _rl_wait(attempt, getattr(r, "headers", {}).get("Retry-After"))
    return r


# ------------------------------------------------------------------ proxies
def _load_proxies():
    raw = os.getenv("GUEST_PROXIES", "").replace("\n", ",")
    lines = [p for p in raw.split(",") if p.strip()]
    try:
        with open(PROXY_FILE, encoding="utf-8") as f:
            lines += f.read().splitlines()
    except Exception:
        pass
    out = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "://" not in line:
            parts = line.split(":")
            line = (f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
                    if len(parts) == 4 else f"http://{line}")
        out.append(line)
    return out


_PROXIES = _load_proxies()


def pick_proxy():
    if not _PROXIES:
        return None
    url = _PROXIES[random.randrange(len(_PROXIES))]
    return {"http": url, "https": url}


# ------------------------------------------------------------------ helpers
def say(*a, **kw):
    if not QUIET:
        print(*a, **kw)

def _hex(n):
    return "".join(random.choices("0123456789abcdef", k=n))

def rand_password(n=PASSWORD_LEN):
    return "".join(random.choices("0123456789ABCDEF", k=n))

REGION_ALIAS = {"IN": "IND", "IDN": "ID", "RU": "CIS"}

def norm_region(v):
    s = str(v).upper()
    return REGION_ALIAS.get(s, s)

def jwt_claims(jwt):
    try:
        c = jwt.split(".")[1]
        c += "=" * (-len(c) % 4)
        return json.loads(base64.urlsafe_b64decode(c))
    except Exception:
        return {}

def claim_region(claims):
    return (claims.get("lock_region") or claims.get("noti_region")
            or claims.get("region") or claims.get("region_code")
            or claims.get("region_name"))

DEVICE_MODELS = [
    ("Asus ASUS_I005DA", "ARMv7 VFPv3 NEON VMH | 2400 | 2", "Adreno (TM) 640"),
    ("SM-A525F", "ARMv8 VFPv4 NEON VMH | 2200 | 8", "Adreno (TM) 618"),
    ("SM-A325M", "ARMv8 VFPv4 NEON VMH | 2000 | 8", "Mali-G52"),
    ("SM-S918B", "ARMv8 VFPv4 NEON VMH | 3200 | 8", "Adreno (TM) 740"),
    ("Redmi Note 10", "ARMv8 VFPv4 NEON VMH | 2200 | 8", "Adreno (TM) 619"),
    ("Redmi Note 11", "ARMv8 VFPv4 NEON VMH | 2400 | 8", "Adreno (TM) 610"),
    ("Poco X3", "ARMv8 VFPv4 NEON VMH | 2300 | 8", "Adreno (TM) 618"),
    ("Poco M4 Pro", "ARMv8 VFPv4 NEON VMH | 2200 | 8", "Mali-G57"),
    ("Pixel 6", "ARMv8 VFPv4 NEON VMH | 2800 | 8", "Mali-G78"),
    ("Pixel 7 Pro", "ARMv8 VFPv4 NEON VMH | 2800 | 8", "Mali-G710"),
    ("OnePlus 9", "ARMv8 VFPv4 NEON VMH | 2800 | 8", "Adreno (TM) 660"),
    ("Infinix X6819", "ARMv8 VFPv4 NEON VMH | 2400 | 8", "Mali-G57"),
    ("vivo 1906", "ARMv8 VFPv4 NEON VMH | 2000 | 8", "Adreno (TM) 610"),
]

ANDROID_VERSIONS = [
    ("Android OS 9 / API-28 (PI/rel.cjw.20220518.114133)", "9", "28"),
    ("Android OS 10 / API-29 (QKQ1.200114.002)", "10", "29"),
    ("Android OS 11 / API-30 (RP1A.201005.001)", "11", "30"),
    ("Android OS 12 / API-31 (SP1A.210812.016)", "12", "31"),
    ("Android OS 13 / API-33 (TQ3A.230805.001)", "13", "33"),
    ("Android OS 14 / API-34 (UP1A.231005.007)", "14", "34"),
]

OPERATORS = ["ATM Mobils", "Telkomsel", "Indosat", "XL Axiata", "Airtel", "Jio",
             "Vodafone", "Globe", "Smart", "Viettel", "Mobifone", "Claro", "Vivo"]
NETWORKS = ["WIFI", "4G", "5G"]
SDK_VER  = ["4.0.38", "4.0.39", "4.0.40", "4.0.41", "4.0.42"]

def new_device():
    model, cpu, gpu = random.choice(DEVICE_MODELS)
    android_full, os_ver, api = random.choice(ANDROID_VERSIONS)
    return {
        "device_id": _hex(32), "android_id": _hex(16),
        "uuid": f"{_hex(8)}-{_hex(4)}-{_hex(4)}-{_hex(4)}-{_hex(12)}",
        "imei": _hex(15), "mac": "02:" + ":".join(_hex(2) for _ in range(5)),
        "model": model, "brand": model.split()[0],
        "cpu": cpu, "gpu": gpu, "gpu_full": f"{gpu}|OpenGL ES 3.2",
        "android_full": android_full, "os": os_ver, "api": api,
        "sdk": random.choice(SDK_VER), "network": random.choice(NETWORKS),
        "operator": random.choice(OPERATORS),
    }

def device_headers(dev):
    return {
        "X-Device-Id": dev["device_id"], "X-Android-Id": dev["android_id"],
        "X-Device-Model": dev["model"], "X-Device-Brand": dev["brand"],
        "X-OS-Version": dev["os"], "X-API-Level": dev["api"],
        "X-SDK-Version": dev["sdk"], "X-Network-Type": dev["network"],
        "X-Operator": dev["operator"], "X-IMEI": dev["imei"],
        "X-Mac": dev["mac"], "X-Client-Uuid": dev["uuid"],
    }

def spoof_ip(country):
    pool = SPOOF_PREFIX.get(country.upper()) or SPOOF_PREFIX["US"]
    return f"{random.choice(pool)}.{random.randint(0, 255)}.{random.randint(1, 254)}"

def with_ip(headers, ip):
    h = dict(headers)
    for k in IP_HEADER_KEYS:
        h[k] = ip
    h["Forwarded"] = f"for={ip}"
    return h

def ua(dev, region):
    lang = REGION_LANG.get(region, "en")
    return f"GarenaMSDK/{dev['sdk']}({dev['model']};Android {dev['os']};{lang};{region};)"

def dbg(tag, r):
    if not DEBUG or not isinstance(r, requests.Response):
        return
    line = (f"--- {datetime.now().isoformat(timespec='seconds')} {tag} "
            f"HTTP {r.status_code} via {getattr(r,'_ff_ip','?')}\n{r.text[:600]}\n")
    with open("debug.log", "a", encoding="utf-8") as f:
        f.write(line)

# ------------------------------------------------------------------ names
def build_name(prefix, digits, plain=False):
    digits = max(1, min(digits, MAX_NAME - 1))
    if len(_used_names) > 20000:
        _used_names.clear()
    for _ in range(500):
        n = "".join(random.choices("0123456789", k=digits))
        if not plain:
            n = n.translate(SUP_MAP)
        room = MAX_NAME - len(n)
        base = prefix[:room] if len(prefix) > room else prefix
        name = base + n
        if name not in _used_names:
            _used_names.add(name)
            return name
    name = "".join(random.choices(string.ascii_letters + string.digits, k=MAX_NAME))
    _used_names.add(name)
    return name

# ------------------------------------------------------------------ resolution
def _local(host):
    out = []
    try:
        for ai in _ORIG_GAI(host, 443, socket.AF_INET, socket.SOCK_STREAM):
            ip = ai[4][0]
            if ip not in out:
                out.append(ip)
    except Exception:
        pass
    return out

def _doh(host):
    out = []
    if not USE_DOH:
        return out
    for url, params, hdrs in DOH_ENDPOINTS:
        try:
            p = dict(params)
            p["name"] = host
            r = SESSION.get(url, params=p, headers=hdrs, timeout=TIMEOUT, verify=False)
            for a in (r.json().get("Answer") or []):
                ip = a.get("data", "")
                if a.get("type") == 1 and ip and ip not in out:
                    out.append(ip)
            if out:
                break
        except Exception:
            continue
    return out

def resolve(host, refresh=False):
    if host in _ip_cache and not refresh:
        ips = _ip_cache[host]
    else:
        ips = []
        for src in (_local(host), _doh(host), STATIC_FALLBACK.get(host, [])):
            for ip in src:
                if ip not in ips:
                    ips.append(ip)
        _ip_cache[host] = ips
    if len(_dead) > 300:
        _dead.clear()
    live = [ip for ip in ips if ip not in _dead]
    dead = [ip for ip in ips if ip in _dead]
    return (live + dead)[:MAX_IPS]

# ------------------------------------------------------------------ transport
def _attempt(method, url, headers, data):
    try:
        return SESSION.request(method, url, headers=headers, data=data,
                               timeout=TIMEOUT, verify=False, allow_redirects=False,
                               proxies=pick_proxy())
    except requests.RequestException as e:
        return e

def _is_retryable(r):
    if r.status_code in RETRYABLE:
        return True
    if r.status_code == 400 and b"FORBIDDEN" in (r.content or b""):
        return True
    return False

def _backoff(attempt):
    time.sleep(0.5 * (attempt + 1) * random.uniform(0.8, 1.3))

def fetch_base(base, path, headers, data=None, method="POST"):
    host = base.split("//", 1)[1].split("/")[0]
    ips = resolve(host)
    if not ips:
        return None
    best = None
    for ip in ips:
        h = dict(headers)
        h["Host"] = host
        url = f"https://{ip}{path}"
        for attempt in range(RETRIES + 1):
            r = _attempt(method, url, h, data)
            if not isinstance(r, requests.Response):
                if isinstance(r, requests.ConnectTimeout):
                    _dead.add(ip)
                if attempt < RETRIES:
                    _backoff(attempt)
                continue
            if r.status_code in (200, 201):
                r._ff_ip = f"https://{ip}"
                return r
            best = r
            if is_rate(r):
                return r
            if _is_retryable(r) and attempt < RETRIES:
                _backoff(attempt)
                continue
            break
    return best

def fetch(host, path, headers, data=None, method="POST", schemes=("https",)):
    r = fetch_base(f"https://{host}", path, headers, data, method)
    if r is None and "http" in schemes:
        host_h = dict(headers)
        host_h["Host"] = host
        for ip in resolve(host)[:4]:
            try:
                rr = SESSION.request(method, f"http://{ip}{path}", headers=host_h,
                                     data=data, timeout=TIMEOUT, verify=False,
                                     proxies=pick_proxy())
            except requests.RequestException:
                continue
            if rr.status_code in (200, 201):
                return rr
            r = rr
    return r

# ------------------------------------------------------------------ protobuf
def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            return bytes(out)

def build_proto(fields):
    parts = []
    for key, val in fields.items():
        if isinstance(val, dict):
            nested = build_proto(val)
            parts.append(varint((key << 3) | 2) + varint(len(nested)) + nested)
        elif isinstance(val, int):
            parts.append(varint((key << 3) | 0) + varint(val))
        else:
            raw = val.encode() if isinstance(val, str) else val
            parts.append(varint((key << 3) | 2) + varint(len(raw)) + raw)
    return b"".join(parts)

def decode_proto(raw):
    out, i, n = {}, 0, len(raw)
    def rv(i):
        s = v = 0
        while True:
            b = raw[i]; i += 1; v |= (b & 0x7F) << s
            if not b & 0x80:
                return v, i
            s += 7
    while i < n:
        try:
            key, i = rv(i)
        except IndexError:
            break
        f, w = key >> 3, key & 7
        try:
            if w == 0:
                out[f], i = rv(i)
            elif w == 2:
                ln, i = rv(i); out[f] = raw[i:i + ln]; i += ln
            elif w == 5:
                i += 4
            elif w == 1:
                i += 8
            else:
                break
        except IndexError:
            break
    return out

def aes_encrypt(data: bytes) -> bytes:
    return AES.new(AES_KEY, AES.MODE_CBC, AES_IV).encrypt(pad(data, 16))

def encode_f14(open_id: str) -> bytes:
    return bytes(ord(c) ^ F14_KS[i % len(F14_KS)] for i, c in enumerate(open_id))

# ------------------------------------------------------------------ routes
def route_chain(region):
    primary = SPOOF_OVERRIDE or SPOOF_COUNTRY.get(region, region)
    countries = [primary]
    for c in FALLBACK_COUNTRIES:
        if c not in countries:
            countries.append(c)
    if region not in countries:
        countries.append(region)
    chain = [(h, c) for c in countries for h in LOGIN_HOSTS]
    win = _route_cache.get(region)
    if win:
        chain.sort(key=lambda x: 0 if x == win else 1)
    return chain

# ------------------------------------------------------------------ auth steps
def step_register(dev, region, ipc):
    password = rand_password(PASSWORD_LEN)
    body = json.dumps({"app_id": 100067, "client_type": 2, "password": password,
                       "source": 2}, separators=(",", ":"))
    sig = hmac.new(HEX_KEY, body.encode(), hashlib.sha256).hexdigest()
    headers = with_ip(device_headers(dev), spoof_ip(ipc))
    headers.update({"User-Agent": ua(dev, region), "Connection": "Keep-Alive",
                    "Accept": "application/json", "Accept-Encoding": "gzip",
                    "Authorization": f"Signature {sig}",
                    "Content-Type": "application/json; charset=utf-8"})
    last = "register failed"
    for attempt in range(1, MAX_RL_TRIES + 1):
        _rl_cool()
        _rl_pace()
        r = fetch(AUTH_HOST, "/api/v2/oauth/guest:register", headers, data=body)
        dbg("guest:register", r)
        if not isinstance(r, requests.Response):
            last = f"no response ({r})"
            time.sleep(1.5 + attempt)
            continue
        if is_rate(r):
            last = "HTTP 429 rate limited"
            cooled = _rl_hit()
            if attempt < MAX_RL_TRIES and not cooled:
                _rl_wait(attempt, r.headers.get("Retry-After"))
            continue
        try:
            data = r.json().get("data") or {}
        except ValueError:
            last = f"HTTP {r.status_code} non-JSON: {r.text[:160]}"
            time.sleep(1.5)
            continue
        uid = data.get("uid")
        if not uid:
            last = f"rejected HTTP {r.status_code}: {r.text[:160]}"
            if r.status_code >= 500:
                time.sleep(2 + attempt)
                continue
            break
        _rl_ok()
        return str(uid), password
    raise RuntimeError(last)

def step_token(uid, password, dev, region, ipc):
    headers = with_ip(device_headers(dev), spoof_ip(ipc))
    headers.update({"User-Agent": ua(dev, region),
                    "Content-Type": "application/x-www-form-urlencoded"})
    body = {"uid": uid, "password": password, "response_type": "token",
            "client_type": CLIENT_TYPE, "client_secret": HEX_KEY.decode(),
            "client_id": APP_ID}
    r = rate_guard(lambda: fetch(AUTH_HOST, "/oauth/guest/token/grant", headers, data=body))
    dbg("token/grant", r)
    if not isinstance(r, requests.Response):
        raise RuntimeError(f"no response ({r})")
    if is_rate(r):
        raise RateLimited("token grant HTTP 429")
    try:
        j = r.json()
    except ValueError:
        raise RuntimeError(f"HTTP {r.status_code} non-JSON: {r.text[:160]}")
    if "access_token" not in j or "open_id" not in j:
        raise RuntimeError(f"rejected HTTP {r.status_code}: {r.text[:160]}")
    return j["access_token"], j["open_id"], j.get("server_url")

def _game_headers(dev, region, ip, bearer="Bearer", with_sv=False):
    h = with_ip(device_headers(dev), ip)
    h.update({"User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
              "Accept": "*/*", "Accept-Encoding": "deflate, gzip",
              "Authorization": bearer, "X-GA": "v1 1", "ReleaseVersion": RELEASE,
              "Content-Type": "application/x-www-form-urlencoded",
              "X-Unity-Version": "2018.4.12f1"})
    if with_sv:
        h["X-Ga-Sv"] = GA_SV
    return h

def step_register_ingame(access_token, open_id, region, name, dev, host, ipc):
    lang = REGION_LANG.get(region, "en")
    payload = {1: name, 2: access_token, 3: open_id, 5: 102000007, 6: 4, 7: 1,
               13: 1, 14: encode_f14(open_id), 15: lang, 16: 2,
               20: CLIENT_VER, 21: 1, 22: FIELD_22}
    ip = spoof_ip(ipc)
    data = aes_encrypt(build_proto(payload))
    h = _game_headers(dev, region, ip)
    r = rate_guard(lambda: fetch(host, "/MajorRegister", h, data=data))
    dbg("MajorRegister", r)
    if not isinstance(r, requests.Response):
        raise RuntimeError("MajorRegister: no response")
    if is_rate(r):
        raise RateLimited("MajorRegister HTTP 429")
    if r.status_code not in (200, 201):
        raise RuntimeError(f"MajorRegister HTTP {r.status_code}: {r.text[:160]}")
    return r

def _login_payload(dev, access_token, open_id, region, ip, lang):
    return {
        3: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        4: b"free fire", 5: 1, 7: CLIENT_VER, 8: dev["android_full"],
        9: b"Handheld", 10: dev["operator"], 11: dev["network"],
        12: 1280, 13: 720, 14: b"240", 15: dev["cpu"],
        16: random.choice([5951, 6000, 6100, 5500]),
        17: dev["gpu"], 18: dev["gpu_full"],
        19: f"Google|{dev['uuid']}", 20: ip, 21: lang,
        22: open_id.encode(), 23: b"4", 24: b"Handheld",
        25: dev["model"], 26: lang, 29: access_token.encode(), 30: 1,
        41: dev["operator"], 42: dev["network"],
        57: b"1ac4b80ecf0478a44203bf8fac6120f5",
        60: 30000, 61: 30000, 62: 2519, 63: 243,
        64: 32357, 65: 34308, 66: 32357, 67: 34308, 73: 1,
        74: (APK_DIR + "/lib/arm").encode(), 76: 2,
        77: b"428775ab8c8845bd341b5357ec61d15e|" + APK_DIR.encode() + b"/base.apk",
        78: 2, 79: 1, 81: b"32", 83: b"2019118525", 85: 3,
        86: b"OpenGLES3", 87: 4095, 88: 4,
        92: random.choice([19788, 20000, 21000]),
        93: b"android_max", 94: FIELD_94,
        96: b'{"cur_rate":null,"support_etc2":true}',
        97: 1, 98: 1, 99: b"4", 100: b"4", 102: b"",
        104: 77149, 105: 1, 106: FIELD_106, 107: FIELD_107,
    }

def step_login(access_token, open_id, region, dev, host, ipc):
    lang = REGION_LANG.get(region, "en")
    ip = spoof_ip(ipc)
    body = aes_encrypt(build_proto(
        _login_payload(dev, access_token, open_id, region, ip, lang)))
    h = _game_headers(dev, region, ip, with_sv=True)
    r = rate_guard(lambda: fetch(host, "/MajorLogin", h, data=body))
    dbg("MajorLogin", r)
    if isinstance(r, requests.Response) and "eyJ" in r.text:
        return _parse_jwt(r)
    if isinstance(r, requests.Response):
        if is_rate(r):
            raise RateLimited("MajorLogin HTTP 429")
        say(f"\n      login HTTP {r.status_code} via {getattr(r,'_ff_ip','?')}: "
            f"{r.text[:120]!r}", end="")
    return None, None

def _parse_jwt(r):
    jwt = r.text[r.text.find("eyJ"):]
    dot2 = jwt.find(".", jwt.find(".") + 1)
    if dot2 != -1:
        jwt = jwt[: dot2 + 44]
    try:
        claims = jwt.split(".")[1]
        claims += "=" * (-len(claims) % 4)
        c = json.loads(base64.urlsafe_b64decode(claims))
        account_id = c.get("account_id") or c.get("external_id")
        return (str(account_id) if account_id else None), jwt
    except Exception:
        return None, jwt

def step_choose_region(region, jwt, dev, host, ipc):
    if not jwt or region == "BR":
        return None
    code = "RU" if region == "CIS" else region
    headers = _game_headers(dev, region, spoof_ip(ipc),
                            bearer=f"Bearer {jwt}", with_sv=True)
    headers["Releaseversion"] = RELEASE
    data = aes_encrypt(build_proto({1: code}))
    r = rate_guard(lambda: fetch(host, "/ChooseRegion", headers, data=data))
    dbg("ChooseRegion", r)
    return r

def bind_region(region, access_token, open_id, account_id, jwt, dev, host, ipc):
    if not jwt:
        raise RuntimeError("no token to bind with")
    r = step_choose_region(region, jwt, dev, host, ipc)
    say(f"\n      choose_region HTTP {getattr(r, 'status_code', '?')} "
        f"body={getattr(r, 'text', '')[:80]!r}")
    new_id, new_jwt = step_login(access_token, open_id, region, dev, host, ipc)
    claims = jwt_claims(new_jwt or "")
    got = claim_region(claims)
    say(f"      relogin id={new_id} lock_region={claims.get('lock_region')!r} "
        f"noti_region={claims.get('noti_region')!r}")
    if new_jwt is None:
        raise RuntimeError("relogin produced no token")
    if got is None:
        raise RuntimeError(f"token carries no region claim (keys={sorted(claims)})")
    if norm_region(got) != norm_region(region):
        raise RuntimeError(f"region bind failed: token={got} wanted={region}")
    return new_id or account_id, new_jwt

# ------------------------------------------------------------------ game api
def profile(jwt, region, target, server_url=None):
    body = aes_encrypt(build_proto({1: int(target), 2: region}))
    h = {"User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
         "Accept": "*/*", "Accept-Encoding": "deflate, gzip",
         "Authorization": f"Bearer {jwt}", "X-GA": "v1 1",
         "ReleaseVersion": RELEASE, "X-Unity-Version": "2018.4.12f1",
         "Content-Type": "application/x-www-form-urlencoded"}
    r = fetch_base(server_url or client_base(region), "/GetPlayerPersonalShow", h, body)
    if not r or r.status_code not in (200, 201):
        return None
    f = decode_proto(r.content)
    nick = f.get(3)
    if isinstance(nick, bytes):
        try:
            nick = nick.decode()
        except Exception:
            nick = None
    return {"nickname": nick, "level": f.get(6), "likes": f.get(8)}

def send_like(jwt, region, target, server_url=None):
    claims = jwt_claims(jwt)
    got = claim_region(claims)
    if isinstance(got, str) and got:
        region = norm_region(got)
    base = server_url or client_base(region)
    body = aes_encrypt(build_proto({1: int(target), 2: region}))
    h = {"User-Agent": "Dalvik/2.1.0 (Linux; U; Android 14; Pixel 8 Build/UP1A.231005.007)",
         "Content-Type": "application/octet-stream", "Authorization": f"Bearer {jwt}",
         "X-Unity-Version": "2018.4.11f1", "X-GA": "v1 1",
         "ReleaseVersion": RELEASE, "Expect": "100-continue",
         "Accept-Encoding": "gzip"}
    return fetch_base(base, "/LikeProfile", h, body)

def like_report(jwt, target, region=TARGET_REGION):
    """Profile, like, profile. Returns before/after likes for the reply embed."""
    before = profile(jwt, region, target)
    if not before:
        raise RuntimeError("UID not found on the Indian server")
    r = send_like(jwt, region, target)
    if not r or r.status_code not in (200, 201):
        raise RuntimeError(f"like rejected HTTP {getattr(r, 'status_code', '?')}")
    after = profile(jwt, region, target) or {}
    return {"nickname": before.get("nickname"),
            "before": before.get("likes"), "after": after.get("likes"),
            "region": region}

# ------------------------------------------------------------------ library entry
def guest_register(region):
    with _GEN_LOCK:
        dev = new_device()
        host, ipc = route_chain(region)[0]
        uid, pw = step_register(dev, region, ipc)
        return uid, pw, dev

def activate(acc):
    with _GEN_LOCK:
        region = acc.get("region") or TARGET_REGION
        dev = json.loads(acc["device"]) if isinstance(acc.get("device"), str) else acc.get("device")
        if not dev:
            dev = new_device()
        last = None
        for attempt, (host, ipc) in enumerate(route_chain(region)[:ROUTE_TRIES], 1):
            try:
                access, open_id, srv = step_token(acc["uid"], acc["password"], dev, region, ipc)
                step_register_ingame(access, open_id, region, acc.get("name") or "Guest",
                                     dev, host, ipc)
                aid, jwt = step_login(access, open_id, region, dev, host, ipc)
                if not jwt:
                    continue
                aid, jwt = bind_region(region, access, open_id, aid, jwt, dev, host, ipc)
                p = profile(jwt, region, aid or acc.get("account_id") or 0,
                            srv or client_base(region)) or {}
                return {"jwt": jwt, "account_id": aid, "level": p.get("level") or 0,
                        "nickname": p.get("nickname"),
                        "server_url": srv or client_base(region), "device": dev}
            except Exception as e:
                last = e
                if attempt < ROUTE_TRIES:
                    time.sleep(ROUTE_DELAY * random.uniform(0.8, 1.2))
        raise RuntimeError(f"activation failed: {last}")

def create_account(region=TARGET_REGION, name_prefix=DEFAULT_NAME,
                   digits=DEFAULT_DIGITS, plain=False, out_dir=None):
    with _GEN_LOCK:
        for attempt, (host, ipc) in enumerate(route_chain(region)[:ROUTE_TRIES], 1):
            dev = new_device()
            name = build_name(name_prefix, digits, plain)
            uid = password = account_id = jwt = None
            try:
                _rl_cool()
                say(f"\n    route {attempt}/{ROUTE_TRIES} {ipc}/{host.split('.')[1]}")
                say("      [1/4] register ....... ", end="")
                uid, password = step_register(dev, region, ipc)
                say(f"uid={uid}")

                say("      [2/4] token grant .... ", end="")
                access_token, open_id, srv = step_token(uid, password, dev, region, ipc)
                say("ok")

                say("      [3/4] major register . ", end="")
                step_register_ingame(access_token, open_id, region, name, dev, host, ipc)
                say("ok")

                say("      [4/4] major login .... ", end="")
                account_id, jwt = step_login(access_token, open_id, region, dev, host, ipc)
                say(f"id={account_id}")

                account_id, jwt = bind_region(region, access_token, open_id,
                                              account_id, jwt, dev, host, ipc)
            except Exception as e:
                say(f"\n      route failed: {e}")
                if uid and not account_id:
                    say(f"      orphan uid={uid} (registered, never entered game)")
                if attempt < ROUTE_TRIES:
                    time.sleep(ROUTE_DELAY * random.uniform(0.8, 1.2))
                continue

            if not account_id or not jwt:
                continue

            _route_cache[region] = (host, ipc)
            server_url = srv or client_base(region)
            p = profile(jwt, region, account_id, server_url) or {}

            acc = {"uid": uid, "password": password, "account_id": account_id,
                   "name": name, "region": region, "jwt": jwt,
                   "server_url": server_url, "level": p.get("level") or 0,
                   "nickname": p.get("nickname"),
                   "status": "ok", "route": f"{ipc}/{host}",
                   "device": dev, "device_model": dev["model"],
                   "created": datetime.now().isoformat(timespec="seconds")}
            if out_dir:
                save(acc, out_dir)
            return acc
        return None

# ------------------------------------------------------------------ persistence
def save(acc, out_dir):
    with _save_lock:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "accounts.json")
        try:
            existing = json.load(open(path, encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
        if any(a.get("uid") == acc["uid"] for a in existing):
            return
        existing.append(acc)
        json.dump(existing, open(path, "w", encoding="utf-8"), indent=2)
        with open(os.path.join(out_dir, "accounts.txt"), "a", encoding="utf-8") as f:
            f.write(f"{acc['uid']}:{acc['password']}\n")

# ------------------------------------------------------------------ diagnostic
def diag():
    print("\n=== DoH reachability ===")
    for url, _, _ in DOH_ENDPOINTS:
        try:
            t = time.time()
            r = SESSION.get(url, params={"name": "example.com", "type": "A"},
                            headers={"accept": "application/dns-json"},
                            timeout=TIMEOUT, verify=False)
            n = len(r.json().get("Answer") or [])
            print(f"{url:42} {r.status_code}  {n} answers  {time.time()-t:.2f}s")
        except Exception as e:
            print(f"{url:42} FAIL  {type(e).__name__}: {e}")

    print("\n=== resolution ===")
    for host in (AUTH_HOST, *LOGIN_HOSTS):
        print(f"{host:34} {len(resolve(host, True))} ips")

    print(f"\n=== proxies: {len(_PROXIES)} loaded ===")

    print("\n=== auth POST probe ===")
    body = json.dumps({"app_id": 100067, "client_type": 2,
                       "password": rand_password(PASSWORD_LEN),
                       "source": 2}, separators=(",", ":"))
    sig = hmac.new(HEX_KEY, body.encode(), hashlib.sha256).hexdigest()
    for ip in resolve(AUTH_HOST)[:3]:
        h = {"Host": AUTH_HOST, "User-Agent": "GarenaMSDK/4.0.40",
             "Accept": "application/json", "Authorization": f"Signature {sig}",
             "Content-Type": "application/json; charset=utf-8"}
        try:
            t = time.time()
            r = SESSION.post(f"https://{ip}/api/v2/oauth/guest:register", headers=h,
                             data=body, timeout=TIMEOUT, verify=False)
            print(f"  {ip:15} HTTP {r.status_code}  {time.time()-t:.2f}s  {r.text[:70]!r}")
        except requests.RequestException as e:
            print(f"  {ip:15} FAIL {type(e).__name__}")

    print("\n=== login POST probe ===")
    for host in LOGIN_HOSTS:
        for ip in resolve(host)[:3]:
            h = {"Host": host, "User-Agent": "UnityPlayer/2018.4.12f1",
                 "Accept": "*/*", "Content-Type": "application/x-www-form-urlencoded",
                 "Authorization": "Bearer x", "X-GA": "v1 1", "ReleaseVersion": RELEASE,
                 "X-Unity-Version": "2018.4.12f1"}
            try:
                t = time.time()
                r = SESSION.post(f"https://{ip}/MajorLogin", headers=h, data=b"\x00" * 32,
                                 timeout=TIMEOUT, verify=False)
                print(f"  {host.split('.')[1]:14} {ip:15} HTTP {r.status_code}  {time.time()-t:.2f}s")
            except requests.RequestException as e:
                print(f"  {host.split('.')[1]:14} {ip:15} FAIL {type(e).__name__}")
    print("=== end ===\n")

# ------------------------------------------------------------------ CLI
def ask_count():
    while True:
        try:
            raw = input("\n  How many accounts [1]: ").strip()
        except EOFError:
            return 1
        if not raw:
            return 1
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("  enter a positive number")

def main():
    global USE_DOH, TIMEOUT, RELEASE, CLIENT_VER, DEBUG, ROUTE_TRIES, SPOOF_OVERRIDE
    ap = argparse.ArgumentParser(description="Free Fire guest generator (Indian server)")
    ap.add_argument("-n", "--count", type=int, default=None)
    ap.add_argument("-r", "--region", default=TARGET_REGION, choices=sorted(REGION_LANG))
    ap.add_argument("--spoof", default=None, choices=sorted(REGION_LANG))
    ap.add_argument("--name", default=DEFAULT_NAME)
    ap.add_argument("--digits", type=int, default=DEFAULT_DIGITS)
    ap.add_argument("--plain", action="store_true")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--delay", type=float, default=3.0)
    ap.add_argument("--timeout", type=float, default=12.0)
    ap.add_argument("--route-tries", type=int, default=ROUTE_TRIES)
    ap.add_argument("--release", default=RELEASE)
    ap.add_argument("--client-ver", default=CLIENT_VER)
    ap.add_argument("--auth-ip", action="append", default=[])
    ap.add_argument("--no-doh", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--diag", action="store_true")
    args = ap.parse_args()

    if args.no_doh:
        USE_DOH = False
    TIMEOUT, RELEASE, CLIENT_VER = args.timeout, args.release, args.client_ver
    DEBUG, ROUTE_TRIES = args.debug, args.route_tries
    SPOOF_OVERRIDE = args.spoof or SPOOF_COUNTRY.get(args.region)
    if args.auth_ip:
        _ip_cache[AUTH_HOST] = list(dict.fromkeys(args.auth_ip))
    if args.diag:
        diag()
        return

    region = args.region
    count = args.count or 1
    out_dir = args.out or f"accounts_{region.lower()}"
    print("\n=== Free Fire guest generator ===")
    print(f"\n  region: {region}   spoof: {SPOOF_OVERRIDE or '(auto)'}   "
          f"count: {count}   out: ./{out_dir}/")
    print(f"  pace: {MIN_GAP:.0f}-{MAX_GAP:.0f}s   proxies: {len(_PROXIES)}")

    ok = 0
    for i in range(1, count + 1):
        print(f"\n[{i}/{count}] ({region})")
        acc = create_account(region, args.name, args.digits, args.plain, out_dir)
        if not acc:
            print("    FAILED: all routes exhausted")
        else:
            ok += 1
            print(f"    uid={acc['uid']}  id={acc['account_id']}  name={acc['name']}")
        if i < count:
            time.sleep(args.delay)

    print(f"\nDone: {ok}/{count} -> ./{out_dir}/accounts.txt")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped")
