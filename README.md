# 🚀 AI-Credits-Hub · AI 算力与积分智能管家

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-blue?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
</p>

> **专为 AI 开发者与程序员打造的算力监控与自动领积分神器！**  
> 一站式实现腾讯 CodeBuddy/WorkBuddy、字节跳动 TRAE 等主流 AI 工具的 **每日全自动批量签到领积分**、**剩余算力与到期时间实时大屏监控**、**全网模型白嫖优惠雷达** 与 **主力编程 IDE 额度断粮后的智能备用调度**。

---

## ✨ 核心特性

- ⚡ **每日全自动批量签到**：7x24 小时云端静默打卡，每日自动领取 TRAE 200 算力补贴、CodeBuddy 100 积分与连签大奖，断签自动补跑。
- 📊 **高颜值科技深色 Dashboard**：实时监控各平台的可用剩余积分、总配额、已消耗比例进度环、精确到期的倒计时天数。
- ⚙️ **可视化凭证维护中心**：无需 SSH 登录服务器修改配置文件，直接在 Web 网页端点击「凭证维护」即可一键更新 Token 与管理密码。
- 🔍 **模型优惠与“白嫖”情报雷达**：汇总整理各大厂商限时免费通道（如 TRAE 每日算力池、智谱 ZCode 闲时车道免额度、Xiaomi MiMo 凌晨 0:00-8:00 全场 0.8 倍折扣）。
- 🛡️ **主力编程工具没额度的备用调度方案**：当主力 Cursor / TRAE Pro 高速额度用尽时，提供分梯队的低成本/零成本备用切换指南。
- 🔑 **本地一键抓取工具（零抓包）**：内置标准算法解密脚本，本地电脑双击即可一键读取本机已登录的各客户端凭据。
- 🔒 **隐私绝对安全**：纯本地及自建私有化部署，不经过任何第三方中转，所有 Token 与私钥仅保存在你自己的机器内。

---

## 🖥️ 快速开始

### 方式一：Linux 云服务器一键安装（推荐）

在你的 Linux 云服务器终端直接执行：

```bash
git clone https://github.com/bishuyuan/AI-Credits-Hub.git
cd AI-Credits-Hub
chmod +x deploy.sh
./deploy.sh
```

部署完成后，在浏览器访问：
👉 `http://你的服务器IP:9527`

点击右上角 **「凭证维护」** 输入你的 Token，即可立即开始监控与自动签到！

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
git clone https://github.com/bishuyuan/AI-Credits-Hub.git
cd AI-Credits-Hub

# 2. 安装依赖
pip install -r requirements.txt

# 3. （可选）自动从本地客户端抓取已登录的 Token
python local_extract.py

# 4. 启动服务
python app.py
```

访问 `http://127.0.0.1:9527` 即可看到本地控制台。

---

## 🔑 本地 Token 提取工具使用说明

本工具自带 `local_extract.py`，专门为懒人设计，**无需手动抓包**：
1. 确保个人电脑上已登录过 CodeBuddy / WorkBuddy 或 TRAE 客户端；
2. 在个人电脑运行：
   ```bash
   python local_extract.py
   ```
3. 脚本会自动读取本地客户端的加密存储，使用内置的 AES-128-CBC 算法完成解密，并自动生成标准的 `config.json`；
4. 你可以直接将生成的 Token 复制到 Web 仪表盘的「凭证维护」弹窗中保存！

---

## 📁 目录结构

```text
AI-Credits-Hub/
├── app.py                # 主服务：Web 仪表盘 + 凭证维护接口 + 自动化调度
├── config.example.json   # 脱敏示例配置文件
├── local_extract.py      # 本地 AI 客户端凭据一键提取与解密工具
├── deploy.sh             # Linux 云服务器一键部署与开机自启脚本
├── Dockerfile            # Docker 镜像构建文件
├── docker-compose.yml    # Docker Compose 容器编排文件
├── requirements.txt      # Python 核心依赖（仅 requests）
├── .gitignore            # 隐私文件过滤规则（确保 Token 不上传）
└── README.md             # 项目完整说明文档
```

---

## ⚙️ 配置文件说明 (`config.json`)

```json
{
  "auth": {
    "admin_password": ""           // 后台密码，留空则免密公开访问
  },
  "codebuddy": {
    "accessToken": "你的Token",
    "refreshToken": "你的刷新Token",
    "nickname": "腾讯用户",
    "uid": "用户UID"
  },
  "trae": {
    "accessToken": "你的Token",
    "refreshToken": "你的刷新Token",
    "uid": "用户UID",
    "deviceId": "766820083601979"
  }
}
```

> **安全提示**：`config.json` 包含你的个人身份凭据，已被 `.gitignore` 默认忽略，切勿上传至公开代码仓库！

---

## 🤝 贡献与反馈

欢迎提交 PR 或 Issue 一起完善更多 AI 平台的自动打卡与额度监控！

## 📄 开源许可

本项目遵循 [MIT License](LICENSE) 开源协议。
