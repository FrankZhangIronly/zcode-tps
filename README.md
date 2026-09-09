# zcode-tps-overlay

ZCode 模型请求速度监控悬浮窗插件：置顶半透明小窗实时显示各 (baseURL, 模型) 的出词速度与
首 token 延迟（TTFT），并提供 MCP 工具让模型可以启停监控、切换语言、查询会话统计。

## 功能

- **速度均值区**：每个 (baseURL, 模型) 的均值/最近速度（近 10 次，tok/s = 输出 token ÷
  流式生成时长，已扣除 TTFT）与 TTFT 均值
- **最近请求列表**：最近 10 次请求表格（进行中 `●` 实时计时 / 完成 `✓` 补速度 / 失败 `✗`）
- **边缘吸附**：拖到屏幕上/下/左/右边缘自动滑入隐藏（留 4px 小边），鼠标碰边滑出、移开缩回
- **双语言 UI**：`en` / `zh` 热切换
- **数据源**：`~/.zcode/cli/db/db.sqlite` 的 `model_usage` 表（真实 token/TTFT，只读 WAL）
  + `~/.zcode/cli/log/` 请求开始日志；不修改任何 zcode 配置
- 依赖：仅 Python 标准库（需 tkinter），零第三方包

## 安装（ZCode 插件市场）

本仓库本身就是一个 ZCode 插件市场（根目录 `marketplace.json`）。

**配置市场**（二选一）：
1. 自动：运行 `python install.py`（把本仓库注册进 `known_marketplaces.json`）
2. 手动：zcode → 设置 → 插件管理 → 发现 → "+" → 填 GitHub 仓库 `FrankZhangIronly/zcode-tps`

**安装插件**：
1. 设置 → 插件管理 → 发现 → 刷新市场列表
2. 找到市场 `zcode-tps` 下的 **zcode-tps-overlay** → 点击安装
3. **重启 zcode 会话**：SessionStart hook 自动拉起悬浮窗，MCP 工具自动连接

> 升级：更新代码后 `git push`，插件管理里刷新并更新（版本号见 `marketplace.json`）。

## MCP 工具（模型可直接调用）

| 工具 | 功能 |
|---|---|
| `tps_start` | 启动悬浮窗（分离进程，pid 记录于 `~/.zcode/tps.pid`） |
| `tps_stop` | 停止悬浮窗 |
| `tps_status` | 运行状态 + 实时快照（各模型 avg/last 速度与 TTFT、进行中请求数） |
| `tps_language` | 读取/切换界面语言（`en`/`zh`，热切换不重启） |
| `tps_session_stats` | 当前会话最近 N 条请求的速度/TTFT 明细与汇总 |

另附斜杠命令 `/zcode-tps-overlay:tps`（状态快照）。

## Hooks

- **SessionStart**（`hooks/session-start.mjs`）：
  1. 把当前 `sessionId` 写入 `~/.zcode/tps.state.json`（供 `tps_session_stats` 定位当前会话）
  2. 自动拉起悬浮窗（`~/.zcode/tps.json` 设 `{"autostart": false}` 可关闭；pid 文件存在
     且进程存活时不重复启动）
  3. 会话注入一行就绪提示

## 独立运行（不装插件）

```
start_monitor.bat
```

入口：`plugins/zcode-tps-overlay/overlay/tps_monitor.py`。

## 目录结构

```
plugins/zcode-tps-overlay/
├── .zcode-plugin/plugin.json   # 插件清单
├── .mcp.json                   # MCP server 注册（stdio）
├── hooks/hooks.json + session-start.mjs
├── mcp/tps_server.py           # MCP server（手写 JSON-RPC，纯标准库）
├── commands/tps.md             # /zcode-tps-overlay:tps
└── overlay/tps_core.py         # 采集核心（日志 tail + DB 轮询 + 配置/进程管理）
    overlay/tps_monitor.py      # tkinter 悬浮窗
```

## License

MIT
