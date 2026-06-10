# Email Wiki 回归测试文档

> 生成时间：2026-06-10 | 分支：code_knowledge_base

## 一、服务启动

| # | 测试点 | 方法 | 预期 |
|---|--------|------|------|
| 1.1 | `./start.sh` 启动 | 直接运行 | 无报错，端口 8000 监听 |
| 1.2 | `import code_routes` | `python3 -c "from code_routes import router"` | 无 SyntaxError/ImportError |
| 1.3 | `import embedder` | `python3 -c "from embedder import get_model_info"` | 正常导入，模型信息正确 |
| 1.4 | `import code_embedder` | `python3 -c "from code_embedder import get_code_model_info"` | 正常导入 |

## 二、API 巡检

| # | 端点 | 方法 | 预期 |
|---|------|------|------|
| 2.1 | `GET /api/stats` | curl | 200, 含 documents/emails/embedder/code_embedder |
| 2.2 | `GET /api/code/repos` | curl | 200, repos 数组 |
| 2.3 | `GET /api/code/stats` | curl | 200, 含 total_chunks/code_embedder |
| 2.4 | `GET /api/code/skip-rules` | curl | 200, 含 skip_dirs/skip_exts |
| 2.5 | `GET /api/code/agent-config` | curl | 200, 含 bot_name/system_prompt |
| 2.6 | `GET /api/performance/trend?type=search` | curl | 200, trend 数组 |
| 2.7 | `GET /api/performance/breakdown?type=search` | curl | 200, breakdown 数组 |
| 2.8 | `GET /api/user/home` | curl | 200, `{"home":"..."}` |
| 2.9 | `GET /api/emails/search?q=test` | curl | 200, emails 数组 |
| 2.10 | `GET /api/logs/tail?lines=10` | curl | 200, lines 数组 |

## 三、代码搜索

| # | 测试点 | 方法 | 预期 |
|---|--------|------|------|
| 3.1 | API 搜索 "登录" | `POST /api/code/search {"query":"登录","mode":"vector","top_k":5}` | 返回结果 + steps |
| 3.2 | steps.details 兼容 | 检查 3.1 的 steps | 每个 step 渲染不报错（dict 格式正常） |
| 3.3 | 无结果时不报错 | 搜索不存在的词 | 返回空结果 + 提示，不抛异常 |
| 3.4 | 前端搜索 "登录" | Chrome 实际输入搜索 | 结果渲染正常，步骤显示，无 console 错误 |
| 3.5 | 默认语义模式 | 打开代码搜索页 | 下拉默认选中 "语义" |
| 3.6 | 筛选下拉 | 查看 repo/lang 下拉 | 从 API 动态加载，非空 |

## 四、代码问答

| # | 测试点 | 方法 | 预期 |
|---|--------|------|------|
| 4.1 | API 问答 | `POST /api/code/chat {"question":"登录实现","top_k":3}` | 返回 answer + sources + steps |
| 4.2 | 前端对话 | Chrome 输入问题发送 | 气泡对话、加载态、答案显示、来源展示 |
| 4.3 | Enter 发送 | 输入后回车 | 触发发送 |
| 4.4 | 重复发送防护 | 快速连点发送 | isCodeChatting 拦截，不重复请求 |
| 4.5 | 来源面板状态 | 第一次有来源→第二次无来源 | 面板应重置（hidden），旧来源不残留 |
| 4.6 | 错误态 | 断网或输入空问题 | 红色错误气泡，不崩溃 |
| 4.7 | Agent 设置按钮 | 点击 ⚙️ | 模态框打开，加载当前配置 |
| 4.8 | Agent 配置保存 | 修改 prompt → 保存 | `PUT /api/code/agent-config` 200 |
| 4.9 | Agent 配置重置 | 点击恢复默认 | 恢复到 DEFAULT_AGENT_PROMPT |
| 4.10 | 仓库筛选 | 选择仓库后提问 | filters.repo_name 传入请求 |

## 五、Tab 路由切换

| # | 测试点 | 方法 | 预期 |
|---|--------|------|------|
| 5.1 | 首次进入默认路由 | 打开 `http://localhost:8000` | 跳转到 `#doc/upload` |
| 5.2 | 侧边栏点击切换 | 依次点击 10 个 tab | 每个正常加载，不卡住 |
| 5.3 | 代码问答/统计/LanceDB 切换 | 重点测试这三个 | 不重叠，不残留上一tab内容 |
| 5.4 | "加载中…" 清除 | 首次加载任一 tab | 占位文字消失 |
| 5.5 | 重复点击同一 tab | 点击已打开的 tab | 不重复加载（router 拦截） |
| 5.6 | 无效 hash 回退 | 访问 `#invalid` | 跳转到 `#doc/upload` |

## 六、代码仓库 + 排除规则

| # | 测试点 | 方法 | 预期 |
|---|--------|------|------|
| 6.1 | 仓库列表加载 | 打开代码仓库 tab | 已索引仓库列表显示 |
| 6.2 | 快捷路径加载 | 查看快捷路径按钮 | 从 `/api/user/home` 动态加载 |
| 6.3 | 排除规则按钮 | 点击 ⚙️ | 模态框打开 |
| 6.4 | 排除规则加载 | 模态框内 | 目录表 + 扩展名表 + gitignore 区 |
| 6.5 | .gitignore 目录 | 填写仓库路径后 | 显示 .gitignore 条目（不拆顶层目录） |
| 6.6 | 扫描预览 | 点刷新按钮 | 显示 "将扫描 X / Y 个文件" |
| 6.7 | 新增排除规则 | 添加目录名 → 保存 | 加入列表，持久化 |
| 6.8 | 删除排除规则 | 点击删除 | 从列表移除 |
| 6.9 | 恢复默认 | 点击恢复默认 | 重置为 build_default_skip_rules() |
| 6.10 | 刷新仓库(增量) | 点击刷新按钮 | scan 不先删数据，增量更新 |

## 七、文档看板 + 数据真实性

| # | 测试点 | 方法 | 预期 |
|---|--------|------|------|
| 7.1 | 统计卡片 | 打开文档统计 tab | 文档数/邮件数/线程数/向量块数正确 |
| 7.2 | 性能指标 | 查看性能卡片 | LanceDB磁盘/搜索耗时/插入耗时 |
| 7.3 | 耗时趋势图 | 查看折线图 | Chart.js 渲染，数据来自 metrics.db |
| 7.4 | Step 拆解图 | 查看水平条形图 | Chart.js 渲染 |
| 7.5 | Embedding 模型路径 | 查看路径显示 | 项目 `models/` 目录，非 `~/.cache/` |
| 7.6 | code_embedder 显示 | 查看代码模型信息 | `model_name` + `dimension` 正确 |

## 八、邮件 Tab

| # | 测试点 | 方法 | 预期 |
|---|--------|------|------|
| 8.1 | 邮件统计 | 打开邮件 tab | 显示邮件数/线程数/发件人数 |
| 8.2 | 邮件预览 | 查看预览列表 | 显示最近 5 封邮件 |
| 8.3 | 邮件导入 | 选择数量 → 导入 | 进度显示，步骤展示 |
| 8.4 | 关键词搜索 | 输入关键词 → 搜索 | `/api/emails/search` 返回结果 |
| 8.5 | `--color-secondary` 渲染 | 查看卡片背景 | 使用 `var(--color-secondary)` 不 fallback |

## 九、前端基础

| # | 测试点 | 方法 | 预期 |
|---|--------|------|------|
| 9.1 | 暗色主题 | 查看整体 | 深色背景 + 绿色强调色，无白色残留 |
| 9.2 | `--color-secondary` | 检查元素 | 值为 `#1A2332` |
| 9.3 | `--color-muted` | 检查元素 | 值为 `#94A3B8`（非旧值 `#64748B`） |
| 9.4 | 侧边栏高亮 | 点击不同 tab | 当前 tab 绿色高亮 + 左侧绿色条 |
| 9.5 | shared.js 加载 | 查看 Network | `?v=5`，无 304 缓存 |
| 9.6 | router.js 加载 | 查看 Network | `?v=7`，无 304 缓存 |
| 9.7 | tab 文件加载 | 查看 Network | `?v=3`，无 304 缓存 |
| 9.8 | `escapeHtml` 定义 | Console 验证 | 只存在于 shared.js，router.js 无重复定义 |
| 9.9 | 日志抽屉默认折叠 | 首次访问 | 日志面板不展开 |
| 9.10 | Console 无错误 | 浏览所有 tab | 无 JS 异常、404、CORS 错误 |

## 十、后端关键修复回归

| # | 测试点 | 方法 | 预期 |
|---|--------|------|------|
| 10.1 | refresh 增量 | `POST /api/code/repos/{name}/refresh` | 不先 delete_by_repo，直接 scan |
| 10.2 | LanceDB 维度不匹配 | 模拟（如已修复则跳过） | 抛 RuntimeError，不静默删表 |
| 10.3 | embedder 截断日志 | 传入 >1500 字符文本 | log.warning 记录 |
| 10.4 | 超大文件统计 | 扫描含 >100KB 文件的仓库 | stats.skipped_files 含 oversized 记录 |
| 10.5 | 搜索阈值默认 0 | 搜索低分内容 | 不过滤，返回所有结果 |
