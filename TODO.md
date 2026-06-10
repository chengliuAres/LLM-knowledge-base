# 待解决问题

## 性能

### code/dashboard 页面刷新卡顿（疑似 Tailwind 运行时阻塞）
- **现象**：在 `http://localhost:8000/#code/dashboard` 页面刷新时，可能卡 20+ 秒才加载完成
- **实测**：后端 API 每个只要 3-5ms，10 个调用共 22ms，后端不是瓶颈
- **可疑根因**：`vendor/js/tailwindcss.js`（407KB 运行时）每次 tab 切换调用 `tailwind.refresh()` 同步扫描 DOM 生成 CSS，可能在浏览器内存压力/扩展干扰下阻塞主线程
- **优化方案**：用 Tailwind CLI 预编译静态 CSS 替换运行时版本，消除不确定性
- **优先级**：中（不频繁刷新时体验正常）
