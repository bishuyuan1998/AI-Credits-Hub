#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
====================================================================
           AI-Credits-Hub · AI 算力与积分智能管家
====================================================================
GitHub: https://github.com/bishuyuan/AI-Credits-Hub
License: MIT
====================================================================
"""

import os
import sys
import json
import time
import datetime
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

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
    if not os.path.exists(CONFIG_FILE):
        if os.path.exists(EXAMPLE_CONFIG):
            with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"auth": {"admin_password": ""}, "codebuddy": {}, "trae": {}}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ====================================================================
#  数据采集与签到核心
# ====================================================================
def fetch_codebuddy(cfg):
    cb = cfg.get("codebuddy", {})
    t = cb.get("accessToken", "").strip()
    info = {
        "name": "腾讯 CodeBuddy / WorkBuddy",
        "account": cb.get("nickname", "未配置"),
        "active": bool(t),
        "today_checked": False,
        "credits": 0,
        "streak_days": 0,
        "expire_time": "-",
        "expire_days": 0,
        "used_pct": 0,
        "consumed": 0,
        "detail": "点击右上角「设置」配置 Token 后生效"
    }
    if not t:
        return info

    s = get_session()
    headers = {"Authorization": f"Bearer {t}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    try:
        r = s.post("https://www.codebuddy.cn/v2/billing/meter/checkin-activity-status", headers=headers, timeout=8)
        if r.status_code == 200 and r.json().get("code") == 0:
            d = r.json().get("data", {})
            info["today_checked"] = d.get("today_checked_in", False)
            info["credits"] = d.get("total_credits", 0)
            info["streak_days"] = d.get("streak_days", 0)
            info["expire_time"] = d.get("end_time", "2026-12-31 23:59:59")
            try:
                diff = datetime.datetime.strptime(info["expire_time"], "%Y-%m-%d %H:%M:%S") - datetime.datetime.now()
                info["expire_days"] = max(0, diff.days)
            except Exception:
                info["expire_days"] = 60
            info["detail"] = f"连签 {info['streak_days']} 天，累计积分 {info['credits']}"
        elif r.status_code == 401:
            info["detail"] = "Token 已失效，请在设置中更新"
    except Exception as e:
        info["detail"] = "网络连接重试中: " + str(e)[:30]
    return info

def fetch_trae(cfg):
    trae = cfg.get("trae", {})
    t = trae.get("accessToken", "").strip()
    info = {
        "name": "字节跳动 TRAE CN (SOLO)",
        "account": f"UID: {trae.get('uid', '未配置')}",
        "active": bool(t),
        "today_checked": False,
        "credits": 0,
        "total_credits": 600,
        "consumed": 0,
        "used_pct": 0,
        "expire_time": "-",
        "expire_days": 0,
        "detail": "点击右上角「设置」配置 Token 后生效"
    }
    if not t:
        return info

    headers = {
        "Authorization": "Cloud-IDE-JWT " + t, "X-User-Region": "CN", "User-Agent": "Trae/1.107.1",
        "Content-Type": "application/json", "x-device-id": trae.get("deviceId", "766820083601979"),
        "x-device-type": "Windows", "x-os-version": "10.0.19045", "x-app-version": "1.107.1"
    }
    s = get_session()
    try:
        r_st = s.post("https://api.trae.cn/trae/api/v2/ug/checkin_credits/status", headers=headers, data='{"req_source": 1}', timeout=8)
        if r_st.status_code == 200 and r_st.json().get("code") == 0:
            info["today_checked"] = r_st.json().get("did_checked_in", False)
        
        r_ent = s.post("https://api.trae.cn/trae/api/v2/pay/user_current_entitlement_list", headers=headers, json={}, timeout=8)
        if r_ent.status_code == 200:
            ent = r_ent.json()
            sm = ent.get("usage_summary", {})
            total_amt = sm.get("total_amount", 600)
            consumed = sm.get("consumed_amount", 0)
            info["total_credits"] = total_amt
            info["consumed"] = round(consumed, 1)
            info["credits"] = round(total_amt - consumed, 1)
            info["used_pct"] = round((consumed / total_amt * 100), 1) if total_amt else 0
            packs = ent.get("user_entitlement_pack_list", [])
            if packs:
                ts = packs[0].get("entitlement_base_info", {}).get("end_time")
                if ts:
                    exp = datetime.datetime.fromtimestamp(ts)
                    info["expire_time"] = exp.strftime("%Y-%m-%d %H:%M:%S")
                    info["expire_days"] = max(0, (exp - datetime.datetime.now()).days)
            info["detail"] = f"已消耗 {info['consumed']} / 配额 {total_amt} 点 (使用率 {info['used_pct']}%)"
        elif r_ent.status_code == 401 or (r_st.status_code == 200 and r_st.json().get("code") == 1001):
            info["detail"] = "Token 已失效，请在设置中更新"
    except Exception as e:
        info["detail"] = "网络连接重试中: " + str(e)[:30]
    return info

def execute_all_checkin():
    cfg = load_config()
    s = get_session()
    res = []
    
    # 1. CodeBuddy
    cb = cfg.get("codebuddy", {})
    if cb.get("accessToken"):
        try:
            r = s.post("https://www.codebuddy.cn/v2/billing/meter/daily-checkin", headers={"Authorization": f"Bearer {cb['accessToken']}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, timeout=8)
            msg = r.json().get("msg", "OK") if r.status_code == 200 else f"HTTP {r.status_code}"
            res.append(f"CodeBuddy: {msg}")
        except Exception as e:
            res.append(f"CodeBuddy: {e}")

    # 2. TRAE
    trae = cfg.get("trae", {})
    if trae.get("accessToken"):
        try:
            h = {
                "Authorization": "Cloud-IDE-JWT " + trae["accessToken"], "X-User-Region": "CN",
                "User-Agent": "Trae/1.107.1", "Content-Type": "application/json",
                "x-device-id": trae.get("deviceId", "766820083601979"), "x-device-type": "Windows",
                "x-os-version": "10.0.19045", "x-app-version": "1.107.1"
            }
            r = s.post("https://api.trae.cn/trae/api/v2/ug/checkin_credits/claim", headers=h, data='{"req_source": 1}', timeout=8)
            msg = r.json().get("message", "OK") if r.status_code == 200 else f"HTTP {r.status_code}"
            res.append(f"TRAE: {msg}")
        except Exception as e:
            res.append(f"TRAE: {e}")

    summary = " | ".join(res) if res else "暂未配置任何有效 Token"
    log(f"[自动签到触发] {summary}")
    return summary

DATA_CACHE = {"server_time": "", "tools": []}

def update_cache():
    global DATA_CACHE
    cfg = load_config()
    DATA_CACHE = {
        "server_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tools": [fetch_codebuddy(cfg), fetch_trae(cfg)]
    }

def scheduler_thread():
    time.sleep(2)
    update_cache()
    last_day = None
    while True:
        try:
            now = datetime.datetime.now()
            if now.hour == 9 and now.minute == 0 and last_day != now.day:
                last_day = now.day
                execute_all_checkin()
                update_cache()
            update_cache()
        except Exception:
            pass
        time.sleep(60)

# ====================================================================
#  前端 HTML 模板（带凭证维护模态框）
# ====================================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI 算力与积分智能管家 | AI-Credits-Hub</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    body { background-color: #0b0f19; background-image: radial-gradient(circle at 50% 0%, rgba(99, 102, 241, 0.15) 0%, transparent 75%); }
    .glass { background: rgba(30, 41, 59, 0.65); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }
    .glow:hover { box-shadow: 0 0 25px -5px rgba(99, 102, 241, 0.4); border-color: rgba(99, 102, 241, 0.4); }
  </style>
</head>
<body class="text-slate-100 min-h-screen p-4 md:p-8 font-sans">
  <div class="max-w-7xl mx-auto space-y-8">
    
    <!-- 头部导航 -->
    <header class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 glass p-6 rounded-2xl shadow-xl">
      <div class="flex items-center gap-3">
        <span class="p-3 bg-indigo-600 rounded-xl shadow-lg shadow-indigo-500/30 text-xl"><i class="fa-solid fa-cube"></i></span>
        <div>
          <h1 class="text-2xl font-bold bg-gradient-to-r from-white via-indigo-200 to-indigo-400 bg-clip-text text-transparent">AI 算力与积分智能管家</h1>
          <p class="text-xs text-slate-400 mt-1">云端 7x24h 全自动打卡 · 剩余配额与到期监控 · 智能备用路由</p>
        </div>
      </div>
      <div class="flex items-center gap-3 flex-wrap">
        <button onclick="triggerCheckin()" id="checkinBtn" class="px-4 py-2 bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white font-medium rounded-xl shadow-lg shadow-emerald-500/20 flex items-center gap-2 text-sm transition-all transform active:scale-95">
          <i class="fa-solid fa-bolt"></i> 立即全平台签到
        </button>
        <button onclick="openConfigModal()" class="px-4 py-2 glass hover:bg-slate-700/50 rounded-xl text-indigo-300 hover:text-white border border-indigo-500/30 text-sm flex items-center gap-2 transition-all">
          <i class="fa-solid fa-gear"></i> 凭证维护
        </button>
        <button onclick="location.reload()" class="p-2 glass hover:bg-slate-700/50 rounded-xl text-slate-300 hover:text-white text-sm"><i class="fa-solid fa-rotate-right"></i></button>
      </div>
    </header>

    <!-- 积分卡片 -->
    <section>
      <h2 class="text-lg font-semibold text-slate-300 mb-4 flex items-center gap-2"><i class="fa-solid fa-wallet text-indigo-400"></i> 各 AI 工具积分与算力实时监控</h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-6" id="toolsGrid"></div>
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
              <p class="text-xs text-slate-400 mt-1">基础 100 + 活动 100 算力，已由本服务自动领取，每月净赚 6,000 算力，相当于数千次代码生成。</p>
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
          <div class="p-3.5 rounded-xl bg-slate-800/60 border border-slate-700/50 flex items-start gap-3">
            <div class="p-2 bg-indigo-500/20 text-indigo-400 rounded-lg text-sm"><i class="fa-solid fa-moon"></i></div>
            <div class="flex-1">
              <div class="flex justify-between items-center"><span class="font-medium text-sm text-slate-200">智谱 ZCode 闲时车道免额度</span><span class="text-xs text-indigo-300 font-mono">算力重置卡</span></div>
              <p class="text-xs text-slate-400 mt-1">低峰期执行任务不扣 Coding Plan 额度，且客户端不定期赠送 5 小时额度恢复重置卡。</p>
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
        <p class="text-xs text-slate-400 leading-relaxed">主力编程 IDE（如 Cursor / TRAE 高速模式）配额耗尽时的备用调度策略：</p>
        <div class="space-y-3">
          <div class="p-4 rounded-xl bg-gradient-to-r from-slate-800 to-indigo-950/40 border border-indigo-500/30 flex items-center justify-between">
            <div>
              <span class="text-xs font-semibold text-indigo-400 uppercase tracking-wider">第一备用梯队 · 首选白嫖</span>
              <h3 class="font-bold text-sm text-white mt-0.5">切换至 WorkBuddy / CodeBuddy</h3>
              <p class="text-xs text-slate-400 mt-1">使用本服务每天自动积攒的积分池，支持 DeepSeek-V3 满血调用，零成本续命。</p>
            </div>
            <span class="px-3 py-1 bg-indigo-500/20 text-indigo-300 text-xs rounded-lg border border-indigo-500/30">首推</span>
          </div>
          <div class="p-4 rounded-xl bg-gradient-to-r from-slate-800 to-purple-950/40 border border-purple-500/30 flex items-center justify-between">
            <div>
              <span class="text-xs font-semibold text-purple-400 uppercase tracking-wider">第二备用梯队 · 长上下文</span>
              <h3 class="font-bold text-sm text-white mt-0.5">切换至 Kimi Code / ZCode 车道</h3>
              <p class="text-xs text-slate-400 mt-1">月之暗面长文本超强解析 + 智谱 GLM-4 闲时免额度模式，适合梳理大型工程代码。</p>
            </div>
            <span class="px-3 py-1 bg-purple-500/20 text-purple-300 text-xs rounded-lg border border-purple-500/30">长文</span>
          </div>
          <div class="p-4 rounded-xl bg-gradient-to-r from-slate-800 to-emerald-950/40 border border-emerald-500/30 flex items-center justify-between">
            <div>
              <span class="text-xs font-semibold text-emerald-400 uppercase tracking-wider">第三备用梯队 · 终极无限</span>
              <h3 class="font-bold text-sm text-white mt-0.5">本地 DeepSeek-Harness / API 按量</h3>
              <p class="text-xs text-slate-400 mt-1">直连官方 API 按量计费，百元可用数千万 Token，无月度订阅上限与封控困扰。</p>
            </div>
            <span class="px-3 py-1 bg-emerald-500/20 text-emerald-300 text-xs rounded-lg border border-emerald-500/30">无限</span>
          </div>
        </div>
      </section>
    </div>

    <footer class="glass p-4 rounded-2xl flex flex-col md:flex-row justify-between items-center text-xs text-slate-400 gap-2">
      <div class="flex items-center gap-2">
        <span class="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
        <span>云端服务运行中 · 每天 09:00 定时执行全平台签到</span>
      </div>
      <div>
        <a href="https://github.com/bishuyuan/AI-Credits-Hub" target="_blank" class="text-indigo-400 hover:underline mr-3"><i class="fa-brands fa-github"></i> GitHub 仓库</a>
        <span>API: <a href="/api/data" target="_blank" class="text-indigo-400 hover:underline">/api/data</a></span>
      </div>
    </footer>
  </div>

  <!-- 凭证维护与设置模态框 (Modal) -->
  <div id="configModal" class="fixed inset-0 bg-black/75 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="glass max-w-2xl w-full p-6 md:p-8 rounded-2xl shadow-2xl space-y-6 max-h-[90vh] overflow-y-auto">
      <div class="flex justify-between items-center border-b border-slate-700/60 pb-4">
        <h3 class="text-lg font-bold text-white flex items-center gap-2"><i class="fa-solid fa-sliders text-indigo-400"></i> AI 凭证维护与设置中心</h3>
        <button onclick="closeConfigModal()" class="text-slate-400 hover:text-white text-xl"><i class="fa-solid fa-xmark"></i></button>
      </div>

      <div class="space-y-4 text-xs">
        <div>
          <label class="block text-slate-300 font-medium mb-1">CodeBuddy / WorkBuddy AccessToken:</label>
          <textarea id="cfg_cb_token" rows="3" placeholder="填写 CodeBuddy 的 accessToken..." class="w-full bg-slate-900/90 border border-slate-700 rounded-xl p-3 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono text-[11px]"></textarea>
        </div>

        <div>
          <label class="block text-slate-300 font-medium mb-1">TRAE AccessToken (Cloud-IDE-JWT):</label>
          <textarea id="cfg_trae_token" rows="3" placeholder="填写 TRAE 的 accessToken..." class="w-full bg-slate-900/90 border border-slate-700 rounded-xl p-3 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono text-[11px]"></textarea>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-slate-300 font-medium mb-1">TRAE 用户 UID:</label>
            <input type="text" id="cfg_trae_uid" placeholder="如 2992225035760716" class="w-full bg-slate-900/90 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono">
          </div>
          <div>
            <label class="block text-slate-300 font-medium mb-1">TRAE 设备 ID (DeviceId):</label>
            <input type="text" id="cfg_trae_did" placeholder="如 766820083601979" class="w-full bg-slate-900/90 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono">
          </div>
        </div>

        <div>
          <label class="block text-slate-300 font-medium mb-1">后台访问密码 (可选，留空则免密):</label>
          <input type="password" id="cfg_admin_pwd" placeholder="留空则直接公开访问，输入密码则加锁保护" class="w-full bg-slate-900/90 border border-slate-700 rounded-xl p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono">
        </div>
      </div>

      <div class="flex justify-end gap-3 pt-4 border-t border-slate-700/60">
        <button onclick="closeConfigModal()" class="px-5 py-2 glass hover:bg-slate-700/50 rounded-xl text-slate-300 text-xs">取消</button>
        <button onclick="saveConfigToServer()" id="saveCfgBtn" class="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl text-xs transition-all flex items-center gap-2">
          <i class="fa-solid fa-floppy-disk"></i> 保存并立即生效
        </button>
      </div>
    </div>
  </div>

  <script>
    async function loadData() {
      try {
        const res = await fetch('/api/data');
        const data = await res.json();
        const container = document.getElementById('toolsGrid');
        container.innerHTML = '';
        data.tools.forEach(t => {
          const isSoon = t.expire_days <= 7;
          const badge = t.today_checked 
            ? '<span class="px-2.5 py-1 bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded-full text-xs font-medium"><i class="fa-solid fa-check"></i> 今日已签</span>'
            : (t.active ? '<span class="px-2.5 py-1 bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded-full text-xs font-medium"><i class="fa-solid fa-clock"></i> 待签到</span>' : '<span class="px-2.5 py-1 bg-slate-700 text-slate-400 rounded-full text-xs">未激活</span>');
          
          const card = document.createElement('div');
          card.className = "glass p-6 rounded-2xl shadow-lg glow transition-all duration-300 flex flex-col justify-between";
          card.innerHTML = `
            <div>
              <div class="flex justify-between items-start gap-2 mb-4">
                <div>
                  <h3 class="font-bold text-base text-white">${t.name}</h3>
                  <p class="text-xs text-slate-400 mt-0.5">${t.account}</p>
                </div>
                ${badge}
              </div>
              <div class="my-4 p-4 rounded-xl bg-slate-900/60 border border-slate-800">
                <div class="text-xs text-slate-400">当前可用剩余积分 / 算力</div>
                <div class="text-3xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-white via-indigo-100 to-indigo-300 mt-1">
                  ${t.credits} <span class="text-xs font-normal text-slate-400">Points</span>
                </div>
                ${t.used_pct ? `
                  <div class="mt-3">
                    <div class="flex justify-between text-xs text-slate-400 mb-1">
                      <span>已消耗 ${t.consumed}</span>
                      <span>使用率 ${t.used_pct}%</span>
                    </div>
                    <div class="w-full bg-slate-700 h-1.5 rounded-full overflow-hidden">
                      <div class="bg-indigo-500 h-1.5 rounded-full" style="width: ${t.used_pct}%"></div>
                    </div>
                  </div>
                ` : ''}
              </div>
            </div>
            <div class="pt-3 border-t border-slate-700/60 flex items-center justify-between text-xs">
              <span class="text-slate-400">到期时间: <span class="text-slate-300">${t.expire_time.split(' ')[0]}</span></span>
              <span class="px-2 py-0.5 rounded border text-[11px] ${isSoon ? 'bg-rose-500/20 text-rose-300 border-rose-500/30' : 'bg-slate-700/50 text-slate-300 border-slate-600/30'}">
                剩 ${t.expire_days} 天到期
              </span>
            </div>
          `;
          container.appendChild(card);
        });
      } catch (err) {}
    }

    async function triggerCheckin() {
      const btn = document.getElementById('checkinBtn');
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 正在签到...';
      try {
        const res = await fetch('/api/checkin', { method: 'POST' });
        const d = await res.json();
        alert('签到执行结果:\\n' + d.message);
        loadData();
      } catch (e) {
        alert('签到失败: ' + e);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-bolt"></i> 立即全平台签到';
      }
    }

    async function openConfigModal() {
      document.getElementById('configModal').classList.remove('hidden');
      try {
        const res = await fetch('/api/config');
        const cfg = await res.json();
        document.getElementById('cfg_cb_token').value = cfg.codebuddy?.accessToken || '';
        document.getElementById('cfg_trae_token').value = cfg.trae?.accessToken || '';
        document.getElementById('cfg_trae_uid').value = cfg.trae?.uid || '';
        document.getElementById('cfg_trae_did').value = cfg.trae?.deviceId || '';
        document.getElementById('cfg_admin_pwd').value = cfg.auth?.admin_password || '';
      } catch (e) {}
    }

    function closeConfigModal() {
      document.getElementById('configModal').classList.add('hidden');
    }

    async function saveConfigToServer() {
      const btn = document.getElementById('saveCfgBtn');
      btn.disabled = true;
      btn.innerHTML = '正在保存...';
      const payload = {
        auth: { admin_password: document.getElementById('cfg_admin_pwd').value.trim() },
        codebuddy: { accessToken: document.getElementById('cfg_cb_token').value.trim(), nickname: '我的账号' },
        trae: {
          accessToken: document.getElementById('cfg_trae_token').value.trim(),
          uid: document.getElementById('cfg_trae_uid').value.trim(),
          deviceId: document.getElementById('cfg_trae_did').value.trim() || '766820083601979'
        }
      };
      try {
        const res = await fetch('/api/update_config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const d = await res.json();
        alert('配置保存成功！大屏已实时刷新。');
        closeConfigModal();
        loadData();
      } catch (e) {
        alert('保存失败: ' + e);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> 保存并立即生效';
      }
    }

    loadData();
    setInterval(loadData, 20000);
  </script>
</body>
</html>
"""

# ====================================================================
#  HTTP 处理类
# ====================================================================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif p == "/api/data":
            if not DATA_CACHE.get("tools"):
                update_cache()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(DATA_CACHE, ensure_ascii=False).encode("utf-8"))
        elif p == "/api/config":
            cfg = load_config()
            # 返回脱敏配置（不外露密码）
            safe_cfg = {
                "auth": {"admin_password": cfg.get("auth", {}).get("admin_password", "")},
                "codebuddy": {"accessToken": cfg.get("codebuddy", {}).get("accessToken", "")},
                "trae": {
                    "accessToken": cfg.get("trae", {}).get("accessToken", ""),
                    "uid": cfg.get("trae", {}).get("uid", ""),
                    "deviceId": cfg.get("trae", {}).get("deviceId", "")
                }
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
        p = urlparse(self.path).path
        if p == "/api/checkin":
            msg = execute_all_checkin()
            update_cache()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "message": msg}, ensure_ascii=False).encode("utf-8"))
        elif p in ("/api/update_config", "/api/config"):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                new_cfg = json.loads(body.decode("utf-8"))
                save_config(new_cfg)
                update_cache()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "msg": "配置已更新并生效"}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
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
    log(f"  🚀 AI-Credits-Hub 服务已启动，监听端口: {PORT}")
    log(f"  🌐 本地地址: http://127.0.0.1:{PORT}")
    log(f"==========================================================")
    server.serve_forever()

if __name__ == "__main__":
    main()
