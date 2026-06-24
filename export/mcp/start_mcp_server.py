#!/usr/bin/env python3
"""MCP Server 一键启动脚本（占位）

⚠️ 当前实现：此脚本是占位文件，等待 P0 实施时实现
⚠️ 完整方案：等 code_mcp_v2.py 接入主后端后，启动命令是
   `cd backend && python3 -m uvicorn main:app --host 0.0.0.0 --port 8000`
   MCP 端点挂载在 /mcp

---

# 未来实现示例（独立 MCP 服务器场景）

```python
# !/usr/bin/env python3
\"\"\"
MCP Server 独立启动脚本（未来实现）

使用场景：
  1. 部署在打包机上的 MCP Server 对外暴露
  2. 不需要启动整个 FastAPI 后端，只暴露 MCP 端点
  3. AI 工具通过 HTTP 连过来调 search/chat/trace
\"\"\"

import sys
import os
import argparse
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from code_mcp_v2 import mcp


def main():
    parser = argparse.ArgumentParser(description=\"CodeKB MCP Server\")
    parser.add_argument(\"--host\", default=\"0.0.0.0\", help=\"Bind host\")
    parser.add_argument(\"--port\", type=int, default=8000, help=\"Bind port\")
    args = parser.parse_args()

    # 挂载 MCP app 到 /mcp 路径
    app = Starlette(routes=[
        Mount(\"/mcp\", app=mcp.streamable_http_app()),
    ])

    print(f\"🚀 CodeKB MCP Server starting at http://{args.host}:{args.port}/mcp\")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == \"__main__\":
    main()
```

---

## 临时启动方式（当前 backend 集成模式）

```bash
# 1. 启动 email-wiki-demo 后端
cd backend
source venv/bin/activate
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000

# 2. MCP 端点
#   端点 URL: http://<your-host>:8000/mcp
#   传输协议: Streamable HTTP (mcp SDK v1.12.4+)
#   Tools: code_search / code_chat / code_list_repos / code_file_context / code_trace
```

## AI 工具接入示例

```bash
# Claude Code
claude mcp add code-kb http://<your-host>:8000/mcp

# Cursor / CodeMaker / OpenCode
# 在 .cursor/mcp.json 或对应配置文件中加：
# {
#   \"mcpServers\": {
#     \"code-kb\": {
#       \"url\": \"http://<your-host>:8000/mcp\",
#       \"transport\": \"streamable_http\"
#     }
#   }
# }
```
"""
