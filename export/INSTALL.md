# 详细安装步骤

> 面向**部署者**：从零搭建 email-wiki-demo 代码知识库 + MCP Server。

## 0. 前置要求

| 工具 | 版本 | 验证命令 |
|------|------|---------|
| Python | 3.9+ | `python3 --version` |
| Git | 2.20+ | `git --version` |
| 磁盘空间 | 10GB+（含模型缓存） | `df -h` |
| 内存 | 8GB+（含 BGE 模型） | `free -h` |
| 网络 | 可访问模型下载源 | `curl -I https://huggingface.co` |

## 1. 克隆项目

```bash
git clone <email-wiki-demo-repo-url>
cd email-wiki-demo
```

## 2. 创建 Python 虚拟环境

```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# Windows: venv\Scripts\activate

# 升级 pip
pip install --upgrade pip
```

## 3. 安装依赖

### 完整依赖（推荐）

```bash
pip install -r backend/requirements.txt
```

### 最小依赖（仅 MCP Server，**不推荐**）

```bash
pip install -r export/mcp/requirements.txt
```

> **注意**：最小依赖**无法运行完整后端**（缺 LanceDB / sentence-transformers / tree-sitter）。
> 如果是开发/演示场景，请用完整依赖。

## 4. 配置环境变量（可选，问答功能需要）

```bash
cp backend/.env.example backend/.env

# 编辑 .env，配置 LLM（openai / ollama / xiaomi）
# LLM_PROVIDER=openai
# LLM_API_KEY=your-api-key
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_MODEL=gpt-3.5-turbo
```

> **注意**：`llm_client.py` 优先读取环境变量，`LLM_PROVIDER` 未设置时默认走小米 MiMo。

## 5. 启动 MCP Server

### 方式 A：随 FastAPI 后端启动（推荐）

```bash
cd backend
source venv/bin/activate
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000

# MCP 端点会自动挂载在 /mcp
# 看到 "Uvicorn running on http://0.0.0.0:8000" 表示启动成功
```

#### 验证 MCP 端点

```bash
# 测试连通性
curl -I http://localhost:8000/mcp
# 应返回 200 OK

# 测试 MCP 握手
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "test", "version": "1.0"}
    }
  }'

# 应返回 JSON-RPC 响应 + Mcp-Session-Id header
```

### 方式 B：独立启动（**未来实现**）

```bash
cd export/mcp
python3 start_mcp_server.py --host 0.0.0.0 --port 8000
```

> **当前状态**：`start_mcp_server.py` 是占位文件，等待 P0 实施。

## 6. 索引代码仓库

启动后端后，通过 Web UI 索引你的代码仓库：

1. 打开浏览器：http://localhost:8000
2. 进入"代码知识库" tab
3. 点击"扫描目录"，选择要索引的代码路径
4. 等待扫描完成（首次需要下载 BGE 模型，约 200MB）

#### API 方式索引

```bash
curl -X POST http://localhost:8000/api/code/scan \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/path/to/your/repo",
    "name": "my-repo"
  }'
```

## 7. 接入 AI 工具

详见 [README.md](README.md) 步骤 2。

### 快速测试

向 AI 工具提问：

```
你好，请搜索我的代码库
```

AI 应能调用 `code_list_repos` 列出已索引的仓库，然后调用 `code_search` 搜索代码。

## 8. 生产部署建议

### 后台运行

```bash
# 使用 nohup
cd backend
nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 > /var/log/code-kb.log 2>&1 &

# 或使用 systemd（推荐）
sudo tee /etc/systemd/system/code-kb.service <<EOF
[Unit]
Description=email-wiki-demo Code KB
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/email-wiki-demo/backend
Environment="PATH=/path/to/email-wiki-demo/backend/venv/bin"
ExecStart=/path/to/email-wiki-demo/backend/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now code-kb
sudo systemctl status code-kb
```

### 反向代理（Nginx）

```nginx
server {
    listen 80;
    server_name code-kb.your-domain.com;

    location /mcp {
        proxy_pass http://localhost:8000/mcp;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
        # SSE 需要
        proxy_cache off;
        proxy_read_timeout 86400;
    }

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### HTTPS（推荐）

```bash
# 使用 certbot
sudo certbot --nginx -d code-kb.your-domain.com
```

## 9. 监控与维护

### 日志

- 应用日志：`backend/data/logs/app.log`（TimedRotatingFileHandler 自动切割）
- 通过 Web UI"日志" tab 查看
- API：`GET /api/logs/tail?lines=100`

### 性能指标

- 数据库：`backend/data/metrics.db`
- API：`GET /api/performance/trend`

### 索引刷新

- 增量刷新：mtime 监控（git_watchdog.py），自动
- 全量刷新：`POST /api/code/repos/{name}/refresh`

## 10. 故障排查

### 启动失败

| 错误 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError: No module named 'mcp'` | 依赖未装全 | `pip install -r backend/requirements.txt` |
| `Address already in use` | 8000 端口被占 | 换端口：`--port 8001` |
| `Permission denied` 写 logs | 无写权限 | `chmod -R 777 backend/data/logs` |
| 模型下载失败 | 网络问题 | 配置代理或手动下载到 `models/` |

### MCP 连接失败

| 错误 | 原因 | 解决 |
|------|------|------|
| `Connection refused` | 后端未启动 | 启动 FastAPI 后端 |
| `Mcp-Session-Id missing` | 协议不匹配 | 检查 AI 工具 MCP 版本（需 1.12.4+） |
| `SSE 解析失败` | 响应格式问题 | 用 `kb_api.py` 兜底模式 |
| `404 Not Found` | 路径不对 | 确认端点 URL 是 `/mcp` 不是 `/mcp/sse` |

### 索引问题

| 错误 | 原因 | 解决 |
|------|------|------|
| 扫描超时 | 仓库太大 | 配置 `code_skip_rules.json` 排除无关目录 |
| 索引不全 | 跳过了某些文件 | 检查 `code_skip_rules.json` |
| 搜索结果为空 | 翻译词典不覆盖 | 在 `query_translator.py` 加新词条 |

## 11. 升级

```bash
cd email-wiki-demo
git pull

# 升级依赖
cd backend
source venv/bin/activate
pip install -r requirements.txt --upgrade

# 重启服务
sudo systemctl restart code-kb
```

## 12. 卸载

```bash
# 停止服务
sudo systemctl stop code-kb
sudo systemctl disable code-kb

# 删除 systemd 文件
sudo rm /etc/systemd/system/code-kb.service

# 删除项目
rm -rf /path/to/email-wiki-demo

# 清理模型缓存（可选）
rm -rf ~/.cache/huggingface/hub/models--BAAI--*
```

## 13. 联系方式

- 项目地址：`../`
- 升级计划：`../docs/code-kb-upgrade-plan.md`
- 问题反馈：在项目仓库提 Issue

---

> **下一步**：完成安装后，回到 [README.md](README.md) 步骤 2 接入你的 AI 工具。
