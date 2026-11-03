FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制程序代码
COPY app.py .
COPY config.example.json .

# 开放 Web 服务端口
EXPOSE 9527

# 启动服务
CMD ["python", "app.py"]
