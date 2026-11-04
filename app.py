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
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs
from http.cookies import SimpleCookie

# 保证控制台正常输出 UTF-8
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
    print("[错误] 缺少 requests 库，请先执行: pip install requests")
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

def load_config():
    """读取配置并自动将旧的单账号格式平滑迁移至多账号列表"""
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
        cfg["auth"] = {"admin_key": "888888", "admin_password": ""}
        changed = True
    if "settings" not in cfg:
        cfg["settings"] = {"auto_checkin_hour": 9, "auto_checkin_minute": 0}
        changed = True

    # 兼容与平滑迁移 CodeBuddy 单账号 -> 多账号列表
    if "codebuddy_accounts" not in cfg:
        cfg["codebuddy_accounts"] = []
        old_cb = cfg.get("codebuddy")
        if old_cb and isinstance(old_cb, dict) and old_cb.get("accessToken"):
            cfg["codebuddy_accounts"].append({
                "id": "cb_" + uuid.uuid4().hex[:8],
                "remark": old_cb.get("nickname") or "主账号",
                "accessToken": old_cb.get("accessToken", "").strip(),
                "refreshToken": old_cb.get("refreshToken", "").strip(),
                "uid": old_cb.get("uid", ""),
                "nickname": old_cb.get("nickname", "用户"),
                "enabled": True
            })
            changed = True

    # 兼容与平滑迁移 TRAE 单账号 -> 多账号列表
    if "trae_accounts" not in cfg:
        cfg["trae_accounts"] = []
        old_trae = cfg.get("trae")
        if old_trae and isinstance(old_trae, dict) and old_trae.get("accessToken"):
            cfg["trae_accounts"].append({
                "id": "trae_" + uuid.uuid4().hex[:8],
                "remark": f"主账号 (UID: {old_trae.get('uid', '未配置')})",
                "accessToken": old_trae.get("accessToken", "").strip(),
                "refreshToken": old_trae.get("refreshToken", "").strip(),
                "uid": str(old_trae.get("uid", "")),
                "deviceId": old_trae.get("deviceId", "766820083601979"),
                "enabled": True
            })
            changed = True

    if changed and os.path.exists(CONFIG_FILE):
        try:
            save_config(cfg)
        except Exception:
            pass

    return cfg

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ====================================================================
#  数据采集与校验逻辑
# ====================================================================
def fetch_single_codebuddy(acc):
    token = acc.get("accessToken", "").strip()
    res = {
        "id": acc.get("id"),
        "remark": acc.get("remark") or "未命名账号",
        "nickname": acc.get("nickname") or "未获取",
        "uid": acc.get("uid") or "-",
        "enabled": acc.get("enabled", True),
        "active": bool(token),
        "today_checked": False,
        "credits": 0,
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
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    try:
        r = s.post("https://www.codebuddy.cn/v2/billing/meter/checkin-activity-status", headers=headers, timeout=8)
        if r.status_code == 200 and r.json().get("code") == 0:
            d = r.json().get("data", {})
            res["valid"] = True
            res["today_checked"] = d.get("today_checked_in", False)
            res["credits"] = d.get("total_credits", 0)
            res["streak_days"] = d.get("streak_days", 0)
            res["expire_time"] = d.get("end_time", "2026-12-31 23:59:59")
            try:
                diff = datetime.datetime.strptime(res["expire_time"], "%Y-%m-%d %H:%M:%S") - datetime.datetime.now()
                res["expire_days"] = max(0, diff.days)
            except Exception:
                res["expire_days"] = 60
            res["status_text"] = f"连签 {res['streak_days']} 天 · 积分 {res['credits']}"
        elif r.status_code == 401:
            res["status_text"] = "Token 已失效 (401)"
        else:
            res["status_text"] = f"响应异常 ({r.status_code})"
    except Exception as e:
        res["status_text"] = f"网络连接重试中: {str(e)[:25]}"
    return res

def fetch_single_trae(acc):
    token = acc.get("accessToken", "").strip()
    res = {
        "id": acc.get("id"),
        "remark": acc.get("remark") or "未命名账号",
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
    s = get_session()
    try:
        r_st = s.post("https://api.trae.cn/trae/api/v2/ug/checkin_credits/status", headers=headers, data='{"req_source": 1}', timeout=8)
        if r_st.status_code == 200 and r_st.json().get("code") == 0:
            res["valid"] = True
            res["today_checked"] = r_st.json().get("did_checked_in", False)

        r_ent = s.post("https://api.trae.cn/trae/api/v2/pay/user_current_entitlement_list", headers=headers, json={}, timeout=8)
        if r_ent.status_code == 200:
            res["valid"] = True
            ent = r_ent.json()
            sm = ent.get("usage_summary", {})
            total_amt = sm.get("total_amount", 600)
            consumed = sm.get("consumed_amount", 0)
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
            res["status_text"] = f"已消耗 {res['consumed']} / 配额 {total_amt} 点 ({res['used_pct']}%)"
        elif r_ent.status_code == 401 or (r_st.status_code == 200 and r_st.json().get("code") == 1001):
            res["status_text"] = "Token 已失效 (401)"
        else:
            res["status_text"] = f"响应异常 ({r_ent.status_code})"
    except Exception as e:
        res["status_text"] = f"网络连接重试中: {str(e)[:25]}"
    return res

# ====================================================================
#  签到执行核心
# ====================================================================
def checkin_codebuddy_account(acc):
    token = acc.get("accessToken", "").strip()
    if not token or not acc.get("enabled", True):
        return "未启用或无 Token"
    s = get_session()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
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

    summary = " | ".join(results) if results else "暂无已启用的有效账号"
    log(f"[多账号签到执行完毕] {summary}")
    return summary

# ====================================================================
#  缓存与后台调度器
# ====================================================================
DATA_CACHE = {}

def update_cache():
    global DATA_CACHE
    cfg = load_config()
    
    cb_list = [fetch_single_codebuddy(acc) for acc in cfg.get("codebuddy_accounts", [])]
    trae_list = [fetch_single_trae(acc) for acc in cfg.get("trae_accounts", [])]

    total_accounts = len(cb_list) + len(trae_list)
    today_checked_count = sum(1 for a in cb_list + trae_list if a.get("today_checked"))
    total_credits = sum(a.get("credits", 0) for a in cb_list + trae_list)

    DATA_CACHE = {
        "server_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "total_accounts": total_accounts,
            "today_checked_count": today_checked_count,
            "total_credits": round(total_credits, 1),
            "scheduler_time": f"{cfg.get('settings', {}).get('auto_checkin_hour', 9):02d}:{cfg.get('settings', {}).get('auto_checkin_minute', 0):02d}"
        },
        "codebuddy_accounts": cb_list,
        "trae_accounts": trae_list
    }

def scheduler_thread():
    time.sleep(2)
    update_cache()
    last_day = None
    while True:
        try:
            cfg = load_config()
            st = cfg.get("settings", {})
            target_hour = st.get("auto_checkin_hour", 9)
            target_min = st.get("auto_checkin_minute", 0)
            now = datetime.datetime.now()
            if now.hour == target_hour and now.minute == target_min and last_day != now.day:
                last_day = now.day
                execute_all_checkin()
                update_cache()
            update_cache()
        except Exception:
            pass
        time.sleep(60)

# ====================================================================
#  HTML 前端模板（多账号卡片 + 模态框）
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
        <div class="flex items-center gap-4 bg-slate-900/60 px-4 py-2 rounded-xl border border-slate-800 text-xs text-slate-300">
          <div>托管账号: <span id="stat_total" class="font-bold text-indigo-400">0</span></div>
          <div class="w-px h-3 bg-slate-700"></div>
          <div>今日已打卡: <span id="stat_checked" class="font-bold text-emerald-400">0</span></div>
          <div class="w-px h-3 bg-slate-700"></div>
          <div>累计总算力: <span id="stat_credits" class="font-bold text-amber-300">0</span></div>
        </div>

        <button onclick="triggerCheckinAll()" id="checkinAllBtn" class="px-4 py-2.5 bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white font-medium rounded-xl shadow-lg shadow-emerald-500/20 flex items-center gap-2 text-sm transition-all transform active:scale-95">
          <i class="fa-solid fa-bolt"></i> 立即全平台签到
        </button>
        <button onclick="openAddAccountModal()" class="px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl shadow-lg shadow-indigo-500/20 flex items-center gap-2 text-sm transition-all">
          <i class="fa-solid fa-user-plus"></i> 添加账号
        </button>
        <button onclick="openSettingsModal()" class="p-2.5 glass hover:bg-slate-700/50 rounded-xl text-slate-300 hover:text-white text-sm" title="系统与凭证设置">
          <i class="fa-solid fa-gear"></i>
        </button>
        <button onclick="loadData()" class="p-2.5 glass hover:bg-slate-700/50 rounded-xl text-slate-300 hover:text-white text-sm" title="刷新数据">
          <i class="fa-solid fa-rotate-right"></i>
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
        <button onclick="openAddAccountModal('codebuddy')" class="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
          <i class="fa-solid fa-plus"></i> 录入 CodeBuddy 账号
        </button>
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
        <button onclick="openAddAccountModal('trae')" class="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
          <i class="fa-solid fa-plus"></i> 录入 TRAE 账号
        </button>
      </div>
      <div id="traeGrid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"></div>
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
          <div class="p-3.5 rounded-xl bg-slate-800/60 border border-slate-700/50 flex items-start gap-3">
            <div class="p-2 bg-purple-500/20 text-purple-400 rounded-lg text-sm"><i class="fa-solid fa-clock"></i></div>
            <div class="flex-1">
              <div class="flex justify-between items-center"><span class="font-medium text-sm text-slate-200">Xiaomi MiMo 闲时 0.8 倍折扣</span><span class="text-xs text-purple-300 font-mono">0:00 - 8:00</span></div>
              <p class="text-xs text-slate-400 mt-1">夜间至清晨调用全系 Pro / Omni 模型仅消耗 0.8 倍点数，大项目批量重构建议错峰执行。</p>
            </div>
          </div>
        </div>
      </section>

      <!-- 备用方案 -->
      <section class="glass p-6 rounded-2xl shadow-xl space-y-4">
        <div class="flex items-center justify-between border-b border-slate-700/60 pb-3">
          <h2 class="text-lg font-semibold text-teal-300 flex items-center gap-2"><i class="fa-solid fa-shield-halved text-teal-400"></i> 主编程软件没额度的可靠备用方案</h2>
          <span class="text-xs px-2.5 py-1 bg-teal-500/20 text-teal-300 rounded-full border border-teal-500/30">断粮兜底</span>
        </div>
        <div class="space-y-3">
          <div class="p-3.5 rounded-xl bg-gradient-to-r from-slate-800 to-indigo-950/40 border border-indigo-500/30 flex items-center justify-between">
            <div>
              <span class="text-xs font-semibold text-indigo-400 uppercase tracking-wider">第一备用梯队 · 首选白嫖</span>
              <h3 class="font-bold text-sm text-white mt-0.5">切换至 WorkBuddy / CodeBuddy</h3>
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

  <!-- 模态框 1：添加 / 编辑账号 -->
  <div id="accountModal" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="glass max-w-xl w-full p-6 md:p-8 rounded-2xl shadow-2xl space-y-6 max-h-[90vh] overflow-y-auto custom-scroll">
      <div class="flex justify-between items-center border-b border-slate-700/60 pb-4">
        <h3 id="accModalTitle" class="text-lg font-bold text-white flex items-center gap-2"><i class="fa-solid fa-user-plus text-indigo-400"></i> 添加 AI 账号</h3>
        <button onclick="closeAccountModal()" class="text-slate-400 hover:text-white text-xl"><i class="fa-solid fa-xmark"></i></button>
      </div>

      <input type="hidden" id="acc_id">
      
      <div class="space-y-4 text-xs">
        <div>
          <label class="block text-slate-300 font-medium mb-1">所属平台:</label>
          <select id="acc_platform" onchange="togglePlatformFields()" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500">
            <option value="codebuddy">腾讯 CodeBuddy / WorkBuddy</option>
            <option value="trae">字节跳动 TRAE CN (SOLO)</option>
          </select>
        </div>

        <div>
          <label class="block text-slate-300 font-medium mb-1">账号备注 (区分小号):</label>
          <input type="text" id="acc_remark" placeholder="例如: 毕书源 (主号)、日常写代码小号1..." class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500">
        </div>

        <div>
          <div class="flex justify-between items-center mb-1">
            <label class="text-slate-300 font-medium">AccessToken (访问凭据):</label>
            <span id="tokenHelpLink" class="text-indigo-400 hover:underline cursor-pointer">快捷获取指引</span>
          </div>
          <textarea id="acc_token" rows="4" placeholder="粘贴该账号的 accessToken / JWT 凭证..." class="w-full bg-slate-900 border border-slate-700 rounded-xl p-3 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono text-[11px]"></textarea>
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

        <div class="p-3 bg-slate-900/60 rounded-xl border border-slate-800 text-[11px] text-slate-400 space-y-1">
          <p><i class="fa-solid fa-lightbulb text-amber-400 mr-1"></i> <b>提示</b>：点击保存时，服务端会自动联网验证该凭据的有效性并获取最新积分！</p>
          <p>也可以在本地电脑直接运行 <code>python local_extract.py</code> 自动提取并一键推送到此服务端！</p>
        </div>
      </div>

      <div class="flex justify-end gap-3 pt-4 border-t border-slate-700/60">
        <button onclick="closeAccountModal()" class="px-5 py-2 glass hover:bg-slate-700/50 rounded-xl text-slate-300 text-xs">取消</button>
        <button onclick="saveAccount()" id="saveAccBtn" class="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl text-xs transition-all flex items-center gap-2">
          <i class="fa-solid fa-floppy-disk"></i> 验证并保存到服务器
        </button>
      </div>
    </div>
  </div>

  <!-- 模态框 2：系统配置中心 -->
  <div id="settingsModal" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="glass max-w-xl w-full p-6 md:p-8 rounded-2xl shadow-2xl space-y-6 max-h-[90vh] overflow-y-auto custom-scroll">
      <div class="flex justify-between items-center border-b border-slate-700/60 pb-4">
        <h3 class="text-lg font-bold text-white flex items-center gap-2"><i class="fa-solid fa-gear text-indigo-400"></i> 系统与定时签到设置</h3>
        <button onclick="closeSettingsModal()" class="text-slate-400 hover:text-white text-xl"><i class="fa-solid fa-xmark"></i></button>
      </div>

      <div class="space-y-4 text-xs">
        <div>
          <label class="block text-slate-300 font-medium mb-1">安全访问密码 / Secret Key:</label>
          <input type="text" id="cfg_admin_key" placeholder="如 888888 (访问时在网址后加 ?key=888888)" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono">
          <p class="text-[11px] text-slate-400 mt-1">设置后未经授权的陌生访问将展示 403 锁定屏，保护你的多账号隐私。</p>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-slate-300 font-medium mb-1">每日定时签到时间 (小时 0-23):</label>
            <input type="number" id="cfg_sched_hour" min="0" max="23" value="9" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono">
          </div>
          <div>
            <label class="block text-slate-300 font-medium mb-1">签到时间 (分钟 0-59):</label>
            <input type="number" id="cfg_sched_min" min="0" max="59" value="0" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono">
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

  <script>
    let globalData = null;

    async function loadData() {
      try {
        const res = await fetch('/api/data');
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

        // 渲染 CodeBuddy
        renderAccounts('codebuddy', globalData.codebuddy_accounts, document.getElementById('codebuddyGrid'));
        document.getElementById('cb_count_badge').innerText = `${globalData.codebuddy_accounts.length} 个账号`;

        // 渲染 TRAE
        renderAccounts('trae', globalData.trae_accounts, document.getElementById('traeGrid'));
        document.getElementById('trae_count_badge').innerText = `${globalData.trae_accounts.length} 个账号`;

      } catch (err) {
        console.error(err);
      }
    }

    function renderAccounts(platform, accounts, container) {
      container.innerHTML = '';
      if (!accounts || accounts.length === 0) {
        container.innerHTML = `
          <div class="col-span-full glass-card p-8 rounded-2xl text-center border-dashed border-2 border-slate-700/60">
            <div class="text-3xl text-slate-600 mb-2"><i class="fa-regular fa-folder-open"></i></div>
            <p class="text-sm text-slate-400">暂未添加任何 ${platform === 'codebuddy' ? 'CodeBuddy' : 'TRAE'} 账号</p>
            <button onclick="openAddAccountModal('${platform}')" class="mt-4 px-4 py-2 bg-indigo-600/30 hover:bg-indigo-600 text-indigo-300 hover:text-white rounded-xl text-xs transition-all">
              <i class="fa-solid fa-plus mr-1"></i> 立即添加此平台账号
            </button>
          </div>
        `;
        return;
      }

      accounts.forEach(acc => {
        const isSoon = acc.expire_days <= 7;
        const badge = acc.today_checked 
          ? '<span class="px-2.5 py-1 bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded-full text-xs font-medium"><i class="fa-solid fa-check"></i> 今日已签</span>'
          : (acc.valid ? '<span class="px-2.5 py-1 bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded-full text-xs font-medium"><i class="fa-solid fa-clock"></i> 待签到</span>' : '<span class="px-2.5 py-1 bg-rose-500/20 text-rose-300 border border-rose-500/30 rounded-full text-xs font-medium">凭据失效</span>');

        const card = document.createElement('div');
        card.className = "glass p-5 rounded-2xl shadow-lg glow transition-all duration-300 flex flex-col justify-between";
        card.innerHTML = `
          <div>
            <div class="flex justify-between items-start gap-2 mb-3">
              <div>
                <h3 class="font-bold text-base text-white flex items-center gap-2">
                  ${acc.remark}
                  ${!acc.enabled ? '<span class="text-[10px] bg-slate-700 text-slate-400 px-1.5 py-0.5 rounded">已暂停</span>' : ''}
                </h3>
                <p class="text-xs text-slate-400 mt-0.5 font-mono">
                  ${platform === 'codebuddy' ? (acc.nickname || '未同步') : ('UID: ' + acc.uid)}
                </p>
              </div>
              ${badge}
            </div>

            <div class="my-3 p-4 rounded-xl bg-slate-900/60 border border-slate-800">
              <div class="text-xs text-slate-400">当前可用剩余积分 / 算力</div>
              <div class="text-2xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-white via-indigo-100 to-indigo-300 mt-1">
                ${acc.credits} <span class="text-xs font-normal text-slate-400">Points</span>
              </div>
              ${platform === 'trae' ? `
                <div class="mt-3">
                  <div class="flex justify-between text-xs text-slate-400 mb-1">
                    <span>已消耗 ${acc.consumed || 0}</span>
                    <span>使用率 ${acc.used_pct || 0}%</span>
                  </div>
                  <div class="w-full bg-slate-700 h-1.5 rounded-full overflow-hidden">
                    <div class="bg-indigo-500 h-1.5 rounded-full" style="width: ${acc.used_pct || 0}%"></div>
                  </div>
                </div>
              ` : `
                <div class="mt-2 text-[11px] text-slate-400">
                  <span>${acc.status_text}</span>
                </div>
              `}
            </div>
          </div>

          <div>
            <div class="py-2 border-t border-slate-700/60 flex items-center justify-between text-xs">
              <span class="text-slate-400">到期: <span class="text-slate-300">${acc.expire_time.split(' ')[0]}</span></span>
              <span class="px-2 py-0.5 rounded border text-[11px] ${isSoon ? 'bg-rose-500/20 text-rose-300 border-rose-500/30' : 'bg-slate-700/50 text-slate-300 border-slate-600/30'}">
                剩 ${acc.expire_days} 天
              </span>
            </div>

            <div class="pt-2 border-t border-slate-700/60 flex items-center justify-end gap-2 text-xs">
              <button onclick="checkinSingle('${platform}', '${acc.id}')" class="px-3 py-1 bg-emerald-600/30 hover:bg-emerald-600 text-emerald-300 hover:text-white rounded-lg transition-all flex items-center gap-1">
                <i class="fa-solid fa-bolt"></i> 单独签到
              </button>
              <button onclick="deleteAccount('${platform}', '${acc.id}')" class="px-2.5 py-1 glass hover:bg-rose-900/40 text-slate-400 hover:text-rose-300 rounded-lg transition-all">
                <i class="fa-solid fa-trash-can"></i>
              </button>
            </div>
          </div>
        `;
        container.appendChild(card);
      });
    }

    // 单账号签到
    async function checkinSingle(platform, id) {
      try {
        const res = await fetch('/api/account/checkin', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ platform, id })
        });
        const d = await res.json();
        alert('签到结果:\\n' + d.message);
        loadData();
      } catch (e) {
        alert('请求失败: ' + e);
      }
    }

    // 全平台所有账号签到
    async function triggerCheckinAll() {
      const btn = document.getElementById('checkinAllBtn');
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 正在签到所有账号...';
      try {
        const res = await fetch('/api/checkin', { method: 'POST' });
        const d = await res.json();
        alert('全平台签到执行结果:\\n' + d.message);
        loadData();
      } catch (e) {
        alert('签到失败: ' + e);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-bolt"></i> 立即全平台签到';
      }
    }

    // 模态框控制
    function openAddAccountModal(platform = 'codebuddy') {
      document.getElementById('accModalTitle').innerHTML = '<i class="fa-solid fa-user-plus text-indigo-400"></i> 添加 AI 账号';
      document.getElementById('acc_id').value = '';
      document.getElementById('acc_platform').value = platform;
      document.getElementById('acc_remark').value = '';
      document.getElementById('acc_token').value = '';
      document.getElementById('acc_trae_uid').value = '';
      document.getElementById('acc_trae_did').value = '766820083601979';
      togglePlatformFields();
      document.getElementById('accountModal').classList.remove('hidden');
    }

    function closeAccountModal() {
      document.getElementById('accountModal').classList.add('hidden');
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

    async function saveAccount() {
      const btn = document.getElementById('saveAccBtn');
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 验证凭证中...';

      const payload = {
        id: document.getElementById('acc_id').value,
        platform: document.getElementById('acc_platform').value,
        remark: document.getElementById('acc_remark').value.trim() || '我的账号',
        accessToken: document.getElementById('acc_token').value.trim(),
        uid: document.getElementById('acc_trae_uid').value.trim(),
        deviceId: document.getElementById('acc_trae_did').value.trim() || '766820083601979'
      };

      if (!payload.accessToken) {
        alert('请填写 AccessToken');
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> 验证并保存到服务器';
        return;
      }

      try {
        const res = await fetch('/api/account/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const d = await res.json();
        if (d.success) {
          alert('账号验证成功并已保存！');
          closeAccountModal();
          loadData();
        } else {
          alert('保存失败: ' + (d.error || d.message));
        }
      } catch (e) {
        alert('网络错误: ' + e);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> 验证并保存到服务器';
      }
    }

    async function deleteAccount(platform, id) {
      if (!confirm('确定要删除此账号吗？')) return;
      try {
        const res = await fetch('/api/account/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ platform, id })
        });
        const d = await res.json();
        if (d.success) {
          loadData();
        } else {
          alert('删除失败: ' + d.error);
        }
      } catch (e) {
        alert('请求失败: ' + e);
      }
    }

    // 系统设置
    async function openSettingsModal() {
      try {
        const res = await fetch('/api/config');
        const cfg = await res.json();
        document.getElementById('cfg_admin_key').value = cfg.auth?.admin_key || '';
        document.getElementById('cfg_sched_hour').value = cfg.settings?.auto_checkin_hour ?? 9;
        document.getElementById('cfg_sched_min').value = cfg.settings?.auto_checkin_minute ?? 0;
        document.getElementById('settingsModal').classList.remove('hidden');
      } catch (e) {
        alert('读取配置失败');
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
        auto_checkin_hour: parseInt(document.getElementById('cfg_sched_hour').value),
        auto_checkin_minute: parseInt(document.getElementById('cfg_sched_min').value)
      };
      try {
        const res = await fetch('/api/system/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const d = await res.json();
        alert('系统设置已更新！');
        closeSettingsModal();
        loadData();
      } catch (e) {
        alert('保存失败: ' + e);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> 保存设置';
      }
    }

    loadData();
    setInterval(loadData, 20000);
  </script>
</body>
</html>
"""

# ====================================================================
#  403 锁定屏（密码保护）
# ====================================================================
LOCK_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>🔒 403 访问受限 | AI-Credits-Hub</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    body { background-color: #0b0f19; background-image: radial-gradient(circle at 50% 0%, rgba(239, 68, 68, 0.15) 0%, transparent 75%); }
    .glass { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(14px); border: 1px solid rgba(255, 255, 255, 0.08); }
  </style>
</head>
<body class="text-slate-100 min-h-screen flex items-center justify-center p-4">
  <div class="glass max-w-md w-full p-8 rounded-2xl shadow-2xl text-center space-y-6">
    <div class="inline-flex p-4 bg-rose-500/20 text-rose-400 rounded-2xl text-3xl">
      <i class="fa-solid fa-lock"></i>
    </div>
    <div>
      <h2 class="text-xl font-bold text-white">私有 AI 算力监控后台</h2>
      <p class="text-xs text-slate-400 mt-2">当前控制台已受密钥后缀保护，请输入管理员密钥解锁</p>
    </div>
    <form onsubmit="handleAuth(event)" class="space-y-4">
      <input type="password" id="authKey" placeholder="输入访问密钥 (如 888888)..." class="w-full bg-slate-900 border border-slate-700 rounded-xl p-3 text-slate-200 text-center font-mono focus:outline-none focus:border-indigo-500">
      <button type="submit" class="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl text-sm transition-all shadow-lg shadow-indigo-500/20">
        验证并进入后台
      </button>
    </form>
  </div>
  <script>
    function handleAuth(e) {
      e.preventDefault();
      const k = document.getElementById('authKey').value.trim();
      if (!k) return;
      document.cookie = "ai_hub_key=" + encodeURIComponent(k) + "; path=/; max-age=2592000";
      window.location.search = "?key=" + encodeURIComponent(k);
    }
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

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        cfg = load_config()
        admin_key = cfg.get("auth", {}).get("admin_key", "").strip()

        # 权限校验
        if not self.check_auth():
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(LOCK_HTML.encode("utf-8"))
            return

        if p in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if admin_key and query.get("key", [""])[0] == admin_key:
                # 种植 30 天 Cookie 免密
                self.send_header("Set-Cookie", f"ai_hub_key={admin_key}; Path=/; Max-Age=2592000; SameSite=Lax")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))

        elif p == "/api/data":
            if not DATA_CACHE.get("summary"):
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
            self.send_response(403)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"success": False, "error": "403 Forbidden"}).encode("utf-8"))
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
            else:
                res_msg = "未知平台"
            update_cache()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "message": res_msg}, ensure_ascii=False).encode("utf-8"))

        elif p == "/api/account/save":
            platform = body.get("platform")
            if platform not in ("codebuddy", "trae"):
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "不支持的平台"}).encode("utf-8"))
                return

            cfg = load_config()
            key_name = f"{platform}_accounts"
            if key_name not in cfg:
                cfg[key_name] = []

            acc_id = body.get("id")
            if not acc_id:
                acc_id = f"{platform}_{uuid.uuid4().hex[:8]}"

            account_data = {
                "id": acc_id,
                "remark": body.get("remark") or "账号",
                "accessToken": body.get("accessToken", "").strip(),
                "enabled": True
            }

            if platform == "codebuddy":
                account_data["refreshToken"] = body.get("refreshToken", "").strip()
                test_res = fetch_single_codebuddy(account_data)
                if not test_res.get("valid"):
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": f"Token 校验失败: {test_res.get('status_text')}"}).encode("utf-8"))
                    return
                account_data["nickname"] = test_res.get("nickname") or account_data["remark"]
            elif platform == "trae":
                account_data["uid"] = str(body.get("uid", "")).strip()
                account_data["deviceId"] = body.get("deviceId", "766820083601979").strip()
                test_res = fetch_single_trae(account_data)
                if not test_res.get("valid"):
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": f"Token 校验失败: {test_res.get('status_text')}"}).encode("utf-8"))
                    return

            # 更新或添加
            existing_idx = next((i for i, a in enumerate(cfg[key_name]) if a.get("id") == acc_id), -1)
            if existing_idx >= 0:
                cfg[key_name][existing_idx] = account_data
            else:
                cfg[key_name].append(account_data)

            save_config(cfg)
            update_cache()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
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
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))

        elif p == "/api/system/save":
            cfg = load_config()
            if "admin_key" in body:
                cfg["auth"]["admin_key"] = body["admin_key"].strip()
            if "auto_checkin_hour" in body:
                cfg["settings"]["auto_checkin_hour"] = int(body["auto_checkin_hour"])
            if "auto_checkin_minute" in body:
                cfg["settings"]["auto_checkin_minute"] = int(body["auto_checkin_minute"])
            save_config(cfg)
            update_cache()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

def main():
    t = threading.Thread(target=scheduler_thread, daemon=True)
    t.start()
    server = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    log(f"==========================================================")
    log(f"  🚀 AI-Credits-Hub (多账号版) 已启动，端口: {PORT}")
    log(f"  🌐 访问地址: http://127.0.0.1:{PORT}")
    log(f"==========================================================")
    server.serve_forever()

if __name__ == "__main__":
    main()
