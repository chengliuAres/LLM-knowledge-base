# 文档知识库 Demo v2.0

基于 LanceDB 的文档语义搜索系统，支持文档上传、邮件导入、智能问答。

<p align="center">
  <img src="diagram/intro@2x.png" alt="项目介绍" width="700"/>
</p>

## 功能特性

- 📄 **文档管理**: 拖拽上传 PDF/TXT/MD/DOCX，自动解析分块
- 📧 **邮件导入**: 从本地邮件DB导入数据，支持批量导入
- 🔍 **语义搜索**: 基于向量相似度的智能搜索，展示执行流程
- 💬 **智能问答**: RAG架构，基于知识库的问答

## 技术栈

| 层 | 技术 |
|----|------|
| Web 框架 | FastAPI + uvicorn |
| 向量数据库 | LanceDB（嵌入式，无需独立部署） |
| Embedding | sentence-transformers `all-MiniLM-L6-v2`（本地，384维） |
| 邮件存储 | SQLite（`data/emails.db`） |
| LLM | OpenAI 兼容接口（默认小米 MiMo，支持 Ollama/OpenAI） |
| 前端 | 单 HTML 文件 + Tailwind CSS（CDN） |

## 快速开始

### 1. 配置环境变量（可选，用于智能问答）

```bash
# 在 backend/ 目录下创建 .env 文件
LLM_PROVIDER=openai          # openai / ollama / xiaomi（默认）
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-3.5-turbo

# 本地 Ollama 示例
# LLM_PROVIDER=ollama
# LLM_MODEL=qwen2:7b
```

> **默认行为**：未配置时使用内置小米 MiMo（`llm_client.py` 中硬编码）。若无需问答功能，可跳过此步。

### 2. 启动服务

```bash
./start.sh
```

启动后访问: http://localhost:8000

> **首次启动**：脚本会自动创建 venv 并安装依赖，Embedding 模型（~90MB）也会在此时自动下载，需等待约 1-2 分钟。

### 3. 关闭服务

```bash
# 方式一：在前台运行时按 Ctrl+C 即可停止

# 方式二：若在后台运行，通过端口号 kill
lsof -ti:8000 | xargs kill

# 方式三：通过进程名 kill
kill $(pgrep -f "uvicorn main:app")
```

### 4. 使用演示

#### 文档上传
1. 切换到"📄 文档管理"标签
2. 拖拽或点击上传文档
3. 等待解析完成

#### 邮件导入
1. 切换到"📧 邮件导入"标签
2. 选择导入数量
3. 点击"开始导入"
4. 查看导入进度和步骤详情

#### 智能搜索
1. 在搜索框输入问题
2. 点击"搜索"
3. 查看执行流程和搜索结果
4. 支持按文件类型过滤

#### 智能问答
1. 切换到"💬 智能问答"标签
2. 输入问题
3. AI会基于知识库回答并显示来源

## 技术架构

<p align="center">
  <img src="diagram/architecture@2x.png" alt="系统架构图" width="900"/>
</p>

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/upload | 上传文档 |
| POST | /api/search | 向量搜索（带步骤追踪） |
| POST | /api/chat | 智能问答（RAG） |
| POST | /api/emails/import | 导入邮件 |
| GET | /api/documents | 文档列表 |
| GET | /api/emails | 邮件列表 |
| GET | /api/emails/search | 搜索邮件 |
| DELETE | /api/documents/{filename} | 删除文档 |
| GET | /api/stats | 统计信息 |

## 项目结构

```
email-wiki-demo/
├── backend/
│   ├── main.py              # FastAPI 主入口
│   ├── parser.py            # 文档解析器
│   ├── embedder.py          # Embedding 封装
│   ├── db.py                # LanceDB 操作
│   ├── email_db.py          # 邮件数据库
│   ├── email_parser.py      # 邮件解析器
│   ├── llm_client.py        # LLM 客户端
│   ├── step_tracker.py      # 步骤追踪器
│   └── requirements.txt
├── frontend/
│   └── index.html           # 前端页面
├── data/                    # 数据目录
├── uploads/                 # 上传文件
├── start.sh                 # 启动脚本
└── README.md
```

## 环境变量说明

| 变量 | 说明 | 默认值 |
|------|------|--------|
| LLM_PROVIDER | LLM提供商 | openai |
| LLM_API_KEY | API密钥 | - |
| LLM_BASE_URL | API地址 | https://api.openai.com/v1 |
| LLM_MODEL | 模型名称 | gpt-3.5-turbo |

## 常见问题

**Q: 如何使用本地LLM？**
A: 安装 Ollama，设置 `LLM_PROVIDER=ollama` 和 `LLM_MODEL=qwen2:7b`

**Q: 邮件数据从哪来？**
A: 系统会在首次启动时自动生成 50 封示例邮件（SQLite 为空时触发），覆盖 8 个模拟发件人和 INBOX/Sent/Drafts 文件夹。

**Q: 搜索结果不准确？**
A: 尝试调整返回数量、切换文件类型过滤，或更换Embedding模型。注意"搜索邮件"和"向量搜索"是两套机制：前者是 SQL `LIKE` 关键词匹配，后者是语义向量搜索。

**Q: 首次启动卡住？**
A: 正在下载 sentence-transformers 模型（~90MB），属正常现象，等待即可。后续启动不再重复下载。
