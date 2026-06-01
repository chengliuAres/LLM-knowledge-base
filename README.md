# 文档知识库

基于 LanceDB 的智能文档知识库系统 —— 从零搭建个人知识库的完整参考实现。

<p align="center">
  <img src="diagram/intro.svg" alt="项目介绍" width="700"/>
</p>

> **项目定位**：一套代码完整、可直接运行的文档知识库系统。旨在帮助你理解如何将 **文档管理 → 向量化 → 语义检索 → RAG 问答** 这条链路串起来。代码结构清晰、模块解耦，适合在此基础上进行二次开发，构建属于自己的个人知识库。

## 功能特性

- 📄 **文档管理**: 拖拽上传 PDF/TXT/MD/DOCX/EML，自动解析、分块、向量化
- 📧 **邮件导入**: 从本地邮件数据库导入邮件，支持批量处理和搜索
- 🔍 **语义搜索**: 基于向量相似度的智能搜索，展示完整执行流程
- 💬 **智能问答**: RAG 架构，基于知识库内容回答问题，附带来源引用
- 📊 **系统看板**: 文档/邮件统计、向量存储状态、性能数据可视化
- 🗄️ **LanceDB 内部探查**: 表结构、版本历史、向量展示，直观理解向量数据库

## 适用场景

- 📖 **学习参考**: 了解 RAG 完整链路 —— Embedding → 向量检索 → LLM 推理
- 🔧 **二次开发**: 基于现成架构快速定制自己的知识库系统
- 🧪 **技术验证**: 测试不同 Embedding 模型、LLM、分块策略的效果
- 📚 **个人知识管理**: 搭建私有文档库，支持语义搜索和智能问答

## 技术栈

| 层 | 技术 |
|----|------|
| Web 框架 | FastAPI + uvicorn |
| 向量数据库 | LanceDB（嵌入式，无需独立部署） |
| Embedding | sentence-transformers（本地，384维） |
| 邮件存储 | SQLite（`data/emails.db`） |
| LLM | OpenAI 兼容接口（默认小米 MiMo，支持 Ollama/OpenAI） |
| 前端 | 单 HTML 文件 + Tailwind CSS（CDN） + Chart.js |

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

### 4. 使用指南

#### 文档上传
1. 切换到"📄 文档管理"标签
2. 拖拽或点击上传文档（支持 PDF / TXT / MD / DOCX / EML）
3. 系统自动解析、分块、向量化并存入 LanceDB

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
3. AI 会基于知识库回答并显示来源

## 技术架构

<p align="center">
  <img src="diagram/architecture.svg" alt="系统架构图" width="900"/>
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

完整 API 文档请参考 [backend/main.py](backend/main.py)。

## 项目结构

```
email-wiki-demo/
├── backend/
│   ├── main.py              # FastAPI 主入口（路由 + 请求处理）
│   ├── parser.py            # 文档解析器（PDF/TXT/MD/DOCX/EML）
│   ├── embedder.py          # Embedding 封装（sentence-transformers）
│   ├── db.py                # LanceDB 向量数据库操作
│   ├── email_db.py          # SQLite 邮件数据库操作
│   ├── email_parser.py      # 邮件解析转换
│   ├── llm_client.py        # LLM 客户端（OpenAI/Ollama/小米）
│   ├── match_reasons.py     # 搜索匹配原因分析
│   ├── metrics_db.py        # 性能指标数据库
│   ├── lancedb_inspect.py   # LanceDB 内部状态探查
│   ├── step_tracker.py      # 全流程执行步骤追踪
│   └── requirements.txt
├── frontend/
│   └── index.html           # 单页前端（全部交互）
├── start.sh                 # 一键启动脚本
├── diagram/
│   ├── intro.svg            # 项目介绍图
│   └── architecture.svg     # 系统架构图
├── benchmark/               # 性能测试工具
├── data/                    # 数据库目录（自动生成，gitignore）
├── models/                  # 模型缓存目录（自动下载，gitignore）
├── uploads/                 # 上传文件目录
└── README.md
```

## 二次开发指引

本项目各模块职责清晰、解耦良好，方便针对性修改：

| 需求 | 改哪里 |
|------|--------|
| 替换 Embedding 模型 | [`backend/embedder.py`](backend/embedder.py) — `MODEL_NAME` 常量改为其他 sentence-transformers 模型 |
| 更换 LLM | [`backend/llm_client.py`](backend/llm_client.py) — 按接口规范接入新模型 |
| 增加文档格式支持 | [`backend/parser.py`](backend/parser.py) — 添加 `read_xxx()` 函数并注册到 `read_file()` |
| 自定义分块策略 | [`backend/parser.py`](backend/parser.py) — 修改 `chunk_text()` 函数 |
| 修改前端界面 | [`frontend/index.html`](frontend/index.html) — 单个 HTML，改起来很方便 |
| 接入其他向量数据库 | [`backend/db.py`](backend/db.py) — 替换 LanceDB 调用为 Milvus/Chroma/Qdrant 等 |
| 添加新的分析功能 | [`backend/metrics_db.py`](backend/metrics_db.py) + [`backend/lancedb_inspect.py`](backend/lancedb_inspect.py) |

## 核心流程

```
上传文档 → Parser 解析 → Chunk 分块 → Embedder 向量化 → LanceDB 存储
用户搜索 → Embedder 编码查询 → LanceDB 向量检索 → 匹配结果排序 → 前端展现
智能问答 → 向量检索 Top-K → 构建 Prompt → LLM 推理 → 返回答案 + 来源
```
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
