# zcode-tps-overlay

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Runtime](https://img.shields.io/badge/runtime-Python%203%20stdlib-brightgreen)

**ZCode 模型请求速度悬浮窗监控插件。** 置顶半透明悬浮窗实时显示各 (baseURL, 模型) 的出词速度
与首 token 延迟(TTFT)——数据直接读取 ZCode usage 数据库,真实 token 数,非估算;并提供 MCP
工具供模型启停监控、切换界面语言、查询会话统计。

> 本仓库同时是一个 ZCode 插件市场(marketplace 名称:`zcode-tps`),插件本体位于
> [`plugins/zcode-tps-overlay/`](plugins/zcode-tps-overlay/)。

## 效果预览

悬浮窗右上角常驻,自动跟随 zcode 的模型请求刷新,无需任何手动操作:

```text
⚡ ZCode TPS  14:02:31
────────────────────────────────────────────────────
TPS avg of last 10 (tok/s excl. TTFT)
 open.bigmodel.cn/api/anthropic
   GLM-5.3-Flash
     avg   63.9 tok/s   TTFT  3.9s
     last  46.9 tok/s   TTFT  3.6s
────────────────────────────────────────────────────
Recent requests (10/10)
  time      model            dur  tok/s  TTFT
✓ 14:02:27  GLM-5.3-Flash   40.7  100.3   4.8
● 14:02:31  GLM-5.3-Flash    2.3     --    --
```

| 区域/字段 | 含义 |
|---|---|
| `avg` / `last tok/s` | 该模型近 10 次平均 / 最近一次出词速度(输出 token ÷ 流式生成时长,已扣除首 token 延迟) |
| `TTFT` | 首 token 延迟:均值行=近 10 次平均,列表行=该次延迟;非流式请求显示 `--` |
| 最近请求表 | 滚动保留最近 10 次:`●` 进行中(dur 实时增长)、`✓` 已完成、`✗` 失败 |
| 边缘吸附 | 拖到屏幕上/下/左/右边缘自动滑入隐藏(留 4px 小边),鼠标碰边滑出、移开缩回;拖回屏幕中间取消吸附 |

界面语言 `en` / `zh` 可热切换(见下文"配置")。

## 功能特性

- **真实速度监控** —— 悬浮窗顶部按 (baseURL, 模型) 分组展示均值/最近出词速度与 TTFT 均值,
  数据来自 usage 数据库的 `model_usage` 表(真实 token 数与 `time_to_first_token_ms`)
- **最近请求滚动列表** —— 最近 10 次请求表格,进行中实时计时,完成就地补该次速度与 TTFT
- **边缘吸附隐藏** —— 拖到屏幕边缘自动让位,鼠标悬停滑出,不遮挡其它工作
- **MCP 工具** —— `tps_start` / `tps_stop` / `tps_status` / `tps_language` / `tps_session_stats`,
  模型可程序化启停监控与取数
- **自动拉起** —— 会话启动自动运行悬浮窗(可配置关闭);运行实例防重复
- **双语言 UI** —— `en` / `zh` 热切换,不重启
- 实现仅依赖 Python 标准库(tkinter),MCP 协议手写,零第三方包;不改任何 zcode 配置

## 安装

### 方式一:从 GitHub 添加(推荐)

在 ZCode 中执行:

```text
/plugin marketplace add FrankZhangIronly/zcode-tps
/plugin install zcode-tps-overlay@zcode-tps
```

或在 **设置 → 插件管理 → 发现 → "+"** 添加 GitHub 仓库 `FrankZhangIronly/zcode-tps`,
刷新市场列表后安装 **zcode-tps-overlay**。也可以在本地先运行 `python install.py`
(把本仓库注册进 `~/.zcode/cli/plugins/known_marketplaces.json`,幂等)。

### 方式二:本地目录

克隆本仓库后,在 ZCode 中打开 **设置 → 插件管理 → 发现 → +**,来源选择"本地目录",
指向仓库根目录即可。

### 更新

```text
/plugin marketplace update zcode-tps
/plugin update zcode-tps-overlay@zcode-tps
```

更新后重开会话使钩子与 MCP server 重新加载。

## 使用

| 场景 | 操作 |
|---|---|
| 随时查看速度 | 无需操作,悬浮窗自动跟随刷新 |
| 悬浮窗没出现 | 输入 `/zcode-tps-overlay:tps` 看状态,或让模型调用 `tps_start` |
| 模型查询会话统计 | 模型调用 MCP 工具 `tps_session_stats`(当前会话最近 N 条请求的速度/TTFT 明细与汇总) |
| 切换界面语言 | 模型调用 `tps_language`,或编辑 `~/.zcode/tps.json` 写 `{"language": "zh"}`(en/zh,~0.5s 生效) |
| 关闭自动拉起 | `~/.zcode/tps.json` 写入 `{"autostart": false}`,重开会话生效 |
| 独立运行(不装插件) | `start_monitor.bat`(入口 `plugins/zcode-tps-overlay/overlay/tps_monitor.py`) |

要求:Windows;Python 3(标准库,含 tkinter,`.mcp.json` 中配置了解释器路径);hook 需要 node
(随 zcode 环境提供)。macOS/Linux 下悬浮窗未适配(进程管理与屏幕边缘检测依赖 Windows API)。

## 工作原理

```
zcode 会话启动
  │
  ├─ SessionStart hook (hooks/session-start.mjs)
  │    ├─ 记录 sessionId → ~/.zcode/tps.state.json
  │    └─ autostart=true 时拉起悬浮窗(pythonw 分离进程,pid 文件防重复)
  │
  └─ MCP server 自动连接 (mcp/tps_server.py,stdio 换行分隔 JSON-RPC)
       ├─ tps_status 快照:复用与悬浮窗相同的采集逻辑(tail 请求日志 + 轮询 usage 库)
       └─ tps_session_stats:按 tps.state.json 的会话 ID 直接查询 model_usage 表

悬浮窗 (overlay/tps_monitor.py, tkinter)
  ├─ tail ~/.zcode/cli/log/zcode-YYYY-MM-DD.jsonl
  │    model.request.started → 进行中行(●,实时计时)
  └─ 轮询 model_usage 表(只读 WAL,1.5s/次)
       completed 行 → 按 traceId+开始时间就近配对,补 dur/tok/s/TTFT,滚动保留 10 条
```

- **数据口径**:速度 = 输出 token ÷ (总耗时 − 首 token 延迟),即纯流式生成速度;个别请求无
  TTFT(非流式标题生成等)自动回退为总耗时口径。均值与列表均保留最近 10 次。
- **traceId 陷阱**:一个 turn 内多个请求会复用 traceId,故配对用开始时间就近匹配而非顺序。
- 悬浮窗与 MCP 共用采集核心 `overlay/tps_core.py`,单份逻辑。

## 常见问题

**Q:显示的速度准确吗?**

A:token 数与 TTFT 来自 `model_usage` 表的真实值(数据库原生记录,含
`time_to_first_token_ms`),非模型自述。口径为"扣除首 token 延迟的纯流式生成速度",
因此比"输出 token ÷ 总耗时"略高;两者之差即首 token 等待占比。

**Q:悬浮窗没有自动弹出?**

A:运行 `/zcode-tps-overlay:tps` 查看状态,或让模型调用 `tps_start`。常见原因:插件安装后
未重开会话(钩子需新会话注册)、`~/.zcode/tps.json` 里 `autostart` 为 false、悬浮窗进程被
杀后 pid 文件残留(重启即自动清理)。

**Q:MCP 工具没有出现?**

A:插件 MCP server 在会话启动时自动连接;安装或更新插件后需重开会话。若仍未出现,在
设置 → 插件管理确认插件已安装且市场已刷新到最新版本。

**Q:如何切换中文界面?**

A:让模型调用 `tps_language`(参数 `zh` / `en`),或直接编辑 `~/.zcode/tps.json` 的
`language` 字段;悬浮窗约 0.5 秒内热切换,无需重启。

**Q:改代码后如何生效?**

A:提交并推送 GitHub → `/plugin marketplace update zcode-tps` → `/plugin update
zcode-tps-overlay@zcode-tps` → 重开会话。

## License

[MIT](LICENSE) © 2026 FrankZhangIronly
