#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
====================================================================
      本地 AI 客户端凭据一键提取与多账号同步工具 (Local Extract)
====================================================================
功能：
  • 自动探测本机安装的 CodeBuddy / WorkBuddy 与 TRAE 客户端
  • 支持多账号自动发现（主号、小号、多客户端多实例）
  • 纯标准库内置 AES-128-CBC 算法自解密 TRAE 凭据
  • 智能调用 WorkBuddy 内核引擎自解密 WorkBuddy 最新凭据
  • 自动追加/更新本地账号池并一键直连同步至云端智能管家
====================================================================
"""

import os
import sys
import json
import base64
import hashlib
import re
import uuid
import subprocess
import ctypes
from ctypes import wintypes

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SALT_A = bytes([82,9,106,213,48,54,165,56,191,64,163,158,129,243,215,251,124,227,57,130,155,47,255,135,52,142,67,68,196,222,233,203,84,123,148,50,166,194,35,61,238,76,149,11,66,250,195,78,8,46,161,102,40,217,36,178,118,91,162,73,109,139,209,37])
SALT_B = bytes([31,221,168,51,136,7,199,49,177,18,16,89,39,128,236,95,96,81,127,169,25,181,74,13,45,229,122,159,147,201,156,239,160,224,59,77,174,42,245,176,200,235,187,60,131,83,153,97,23,43,4,126,186,119,214,38,225,105,20,99,85,33,12,125])
SALT_AES = bytes(a ^ b for a, b in zip(SALT_A, SALT_B))
STORAGE_KEY = "iCubeAuthInfo://icube.cloudide"

def _gmul(a, b):
    p = 0
    for _ in range(8):
        if b & 1: p ^= a
        hi = a & 0x80; a = (a << 1) & 0xFF
        if hi: a ^= 0x1B
        b >>= 1
    return p

def _build_sbox():
    inv = [0] * 256
    for i in range(1, 256):
        for j in range(1, 256):
            if _gmul(i, j) == 1:
                inv[i] = j; break
    sb = [0] * 256
    for i in range(256):
        x = inv[i] if i else 0; s = x
        for _ in range(4):
            x = ((x << 1) | (x >> 7)) & 0xFF; s ^= x
        sb[i] = s ^ 0x63
    return sb

SBOX = _build_sbox()
INV = [0] * 256
for _i, _v in enumerate(SBOX): INV[_v] = _i
RC = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1B,0x36]

def _expand(key):
    w = [list(key[i*4:i*4+4]) for i in range(4)]
    for i in range(4, 44):
        t = w[i-1][:]
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= RC[i//4-1]
        w.append([w[i-4][j] ^ t[j] for j in range(4)])
    return w

def _rk(w, r):
    ws = w[r*4:r*4+4]
    return [ws[c][k] for c in range(4) for k in range(4)]

def _addrk(s, k): return [s[i] ^ k[i] for i in range(16)]
def _isub(s): return [INV[b] for b in s]
def _ishift(s): return [s[0],s[13],s[10],s[7], s[4],s[1],s[14],s[11], s[8],s[5],s[2],s[15], s[12],s[9],s[6],s[3]]
def _imix(s):
    o = []
    for c in range(4):
        a = s[c*4:c*4+4]
        o += [_gmul(a[0],14)^_gmul(a[1],11)^_gmul(a[2],13)^_gmul(a[3],9),
              _gmul(a[0],9)^_gmul(a[1],14)^_gmul(a[2],11)^_gmul(a[3],13),
              _gmul(a[0],13)^_gmul(a[1],9)^_gmul(a[2],14)^_gmul(a[3],11),
              _gmul(a[0],11)^_gmul(a[1],13)^_gmul(a[2],9)^_gmul(a[3],14)]
    return o

def aes128_cbc_decrypt(key, iv, data):
    w = _expand(key); out = b""; prev = list(iv)
    for off in range(0, len(data), 16):
        blk = list(data[off:off+16]); s = _addrk(blk, _rk(w, 10))
        for r in range(9, 0, -1):
            s = _ishift(s); s = _isub(s); s = _addrk(s, _rk(w, r)); s = _imix(s)
        s = _ishift(s); s = _isub(s); s = _addrk(s, _rk(w, 0))
        out += bytes(a ^ b for a, b in zip(s, prev)); prev = blk
    return out

def decrypt_trae_storage_value(b64):
    buf = base64.b64decode(b64)
    rb, enc = buf[6:38], buf[38:]
    h = hashlib.sha512(rb).digest()
    fh = hashlib.sha512(h + SALT_AES).digest()
    pt = aes128_cbc_decrypt(fh[:16], fh[16:32], enc)[64:]
    pad = pt[-1] if pt else 0
    if 1 <= pad <= 16:
        return pt[:-pad]
    return pt.rstrip(b"\x00").rstrip()

def extract_workbuddy_desktop():
    """使用 WorkBuddy 自带的 Node 运行环境解密 workbuddy-desktop.info 凭据"""
    wb_candidates = [
        r"D:\WorkBuddy\WorkBuddy.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\WorkBuddy\WorkBuddy.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\WorkBuddy\WorkBuddy.exe")
    ]
    wb_exe = next((p for p in wb_candidates if os.path.exists(p)), None)
    if not wb_exe:
        return []

    app_asar = os.path.join(os.path.dirname(wb_exe), "resources", "app.asar")
    if not os.path.exists(app_asar):
        return []

    info_path = os.path.expandvars(r"%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info")
    if not os.path.exists(info_path):
        return []

    js_code = f"""
const fs = require('fs');
const path = require('path');

try {{
  const binding = process._linkedBinding("electron_browser_workbuddy_storage");
  const rawLogger = binding.loggerGet();
  const mainDir = '{app_asar.replace("\\", "/")}/main';
  const require_dist = require(path.join(mainDir, 'dist.js'));
  const cp = require(path.join(mainDir, 'credential-protection.js'));
  cp.t();

  const configDir = path.join(process.env.USERPROFILE, '.workbuddy');
  const i = require_dist.T(rawLogger);
  const protectorKey = i.symmetric.value;

  let userKey = null;
  const keyblobPath = require_dist.l(configDir);
  if (fs.existsSync(keyblobPath)) {{
    const o = require_dist.u({{ keyblobPath, protectorKey }});
    if (o.status === 'ready') {{
      userKey = o.value;
    }}
  }}

  const bootstrap = {{
    policy: 'required',
    symmetricKey: protectorKey,
    ...(userKey ? {{ userKey }} : {{}}),
    ...(i.developerPublicKey.status === 'ready' ? {{ developerPublicKey: i.developerPublicKey.value }} : {{}})
  }};

  cp._(bootstrap);

  const authPath = '{info_path.replace("\\", "/")}';
  const authRaw = fs.readFileSync(authPath, 'utf8');
  const codec = cp.v({{
    purpose: 'workbuddy-auth-session',
    resourceId: 'auth/workbuddy-desktop.info'
  }});

  try {{
    const decoded = codec.decode(JSON.parse(authRaw), cp.l);
    const session = decoded.value;
    const res = {{
      uid: session?.account?.uid || '',
      nickname: session?.account?.nickname || '',
      phone: session?.account?.phoneNumber || '',
      accessToken: session?.auth?.accessToken || '',
      refreshToken: session?.auth?.refreshToken || ''
    }};
    process.stdout.write(JSON.stringify(res));
  }} finally {{
    codec.dispose();
  }}
}} catch (e) {{
  process.stderr.write(e.message || String(e));
}}
process.exit(0);
"""
    env = os.environ.copy()
    env["ELECTRON_RUN_AS_NODE"] = "1"

    try:
        proc = subprocess.run(
            [wb_exe, "-e", js_code],
            env=env,
            capture_output=True,
            text=True,
            timeout=10
        )
        if proc.returncode == 0 and proc.stdout.strip():
            acc = json.loads(proc.stdout.strip())
            if acc.get("accessToken"):
                acc["source"] = "WorkBuddy客户端"
                return [acc]
    except Exception as e:
        print(f"  ⚠️ WorkBuddy 桌面端凭据解析异常: {e}")
    return []


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte))
    ]

def _dpapi_decrypt(cipher_bytes):
    try:
        blob_in = DATA_BLOB(len(cipher_bytes), ctypes.cast(ctypes.create_string_buffer(cipher_bytes), ctypes.POINTER(ctypes.c_byte)))
        blob_out = DATA_BLOB()
        res = ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
        if res:
            out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
            return out
    except Exception:
        pass
    return None

def extract_qoder():
    appdata = os.getenv("APPDATA", "")
    if not appdata:
        return []
    
    candidates = [
        ("Qoder CN", os.path.join(appdata, "com.qodercn.app.stable")),
        ("Qoder", os.path.join(appdata, "com.qoder.app.stable")),
        ("Qoder", os.path.join(appdata, "Qoder"))
    ]
    
    accounts = []
    seen_tokens = set()
    
    for name, qdir in candidates:
        auth_file = os.path.join(qdir, "auth.v1.dat")
        ls_file = os.path.join(qdir, "Local State")
        if not (os.path.exists(auth_file) and os.path.exists(ls_file)):
            continue
        try:
            with open(ls_file, "r", encoding="utf-8") as f:
                ls = json.load(f)
            encrypted_key_b64 = ls.get("os_crypt", {}).get("encrypted_key")
            if not encrypted_key_b64:
                continue
            enc_key = base64.b64decode(encrypted_key_b64)
            if enc_key.startswith(b"DPAPI"):
                enc_key = enc_key[5:]
            master_key = _dpapi_decrypt(enc_key)
            if not master_key:
                continue

            with open(auth_file, "rb") as f:
                raw = f.read()

            if not raw.startswith(b"v10") or len(raw) < 15:
                continue

            nonce = raw[3:15]
            ciphertext = raw[15:]

            dec_bytes = None
            try:
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                aesgcm = AESGCM(master_key)
                dec_bytes = aesgcm.decrypt(nonce, ciphertext, None)
            except Exception:
                pass

            if not dec_bytes:
                node_candidates = [
                    os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "Qoder CN", "Qoder CN.exe"),
                    "D:\\Qoder CN\\Qoder CN.exe",
                    "node"
                ]
                for n_exe in node_candidates:
                    if os.path.exists(n_exe) or n_exe == "node":
                        js_script = f"""
const crypto = require('crypto');
try {{
    const key = Buffer.from('{base64.b64encode(master_key).decode()}', 'base64');
    const nonce = Buffer.from('{base64.b64encode(nonce).decode()}', 'base64');
    const ctWithTag = Buffer.from('{base64.b64encode(ciphertext).decode()}', 'base64');
    const tag = ctWithTag.slice(-16);
    const ct = ctWithTag.slice(0, -16);
    const d = crypto.createDecipheriv('aes-256-gcm', key, nonce);
    d.setAuthTag(tag);
    const dec = Buffer.concat([d.update(ct), d.final()]);
    console.log(dec.toString('utf8'));
}} catch(e) {{
    process.exit(1);
}}
"""
                        env = os.environ.copy()
                        env["ELECTRON_RUN_AS_NODE"] = "1"
                        try:
                            proc = subprocess.run([n_exe, "-e", js_script], env=env, capture_output=True, text=True, timeout=5)
                            if proc.returncode == 0 and proc.stdout.strip():
                                dec_bytes = proc.stdout.strip().encode("utf-8")
                                break
                        except Exception:
                            continue

            if dec_bytes:
                info = json.loads(dec_bytes.decode("utf-8", "ignore"))
                user = info.get("user") or {}
                tokens = info.get("tokens") or {}
                tok = info.get("token") or tokens.get("token") or tokens.get("accessToken") or ""
                rt = info.get("refreshToken") or tokens.get("refreshToken") or ""
                uid = user.get("id") or info.get("uid") or ""
                phone = user.get("phone") or ""
                nick = user.get("name") or user.get("username") or phone or "Qoder用户"
                
                if tok and tok not in seen_tokens:
                    seen_tokens.add(tok)
                    accounts.append({
                        "token": tok,
                        "refreshToken": rt,
                        "uid": uid,
                        "phone": phone,
                        "name": nick,
                        "source": name,
                        "expiresAt": info.get("expiresAt") or tokens.get("expiresAt", "")
                    })
                    print(f"✅ 成功解密 [{name}] 登录凭据 (账号: {phone or nick}, UID: {uid[:8]}...)")
        except Exception as e:
            print(f"⚠️ 解析 [{name}] 凭据失败: {e}")

    return accounts

def extract_all():
    extracted = {
        "codebuddy": [],
        "trae": [],
        "qoder": []
    }
    seen_cb_uids = set()
    seen_trae_uids = set()

    # 1. 提取 CodeBuddy 扩展插件凭据 (旧版/插件明文存储)
    local_app_data = os.getenv("LOCALAPPDATA", "")
    if local_app_data:
        cb_path = os.path.join(local_app_data, "CodeBuddyExtension", "Data", "Public", "auth", "Tencent-Cloud.coding-copilot.info")
        if os.path.exists(cb_path):
            try:
                with open(cb_path, "r", encoding="utf-8") as f:
                    cb_json = json.load(f)
                uid = cb_json.get("account", {}).get("uid", "")
                at = cb_json.get("auth", {}).get("accessToken", "")
                if at:
                    extracted["codebuddy"].append({
                        "accessToken": at,
                        "refreshToken": cb_json.get("auth", {}).get("refreshToken", ""),
                        "nickname": cb_json.get("account", {}).get("nickname", "腾讯用户"),
                        "phone": cb_json.get("account", {}).get("phoneNumber", ""),
                        "uid": uid,
                        "source": "CodeBuddy插件"
                    })
                    if uid: seen_cb_uids.add(uid)
                    print(f"✅ 成功提取 CodeBuddy 插件登录凭据 (UID: {uid[:8]}...)")
            except Exception as e:
                print(f"⚠️ 读取 CodeBuddy 插件凭据失败: {e}")

    # 2. 提取 WorkBuddy 桌面客户端凭据 (新版安全加密存储)
    wb_accounts = extract_workbuddy_desktop()
    for acc in wb_accounts:
        uid = acc.get("uid", "")
        if uid and uid not in seen_cb_uids:
            seen_cb_uids.add(uid)
            extracted["codebuddy"].append(acc)
            print(f"✅ 成功解密 WorkBuddy 桌面客户端登录凭据 (账号: {acc.get('nickname')}, UID: {uid[:8]}...)")
        elif not uid:
            extracted["codebuddy"].append(acc)

    # 3. 提取 TRAE 凭据 (扫描所有安装实例：TRAE SOLO CN / Trae CN)
    appdata = os.getenv("APPDATA", "")
    if appdata:
        trae_candidates = [
            ("TRAE SOLO CN", os.path.join(appdata, "TRAE SOLO CN", "User", "globalStorage", "storage.json")),
            ("Trae CN", os.path.join(appdata, "Trae CN", "User", "globalStorage", "storage.json"))
        ]
        for name, sp in trae_candidates:
            if os.path.exists(sp):
                try:
                    with open(sp, "r", encoding="utf-8") as f:
                        t_json = json.load(f)
                    auth_val = t_json.get(STORAGE_KEY)
                    if auth_val:
                        dec = decrypt_trae_storage_value(auth_val).decode("utf-8", "replace")
                        at = re.search(r'"token"\s*:\s*"([^"]+)"', dec)
                        rt = re.search(r'"refreshToken"\s*:\s*"([^"]+)"', dec)
                        uid = re.search(r'"userId"\s*:\s*"(\d+)"', dec)

                        real_device_id = "766820083601979"
                        for k in t_json.keys():
                            if k.startswith("iCubeAuthInfo://icube-dc:"):
                                real_device_id = k.split(":")[-1]
                                break

                        uid_val = uid.group(1) if uid else ""
                        if at and at.group(1):
                            if uid_val not in seen_trae_uids:
                                seen_trae_uids.add(uid_val)
                                extracted["trae"].append({
                                    "accessToken": at.group(1),
                                    "refreshToken": rt.group(1) if rt else "",
                                    "uid": uid_val,
                                    "deviceId": real_device_id,
                                    "source": name
                                })
                                print(f"✅ 成功提取 [{name}] 登录凭据 (UID: {uid_val})")
                except Exception as e:
                    print(f"⚠️ 读取 TRAE [{name}] 失败: {e}")

    # 4. 提取 Qoder 客户端凭据 (DPAPI + AES-256-GCM 安全存储)
    extracted["qoder"] = extract_qoder()

    return extracted

def push_to_remote(server_url, key, platform, acc_data):
    try:
        import urllib.request
        no_proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(no_proxy_handler)

        sep = "&" if "?" in server_url else "?"
        url = server_url.rstrip("/") + f"/api/account/save{sep}key={key}"
        
        remark = acc_data.get("remark")
        if not remark:
            if platform == "codebuddy":
                nick = acc_data.get("nickname") or acc_data.get("phone") or "用户"
                remark = f"{acc_data.get('source', 'CodeBuddy')} ({nick})"
            elif platform == "qoder":
                nick = acc_data.get("name") or acc_data.get("phone") or "Qoder用户"
                remark = f"{acc_data.get('source', 'Qoder')} ({nick})"
            else:
                remark = f"TRAE ({acc_data.get('source', '客户端')} UID: {acc_data.get('uid')})"

        payload = {
            "id": acc_data.get("id"),
            "platform": platform,
            "remark": remark,
            "phone": acc_data.get("phone", ""),
            "accessToken": acc_data.get("accessToken") or acc_data.get("token", ""),
            "token": acc_data.get("token") or acc_data.get("accessToken", ""),
            "refreshToken": acc_data.get("refreshToken", ""),
            "uid": acc_data.get("uid", ""),
            "name": acc_data.get("name", ""),
            "deviceId": acc_data.get("deviceId", "766820083601979")
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AI-Hub-Sync/1.0",
                "X-Hub-Key": key
            }
        )
        for attempt in range(1, 3):
            try:
                with opener.open(req, timeout=25) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    if res.get("success"):
                        print(f"  ☁️  远程同步成功 [{platform}] {payload['remark']}: {res.get('message', '账号已入库')}")
                        return True
                    else:
                        print(f"  ⚠️  远程同步失败 [{platform}] {payload['remark']}: {res.get('error')}")
                        return False
            except Exception as ex:
                if attempt < 2:
                    time.sleep(1.5)
                    continue
                print(f"  ❌ 远程推送失败 [{platform}]: {ex}")
                return False
        return False
    except Exception as e:
        print(f"  ❌ 远程推送准备异常 [{platform}]: {e}")
        return False

def main():
    import argparse
    parser = argparse.ArgumentParser(description="AI-Credits-Hub 本机凭据提取与同步")
    parser.add_argument("--server", help="远程 Hub 服务器地址，例如 http://47.77.190.116:9527")
    parser.add_argument("--key", help="远程 Hub 密钥", default="Hub_98bxy_Sec2026")
    parser.add_argument("--push", action="store_true", help="是否直接推送到云端")
    args = parser.parse_args()

    print("=" * 64)
    print("       🚀 本地 AI 客户端凭据一键提取与多账号同步工具")
    print("=" * 64)

    data = extract_all()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_file = os.path.join(script_dir, "config.json")

    # 读取本地已有配置
    cfg = {"auth": {"admin_key": "Hub_98bxy_Sec2026"}, "codebuddy_accounts": [], "trae_accounts": []}
    if os.path.exists(out_file):
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

    if "codebuddy_accounts" not in cfg:
        cfg["codebuddy_accounts"] = []
    if "trae_accounts" not in cfg:
        cfg["trae_accounts"] = []
    if "qoder_accounts" not in cfg:
        cfg["qoder_accounts"] = []

    # 追加或更新所有 CodeBuddy 账号
    for cb in data.get("codebuddy", []):
        cb_uid = cb.get("uid", "")
        existing = next((a for a in cfg["codebuddy_accounts"] if a.get("uid") == cb_uid and cb_uid), None)
        if existing:
            existing["accessToken"] = cb["accessToken"]
            existing["refreshToken"] = cb.get("refreshToken", "")
            existing["nickname"] = cb.get("nickname", existing.get("nickname", "用户"))
            existing["phone"] = cb.get("phone", existing.get("phone", ""))
        else:
            nick = cb.get("nickname") or cb.get("phone") or "用户"
            cfg["codebuddy_accounts"].append({
                "id": "cb_" + uuid.uuid4().hex[:8],
                "remark": f"{cb.get('source', 'CodeBuddy')} ({nick})",
                "accessToken": cb["accessToken"],
                "refreshToken": cb.get("refreshToken", ""),
                "nickname": nick,
                "phone": cb.get("phone", ""),
                "uid": cb_uid,
                "enabled": True
            })

    # 追加或更新所有 TRAE 账号
    for trae in data.get("trae", []):
        trae_uid = trae.get("uid", "")
        existing = next((a for a in cfg["trae_accounts"] if a.get("uid") == trae_uid and trae_uid), None)
        if existing:
            existing["accessToken"] = trae["accessToken"]
            existing["refreshToken"] = trae.get("refreshToken", "")
            existing["deviceId"] = trae.get("deviceId", "766820083601979")
        else:
            cfg["trae_accounts"].append({
                "id": "trae_" + uuid.uuid4().hex[:8],
                "remark": f"{trae.get('source', 'TRAE')} (UID: {trae_uid})",
                "accessToken": trae["accessToken"],
                "refreshToken": trae.get("refreshToken", ""),
                "uid": trae_uid,
                "deviceId": trae.get("deviceId", "766820083601979"),
                "enabled": True
            })

    # 追加或更新所有 Qoder 账号
    for qd in data.get("qoder", []):
        qd_uid = qd.get("uid", "")
        qd_token = qd.get("token", "")
        existing = next((a for a in cfg["qoder_accounts"] if (qd_uid and a.get("uid") == qd_uid) or (qd_token and a.get("token") == qd_token)), None)
        if existing:
            existing["token"] = qd_token
            existing["refreshToken"] = qd.get("refreshToken", "")
            existing["name"] = qd.get("name", existing.get("name", "Qoder用户"))
            existing["phone"] = qd.get("phone", existing.get("phone", ""))
        else:
            nick = qd.get("name") or qd.get("phone") or "Qoder用户"
            cfg["qoder_accounts"].append({
                "id": "qoder_" + uuid.uuid4().hex[:8],
                "remark": f"{qd.get('source', 'Qoder')} ({nick})",
                "token": qd_token,
                "refreshToken": qd.get("refreshToken", ""),
                "name": nick,
                "phone": qd.get("phone", ""),
                "uid": qd_uid,
                "enabled": True
            })

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    print(f"\n🎉 凭证已成功保存至本地配置文件: {out_file}")
    print(f"📊 当前识别到本地有效账号数: CodeBuddy/WorkBuddy x {len(data['codebuddy'])} 个, TRAE x {len(data['trae'])} 个, Qoder x {len(data['qoder'])} 个")

    remote = args.server
    key = args.key
    if not remote and not args.push:
        try:
            remote = input("\n👉 是否推送到远程云服务器？(直接回车跳过，或输入如 http://47.77.190.116:9527): ").strip()
            if remote:
                key = input("👉 请输入远程管理密钥 (默认 Hub_98bxy_Sec2026): ").strip() or "Hub_98bxy_Sec2026"
        except (KeyboardInterrupt, EOFError):
            pass

    if remote:
        print(f"\n正在同步到云端服务器: {remote} ...")
        for cb in data.get("codebuddy", []):
            existing = next((a for a in cfg.get("codebuddy_accounts", []) if a.get("uid") == cb.get("uid") and cb.get("uid")), None)
            if existing:
                if existing.get("remark"):
                    cb["remark"] = existing["remark"]
                if existing.get("id"):
                    cb["id"] = existing["id"]
            push_to_remote(remote, key, "codebuddy", cb)
        for trae in data.get("trae", []):
            existing = next((a for a in cfg.get("trae_accounts", []) if a.get("uid") == trae.get("uid") and trae.get("uid")), None)
            if existing:
                if existing.get("remark"):
                    trae["remark"] = existing["remark"]
                if existing.get("id"):
                    trae["id"] = existing["id"]
            push_to_remote(remote, key, "trae", trae)
        for qd in data.get("qoder", []):
            existing = next((a for a in cfg.get("qoder_accounts", []) if a.get("uid") == qd.get("uid") and qd.get("uid")), None)
            if existing:
                if existing.get("remark"):
                    qd["remark"] = existing["remark"]
                if existing.get("id"):
                    qd["id"] = existing["id"]
            push_to_remote(remote, key, "qoder", qd)
        print("\n✅ 所有账号远程多账号同步完成！")

    print("=" * 64)

if __name__ == "__main__":
    main()
