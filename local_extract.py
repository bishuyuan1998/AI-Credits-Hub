#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
====================================================================
      本地 AI 客户端凭据一键提取与多账号同步工具 (Local Extract)
====================================================================
功能：
  • 自动探测本机安装的 CodeBuddy / WorkBuddy 与 TRAE 客户端
  • 纯标准库内置 AES-128-CBC 算法自解密，零第三方复杂依赖
  • 自动提取当前账号凭据，支持追加到多账号池
  • 支持一键推送到远程云服务器智能管家
====================================================================
"""

import os
import sys
import json
import base64
import hashlib
import re
import uuid

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

def extract_all():
    extracted = {
        "codebuddy": {},
        "trae": {}
    }

    # 1. 提取 CodeBuddy
    local_app_data = os.getenv("LOCALAPPDATA", "")
    if local_app_data:
        cb_path = os.path.join(local_app_data, "CodeBuddyExtension", "Data", "Public", "auth", "Tencent-Cloud.coding-copilot.info")
        if os.path.exists(cb_path):
            try:
                with open(cb_path, "r", encoding="utf-8") as f:
                    cb_json = json.load(f)
                extracted["codebuddy"] = {
                    "accessToken": cb_json.get("auth", {}).get("accessToken", ""),
                    "refreshToken": cb_json.get("auth", {}).get("refreshToken", ""),
                    "nickname": cb_json.get("account", {}).get("nickname", "腾讯用户"),
                    "uid": cb_json.get("account", {}).get("uid", "")
                }
                print("✅ 成功提取 CodeBuddy / WorkBuddy 本机登录凭据")
            except Exception as e:
                print(f"⚠️ 读取 CodeBuddy 失败: {e}")

    # 2. 提取 TRAE
    appdata = os.getenv("APPDATA", "")
    if appdata:
        trae_candidates = [
            os.path.join(appdata, "TRAE SOLO CN", "User", "globalStorage", "storage.json"),
            os.path.join(appdata, "Trae CN", "User", "globalStorage", "storage.json")
        ]
        for sp in trae_candidates:
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
                                
                        extracted["trae"] = {
                            "accessToken": at.group(1) if at else "",
                            "refreshToken": rt.group(1) if rt else "",
                            "uid": uid.group(1) if uid else "",
                            "deviceId": real_device_id
                        }
                        print("✅ 成功提取 TRAE 本机登录凭据与设备指纹")
                        break
                except Exception as e:
                    print(f"⚠️ 读取 TRAE 失败: {e}")

    return extracted

def push_to_remote(server_url, key, platform, acc_data):
    try:
        import urllib.request
        url = server_url.rstrip("/") + "/api/account/save"
        payload = {
            "platform": platform,
            "remark": acc_data.get("remark") or acc_data.get("nickname") or "本机自动提取账号",
            "phone": acc_data.get("phone", ""),
            "accessToken": acc_data.get("accessToken", ""),
            "refreshToken": acc_data.get("refreshToken", ""),
            "uid": acc_data.get("uid", ""),
            "deviceId": acc_data.get("deviceId", "766820083601979")
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Hub-Key": key
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("success"):
                print(f"  ☁️ 远程同步成功 [{platform}]: {res.get('id')}")
            else:
                print(f"  ⚠️ 远程同步失败 [{platform}]: {res.get('error')}")
    except Exception as e:
        print(f"  ❌ 远程推送失败: {e}")

def main():
    print("=" * 64)
    print("       🚀 本地 AI 客户端凭据一键提取与多账号同步工具")
    print("=" * 64)

    data = extract_all()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_file = os.path.join(script_dir, "config.json")

    # 读取已有配置
    cfg = {"auth": {"admin_key": "888888"}, "codebuddy_accounts": [], "trae_accounts": []}
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

    # 追加或更新 CodeBuddy 账号
    if data.get("codebuddy", {}).get("accessToken"):
        cb = data["codebuddy"]
        cb_uid = cb.get("uid", "")
        existing = next((a for a in cfg["codebuddy_accounts"] if a.get("uid") == cb_uid and cb_uid), None)
        if existing:
            existing["accessToken"] = cb["accessToken"]
            existing["nickname"] = cb.get("nickname", "用户")
        else:
            cfg["codebuddy_accounts"].append({
                "id": "cb_" + uuid.uuid4().hex[:8],
                "remark": f"本机 CodeBuddy ({cb.get('nickname', '主号')})",
                "accessToken": cb["accessToken"],
                "refreshToken": cb.get("refreshToken", ""),
                "nickname": cb.get("nickname", "用户"),
                "uid": cb_uid,
                "enabled": True
            })

    # 追加或更新 TRAE 账号
    if data.get("trae", {}).get("accessToken"):
        trae = data["trae"]
        trae_uid = trae.get("uid", "")
        existing = next((a for a in cfg["trae_accounts"] if a.get("uid") == trae_uid and trae_uid), None)
        if existing:
            existing["accessToken"] = trae["accessToken"]
        else:
            cfg["trae_accounts"].append({
                "id": "trae_" + uuid.uuid4().hex[:8],
                "remark": f"本机 TRAE (UID: {trae_uid})",
                "accessToken": trae["accessToken"],
                "refreshToken": trae.get("refreshToken", ""),
                "uid": trae_uid,
                "deviceId": trae.get("deviceId", "766820083601979"),
                "enabled": True
            })

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    print(f"\n🎉 凭证已成功保存至本地多账号配置文件: {out_file}")

    # 询问是否推送到云服务器
    try:
        remote = input("\n👉 是否推送到远程云服务器？(直接按回车跳过，或输入服务器地址如 http://47.77.190.116:9527): ").strip()
        if remote:
            key = input("👉 请输入远程管理密钥 (默认 888888): ").strip() or "888888"
            print("正在同步到云端...")
            if data.get("codebuddy", {}).get("accessToken"):
                push_to_remote(remote, key, "codebuddy", data["codebuddy"])
            if data.get("trae", {}).get("accessToken"):
                push_to_remote(remote, key, "trae", data["trae"])
            print("✅ 远程多账号同步完成！")
    except (KeyboardInterrupt, EOFError):
        pass

    print("=" * 64)

if __name__ == "__main__":
    main()
