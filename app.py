#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
====================================================================
           AI-Credits-Hub · AI 算力与积分智能管家 (多账号版)
====================================================================
GitHub: https://github.com/bishuyuan1998/AI-Credits-Hub
License: MIT
====================================================================
"""

import os
import sys
import json
import time
import uuid
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs
from http.cookies import SimpleCookie

# 保证控制台输出 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("[错误] 缺少 requests 库，请执行: pip install requests")
    sys.exit(1)

PORT = int(os.environ.get("PORT", 9527))
if len(sys.argv) > 1 and sys.argv[1].isdigit():
    PORT = int(sys.argv[1])

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
EXAMPLE_CONFIG = os.path.join(SCRIPT_DIR, "config.example.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "checkin.log")

def get_session():
    s = requests.Session()
    adapter = HTTPAdapter(max_retries=Retry(total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504]))
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

def log(msg):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{now_str}] {msg}"
    print(formatted)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

def extract_jwt_claims(token):
    try:
        parts = token.strip().split(".")
        if len(parts) >= 2:
            import base64
            b64_str = parts[1]
            pad = len(b64_str) % 4
            if pad:
                b64_str += "=" * (4 - pad)
            payload = base64.urlsafe_b64decode(b64_str.encode("ascii")).decode("utf-8", "ignore")
            return json.loads(payload)
    except Exception:
        pass
    return {}

def format_phone(p):
    p = str(p or "").strip()
    if len(p) == 11 and p.isdigit():
        return f"{p[:3]}****{p[-4:]}"
    return p


def deduplicate_accounts(cfg):
    """全局自动去重：按照 uid / token 合并同账号，防止重复卡片，保留用户自定义备注"""
    changed = False

    for key_name in ["codebuddy_accounts", "trae_accounts", "qoder_accounts"]:
        accounts = cfg.get(key_name, [])
        if not accounts:
            continue

        unique_map = {}
        cleaned_list = []

        for acc in accounts:
            uid = str(acc.get("uid") or "").strip()
            token = (acc.get("token") or acc.get("accessToken") or "").strip()
            # 唯一标识优先用 uid，其次用 token 签名
            ident = uid if uid else (token[:32] if token else acc.get("id"))

            if not ident:
                cleaned_list.append(acc)
                continue

            if ident not in unique_map:
                unique_map[ident] = acc
                cleaned_list.append(acc)
            else:
                existing = unique_map[ident]
                changed = True
                
                # 保留非泛型自定义备注
                cur_remark = existing.get("remark", "")
                new_remark = acc.get("remark", "")
                is_cur_generic = not cur_remark or "UID:" in cur_remark or cur_remark.startswith("主账号") or cur_remark in ("我的账号", "用户")
                is_new_generic = not new_remark or "UID:" in new_remark or new_remark.startswith("主账号") or new_remark in ("我的账号", "用户")
                
                if is_cur_generic and not is_new_generic:
                    existing["remark"] = new_remark
                    existing["is_custom_remark"] = True
                elif acc.get("is_custom_remark") and not existing.get("is_custom_remark"):
                    existing["remark"] = new_remark
                    existing["is_custom_remark"] = True

                # 合并属性
                for k in ["phone", "accessToken", "token", "refreshToken", "deviceId", "name", "nickname"]:
                    if not existing.get(k) and acc.get(k):
                        existing[k] = acc[k]

        if changed or len(cleaned_list) != len(accounts):
            cfg[key_name] = cleaned_list
            changed = True

    # 移除可能遗留的旧版单账号字典
    if "trae" in cfg and isinstance(cfg["trae"], dict):
        del cfg["trae"]
        changed = True
    if "codebuddy" in cfg and isinstance(cfg["codebuddy"], dict):
        del cfg["codebuddy"]
        changed = True

    return changed

def load_config():
    """读取配置并自动将旧的单账号格式平滑迁移为多账号列表"""
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            log(f"[配置读取失败] {e}")
            cfg = {}
    elif os.path.exists(EXAMPLE_CONFIG):
        try:
            with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

    changed = False
    if "auth" not in cfg:
        cfg["auth"] = {"admin_key": "Hub_98bxy_Sec2026", "admin_password": ""}
        changed = True
    if "settings" not in cfg:
        cfg["settings"] = {"auto_checkin_hour": 9, "auto_checkin_minute": 0}
        changed = True

    # 平滑迁移旧 CodeBuddy 账号 -> 账号列表
    if "codebuddy_accounts" not in cfg:
        cfg["codebuddy_accounts"] = []
        old_cb = cfg.get("codebuddy")
        if old_cb and isinstance(old_cb, dict) and old_cb.get("accessToken"):
            cfg["codebuddy_accounts"].append({
                "id": "cb_" + uuid.uuid4().hex[:8],
                "remark": old_cb.get("nickname") or "主账号",
                "phone": old_cb.get("phone", ""),
                "accessToken": old_cb.get("accessToken", "").strip(),
                "refreshToken": old_cb.get("refreshToken", "").strip(),
                "uid": old_cb.get("uid", ""),
                "nickname": old_cb.get("nickname", "用户"),
                "enabled": True
            })
            changed = True

    # 自动从 JWT 中补全 CodeBuddy 手机号
    for acc in cfg.get("codebuddy_accounts", []):
        if not acc.get("phone") and acc.get("accessToken"):
            c = extract_jwt_claims(acc["accessToken"])
            if c.get("preferred_username"):
                acc["phone"] = str(c.get("preferred_username")).strip()
                changed = True

    # 平滑迁移旧 TRAE 账号 -> 账号列表
    if "trae_accounts" not in cfg:
        cfg["trae_accounts"] = []
    if "qoder_accounts" not in cfg:
        cfg["qoder_accounts"] = []
        old_trae = cfg.get("trae")
        if old_trae and isinstance(old_trae, dict) and old_trae.get("accessToken"):
            cfg["trae_accounts"].append({
                "id": "trae_" + uuid.uuid4().hex[:8],
                "remark": f"主账号 (UID: {old_trae.get('uid', '未设')})",
                "phone": old_trae.get("phone", ""),
                "accessToken": old_trae.get("accessToken", "").strip(),
                "refreshToken": old_trae.get("refreshToken", "").strip(),
                "uid": str(old_trae.get("uid", "")),
                "deviceId": old_trae.get("deviceId", "766820083601979"),
                "enabled": True
            })
            changed = True

    if deduplicate_accounts(cfg):
        changed = True

    if changed and os.path.exists(CONFIG_FILE):
        try:
            save_config(cfg)
        except Exception:
            pass

    return cfg

def save_config(cfg):
    deduplicate_accounts(cfg)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ====================================================================
#  数据采集与校验逻辑
# ====================================================================
def fetch_single_codebuddy(acc):
    token = acc.get("accessToken", "").strip()
    claims = extract_jwt_claims(token)
    phone = acc.get("phone") or claims.get("preferred_username") or ""
    uid = acc.get("uid") or claims.get("sub") or ""
    nickname = acc.get("nickname") or claims.get("nickname") or ""
    res = {
        "id": acc.get("id"),
        "remark": acc.get("remark") or "我的账号",
        "nickname": nickname or "用户",
        "phone": phone,
        "masked_phone": format_phone(phone),
        "uid": uid or "-",
        "enabled": acc.get("enabled", True),
        "active": bool(token),
        "today_checked": False,
        "credits": 0,
        "total_earned": 0,
        "plan_name": "体验版",
        "streak_days": 0,
        "expire_time": "-",
        "expire_days": 0,
        "status_text": "未配置 Token",
        "valid": False
    }
    if not token:
        return res

    s = get_session()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-User-Id": uid,
        "Accept-Language": "zh",
        "Origin": "https://www.codebuddy.cn",
        "Referer": "https://www.codebuddy.cn/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WorkBuddy/1.0.0",
        "Content-Type": "application/json"
    }

    # 1. 查询真实实时可用积分余额与套餐版本 (get-user-resource-summary)
    has_summary = False
    try:
        r_sum = s.post("https://www.codebuddy.cn/billing/meter/get-user-resource-summary", headers=headers, json={}, timeout=8)
        if r_sum.status_code == 200 and r_sum.json().get("code") == 0:
            d_sum = r_sum.json().get("data", {})
            has_summary = True
            total_credits_val = d_sum.get("TotalCredits", 0)
            res["credits"] = round(float(total_credits_val), 1)
            is_paid = d_sum.get("IsPaidUser", False)
            pkg_name = d_sum.get("SubscriptionPackageName")
            res["plan_name"] = pkg_name if pkg_name else ("付费专业版" if is_paid else "体验版")
    except Exception as e:
        log(f"[CodeBuddy 余额查询异常] {e}")

    # 2. 查询每日签到状态与连签天数 (checkin-activity-status)
    try:
        r = s.post("https://www.codebuddy.cn/v2/billing/meter/checkin-activity-status", headers=headers, json={}, timeout=8)
        if r.status_code == 200 and r.json().get("code") == 0:
            d = r.json().get("data", {})
            res["valid"] = True
            res["today_checked"] = d.get("today_checked_in", False)
            res["total_earned"] = d.get("total_credits", 0)
            if not has_summary:
                res["credits"] = d.get("total_credits", 0)
            res["streak_days"] = d.get("streak_days", 0)
            res["expire_time"] = d.get("end_time", "2026-12-31 23:59:59")
            try:
                diff = datetime.datetime.strptime(res["expire_time"], "%Y-%m-%d %H:%M:%S") - datetime.datetime.now()
                res["expire_days"] = max(0, diff.days)
            except Exception:
                res["expire_days"] = 60
            res["status_text"] = f"连签 {res['streak_days']} 天 · 累计所得 {res['total_earned']}"
        elif r.status_code == 401:
            if has_summary:
                res["valid"] = True
                res["status_text"] = "有效账号"
            else:
                res["status_text"] = "Token 已失效 (401)"
        else:
            if has_summary:
                res["valid"] = True
                res["status_text"] = "有效账号"
            else:
                res["status_text"] = f"响应异常 ({r.status_code})"
    except Exception as e:
        if has_summary:
            res["valid"] = True
            res["status_text"] = "有效账号"
        else:
            res["status_text"] = f"请求错误: {str(e)[:25]}"
    return res

def fetch_single_trae(acc):
    token = acc.get("accessToken", "").strip()
    phone = acc.get("phone") or acc.get("username") or ""
    res = {
        "id": acc.get("id"),
        "remark": acc.get("remark") or "未命名账号",
        "phone": phone,
        "masked_phone": format_phone(phone),
        "uid": acc.get("uid") or "未配置",
        "deviceId": acc.get("deviceId") or "766820083601979",
        "enabled": acc.get("enabled", True),
        "active": bool(token),
        "today_checked": False,
        "credits": 0,
        "total_credits": 600,
        "consumed": 0,
        "used_pct": 0,
        "expire_time": "-",
        "expire_days": 0,
        "status_text": "未配置 Token",
        "valid": False
    }
    if not token:
        return res

    s = get_session()
    headers = {
        "Authorization": "Cloud-IDE-JWT " + token,
        "X-User-Region": "CN",
        "User-Agent": "Trae/1.107.1",
        "Content-Type": "application/json",
        "x-device-id": res["deviceId"],
        "x-device-type": "Windows",
        "x-os-version": "10.0.19045",
        "x-app-version": "1.107.1"
    }

    # 1. 签到状态
    try:
        r_st = s.post("https://api.trae.cn/trae/api/v2/ug/checkin_credits/status", headers=headers, data='{"req_source": 1}', timeout=8)
        if r_st.status_code == 200 and r_st.json().get("code") == 0:
            res["today_checked"] = r_st.json().get("did_checked_in", False)
    except Exception:
        pass

    # 2. 额度与权益列表
    try:
        r_ent = s.post("https://api.trae.cn/trae/api/v2/pay/user_current_entitlement_list", headers=headers, json={}, timeout=8)
        if r_ent.status_code == 200:
            ent = r_ent.json()
            sm = ent.get("usage_summary", {})
            total_amt = sm.get("total_amount", 600)
            consumed = sm.get("consumed_amount", 0)
            res["valid"] = True
            res["total_credits"] = total_amt
            res["consumed"] = round(consumed, 1)
            res["credits"] = round(total_amt - consumed, 1)
            res["used_pct"] = round((consumed / total_amt * 100), 1) if total_amt else 0
            packs = ent.get("user_entitlement_pack_list", [])
            if packs:
                ts = packs[0].get("entitlement_base_info", {}).get("end_time")
                if ts:
                    exp = datetime.datetime.fromtimestamp(ts)
                    res["expire_time"] = exp.strftime("%Y-%m-%d %H:%M:%S")
                    res["expire_days"] = max(0, (exp - datetime.datetime.now()).days)
            res["status_text"] = "今日已签" if res["today_checked"] else "待签到"
        elif r_ent.status_code == 401 or (r_st.status_code == 200 and r_st.json().get("code") == 1001):
            res["status_text"] = "Token 已失效 (401)"
        else:
            res["status_text"] = f"响应异常 ({r_ent.status_code})"
    except Exception as e:
        res["status_text"] = f"请求错误: {str(e)[:25]}"

    return res

def checkin_codebuddy_account(acc):
    token = acc.get("accessToken", "").strip()
    if not token or not acc.get("enabled", True):
        return "未启用或无 Token"
    claims = extract_jwt_claims(token)
    uid = acc.get("uid") or claims.get("sub") or ""
    s = get_session()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-User-Id": uid,
        "Accept-Language": "zh",
        "Origin": "https://www.codebuddy.cn",
        "Referer": "https://www.codebuddy.cn/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WorkBuddy/1.0.0",
        "Content-Type": "application/json"
    }
    try:
        r = s.post("https://www.codebuddy.cn/v2/billing/meter/daily-checkin", headers=headers, timeout=8)
        if r.status_code == 200:
            return r.json().get("msg", "签到成功")
        return f"HTTP {r.status_code}"
    except Exception as e:
        return f"网络异常: {e}"

def checkin_trae_account(acc):
    token = acc.get("accessToken", "").strip()
    if not token or not acc.get("enabled", True):
        return "未启用或无 Token"
    s = get_session()
    headers = {
        "Authorization": "Cloud-IDE-JWT " + token,
        "X-User-Region": "CN",
        "User-Agent": "Trae/1.107.1",
        "Content-Type": "application/json",
        "x-device-id": acc.get("deviceId", "766820083601979"),
        "x-device-type": "Windows",
        "x-os-version": "10.0.19045",
        "x-app-version": "1.107.1"
    }
    try:
        r = s.post("https://api.trae.cn/trae/api/v2/ug/checkin_credits/claim", headers=headers, data='{"req_source": 1}', timeout=8)
        if r.status_code == 200:
            return r.json().get("message", "签到成功")
        return f"HTTP {r.status_code}"
    except Exception as e:
        return f"网络异常: {e}"


def fetch_single_qoder(acc):
    token = (acc.get("token") or acc.get("accessToken") or "").strip()
    phone = acc.get("phone") or ""
    res = {
        "id": acc.get("id"),
        "remark": acc.get("remark") or "我的 Qoder 账号",
        "phone": phone,
        "masked_phone": format_phone(phone) if phone else (acc.get("name") or "Qoder用户"),
        "name": acc.get("name") or "Qoder用户",
        "uid": acc.get("uid") or "未配置",
        "enabled": acc.get("enabled", True),
        "active": bool(token),
        "today_checked": False,
        "credits": 0,
        "total_credits": 1000,
        "consumed": 0,
        "used_pct": 0,
        "plan_name": "Free 体验版",
        "expire_time": "30天滚动有效",
        "expire_days": 30,
        "status_text": "未配置 Token",
        "valid": False,
        "campaign_id": ""
    }
    if not token:
        return res

    s = get_session()
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "Cosy-ClientType": "10",
        "Cosy-Version": "0.4.8",
        "User-Agent": "Qoder"
    }

    # 1. 查询活动与今日签到状态 (每天领 100 Credits)
    try:
        r_camp = s.get("https://openapi.qoder.com.cn/sash/api/v1/me/campaigns", headers=headers, timeout=8)
        if r_camp.status_code == 200:
            cdata = r_camp.json()
            for c in cdata.get("campaigns", []):
                if c.get("actionType") == "CLAIM_BENEFIT" and c.get("benefit", {}).get("kind") == "CREDITS":
                    res["campaign_id"] = c.get("campaignId", "")
                    res["today_checked"] = (c.get("claimStatus") == "CLAIMED")
                    break
    except Exception:
        pass

    # 2. 查询用量与额度 (Usage)
    try:
        r_usg = s.get("https://openapi.qoder.com.cn/sash/api/v2/me/usage", headers=headers, timeout=8)
        if r_usg.status_code == 200:
            res["valid"] = True
            udata = r_usg.json()
            qu = udata.get("qoderUsage", {})
            user_q = qu.get("userQuota", {})
            addon_q = qu.get("addOnQuota", {})
            
            tot = user_q.get("total", 0) + addon_q.get("total", 0)
            rem = user_q.get("remaining", 0) + addon_q.get("remaining", 0)
            used = user_q.get("used", 0) + addon_q.get("used", 0)
            
            res["total_credits"] = tot if tot > 0 else 1000
            res["credits"] = rem
            res["consumed"] = used
            res["used_pct"] = round((used / tot * 100), 1) if tot > 0 else 0
            
            exp_ts = qu.get("expiresAt")
            if exp_ts and exp_ts < 253402214400000:
                exp = datetime.datetime.fromtimestamp(exp_ts / 1000 if exp_ts > 1e11 else exp_ts)
                res["expire_time"] = exp.strftime("%Y-%m-%d %H:%M:%S")
                res["expire_days"] = max(0, (exp - datetime.datetime.now()).days)
            else:
                res["expire_time"] = "30天滚动有效"
                res["expire_days"] = 30
                
            res["status_text"] = "今日已领 100 Credits" if res["today_checked"] else "待领取 100 Credits"
        elif r_usg.status_code == 401:
            res["status_text"] = "Token 已失效 (401)"
        else:
            res["status_text"] = f"响应异常 ({r_usg.status_code})"
    except Exception as e:
        res["status_text"] = f"请求错误: {str(e)[:25]}"

    return res

DEFAULT_QODER_CAMPAIGN_ID = "01a1bbe3-30ba-72fc-b08c-77074f059623"

def checkin_qoder_account(acc):
    token = (acc.get("token") or acc.get("accessToken") or "").strip()
    if not token or not acc.get("enabled", True):
        return "未启用或无 Token"
    s = get_session()
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "Cosy-ClientType": "10",
        "Cosy-Version": "0.4.8",
        "User-Agent": "Qoder"
    }
    try:
        campaign_id = acc.get("campaign_id")
        if not campaign_id:
            r_c = s.get("https://openapi.qoder.com.cn/sash/api/v1/me/campaigns", headers=headers, timeout=8)
            if r_c.status_code == 200:
                for c in r_c.json().get("campaigns", []):
                    if c.get("actionType") == "CLAIM_BENEFIT" and c.get("benefit", {}).get("kind") == "CREDITS":
                        campaign_id = c.get("campaignId")
                        if c.get("claimStatus") == "CLAIMED":
                            return "今日已领 100 Credits (无需重复领取)"
                        break

        # 若未在个人活动列表中返回，使用默认每日打卡活动 ID
        if not campaign_id:
            campaign_id = DEFAULT_QODER_CAMPAIGN_ID

        r_claim = s.post(f"https://openapi.qoder.com.cn/sash/api/v1/me/campaigns/{campaign_id}/claim", headers=headers, json={}, timeout=8)
        if r_claim.status_code == 200:
            cres = r_claim.json()
            if cres.get("replayed"):
                return "今日已领 100 Credits (无需重复领取)"
            if cres.get("failureCode") == "SAME_PERSON_ALREADY_CLAIMED":
                return "今日已领 100 Credits (同实名认证已领取)"
            if cres.get("status") == "BLOCKED":
                return f"领取受限: {cres.get('failureCode', '风控保护')}"
            return "🎉 成功领取今日 100 Credits 算力！"
        return f"HTTP {r_claim.status_code}: {r_claim.text[:50]}"
    except Exception as e:
        return f"网络异常: {e}"

def execute_all_checkin():
    cfg = load_config()
    results = []

    # CodeBuddy 批量签到
    cb_accounts = cfg.get("codebuddy_accounts", [])
    for acc in cb_accounts:
        if acc.get("enabled", True) and acc.get("accessToken"):
            res = checkin_codebuddy_account(acc)
            results.append(f"CodeBuddy [{acc.get('remark')}]: {res}")

    # TRAE 批量签到
    trae_accounts = cfg.get("trae_accounts", [])
    for acc in trae_accounts:
        if acc.get("enabled", True) and acc.get("accessToken"):
            res = checkin_trae_account(acc)
            results.append(f"TRAE [{acc.get('remark')}]: {res}")

    # Qoder 批量签到
    qoder_accounts = cfg.get("qoder_accounts", [])
    for acc in qoder_accounts:
        if acc.get("enabled", True) and (acc.get("token") or acc.get("accessToken")):
            res = checkin_qoder_account(acc)
            results.append(f"Qoder [{acc.get('remark')}]: {res}")

    summary = " | ".join(results) if results else "暂无已启用的有效账号"
    log(f"[多账号签到执行完毕] {summary}")
    return summary

# ====================================================================
#  缓存与后台调度器
# ====================================================================
DATA_CACHE = {}
CACHE_LAST_FETCH = 0

def update_cache():
    global DATA_CACHE, CACHE_LAST_FETCH
    cfg = load_config()
    cb_accounts = cfg.get("codebuddy_accounts", [])
    trae_accounts = cfg.get("trae_accounts", [])
    qoder_accounts = cfg.get("qoder_accounts", [])

    # 使用多线程高并发并行查询所有账号
    with ThreadPoolExecutor(max_workers=15) as executor:
        cb_futures = [executor.submit(fetch_single_codebuddy, a) for a in cb_accounts]
        trae_futures = [executor.submit(fetch_single_trae, a) for a in trae_accounts]
        qoder_futures = [executor.submit(fetch_single_qoder, a) for a in qoder_accounts]
        cb_res = [f.result() for f in cb_futures]
        trae_res = [f.result() for f in trae_futures]
        qoder_res = [f.result() for f in qoder_futures]

    all_res = cb_res + trae_res + qoder_res
    total_acc = len(all_res)
    checked_count = sum(1 for a in all_res if a.get("today_checked"))
    total_credits = round(sum(float(a.get("credits", 0)) for a in all_res), 1)

    DATA_CACHE = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "total_accounts": total_acc,
            "today_checked_count": checked_count,
            "total_credits": total_credits,
            "codebuddy_count": len(cb_res),
            "trae_count": len(trae_res),
            "qoder_count": len(qoder_res),
            "scheduler_time": f"{cfg.get('settings', {}).get('auto_checkin_hour', 10):02d}:{cfg.get('settings', {}).get('auto_checkin_minute', 5):02d}"
        },
        "codebuddy_accounts": cb_res,
        "trae_accounts": trae_res,
        "qoder_accounts": qoder_res
    }
    CACHE_LAST_FETCH = time.time()
    return DATA_CACHE

def scheduler_worker():
    log("[定时任务模块启动] 守护进程持续监听每日签到时刻...")
    last_run_day = None
    while True:
        try:
            cfg = load_config()
            hour = cfg.get("settings", {}).get("auto_checkin_hour", 9)
            minute = cfg.get("settings", {}).get("auto_checkin_minute", 0)

            now = datetime.datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            if now.hour == hour and now.minute == minute and last_run_day != today_str:
                log(f"[触发每日定时打卡] 开始为所有账号执行签到任务...")
                execute_all_checkin()
                update_cache()
                last_run_day = today_str

            time.sleep(30)
        except Exception as e:
            log(f"[调度循环异常] {e}")
            time.sleep(60)

# ====================================================================
#  UI 前端面板 HTML 模板 (内嵌多账号卡片 + 模态框 + 快捷登录)
# ====================================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI 算力与积分智能管家 (多账号版) | AI-Credits-Hub</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    body { background-color: #0b0f19; background-image: radial-gradient(circle at 50% 0%, rgba(99, 102, 241, 0.18) 0%, transparent 75%); }
    .glass { background: rgba(30, 41, 59, 0.65); backdrop-filter: blur(14px); border: 1px solid rgba(255, 255, 255, 0.08); }
    .glass-card { background: rgba(23, 31, 50, 0.7); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.06); }
    .glow:hover { box-shadow: 0 0 25px -4px rgba(99, 102, 241, 0.45); border-color: rgba(99, 102, 241, 0.5); }
    .custom-scroll::-webkit-scrollbar { width: 6px; }
    .custom-scroll::-webkit-scrollbar-thumb { background: rgba(99, 102, 241, 0.3); border-radius: 4px; }
  </style>
</head>
<body class="text-slate-100 min-h-screen p-3 md:p-8 font-sans">
  <div class="max-w-7xl mx-auto space-y-8">
    
    <!-- 头部导航与统计 -->
    <header class="glass p-6 rounded-2xl shadow-2xl flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
      <div class="flex items-center gap-4">
        <div class="p-3.5 bg-gradient-to-br from-indigo-500 to-indigo-700 rounded-2xl shadow-xl shadow-indigo-500/30 text-2xl">
          <i class="fa-solid fa-cubes"></i>
        </div>
        <div>
          <div class="flex items-center gap-3">
            <h1 class="text-2xl font-bold bg-gradient-to-r from-white via-indigo-200 to-indigo-400 bg-clip-text text-transparent">AI 算力与积分智能管家</h1>
            <span class="px-2.5 py-0.5 text-xs font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 rounded-full">多账号版</span>
          </div>
          <p class="text-xs text-slate-400 mt-1">云端 7x24h 自动签到 · 多账号小号矩阵集中托管 · 算力与到期监控</p>
        </div>
      </div>
      
      <!-- 汇总状态胶囊 -->
      <div class="flex items-center gap-3 flex-wrap">
        <div class="flex items-center gap-3 bg-slate-900/60 px-4 py-2 rounded-xl border border-slate-800 text-xs text-slate-300">
          <div>托管账号: <span id="stat_total" class="font-bold text-indigo-400">0</span></div>
          <div class="w-px h-3 bg-slate-700"></div>
          <div>今日已打卡: <span id="stat_checked" class="font-bold text-emerald-400">0</span></div>
          <div class="w-px h-3 bg-slate-700"></div>
          <div>累计可用算力: <span id="stat_credits" class="font-bold text-amber-300">0</span></div>
          <div class="w-px h-3 bg-slate-700"></div>
          <div id="stat_refresh_time" class="text-emerald-400 text-[11px] flex items-center gap-1">
            <i class="fa-solid fa-circle text-[7px] animate-pulse"></i> 实时监控中
          </div>
        </div>

        <button onclick="triggerCheckinAll()" id="checkinAllBtn" class="px-4 py-2.5 bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white font-medium rounded-xl shadow-lg shadow-emerald-500/20 flex items-center gap-2 text-sm transition-all transform active:scale-95">
          <i class="fa-solid fa-bolt"></i> 立即全平台签到
        </button>
        <button onclick="openAddAccountModal()" class="px-4 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-medium rounded-xl shadow-lg shadow-indigo-500/20 flex items-center gap-2 text-sm transition-all">
          <i class="fa-solid fa-user-plus"></i> 添加 / 快捷同步账号
        </button>
        <button onclick="openSettingsModal()" class="p-2.5 glass hover:bg-slate-700/50 rounded-xl text-slate-300 hover:text-white text-sm" title="系统与凭证设置">
          <i class="fa-solid fa-gear"></i>
        </button>
        <button onclick="loadData(true)" id="refreshBtn" class="p-2.5 glass hover:bg-slate-700/50 rounded-xl text-slate-300 hover:text-white text-sm" title="重新从平台查询最新实时算力">
          <i id="refreshIcon" class="fa-solid fa-rotate-right"></i>
        </button>
      </div>
    </header>

    <!-- CodeBuddy 账号矩阵 -->
    <section class="space-y-4">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <span class="p-2 bg-blue-500/20 text-blue-400 rounded-xl text-base"><i class="fa-solid fa-code"></i></span>
          <h2 class="text-lg font-bold text-slate-200">腾讯 CodeBuddy / WorkBuddy 账号池</h2>
          <span id="cb_count_badge" class="px-2 py-0.5 text-xs bg-slate-800 text-slate-400 rounded-md border border-slate-700">0 个账号</span>
        </div>
        <div class="flex items-center gap-3">
          <button onclick="openLoginHelperModal('codebuddy')" class="text-xs text-indigo-400 hover:text-indigo-300 transition-colors flex items-center gap-1.5 bg-indigo-500/10 hover:bg-indigo-500/20 px-3 py-1.5 rounded-lg border border-indigo-500/20">
            <i class="fa-solid fa-qrcode"></i> 扫码 / 快捷登录
          </button>
          <button onclick="openAddAccountModal('codebuddy')" class="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
            <i class="fa-solid fa-plus"></i> 手动录入
          </button>
        </div>
      </div>
      <div id="codebuddyGrid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"></div>
    </section>

    <!-- TRAE 账号矩阵 -->
    <section class="space-y-4">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <span class="p-2 bg-purple-500/20 text-purple-400 rounded-xl text-base"><i class="fa-solid fa-brain"></i></span>
          <h2 class="text-lg font-bold text-slate-200">字节跳动 TRAE CN (SOLO) 账号池</h2>
          <span id="trae_count_badge" class="px-2 py-0.5 text-xs bg-slate-800 text-slate-400 rounded-md border border-slate-700">0 个账号</span>
        </div>
        <div class="flex items-center gap-3">
          <button onclick="openLoginHelperModal('trae')" class="text-xs text-indigo-400 hover:text-indigo-300 transition-colors flex items-center gap-1.5 bg-indigo-500/10 hover:bg-indigo-500/20 px-3 py-1.5 rounded-lg border border-indigo-500/20">
            <i class="fa-solid fa-qrcode"></i> 扫码 / 快捷登录
          </button>
          <button onclick="openAddAccountModal('trae')" class="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
            <i class="fa-solid fa-plus"></i> 手动录入
          </button>
        </div>
      </div>
      <div id="traeGrid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"></div>
    </section>

    <!-- Qoder 账号矩阵 -->
    <section class="space-y-4 mb-8">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <span class="p-2 bg-emerald-500/20 text-emerald-400 rounded-xl text-base"><i class="fa-solid fa-cube"></i></span>
          <h2 class="text-lg font-bold text-slate-200">通义 / 阿里 Qoder (每天 100 Credits) 账号池</h2>
          <span id="qoder_count_badge" class="px-2 py-0.5 text-xs bg-slate-800 text-slate-400 rounded-md border border-slate-700">0 个账号</span>
        </div>
        <div class="flex items-center gap-3">
          <button onclick="openLoginHelperModal('qoder')" class="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
            <i class="fa-solid fa-wand-magic-sparkles"></i> 快捷同步指南
          </button>
          <button onclick="openAddAccountModal('qoder')" class="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
            <i class="fa-solid fa-plus"></i> 手动录入
          </button>
        </div>
      </div>
      <div id="qoderGrid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"></div>
    </section>

    <!-- 优惠情报与备用切换 -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
      <!-- 优惠雷达 -->
      <section class="glass p-6 rounded-2xl shadow-xl space-y-4">
        <div class="flex items-center justify-between border-b border-slate-700/60 pb-3">
          <h2 class="text-lg font-semibold text-amber-300 flex items-center gap-2"><i class="fa-solid fa-fire text-amber-400"></i> 模型优惠与“白嫖”情报雷达</h2>
          <span class="text-xs px-2.5 py-1 bg-amber-500/20 text-amber-300 rounded-full border border-amber-500/30">每日更新</span>
        </div>
        <div class="space-y-3">
          <div class="p-3.5 rounded-xl bg-slate-800/60 border border-slate-700/50 flex items-start gap-3">
            <div class="p-2 bg-emerald-500/20 text-emerald-400 rounded-lg text-sm"><i class="fa-solid fa-gift"></i></div>
            <div class="flex-1">
              <div class="flex justify-between items-center"><span class="font-medium text-sm text-slate-200">TRAE 每日 200 算力补贴</span><span class="text-xs text-emerald-400 font-mono">100% 免费</span></div>
              <p class="text-xs text-slate-400 mt-1">基础 100 + 活动 100 算力，已由本服务自动领取，每个账号每月净赚 6,000 算力。</p>
            </div>
          </div>
          <div class="p-3.5 rounded-xl bg-slate-800/60 border border-slate-700/50 flex items-start gap-3">
            <div class="p-2 bg-blue-500/20 text-blue-400 rounded-lg text-sm"><i class="fa-solid fa-coins"></i></div>
            <div class="flex-1">
              <div class="flex justify-between items-center"><span class="font-medium text-sm text-slate-200">CodeBuddy 每日连签奖励</span><span class="text-xs text-blue-400 font-mono">稳定白嫖</span></div>
              <p class="text-xs text-slate-400 mt-1">每日 +100 积分，连续 7 天触发额外盲盒大奖，积分池可抵扣 DeepSeek-V3 满血调用。</p>
            </div>
          </div>
        </div>
      </section>

      <!-- 应急备用路线 -->
      <section class="glass p-6 rounded-2xl shadow-xl space-y-4">
        <div class="flex items-center justify-between border-b border-slate-700/60 pb-3">
          <h2 class="text-lg font-semibold text-indigo-300 flex items-center gap-2"><i class="fa-solid fa-shield-halved text-indigo-400"></i> 算力熔断与应急切换梯队</h2>
          <span class="text-xs px-2.5 py-1 bg-indigo-500/20 text-indigo-300 rounded-full border border-indigo-500/30">应急推荐</span>
        </div>
        <div class="space-y-3">
          <div class="p-3.5 rounded-xl bg-gradient-to-r from-slate-800 to-indigo-950/40 border border-indigo-500/30 flex items-center justify-between">
            <div>
              <span class="text-xs font-semibold text-indigo-400 uppercase tracking-wider">第一备用梯队 · 国内直连</span>
              <h3 class="font-bold text-sm text-white mt-0.5">无缝切至 CodeBuddy 积分池</h3>
              <p class="text-xs text-slate-400 mt-1">使用本服务每天自动积攒的积分池，支持 DeepSeek-V3 满血调用，零成本续命。</p>
            </div>
            <span class="px-3 py-1 bg-indigo-500/20 text-indigo-300 text-xs rounded-lg border border-indigo-500/30">首推</span>
          </div>
          <div class="p-3.5 rounded-xl bg-gradient-to-r from-slate-800 to-purple-950/40 border border-purple-500/30 flex items-center justify-between">
            <div>
              <span class="text-xs font-semibold text-purple-400 uppercase tracking-wider">第二备用梯队 · 长上下文</span>
              <h3 class="font-bold text-sm text-white mt-0.5">切换至 Kimi Code / ZCode 车道</h3>
              <p class="text-xs text-slate-400 mt-1">月之暗面长文本超强解析 + 智谱 GLM-4 闲时免额度模式，适合梳理大型工程代码。</p>
            </div>
            <span class="px-3 py-1 bg-purple-500/20 text-purple-300 text-xs rounded-lg border border-purple-500/30">长文</span>
          </div>
        </div>
      </section>
    </div>

    <footer class="glass p-4 rounded-2xl flex flex-col md:flex-row justify-between items-center text-xs text-slate-400 gap-2">
      <div class="flex items-center gap-2">
        <span class="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
        <span>云端服务运行中 · 每天 <span id="footer_sched_time" class="text-indigo-400 font-mono">09:00</span> 定时执行全平台多账号签到</span>
      </div>
      <div>
        <a href="https://github.com/bishuyuan1998/AI-Credits-Hub" target="_blank" class="text-indigo-400 hover:underline mr-3"><i class="fa-brands fa-github"></i> GitHub 开源仓库</a>
        <span>API: <a href="/api/data" target="_blank" class="text-indigo-400 hover:underline">/api/data</a></span>
      </div>
    </footer>
  </div>

  <!-- 模态框：添加 / 编辑账号 / 快捷同步 -->
  <div id="accountModal" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="glass max-w-2xl w-full p-6 md:p-8 rounded-2xl shadow-2xl space-y-6 max-h-[92vh] overflow-y-auto custom-scroll">
      
      <div class="flex justify-between items-center border-b border-slate-700/60 pb-4">
        <div>
          <h3 id="accModalTitle" class="text-lg font-bold text-white flex items-center gap-2">
            <i class="fa-solid fa-user-plus text-indigo-400"></i> 录入与同步 AI 账号
          </h3>
          <p class="text-xs text-slate-400 mt-0.5">支持本机客户端一键极速同步、智能粘贴或网页控制台秒录</p>
        </div>
        <button onclick="closeAccountModal()" class="text-slate-400 hover:text-white text-xl"><i class="fa-solid fa-xmark"></i></button>
      </div>

      <!-- 选项卡切换 (默认展示最省心的本机一键同步) -->
      <div class="flex border-b border-slate-700/60 pb-3 gap-2">
        <button type="button" id="tab_btn_local" onclick="switchModalTab('local')" class="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 text-white transition-all flex items-center gap-1.5">
          <i class="fa-solid fa-laptop-code text-amber-300"></i> 💻 电脑客户端一键同步 (最推荐)
        </button>
        <button type="button" id="tab_btn_manual" onclick="switchModalTab('manual')" class="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-300 hover:text-white transition-all flex items-center gap-1.5">
          <i class="fa-solid fa-wand-magic-sparkles"></i> 📋 智能粘贴 / 快捷录入
        </button>
        <button type="button" id="tab_btn_web" onclick="switchModalTab('web')" class="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-300 hover:text-white transition-all flex items-center gap-1.5">
          <i class="fa-solid fa-globe"></i> 🌐 网页 1 秒代码抓取 (免拖书签)
        </button>
      </div>

      <!-- 内容区 1：本机客户端全自动一键同步 (默认最简单推荐) -->
      <div id="tab_content_local" class="space-y-4 text-xs">
        <div class="p-4 bg-gradient-to-r from-emerald-950/40 via-teal-950/40 to-slate-900 rounded-xl border border-emerald-500/30 space-y-3">
          <div class="flex items-center gap-2 text-emerald-300 font-bold text-sm">
            <i class="fa-solid fa-bolt text-amber-400"></i> 零门槛操作：电脑客户端已登录，一键直连同步
          </div>
          <p class="text-slate-300 leading-relaxed">
            只要你的电脑上安装并登录过 <b>腾讯 CodeBuddy / WorkBuddy</b> 或 <b>字节跳动 TRAE CN / SOLO</b> 客户端，无需手动复制 Token 或密码，工具将自动自解密读取凭据并推送到本云端！
          </p>
        </div>

        <!-- 方案 A：本地已有项目直接双击 -->
        <div class="p-4 bg-slate-900/80 rounded-xl border border-slate-700/70 space-y-2.5">
          <div class="flex items-center justify-between">
            <span class="font-bold text-slate-200 flex items-center gap-2">
              <span class="w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-400 flex items-center justify-center text-[11px] font-bold">1</span>
              在本地项目直接双击（最快）
            </span>
            <span class="text-[11px] text-emerald-400 font-medium">已预装好脚本</span>
          </div>
          <p class="text-slate-400 leading-relaxed text-[11px]">
            在本地项目文件夹 <code class="text-indigo-300 bg-slate-950 px-1.5 py-0.5 rounded font-mono">D:/yinhai/project/AI-Credits-Hub</code> 中，直接双击运行：
          </p>
          <div class="p-2.5 bg-slate-950 rounded-lg border border-indigo-500/30 flex items-center justify-between text-indigo-300 font-mono text-xs">
            <span>👉 【双击一键同步账号到云端】.bat</span>
            <span class="text-slate-500 text-[11px]">双击即自动提取并同步全部账号</span>
          </div>
        </div>

        <!-- 方案 B：下载通用同步工具 -->
        <div class="p-4 bg-slate-900/80 rounded-xl border border-slate-700/70 space-y-2.5">
          <div class="flex items-center justify-between">
            <span class="font-bold text-slate-200 flex items-center gap-2">
              <span class="w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-400 flex items-center justify-center text-[11px] font-bold">2</span>
              在任意安装了客户端的电脑上一键同步
            </span>
          </div>
          <p class="text-slate-400 text-[11px]">点击下方按钮下载预先配置好本服务器密钥的同步脚本，下载后直接双击即可：</p>
          <div class="flex items-center gap-3">
            <button onclick="downloadSyncBat()" class="px-4 py-2 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white font-medium rounded-xl shadow-lg shadow-indigo-500/20 flex items-center gap-2 transition-all">
              <i class="fa-solid fa-download"></i> 立即下载一键同步脚本 (ai_sync.bat)
            </button>
            <button onclick="copyLocalCommand()" class="px-4 py-2 glass hover:bg-slate-700/50 text-slate-300 hover:text-white rounded-xl flex items-center gap-1.5 transition-all">
              <i class="fa-solid fa-terminal"></i> 复制 Python 命令
            </button>
          </div>
        </div>
      </div>

      <!-- 内容区 2：智能粘贴 / 手动录入 -->
      <div id="tab_content_manual" class="space-y-4 text-xs hidden">
        <input type="hidden" id="acc_id">
        
        <!-- 智能粘贴识别区 -->
        <div class="p-4 bg-slate-900/90 rounded-xl border border-dashed border-indigo-500/50 space-y-2">
          <div class="flex justify-between items-center">
            <span class="font-bold text-indigo-300 flex items-center gap-1.5">
              <i class="fa-solid fa-wand-magic-sparkles text-amber-300"></i> 极速智能粘贴板 (自动解析平台、手机号与凭据)
            </span>
            <span class="text-[10px] text-slate-400">贴入即自动填充</span>
          </div>
          <textarea id="acc_smart_paste" rows="3" oninput="handleSmartPaste(this.value)" placeholder="直接在此粘贴 Token、或在 F12 复制的整段 JWT、请求头、JSON，系统自动提取识别..." class="w-full bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono text-[11px]"></textarea>
          <div id="paste_status_hint" class="text-[11px] text-slate-400">💡 提示：支持粘贴 Bearer eyJ... 或包含 token 的任何文本。</div>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label class="block text-slate-300 font-medium mb-1">所属平台:</label>
            <select id="acc_platform" onchange="togglePlatformFields()" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500">
              <option value="codebuddy">腾讯 CodeBuddy / WorkBuddy</option>
              <option value="trae">字节跳动 TRAE CN (SOLO)</option>
              <option value="qoder">通义 / 阿里 Qoder (每天 100 Credits)</option>
            </select>
          </div>

          <div>
            <label class="block text-slate-300 font-medium mb-1">账号备注 (区分小号):</label>
            <input type="text" id="acc_remark" placeholder="例如: 毕书源 (主号)、日常小号1..." class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500">
          </div>
        </div>

        <div>
          <label class="block text-slate-300 font-medium mb-1">绑定手机号 / 标识 (用于大屏醒目标识):</label>
          <input type="text" id="acc_phone" placeholder="例如: 13032213110 (CodeBuddy 自动提取)" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono">
        </div>

        <div>
          <div class="flex justify-between items-center mb-1">
            <label class="text-slate-300 font-medium">AccessToken (访问凭据):</label>
            <span class="text-slate-400 text-[11px]">支持 Bearer eyJ...</span>
          </div>
          <textarea id="acc_token" rows="3" placeholder="粘贴账号的 accessToken / JWT 凭证..." class="w-full bg-slate-900 border border-slate-700 rounded-xl p-3 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono text-[11px]"></textarea>
        </div>

        <!-- TRAE 专属字段 -->
        <div id="traeFields" class="grid grid-cols-2 gap-4 hidden">
          <div>
            <label class="block text-slate-300 font-medium mb-1">TRAE 用户 UID:</label>
            <input type="text" id="acc_trae_uid" placeholder="如 2992225035760716" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono">
          </div>
          <div>
            <label class="block text-slate-300 font-medium mb-1">设备 ID (DeviceId):</label>
            <input type="text" id="acc_trae_did" placeholder="默认 766820083601979" value="766820083601979" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono">
          </div>
        </div>

        <div class="flex justify-end gap-3 pt-3 border-t border-slate-700/60">
          <button onclick="closeAccountModal()" class="px-5 py-2 glass hover:bg-slate-700/50 rounded-xl text-slate-300 text-xs">取消</button>
          <button onclick="saveAccount()" id="saveAccBtn" class="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl text-xs transition-all flex items-center gap-2">
            <i class="fa-solid fa-floppy-disk"></i> 验证并保存到服务器
          </button>
        </div>
      </div>

      <!-- 内容区 3：网页版快捷抓取 (完全免拖书签) -->
      <div id="tab_content_web" class="space-y-4 text-xs hidden">
        <div class="p-4 bg-slate-900/80 rounded-xl border border-slate-800 space-y-3">
          <div class="font-bold text-slate-200 flex items-center gap-2 text-sm">
            <i class="fa-solid fa-globe text-blue-400"></i> 网页登录小号：免拖书签，2 步极速导入
          </div>
          <p class="text-slate-300 leading-relaxed">
            无需繁琐地把按钮拖到书签栏！直接在新标签页打开官网登录后，在控制台（Console）粘贴一行代码按回车，1 秒自动完成同步：
          </p>
        </div>

        <div class="space-y-3">
          <div class="font-semibold text-slate-200">第一步：在新窗口打开对应平台，登录你的小号</div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <a href="https://www.codebuddy.cn/" target="_blank" class="p-3 bg-blue-950/40 hover:bg-blue-900/50 border border-blue-500/30 rounded-xl flex items-center justify-between text-blue-200 transition-all">
              <span class="font-bold"><i class="fa-solid fa-code mr-1.5 text-blue-400"></i> 打开 CodeBuddy 登录页</span>
              <i class="fa-solid fa-arrow-up-right-from-square text-xs text-blue-400"></i>
            </a>
            <a href="https://www.trae.ai/" target="_blank" class="p-3 bg-purple-950/40 hover:bg-purple-900/50 border border-purple-500/30 rounded-xl flex items-center justify-between text-purple-200 transition-all">
              <span class="font-bold"><i class="fa-solid fa-brain mr-1.5 text-purple-400"></i> 打开 TRAE 登录页</span>
              <i class="fa-solid fa-arrow-up-right-from-square text-xs text-purple-400"></i>
            </a>
          </div>
        </div>

        <div class="space-y-2 pt-1">
          <div class="font-semibold text-slate-200">第二步：登录后按 F12 打开控制台，粘贴复制这一行脚本并按回车</div>
          <div class="p-3 bg-slate-950 rounded-xl border border-slate-700/80 flex items-center justify-between gap-3">
            <span id="webSnippetText" class="font-mono text-indigo-300 text-[11px] truncate select-all"></span>
            <button onclick="copyWebSnippet()" class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 whitespace-nowrap">
              <i class="fa-solid fa-copy"></i> 复制脚本代码
            </button>
          </div>
          <p class="text-[11px] text-slate-400">回车后将自动提取网页登录凭证并弹出“🎉 同步成功”提示，回到本页面刷新即可！</p>
        </div>
      </div>

    </div>
  </div>

  <!-- 模态框 2：系统设置 -->
  <div id="settingsModal" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="glass max-w-xl w-full p-6 md:p-8 rounded-2xl shadow-2xl space-y-6 max-h-[90vh] overflow-y-auto custom-scroll">
      <div class="flex justify-between items-center border-b border-slate-700/60 pb-4">
        <h3 class="text-lg font-bold text-white flex items-center gap-2"><i class="fa-solid fa-gear text-indigo-400"></i> 系统与定时签到设置</h3>
        <button onclick="closeSettingsModal()" class="text-slate-400 hover:text-white text-xl"><i class="fa-solid fa-xmark"></i></button>
      </div>

      <div class="space-y-4 text-xs">
        <div>
          <label class="block text-slate-300 font-medium mb-1">安全访问密钥 / Secret Key:</label>
          <input type="text" id="cfg_admin_key" placeholder="设置后台访问防伪密钥" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono">
          <p class="text-[11px] text-slate-400 mt-1">外部访客无此密钥时，连接将被物理直接阻断（ERR_EMPTY_RESPONSE），完全隐身隐藏服务。</p>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-slate-300 font-medium mb-1">每日定时签到 (小时 0-23):</label>
            <input type="number" id="cfg_sched_hour" min="0" max="23" value="9" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500">
          </div>
          <div>
            <label class="block text-slate-300 font-medium mb-1">每日定时签到 (分钟 0-59):</label>
            <input type="number" id="cfg_sched_min" min="0" max="59" value="0" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500">
          </div>
        </div>
      </div>

      <div class="flex justify-end gap-3 pt-4 border-t border-slate-700/60">
        <button onclick="closeSettingsModal()" class="px-5 py-2 glass hover:bg-slate-700/50 rounded-xl text-slate-300 text-xs">取消</button>
        <button onclick="saveSystemSettings()" id="saveSysBtn" class="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl text-xs transition-all flex items-center gap-2">
          <i class="fa-solid fa-floppy-disk"></i> 保存设置
        </button>
      </div>
    </div>
  </div>

  <!-- 模态框：快速修改账号备注 -->
  <div id="remarkModal" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="glass max-w-md w-full p-6 rounded-2xl shadow-2xl space-y-5 border border-slate-700/80">
      <div class="flex justify-between items-center border-b border-slate-700/60 pb-3">
        <div>
          <h3 class="text-base font-bold text-white flex items-center gap-2">
            <i class="fa-solid fa-pen-to-square text-indigo-400"></i> 修改账号备注
          </h3>
          <p id="remarkModalSubtitle" class="text-xs text-slate-400 mt-0.5">为账号设置个性化备注，方便区分多账号</p>
        </div>
        <button onclick="closeRemarkModal()" class="text-slate-400 hover:text-white text-lg"><i class="fa-solid fa-xmark"></i></button>
      </div>

      <input type="hidden" id="remark_platform" value="">
      <input type="hidden" id="remark_acc_id" value="">

      <div class="space-y-3 text-xs">
        <div>
          <label class="block text-slate-300 font-medium mb-1.5">账号自定义备注名称：</label>
          <input type="text" id="remark_input" placeholder="例如: TRAE主号 (大号) / 自用小号 / 工作号" 
            class="w-full bg-slate-900 border border-slate-700 rounded-xl p-3 text-white text-sm focus:outline-none focus:border-indigo-500 font-medium">
        </div>

        <div>
          <span class="text-[11px] text-slate-400 mb-1.5 block">快捷预设标签（点击填入）：</span>
          <div class="flex flex-wrap gap-1.5">
            <button type="button" onclick="setPresetRemark('TRAE 主号 (主力开发)')" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-indigo-600/30 hover:border-indigo-500/50 text-slate-300 border border-slate-700 text-[11px] transition-all">TRAE 主号</button>
            <button type="button" onclick="setPresetRemark('TRAE 小号 (自用备用)')" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-indigo-600/30 hover:border-indigo-500/50 text-slate-300 border border-slate-700 text-[11px] transition-all">TRAE 小号</button>
            <button type="button" onclick="setPresetRemark('TRAE 体验号')" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-indigo-600/30 hover:border-indigo-500/50 text-slate-300 border border-slate-700 text-[11px] transition-all">TRAE 体验号</button>
            <button type="button" onclick="setPresetRemark('CodeBuddy 主号')" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-indigo-600/30 hover:border-indigo-500/50 text-slate-300 border border-slate-700 text-[11px] transition-all">CodeBuddy 主号</button>
            <button type="button" onclick="setPresetRemark('WorkBuddy 小号')" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-indigo-600/30 hover:border-indigo-500/50 text-slate-300 border border-slate-700 text-[11px] transition-all">WorkBuddy 小号</button>
          </div>
        </div>
      </div>

      <div class="flex justify-end gap-3 pt-3 border-t border-slate-700/60">
        <button type="button" onclick="closeRemarkModal()" class="px-4 py-2 glass hover:bg-slate-700/50 rounded-xl text-slate-300 text-xs font-medium">取消</button>
        <button type="button" id="saveRemarkBtn" onclick="submitRemarkChange()" class="px-5 py-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-indigo-500/20 transition-all flex items-center gap-1.5">
          <i class="fa-solid fa-floppy-disk"></i> 保存备注
        </button>
      </div>
    </div>
  </div>

  <script>
    window.__ADMIN_KEY__ = "{{ADMIN_KEY}}";
    let globalData = null;
    let currentAdminKey = window.__ADMIN_KEY__ || new URLSearchParams(window.location.search).get('key') || localStorage.getItem('ai_hub_key') || '';
    if (currentAdminKey) localStorage.setItem('ai_hub_key', currentAdminKey);

    // 统一 API 请求封装：自动携带安全密钥（无论 Cookie 是否被浏览器阻断，均 100% 鉴权成功）
    function apiFetch(url, options = {}) {
      const k = currentAdminKey || localStorage.getItem('ai_hub_key') || '';
      const sep = url.includes('?') ? '&' : '?';
      const fullUrl = k ? `${url}${sep}key=${encodeURIComponent(k)}` : url;
      options.headers = options.headers || {};
      if (k) options.headers['X-Hub-Key'] = k;
      return fetch(fullUrl, options);
    }

    async function loadData(force = false) {
      const icon = document.getElementById('refreshIcon');
      if (icon) icon.classList.add('fa-spin');
      try {
        const url = force ? '/api/data?refresh=1' : '/api/data';
        const res = await apiFetch(url);
        if (res.status === 403) {
          location.reload();
          return;
        }
        globalData = await res.json();
        
        // 更新统计
        document.getElementById('stat_total').innerText = globalData.summary.total_accounts;
        document.getElementById('stat_checked').innerText = globalData.summary.today_checked_count;
        document.getElementById('stat_credits').innerText = globalData.summary.total_credits;
        document.getElementById('footer_sched_time').innerText = globalData.summary.scheduler_time;

        const nowStr = new Date().toLocaleTimeString();
        const refreshEl = document.getElementById('stat_refresh_time');
        if (refreshEl) {
          refreshEl.innerHTML = `<i class="fa-solid fa-circle text-[7px] text-emerald-400 animate-pulse"></i> 实时已更新于 ${nowStr}`;
        }

        // 渲染 CodeBuddy
        renderAccounts('codebuddy', globalData.codebuddy_accounts, document.getElementById('codebuddyGrid'));
        document.getElementById('cb_count_badge').innerText = `${globalData.codebuddy_accounts.length} 个账号`;

        // 渲染 TRAE
        renderAccounts('trae', globalData.trae_accounts, document.getElementById('traeGrid'));
        document.getElementById('trae_count_badge').innerText = `${globalData.trae_accounts.length} 个账号`;

        // 渲染 Qoder
        if (globalData.qoder_accounts) {
          renderAccounts('qoder', globalData.qoder_accounts, document.getElementById('qoderGrid'));
          const qb = document.getElementById('qoder_count_badge');
          if (qb) qb.innerText = `${globalData.qoder_accounts.length} 个账号`;
        }

      } catch (err) {
        console.error('loadData error:', err);
        const refreshEl = document.getElementById('stat_refresh_time');
        if (refreshEl) {
          refreshEl.innerHTML = `<span class="text-rose-400 cursor-pointer" onclick="loadData(true)"><i class="fa-solid fa-triangle-exclamation"></i> 刷新失败，点击重试</span>`;
        }
      } finally {
        if (icon) icon.classList.remove('fa-spin');
      }
    }

    // 初始化提取工具与命令
    async function setupWebTools() {
      try {
        const res = await apiFetch('/api/config');
        const cfg = await res.json();
        currentAdminKey = cfg.auth?.admin_key || currentAdminKey || 'Hub_98bxy_Sec2026';
        const hubOrigin = window.location.origin;

        // 网页控制台 1 键提取并推送代码
        const snippet = `fetch('${hubOrigin}/api/account/save?key=${currentAdminKey}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({platform:location.host.includes('trae')?'trae':'codebuddy',accessToken:(function(){for(var i=0;i<localStorage.length;i++){var v=localStorage.getItem(localStorage.key(i));if(v&&v.includes('eyJ'))try{return JSON.parse(v).accessToken||v}catch(e){return v}}return (document.cookie.match(/(?:accessToken|token|jwt)=([^;]+)/)||[])[1]||''})(),remark:'网页一键录入 '+new Date().toLocaleDateString()})}).then(r=>r.json()).then(d=>alert(d.success?'🎉 账号已成功录入云端！':'失败: '+(d.error||d.message))).catch(e=>alert('请求错误: '+e));`;
        const snipEl = document.getElementById('webSnippetText');
        if (snipEl) snipEl.innerText = snippet;
        
        const cmdEl = document.getElementById('localCmdText');
        if (cmdEl) cmdEl.innerText = `python local_extract.py --server ${hubOrigin} --key ${currentAdminKey}`;
      } catch (e) {
        console.error('初始化工具异常:', e);
      }
    }

    function copyWebSnippet() {
      const text = document.getElementById('webSnippetText').innerText;
      if (!text) return;
      navigator.clipboard.writeText(text).then(() => {
        alert('✅ 网页控制台抓取脚本已复制！可直接在 CodeBuddy 或 TRAE 官网按 F12 控制台粘贴回车！');
      }).catch(() => {
        prompt('请全选复制以下脚本：', text);
      });
    }

    function downloadSyncBat() {
      const k = currentAdminKey || localStorage.getItem('ai_hub_key') || 'Hub_98bxy_Sec2026';
      window.location.href = `/api/download/sync-bat?key=${encodeURIComponent(k)}`;
    }

    function copyLocalCommand() {
      const hubOrigin = window.location.origin;
      const key = currentAdminKey || 'Hub_98bxy_Sec2026';
      const cmd = `python local_extract.py --server ${hubOrigin} --key ${key}`;
      navigator.clipboard.writeText(cmd).then(() => {
        alert('✅ 本地同步命令已复制：' + cmd);
      });
    }

    function renderAccounts(platform, accounts, container) {
      container.innerHTML = '';
      if (!accounts || accounts.length === 0) {
        container.innerHTML = `
          <div class="col-span-full glass-card p-8 rounded-2xl text-center border-dashed border-2 border-slate-700/60">
            <div class="text-3xl text-slate-600 mb-2"><i class="fa-regular fa-folder-open"></i></div>
            <p class="text-sm text-slate-400">暂未添加任何 ${platform === 'codebuddy' ? 'CodeBuddy' : (platform === 'trae' ? 'TRAE' : 'Qoder')} 账号</p>
            <div class="mt-4 flex items-center justify-center gap-3">
              <button onclick="openAddAccountModal('${platform}')" class="px-4 py-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-indigo-500/20 transition-all">
                <i class="fa-solid fa-user-plus mr-1"></i> 添加 / 录入小号
              </button>
            </div>
          </div>
        `;
        return;
      }

      accounts.forEach(acc => {
        const isSoon = acc.expire_days <= 7;
        const checkedLabel = platform === 'qoder' ? '今日已领 100' : '今日已签';
        const pendingLabel = platform === 'qoder' ? '待领 100 算力' : '待签到';
        const badge = acc.today_checked 
          ? `<span class="px-2.5 py-1 bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded-full text-xs font-medium"><i class="fa-solid fa-check"></i> ${checkedLabel}</span>`
          : (acc.valid ? `<span class="px-2.5 py-1 bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded-full text-xs font-medium"><i class="fa-solid fa-gift"></i> ${pendingLabel}</span>` : '<span class="px-2.5 py-1 bg-rose-500/20 text-rose-300 border border-rose-500/30 rounded-full text-xs font-medium">凭据失效</span>');

        const card = document.createElement('div');
        card.className = "glass p-5 rounded-2xl shadow-lg glow transition-all duration-300 flex flex-col justify-between";
        card.innerHTML = `
          <div>
            <div class="flex justify-between items-start gap-2 mb-3">
              <div>
                <h3 class="font-bold text-base text-white flex items-center gap-2 group">
                  <span class="hover:text-indigo-300 cursor-pointer transition-colors" onclick="openRemarkModal('${platform}', '${acc.id}')" title="点击直接修改备注">
                    ${acc.remark}
                  </span>
                  <button type="button" onclick="openRemarkModal('${platform}', '${acc.id}')" class="opacity-60 hover:opacity-100 text-xs text-indigo-400 hover:text-indigo-200 transition-all p-1" title="修改备注">
                    <i class="fa-solid fa-pen-to-square"></i>
                  </button>
                  ${!acc.enabled ? '<span class="text-[10px] bg-slate-700 text-slate-400 px-1.5 py-0.5 rounded">已暂停</span>' : ''}
                </h3>
                <div class="flex items-center gap-2 text-xs text-slate-400 mt-1 flex-wrap">
                  ${acc.masked_phone ? `
                    <span class="inline-flex items-center gap-1.5 text-emerald-300 font-mono bg-emerald-500/15 px-2 py-0.5 rounded-md border border-emerald-500/30 text-xs font-semibold">
                      <i class="fa-solid fa-mobile-screen text-[11px]"></i> ${acc.masked_phone}
                    </span>
                  ` : ''}
                  <span class="font-mono text-slate-400 text-xs">
                    ${platform === 'codebuddy' ? (acc.nickname ? `(${acc.nickname})` : '') : ('UID: ' + acc.uid)}
                  </span>
                </div>
              </div>
              ${badge}
            </div>

            <div class="my-3 p-4 rounded-xl bg-slate-900/60 border border-slate-800">
              <div class="text-xs text-slate-400 flex justify-between items-center">
                <span>当前可用剩余积分 / 算力</span>
                <span class="px-2 py-0.5 text-[11px] rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">${acc.plan_name || '体验版'}</span>
              </div>
              <div class="flex items-baseline gap-2 mt-2">
                <span class="text-3xl font-extrabold text-white">${acc.credits}</span>
                <span class="text-sm font-semibold text-slate-400">${platform === 'qoder' ? 'Credits' : 'Points'}</span>
              </div>
              <div class="mt-2 text-xs text-slate-400 flex items-center justify-between">
                <span>${acc.status_text}</span>
                ${platform === 'trae' && acc.consumed !== undefined ? `<span class="text-[11px] text-slate-400">使用率 ${acc.used_pct}%</span>` : '<span class="text-emerald-400 text-[11px]">体验版可用</span>'}
              </div>
            </div>

            <div class="flex justify-between items-center text-xs text-slate-400 pt-2 border-t border-slate-800/80">
              <span>到期: ${acc.expire_time ? acc.expire_time.split(' ')[0] : '-'}</span>
              <span class="${isSoon ? 'text-amber-400 font-semibold' : 'text-slate-400'}">剩 ${acc.expire_days} 天</span>
            </div>
          </div>

          <div class="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between gap-2 flex-wrap">
            <button onclick="triggerCheckinSingle('${platform}', '${acc.id}')" class="px-3 py-1.5 bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all">
              <i class="fa-solid fa-bolt text-emerald-400"></i> 单独签到
            </button>
            <div class="flex items-center gap-2">
              <button onclick="openRemarkModal('${platform}', '${acc.id}')" class="px-2.5 py-1.5 glass hover:bg-slate-700/60 text-slate-300 hover:text-white rounded-lg text-xs flex items-center gap-1.5 transition-all" title="修改备注">
                <i class="fa-solid fa-pen text-indigo-400"></i> 修改备注
              </button>
              <button onclick="editAccount('${platform}', '${acc.id}')" class="p-1.5 text-slate-400 hover:text-white glass rounded-lg" title="完整凭据设置">
                <i class="fa-solid fa-gear"></i>
              </button>
              <button onclick="deleteAccount('${platform}', '${acc.id}')" class="p-1.5 text-slate-400 hover:text-rose-400 glass rounded-lg" title="删除账号">
                <i class="fa-solid fa-trash-can"></i>
              </button>
            </div>
          </div>
        `;
        container.appendChild(card);
      });
    }

    async function triggerCheckinSingle(platform, id) {
      try {
        const res = await apiFetch('/api/account/checkin', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ platform, id })
        });
        const d = await res.json();
        alert('签到结果: ' + d.message);
        loadData(true);
      } catch (e) {
        alert('签到请求异常: ' + e);
      }
    }

    async function triggerCheckinAll() {
      const btn = document.getElementById('checkinAllBtn');
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 正在全平台打卡...';
      try {
        const res = await apiFetch('/api/checkin', { method: 'POST' });
        const d = await res.json();
        alert('全平台签到执行结果:\\n' + d.message);
        loadData(true);
      } catch (e) {
        alert('签到失败: ' + e);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-bolt"></i> 立即全平台签到';
      }
    }

    // 模态框控制
    function openLoginHelperModal(platform = 'codebuddy') {
      openAddAccountModal(platform);
    }

    function openAddAccountModal(platform = 'codebuddy') {
      document.getElementById('accModalTitle').innerHTML = '<i class="fa-solid fa-user-plus text-indigo-400"></i> 录入与同步 AI 账号';
      document.getElementById('acc_id').value = '';
      document.getElementById('acc_platform').value = platform;
      document.getElementById('acc_remark').value = '';
      document.getElementById('acc_phone').value = '';
      document.getElementById('acc_token').value = '';
      document.getElementById('acc_smart_paste').value = '';
      document.getElementById('acc_trae_uid').value = '';
      document.getElementById('acc_trae_did').value = '766820083601979';
      togglePlatformFields();
      switchModalTab('local'); // 默认展示最省心的一键自动同步
      document.getElementById('accountModal').classList.remove('hidden');
    }

    function closeAccountModal() {
      document.getElementById('accountModal').classList.add('hidden');
    }

    function switchModalTab(tab) {
      const tabs = ['local', 'manual', 'web'];
      tabs.forEach(t => {
        const btn = document.getElementById(`tab_btn_${t}`);
        const content = document.getElementById(`tab_content_${t}`);
        if (!btn || !content) return;
        if (t === tab) {
          btn.className = "px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 text-white transition-all flex items-center gap-1.5";
          content.classList.remove('hidden');
        } else {
          btn.className = "px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-300 hover:text-white transition-all flex items-center gap-1.5";
          content.classList.add('hidden');
        }
      });
    }

    function handleSmartPaste(val) {
      val = (val || '').trim();
      const hintEl = document.getElementById('paste_status_hint');
      if (!val) {
        if (hintEl) hintEl.innerText = '💡 提示：支持粘贴 Bearer eyJ... 或包含 token 的任何文本。';
        return;
      }
      try {
        // 尝试解析 JSON
        if (val.startsWith('{') && val.endsWith('}')) {
          const j = JSON.parse(val);
          if (j.accessToken) document.getElementById('acc_token').value = j.accessToken;
          if (j.phone) document.getElementById('acc_phone').value = j.phone;
          if (j.remark || j.nickname) document.getElementById('acc_remark').value = j.remark || j.nickname;
          if (j.platform) {
            document.getElementById('acc_platform').value = j.platform;
            togglePlatformFields();
          }
          if (j.uid) document.getElementById('acc_trae_uid').value = j.uid;
          if (hintEl) hintEl.innerHTML = '<span class="text-emerald-400 font-semibold">✅ 成功解析 JSON 凭据数据</span>';
          return;
        }
      } catch (e) {}

      // 提取 Bearer Token 或 JWT
      if (val.includes('eyJ')) {
        let token = val;
        const m = val.match(/eyJ[a-zA-Z0-9_-]+\\.[a-zA-Z0-9_-]+\\.[a-zA-Z0-9_-]+/);
        if (m) token = m[0];
        document.getElementById('acc_token').value = token;
        
        // 尝试解码 JWT claims
        try {
          const parts = token.split('.');
          if (parts.length >= 2) {
            const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
            const payload = JSON.parse(decodeURIComponent(escape(atob(b64))));
            let phone = payload.preferred_username || '';
            let nick = payload.nickname || '';
            if (phone) document.getElementById('acc_phone').value = phone;
            if (nick && !document.getElementById('acc_remark').value) {
              document.getElementById('acc_remark').value = nick;
            }
            if (payload.iss && payload.iss.includes('codebuddy')) {
              document.getElementById('acc_platform').value = 'codebuddy';
              togglePlatformFields();
            }
            if (hintEl) hintEl.innerHTML = `<span class="text-emerald-400 font-semibold">✅ 已成功提取 Token · ${nick ? nick : ''} ${phone ? '('+phone+')' : ''}</span>`;
          }
        } catch (e) {
          if (hintEl) hintEl.innerHTML = '<span class="text-emerald-400 font-semibold">✅ 已提取 Token 凭据字符串</span>';
        }
      }
    }

    function togglePlatformFields() {
      const p = document.getElementById('acc_platform').value;
      const tf = document.getElementById('traeFields');
      if (p === 'trae') {
        tf.classList.remove('hidden');
      } else {
        tf.classList.add('hidden');
      }
    }

        // 快速备注修改逻辑
    function openRemarkModal(platform, id) {
      const list = platform === 'codebuddy' ? globalData?.codebuddy_accounts : (platform === 'trae' ? globalData?.trae_accounts : globalData?.qoder_accounts);
      const acc = (list || []).find(a => a.id === id);
      if (!acc) return;
      document.getElementById('remark_platform').value = platform;
      document.getElementById('remark_acc_id').value = id;
      const input = document.getElementById('remark_input');
      input.value = acc.remark || '';
      
      const platName = platform === 'trae' ? '字节跳动 TRAE CN' : (platform === 'codebuddy' ? '腾讯 CodeBuddy / WorkBuddy' : '通义 / 阿里 Qoder');
      const uidText = acc.uid ? ` (UID: ${acc.uid})` : '';
      document.getElementById('remarkModalSubtitle').innerText = `${platName}${uidText}`;

      document.getElementById('remarkModal').classList.remove('hidden');
      setTimeout(() => {
        input.focus();
        input.select();
      }, 50);
    }

    function closeRemarkModal() {
      document.getElementById('remarkModal').classList.add('hidden');
    }

    function setPresetRemark(text) {
      const input = document.getElementById('remark_input');
      input.value = text;
      input.focus();
    }

    async function submitRemarkChange() {
      const platform = document.getElementById('remark_platform').value;
      const id = document.getElementById('remark_acc_id').value;
      const remark = document.getElementById('remark_input').value.trim();
      if (!remark) {
        alert('请输入备注名称！');
        return;
      }

      const btn = document.getElementById('saveRemarkBtn');
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 保存中...';

      try {
        const res = await apiFetch('/api/account/remark', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ platform, id, remark })
        });
        const d = await res.json();
        if (d.success) {
          closeRemarkModal();
          loadData(false);
        } else {
          alert('修改备注失败: ' + (d.error || d.message));
        }
      } catch (e) {
        alert('网络请求异常: ' + e);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> 保存备注';
      }
    }

    // 支持在备注框直接回车保存
    document.addEventListener('DOMContentLoaded', () => {
      const el = document.getElementById('remark_input');
      if (el) {
        el.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            submitRemarkChange();
          }
        });
      }
    });

    async function editAccount(platform, id) {
      const list = platform === 'codebuddy' ? (globalData.codebuddy_accounts || []) : (platform === 'qoder' ? (globalData.qoder_accounts || []) : (globalData.trae_accounts || []));
      const acc = list.find(a => a.id === id);
      if (!acc) return;
      document.getElementById('accModalTitle').innerHTML = '<i class="fa-solid fa-pen-to-square text-indigo-400"></i> 编辑账号凭据';
      document.getElementById('acc_id').value = acc.id;
      document.getElementById('acc_platform').value = platform;
      document.getElementById('acc_remark').value = acc.remark;
      document.getElementById('acc_phone').value = acc.phone || '';
      document.getElementById('acc_token').value = '';
      document.getElementById('acc_trae_uid').value = acc.uid || '';
      document.getElementById('acc_trae_did').value = acc.deviceId || '766820083601979';
      togglePlatformFields();
      switchModalTab('manual');
      document.getElementById('accountModal').classList.remove('hidden');
    }

    async function saveAccount() {
      const btn = document.getElementById('saveAccBtn');
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 验证凭证中...';

      const payload = {
        id: document.getElementById('acc_id').value,
        platform: document.getElementById('acc_platform').value,
        remark: document.getElementById('acc_remark').value.trim() || '我的账号',
        phone: document.getElementById('acc_phone').value.trim(),
        accessToken: document.getElementById('acc_token').value.trim(),
        uid: document.getElementById('acc_trae_uid').value.trim(),
        deviceId: document.getElementById('acc_trae_did').value.trim() || '766820083601979'
      };

      if (!payload.accessToken && !payload.id) {
        alert('请填写 AccessToken');
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> 验证并保存到服务器';
        return;
      }

      try {
        const res = await apiFetch('/api/account/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const d = await res.json();
        if (d.success) {
          alert('🎉 账号验证成功，已保存到云端定时签到池！');
          closeAccountModal();
          loadData(true);
        } else {
          alert('保存失败: ' + (d.error || d.message));
        }
      } catch (e) {
        alert('请求错误: ' + e);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> 验证并保存到服务器';
      }
    }

    async function deleteAccount(platform, id) {
      if (!confirm('确定要删除该账号吗？')) return;
      try {
        const res = await apiFetch('/api/account/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ platform, id })
        });
        const d = await res.json();
        if (d.success) {
          loadData(true);
        } else {
          alert('删除失败: ' + d.error);
        }
      } catch (e) {
        alert('操作失败: ' + e);
      }
    }

    // 系统设置
    async function openSettingsModal() {
      try {
        const res = await apiFetch('/api/config');
        const cfg = await res.json();
        document.getElementById('cfg_admin_key').value = cfg.auth?.admin_key || '';
        document.getElementById('cfg_sched_hour').value = cfg.settings?.auto_checkin_hour ?? 9;
        document.getElementById('cfg_sched_min').value = cfg.settings?.auto_checkin_minute ?? 0;
        document.getElementById('settingsModal').classList.remove('hidden');
      } catch (e) {
        alert('获取配置失败');
      }
    }

    function closeSettingsModal() {
      document.getElementById('settingsModal').classList.add('hidden');
    }

    async function saveSystemSettings() {
      const btn = document.getElementById('saveSysBtn');
      btn.disabled = true;
      btn.innerHTML = '正在保存...';
      const payload = {
        admin_key: document.getElementById('cfg_admin_key').value.trim(),
        auto_checkin_hour: parseInt(document.getElementById('cfg_sched_hour').value, 10),
        auto_checkin_minute: parseInt(document.getElementById('cfg_sched_min').value, 10)
      };

      try {
        const res = await apiFetch('/api/config/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const d = await res.json();
        alert(d.message || '系统设置已更新');
        closeSettingsModal();
        loadData(true);
      } catch (e) {
        alert('保存失败: ' + e);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> 保存设置';
      }
    }

    setupWebTools();
    // 每次进入或刷新页面，强制向平台查最新数据
    loadData(true);
    setInterval(() => loadData(false), 20000);

    // 当用户切回网页标签页时，自动重新查询最新算力
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        loadData(true);
      }
    });
  </script>
</body>
</html>
"""

# ====================================================================
#  HTTP Request Handler
# ====================================================================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def check_auth(self):
        """校验管理员访问权限"""
        cfg = load_config()
        admin_key = cfg.get("auth", {}).get("admin_key", "").strip()
        if not admin_key:
            return True

        # 1. Query 参数 ?key=...
        query = parse_qs(urlparse(self.path).query)
        if query.get("key", [""])[0] == admin_key:
            return True

        # 2. Cookie ai_hub_key=...
        cookie_header = self.headers.get("Cookie", "")
        if cookie_header:
            c = SimpleCookie()
            try:
                c.load(cookie_header)
                if "ai_hub_key" in c and c["ai_hub_key"].value == admin_key:
                    return True
            except Exception:
                pass

        # 3. Header X-Hub-Key
        if self.headers.get("X-Hub-Key") == admin_key:
            return True

        return False

    def drop_connection(self):
        """直接物理阻断 TCP 连接：不返回任何 HTTP 状态码、协议头或内容，外部扫描器/陌生人只会得到 ERR_EMPTY_RESPONSE 或 ERR_CONNECTION_CLOSED"""
        self.close_connection = True
        try:
            import socket
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
        except Exception:
            pass

    def do_OPTIONS(self):
        """处理跨域 OPTIONS 预检请求（支持书签跨域导入）"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Hub-Key")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_HEAD(self):
        if not self.check_auth():
            self.drop_connection()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        cfg = load_config()
        admin_key = cfg.get("auth", {}).get("admin_key", "").strip()

        # 权限校验：无密钥直接物理阻断连接，不暴露任何服务信息
        if not self.check_auth():
            self.drop_connection()
            return

        if p in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if admin_key and query.get("key", [""])[0] == admin_key:
                # 种植 30 天 Cookie 免密
                self.send_header("Set-Cookie", f"ai_hub_key={admin_key}; Path=/; Max-Age=2592000; SameSite=Lax")
            self.end_headers()
            rendered_page = HTML_PAGE.replace("{{ADMIN_KEY}}", admin_key)
            self.wfile.write(rendered_page.encode("utf-8"))

        elif p == "/api/download/local-extract":
            le_path = os.path.join(SCRIPT_DIR, "local_extract.py")
            if os.path.exists(le_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/x-python; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=local_extract.py")
                self.end_headers()
                with open(le_path, "rb") as fp:
                    self.wfile.write(fp.read())
            else:
                self.send_response(404)
                self.end_headers()

        elif p == "/api/download/sync-bat":
            host = self.headers.get("Host", f"47.77.190.116:{PORT}")
            bat_lines = [
                "@echo off",
                "chcp 936 >nul",
                "title AI-Credits-Hub 本机多账号一键同步工具",
                "echo ================================================================",
                "echo       AI 算力与积分智能管家 · 本机账号一键同步",
                "echo ================================================================",
                "echo.",
                "echo 正在自动探测本机 CodeBuddy / WorkBuddy、TRAE 和 Qoder 客户端凭据...",
                "echo.",
                'if not exist "%~dp0local_extract.py" (',
                '    echo [1/2] 正在拉取最新的凭据提取引擎...',
                f"    powershell -NoProfile -Command \"(New-Object Net.WebClient).DownloadFile('http://{host}/api/download/local-extract', '%~dp0local_extract.py')\"",
                ")",
                f'python "%~dp0local_extract.py" --server http://{host} --key {admin_key} --push',
                "echo.",
                "echo ================================================================",
                "echo 同步执行完毕！请刷新云端智能管家控制台查看最新状态。",
                "echo ================================================================",
                "pause"
            ]
            bat_code = "\r\n".join(bat_lines) + "\r\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", "attachment; filename=sync.bat")
            self.end_headers()
            self.wfile.write(bat_code.encode("gbk", errors="replace"))

        elif p == "/api/data":
            force_refresh = query.get("refresh", [""])[0] in ("1", "true")
            cache_expired = (time.time() - CACHE_LAST_FETCH) > 5
            if force_refresh or cache_expired or not DATA_CACHE.get("summary"):
                update_cache()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(DATA_CACHE, ensure_ascii=False).encode("utf-8"))

        elif p == "/api/config":
            safe_cfg = {
                "auth": {"admin_key": cfg.get("auth", {}).get("admin_key", "")},
                "settings": cfg.get("settings", {"auto_checkin_hour": 9, "auto_checkin_minute": 0})
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(safe_cfg, ensure_ascii=False).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if not self.check_auth():
            self.drop_connection()
            return

        p = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body_raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(body_raw.decode("utf-8")) if body_raw else {}
        except Exception:
            body = {}

        if p == "/api/checkin":
            msg = execute_all_checkin()
            update_cache()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "message": msg}, ensure_ascii=False).encode("utf-8"))

        elif p == "/api/account/checkin":
            platform = body.get("platform")
            acc_id = body.get("id")
            cfg = load_config()
            target_list = cfg.get(f"{platform}_accounts", [])
            acc = next((a for a in target_list if a.get("id") == acc_id), None)
            if not acc:
                res_msg = "未找到指定账号"
            elif platform == "codebuddy":
                res_msg = checkin_codebuddy_account(acc)
            elif platform == "trae":
                res_msg = checkin_trae_account(acc)
            elif platform == "qoder":
                res_msg = checkin_qoder_account(acc)
            else:
                res_msg = "未知平台"
            update_cache()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "message": res_msg}, ensure_ascii=False).encode("utf-8"))

        elif p == "/api/account/remark":
            platform = body.get("platform")
            acc_id = body.get("id")
            new_remark = (body.get("remark") or "").strip()
            if platform not in ("codebuddy", "trae", "qoder"):
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "不支持的平台"}).encode("utf-8"))
                return
            if not acc_id:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "缺少账号 ID"}).encode("utf-8"))
                return
            if not new_remark:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "备注不能为空"}).encode("utf-8"))
                return

            cfg = load_config()
            key_name = f"{platform}_accounts"
            if key_name not in cfg:
                cfg[key_name] = []

            matched = False
            for acc in cfg[key_name]:
                if acc.get("id") == acc_id:
                    acc["remark"] = new_remark
                    acc["is_custom_remark"] = True
                    matched = True
                    break

            if not matched:
                self.send_response(404)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "未找到指定账号"}).encode("utf-8"))
                return

            save_config(cfg)
            update_cache()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "remark": new_remark}, ensure_ascii=False).encode("utf-8"))

        elif p == "/api/account/save":
            platform = body.get("platform")
            if platform not in ("codebuddy", "trae", "qoder"):
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "不支持的平台"}).encode("utf-8"))
                return

            cfg = load_config()
            key_name = f"{platform}_accounts"
            if key_name not in cfg:
                cfg[key_name] = []

            acc_id = body.get("id")
            token = body.get("accessToken", "").strip()

            # 若编辑已有账号且未填写 token，直接就地更新备注与基础属性，无需重新校验 token
            if acc_id and not token:
                matched = False
                for acc in cfg[key_name]:
                    if acc.get("id") == acc_id:
                        if body.get("remark"):
                            acc["remark"] = body.get("remark").strip()
                            acc["is_custom_remark"] = True
                        if "phone" in body:
                            acc["phone"] = body.get("phone", "").strip()
                        if "enabled" in body:
                            acc["enabled"] = bool(body.get("enabled"))
                        matched = True
                        break
                if matched:
                    save_config(cfg)
                    update_cache()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "id": acc_id}).encode("utf-8"))
                    return
                else:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "未找到指定账号"}).encode("utf-8"))
                    return

            if not token:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "Token 不能为空"}).encode("utf-8"))
                return

            acc_id = body.get("id")
            if not acc_id:
                acc_id = f"{platform}_{uuid.uuid4().hex[:8]}"

            account_data = {
                "id": acc_id,
                "remark": body.get("remark") or "账号",
                "phone": body.get("phone", "").strip(),
                "accessToken": token,
                "enabled": True
            }

            if platform == "codebuddy":
                account_data["refreshToken"] = body.get("refreshToken", "").strip()
                test_res = fetch_single_codebuddy(account_data)
                if not test_res.get("valid"):
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": f"Token 校验失败: {test_res.get('status_text')}"}).encode("utf-8"))
                    return
                account_data["nickname"] = test_res.get("nickname") or account_data["remark"]
                if not account_data["phone"] and test_res.get("phone"):
                    account_data["phone"] = test_res.get("phone")
                account_data["uid"] = test_res.get("uid") or ""
            elif platform == "trae":
                account_data["uid"] = str(body.get("uid", "")).strip()
                account_data["deviceId"] = body.get("deviceId", "766820083601979").strip()
                test_res = fetch_single_trae(account_data)
                if not test_res.get("valid"):
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": f"Token 校验失败: {test_res.get('status_text')}"}).encode("utf-8"))
                    return
                if not account_data["phone"] and test_res.get("phone"):
                    account_data["phone"] = test_res.get("phone")

            elif platform == "qoder":
                token = (body.get("token") or body.get("accessToken") or "").strip()
                if not token:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Qoder Token 不能为空"}).encode("utf-8"))
                    return
                account_data["token"] = token
                account_data["refreshToken"] = body.get("refreshToken", "").strip()
                account_data["uid"] = str(body.get("uid", "")).strip()
                account_data["name"] = body.get("name", "").strip()
                account_data["phone"] = body.get("phone", "").strip()
                test_res = fetch_single_qoder(account_data)
                if not test_res.get("valid"):
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": f"Qoder Token 校验失败: {test_res.get('status_text')}"}).encode("utf-8"))
                    return
                if not account_data["phone"] and test_res.get("phone"):
                    account_data["phone"] = test_res.get("phone")
                if not account_data["name"] and test_res.get("name"):
                    account_data["name"] = test_res.get("name")

            # 智能防重：根据 id 或平台的唯一 uid 匹配已有账号进行就地更新
            target_uid = account_data.get("uid")
            existing_idx = next(
                (i for i, a in enumerate(cfg[key_name]) if (acc_id and a.get("id") == acc_id) or (target_uid and str(a.get("uid")) == str(target_uid))),
                -1
            )
            if existing_idx >= 0:
                old_acc = cfg[key_name][existing_idx]
                account_data["id"] = old_acc.get("id", acc_id)
                # 若已有自定义备注，且当前推送的是系统自动探测默认格式的备注，则保持自定义备注不变
                incoming_remark = body.get("remark", "")
                is_auto_generated = (
                    not incoming_remark or
                    incoming_remark in ("账号", "本机自动提取账号") or
                    incoming_remark.startswith("TRAE (") or
                    incoming_remark.startswith("CodeBuddy (") or
                    incoming_remark.startswith("WorkBuddy客户端 (") or
                    incoming_remark.startswith("Qoder (") or
                    incoming_remark.startswith("Qoder CN (")
                )
                if old_acc.get("is_custom_remark") or (old_acc.get("remark") and is_auto_generated):
                    account_data["remark"] = old_acc.get("remark")
                    account_data["is_custom_remark"] = True
                cfg[key_name][existing_idx] = account_data
            else:
                cfg[key_name].append(account_data)

            save_config(cfg)
            update_cache()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "id": acc_id}).encode("utf-8"))

        elif p == "/api/account/delete":
            platform = body.get("platform")
            acc_id = body.get("id")
            cfg = load_config()
            key_name = f"{platform}_accounts"
            if key_name in cfg:
                cfg[key_name] = [a for a in cfg[key_name] if a.get("id") != acc_id]
                save_config(cfg)
                update_cache()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))

        elif p == "/api/config/save":
            cfg = load_config()
            if "admin_key" in body and body["admin_key"]:
                cfg["auth"]["admin_key"] = body["admin_key"].strip()
            if "auto_checkin_hour" in body:
                cfg["settings"]["auto_checkin_hour"] = int(body["auto_checkin_hour"])
            if "auto_checkin_minute" in body:
                cfg["settings"]["auto_checkin_minute"] = int(body["auto_checkin_minute"])
            save_config(cfg)
            update_cache()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "message": "配置保存成功！"}).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

def main():
    load_config()
    update_cache()

    t = threading.Thread(target=scheduler_worker, daemon=True)
    t.start()

    server = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    print("=" * 65)
    print(f"  AI-Credits-Hub (多账号版) 运行中...")
    print(f"  本地服务地址: http://127.0.0.1:{PORT}")
    print(f"  安全访问密钥: Hub_98bxy_Sec2026")
    print("=" * 65)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[退出] 服务已停止")

if __name__ == "__main__":
    main()
