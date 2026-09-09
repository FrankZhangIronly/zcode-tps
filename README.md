# zcode-tps — ZCode 模型返回速度悬浮窗（TTFT 监控）

一个 ZCode 插件：置顶半透明悬浮窗，实时监控 ZCode 的模型请求速度与首 token 延迟（TTFT），
并附带一组 MCP 工具，让模型可以直接启停监控、切换界面语言、查询会话统计。

- **顶部**：每个 `baseURL` 下每个模型的返回速度**均值（近 10 次平均）**与最近一次速度
  （速度 = 输出 token ÷ 流式生成时长，已扣除首 token 延迟）
- **下方**：最近 10 次请求滚动列表。进行中的行显示已运行时间（`●`，秒数实时增长），
  完成后就地更新为最终耗时、本次速度与 TTFT（`✓`），失败显示 `✗`
- **边缘吸附**：拖到屏幕上/下/左/右边缘自动滑入隐藏（露出 4px 小边），鼠标碰边滑出，
  移开缩回；拖回屏幕中间取消吸附

## 安装（ZCode 插件市场）

本仓库本身就是一个 ZCode 插件市场：

```
python install.py     # 把本仓库注册为 ZCode 插件市场（幂等）
```

然后 重启 zcode 会话 → 设置 → 插件管理 → 发现 → 安装 **zcode-tps-overlay**。
（也可以在"发现"页用"+"手动添加 GitHub 市场 `FrankZhangIronly/zcode-tps`。）

安装后：

- **SessionStart hook** 自动拉起悬浮窗（`~/.zcode/tps.json` 里 `{"autostart": false}` 可关），
  并记录当前会话 ID 供统计工具使用
- **MCP 工具**（模型可直接调用）：

  | 工具 | 功能 |
  |---|---|
  | `tps_start` / `tps_stop` | 启动 / 停止悬浮窗 |
  | `tps_status` | 运行状态 + 各 (baseURL, model) 的 avg/last 速度与 TTFT 快照 |
  | `tps_language` | 读取或切换悬浮窗语言（`en` / `zh`，热切换） |
  | `tps_session_stats` | 当前会话最近 N 条请求的速度/TTFT 明细与汇总 |

- 斜杠命令 `/zcode-tps-overlay:tps`：查看状态快照

## 独立运行（不装插件）

```
start_monitor.bat
```

悬浮窗入口在 `plugins/zcode-tps-overlay/overlay/tps_monitor.py`，仅依赖 Python 标准库
（需要 tkinter，Windows 版 CPython 自带）。

## 操作

- 按住窗口任意位置**拖动**（移动 3px 以上才生效，避免点击误拖）
- **边缘吸附**见上；右键菜单：退出

## 数据口径

- **速度 = 输出 token ÷ 流式生成时长**（总耗时扣除首 token 延迟）；个别请求无首 token
  时间（如非流式的标题生成）时回退为 总耗时 口径，TTFT 显示 `--`
- **TTFT**：从发起请求到收到第一个 token 的毫秒数。均值行显示近 10 次均值，最近行显示最近一次
- 数据来自 `~/.zcode/cli/db/db.sqlite` 的 `model_usage` 表（只读 WAL，不影响 zcode 运行）
  与 `~/.zcode/cli/log/zcode-YYYY-MM-DD.jsonl` 的 `model.request.started` 事件
  （按 traceId + 开始时间就近配对；一个 turn 内多个请求会复用 traceId）
- 启动时用数据库近 6 小时的记录播种均值，滚动列表保留最近 10 条

## 开发

```
plugins/zcode-tps-overlay/
├── .zcode-plugin/plugin.json   # 插件清单
├── .mcp.json                   # MCP server 注册（stdio）
├── hooks/session-start.mjs     # SessionStart：记录会话 ID + 自动拉起悬浮窗
├── mcp/tps_server.py           # MCP server（手写 JSON-RPC，纯标准库）
├── commands/tps.md             # /zcode-tps-overlay:tps 命令
└── overlay/
    ├── tps_core.py             # 采集核心（日志 tail + DB 轮询 + 配置/进程工具）
    └── tps_monitor.py          # tkinter 悬浮窗（i18n + 边缘吸附 + 平滑动画）
```

修改后重新发布：更新 `plugins/zcode-tps-overlay/.zcode-plugin/plugin.json` 与根目录
`marketplace.json` 的版本号，提交并推送即可（ZCode 刷新市场后可升级）。

## License

MIT
