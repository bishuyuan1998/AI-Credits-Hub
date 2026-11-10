# 🚀 AI-Credits-Hub · AI 算力与积分智能管家 (多账号版)

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-blue?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
</p>

> **专为 AI 开发者打造的多账号算力监控与自动领积分神器！**  
> 一站式实现腾讯 CodeBuddy/WorkBuddy、字节跳动 TRAE CN/SOLO、阿里 Qoder (通义灵码) 等主流 AI 工具的 **多账号小号矩阵每日全自动批量打卡**、**剩余算力与到期时间实时大屏监控**、**全网模型白嫖优惠雷达** 与 **主力编程 IDE 额度断粮后的智能备用调度**。

---

## ✨ 核心特性

- 👥 **三平台多账号小号矩阵集中托管**：支持同时绑定任意多个 **腾讯 CodeBuddy / WorkBuddy**、**字节跳动 TRAE CN / SOLO** 与 **阿里 Qoder (通义灵码)** 账号，主号小号一览无余，独立展示各账号积分、到期倒计时与使用进度。
- ⚡ **每日全自动智能批量打卡与防漏补签**：7x24 小时云端静默守护，每日 10:05 智能遍历所有启用账号：
  - **时间科学契合**：默认优化为每日 **10:05** 执行（避开早 9 点/10 点整点网络高峰，并无缝衔接阿里 Qoder 每日 10:00:00 准时上架的新活动额度）；
  - **三级指数退避重试**：遇到服务端 HTTP 500、502、504 或偶发网络抖动时自动休眠重试 3 次，大幅提升打卡稳定性；
  - **防漏补签与静默守护**：服务开机/重启时自动检查当日打卡状况并补执行，白天（10:00~22:00）每隔 30 分钟后台巡检，自动无感挽救漏签账号；
  - **动态 Campaign 实时抓取**：自动追踪阿里 Qoder 官方最新有效活动 ID，精准识别同一实名认证已领状态；
  - **多平台福利全收割**：字节跳动 TRAE（200 算力/日）、腾讯 CodeBuddy（100 积分/日与连签盲盒）、阿里 Qoder（100 Credits/日）。
- 🖥️ **管理后台直接录入与维护**：无需 SSH 登录服务器黑框，直接在 Web 网页后台一键添加账号、更新凭据、快速修改自定义备注、测试单账号签到或删除账号。
- ⭐ **网页版 1 秒书签同步（免代码/免F12）**：将网页后台提供的书签按钮拖到浏览器书签栏，在各大官网登录账号后，点击一下书签即可 1 秒将账号同步推送到云端入库并开启自动签到！
- 📊 **科技深色 Dashboard**：实时监控各账号的可用剩余积分、总配额、已消耗比例进度条、精确到期的倒计时天数与状态徽章。
- 🔒 **密钥后缀安全防线**：支持通过 `?key=YourSecretKey` 或 Cookie 进行安全身份验证，未知访问展示物理连接阻断或锁定屏，保护个人多账号隐私与 Token 安全。
- 🔍 **模型优惠与“白嫖”情报雷达**：汇总整理各大厂商限时免费通道（如 TRAE 每日算力池、智谱 ZCode 闲时车道免额度、Xiaomi MiMo 闲时折扣）。
- 🛡️ **主力编程工具没额度的备用调度方案**：当主力 Cursor / TRAE Pro 高速额度用尽时，提供分梯队的低成本/零成本备用切换指南。
- 🔑 **本地一键抓取工具（零抓包自解密）**：内置标准算法解密脚本（支持 Windows DPAPI、AES-256-GCM、AES-128-CBC 与 WorkBuddy 内部存储协议），本地电脑运行即可一键提取本机已登录的各客户端凭据，并支持一键推送到云端服务。

---

## 🖥️ 快速开始

### 方式一：Linux 云服务器一键安装（推荐）

在你的 Linux 云服务器终端直接执行：

```bash
git clone https://github.com/bishuyuan1998/AI-Credits-Hub.git
cd AI-Credits-Hub
chmod +x deploy.sh
./deploy.sh
```

部署完成后，在浏览器访问：
👉 `http://你的服务器IP:9527/?key=YourSecretKey2026`

点击右上角 **「添加账号」** 即可录入多个主号与小号，大屏将实时自动刷新并进入 7x24h 每日自动签到！

---

### 方式二：Docker 一键启动

```bash
# 启动容器
docker-compose up -d

# 查看日志
docker logs -f ai-credits-hub
```

---

### 方式三：本地运行

```bash
# 1. 克隆代码
git clone https://github.com/bishuyuan1998/AI-Credits-Hub.git
cd AI-Credits-Hub

# 2. 安装依赖
pip install -r requirements.txt

# 3. （可选）自动从本地客户端抓取已登录的 Token
python local_extract.py

# 4. 启动服务
python app.py
```

访问 `http://127.0.0.1:9527/?key=YourSecretKey2026` 即可进入本地控制台。

---

## 🔑 本地 Token 提取工具使用说明

本工具自带 `local_extract.py`，专门为懒人设计，**无需手动抓包**：
1. 确保个人电脑上已登录过 CodeBuddy / WorkBuddy、TRAE 或 Qoder 客户端；
2. 在个人电脑运行：
   ```bash
   python local_extract.py
   ```
3. 脚本会自动读取本地各客户端的安全加密存储（DPAPI + AES-256-GCM / AES-128-CBC），自解密还原凭证，并自动生成标准的多账号 `config.json`；
4. 运行最后可选择直接输入云服务器地址（如 `http://47.77.190.116:9527`），一键将本地账号推送到云端服务器托管！
5. 支持 `--daemon` 守护模式，后台静默监控账号更新并自动上报。

---

## 📁 目录结构

```text
AI-Credits-Hub/
├── app.py                # 主服务：三平台多账号 Web 仪表盘 + 凭证维护接口 + 自动化调度器
├── config.example.json   # 脱敏示例多账号配置文件
├── local_extract.py      # 本地 AI 客户端凭据一键提取与云端推送工具 (含自解密)
├── deploy.sh             # Linux 云服务器一键部署与开机自启脚本
├── Dockerfile            # Docker 容器镜像构建文件
├── docker-compose.yml    # Docker 容器编排文件
├── requirements.txt      # Python 依赖清单 (仅需 requests)
└── README.md             # 项目完整说明文档
```

---

## 🛡️ 开源协议与声明

本项目采用 [MIT License](LICENSE) 协议开源。仅供个人技术研究与日常开发提效使用，请勿用于非法用途。
