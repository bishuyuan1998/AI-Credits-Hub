#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
====================================================================
           本地 AI 客户端凭据一键提取与同步工具 (Local Extract)
====================================================================
功能：
  • 自动探测本机安装的 CodeBuddy / WorkBuddy 与 TRAE 客户端
  • 纯标准库内置 AES-128-CBC 算法自解密，零第三方复杂依赖
  • 自动生成本地 config.json，并支持一键推送到云服务器
====================================================================
"""

import os
import sys
import json
import base64
import hashlib
import re

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ====================================================================
#  TRAE AES-128-CBC 纯算法解密
# ====================================================================
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


def main():
    print("=" * 64)
    print("       🚀 本地 AI 客户端凭据一键提取与配置生成工具")
    print("=" * 64)

    data = extract_all()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_file = os.path.join(script_dir, "config.json")

    # 如果已有密码配置，保留密码
    admin_pwd = ""
    if os.path.exists(out_file):
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                old = json.load(f)
                admin_pwd = old.get("auth", {}).get("admin_password", "")
        except Exception:
            pass

    full_cfg = {
        "auth": {
            "admin_password": admin_pwd
        },
        "codebuddy": data["codebuddy"],
        "trae": data["trae"]
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(full_cfg, f, indent=2, ensure_ascii=False)

    print(f"\n🎉 凭证已成功保存至本地配置文件: {out_file}")
    print("💡 提示：config.json 已被 .gitignore 忽略，请放心使用，切勿泄露给他人。")
    print("=" * 64)


if __name__ == "__main__":
    main()
