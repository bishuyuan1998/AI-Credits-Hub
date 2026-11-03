#!/bin/bash
set -e

echo "=============================================================="
echo "    🚀 AI-Credits-Hub · Linux 云服务器一键安装部署"
echo "=============================================================="

# 1. 检查并安装环境
echo "[1/4] 安装 Python3、pip 与 cron 环境..."
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq python3 python3-pip python3-requests cron >/dev/null 2>&1 || true
elif command -v yum >/dev/null 2>&1; then
    yum install -y -q python3 python3-pip cronie >/dev/null 2>&1 || true
fi

if ! python3 -c "import requests" >/dev/null 2>&1; then
    pip3 install requests -q 2>/dev/null || pip install requests -q 2>/dev/null || true
fi

# 2. 检查配置文件
INSTALL_DIR=$(pwd)
if [ ! -f "$INSTALL_DIR/config.json" ]; then
    if [ -f "$INSTALL_DIR/config.example.json" ]; then
        cp "$INSTALL_DIR/config.example.json" "$INSTALL_DIR/config.json"
        echo "[提示] 已自动创建 config.json，可在网页打开后在「凭证维护」中填写 Token！"
    fi
fi

# 3. 注册 systemd 系统自启守护服务
echo "[2/4] 注册 systemd 开机自启服务..."
cat << EOF > /etc/systemd/system/ai-hub.service
[Unit]
Description=AI Credits and Fallback Hub Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ai-hub >/dev/null 2>&1
systemctl restart ai-hub

# 4. 放行系统内部防火墙端口
echo "[3/4] 检查系统内部防火墙端口 9527..."
ufw allow 9527/tcp >/dev/null 2>&1 || true
iptables -I INPUT -p tcp --dport 9527 -j ACCEPT >/dev/null 2>&1 || true

echo "[4/4] 验证服务运行状态..."
sleep 2
systemctl status ai-hub --no-pager

echo ""
echo "=============================================================="
echo "  🎉 恭喜！AI 算力与积分智能管家部署成功！"
echo "=============================================================="
echo "• 仪表盘访问: http://你的服务器IP:9527"
echo "• 凭证维护: 浏览器打开网页后点击右上角「凭证维护」即可修改"
echo "• 服务管理命令: systemctl restart ai-hub | systemctl status ai-hub"
echo "=============================================================="
