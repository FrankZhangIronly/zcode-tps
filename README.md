# zcode-tps-overlay

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blue)
![Runtime](https://img.shields.io/badge/runtime-Node%20%2B%20host%20Python%203%20stdlib-brightgreen)

**ZCode 模型请求速度悬浮窗监控插件。** 置顶半透明悬浮窗实时显示各 (baseURL, 模型) 的出词速度
与首 token 延迟(TTFT)——数据直接读取 ZCode usage 数据库,真实 token 数,非估算;并提供 MCP
工具供模型启停监控、切换界面语言、查询会话统计。

> 本仓库同时是一个 ZCode 插件市场(marketplace 名称:`zcode-tps`),插件本体位于
> [`plugins/zcode-tps-overlay/`](plugins/zcode-tps-overlay/)。
>
> **0.2.0 起 Python 解释器不再写死**:由 Node 启动器在运行时动态解析,首次使用可用
> `tps-setup` skill 自动定位;换机器、换 conda 环境后自愈。

## 效果预览

悬浮窗右上角常驻,自动跟随 zcode 的模型请求刷新,无需任何手动操作:

![悬浮窗效果](docs/overlay-preview.png)

| 区域/字段 | 含义 |
|---|---|
| `avg` / `last tok/s` | 该模型近 10 次平均 / 最近一次出词速度(输出 token ÷ 流式生成时长,已扣除首 token 延迟) |
| `TTFT` | 首 token 延迟:均值行=近 10 次平均,列表行=该次延迟;非流式请求显示 `--` |
| 最近请求表 | 滚动保留最近 10 次:`●` 进行中(dur 实时增长)、`✓` 已完成、`✗` 失败 |
| 边缘吸附 | 拖到屏幕上/下/左/右边缘自动滑入隐藏(露出 20px 可见边,与悬停弹出范围一致),鼠标碰边滑出、移开缩回;拖回屏幕中间取消吸附 |

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
- **解释器自动定位** —— Python 路径运行时解析并写入 `~/.zcode/tps.json`,换机器/换环境自愈;
  找不到时由 `tps-setup` skill 引导定位与安装,不依赖任何硬编码路径
- 实现仅依赖 Python 标准库(tkinter),MCP 协议手写,零第三方包;不改任何 zcode 配置

## 安装

### 方式一:从 GitHub 添加(推荐)

在 ZCode 中执行:

```text
/plugin marketplace add FrankZhangIronly/zcode-tps
/plugin install zcode-tps-overlay@zcode-tps
```

或在 **设置 → 插件管理 → 发现 → "+"** 添加 GitHub 仓库 `FrankZhangIronly/zcode-tps`,
刷新市场列表后安装 **zcode-tps-overlay**。也可以在本地先运行 `node install.mjs`
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

## 首次运行(解释器自动配置)

插件不再假设 Python 装在哪里。启动器(`mcp/launch.mjs`、SessionStart hook、`start.mjs`)
每次按下面的优先级在**运行时**解析解释器:

1. `--python <path>`(仅 `tps-setup` 用)
2. 环境变量 `TPS_PYTHON`
3. `~/.zcode/tps.json` 的 `python` 字段
4. 自动发现 —— `py -0p` 注册表、`PATH`、常见安装位,以及 conda/mamba 环境
   (含 Windows 各盘符下的 `*conda3*\envs\*`)

候选必须实测通过 `import tkinter, sqlite3` 且为 Python 3.8+ 才会被采用,因此
Windows 的 Microsoft Store 占位符、没有 tkinter 的 macOS Xcode `python3` 会被自动淘汰。

**大多数情况无需任何操作**:会话启动时 hook 会自动找到并写好 `~/.zcode/tps.json`。
兜底路径:

| 情况 | 做法 |
|---|---|
| 悬浮窗没出现 / `tps_*` 工具缺失 | 让模型运行 `tps-setup` skill,或手动 `npm run setup` |
| 自己指定解释器 | `node plugins/zcode-tps-overlay/skills/tps-setup/setup.mjs --python "<路径>" --start` |
| 只是想看当前配置 | `node plugins/zcode-tps-overlay/skills/tps-setup/setup.mjs --json` |
| 没有 Python | `tps-setup` 会给出各平台安装命令(Windows `winget install Python.Python.3.12`;macOS `brew install python-tk`;Ubuntu `sudo apt install python3-tk`) |

配置写入后,**MCP 工具需重开会话**才会加载(server 进程在会话启动时定好解释器);
悬浮窗本身会立即启动。若配置的解释器失效(如删掉了 conda 环境),下次运行会自动
重新发现并修正配置,无需手工干预。

## 使用

| 场景 | 操作 |
|---|---|
| 随时查看速度 | 无需操作,悬浮窗自动跟随刷新 |
| 悬浮窗没出现 | 输入 `/zcode-tps-overlay:tps` 看状态,或让模型调用 `tps_start` |
| 模型查询会话统计 | 模型调用 MCP 工具 `tps_session_stats`(当前会话最近 N 条请求的速度/TTFT 明细与汇总) |
| 切换界面语言 | 模型调用 `tps_language`,或编辑 `~/.zcode/tps.json` 写 `{"language": "zh"}`(en/zh,~0.5s 生效) |
| 关闭自动拉起 | `~/.zcode/tps.json` 写入 `{"autostart": false}`,重开会话生效 |
| 独立运行(不装插件) | `node start.mjs` / `node start.mjs --stop`(入口 `plugins/zcode-tps-overlay/overlay/tps_monitor.py`) |

要求:**Windows / Linux / macOS**;Node 18+(hook 与启动器,随 zcode 环境提供);
Python 3.8+(标准库含 tkinter 与 sqlite3,路径自动发现,可用 `TPS_PYTHON` 或
`tps.json` 指定)。开发与测试:`npm test`(零依赖,`node --test`)。

已实测 Windows;Linux/macOS 为 best-effort(代码路径已跨平台化,但未在实机验证)。
已知限制:Linux 下 Tk 不支持窗口透明度(`-alpha` 失效,会自动降级为不透明);
Wayland 下置顶取决于合成器。

## 工作原理

```
zcode 会话启动
  │
  ├─ SessionStart hook (hooks/session-start.mjs)
  │    ├─ 记录 sessionId → ~/.zcode/tps.state.json
  │    ├─ 运行时解析 Python 解释器(lib/python.mjs,失效则自愈重写 tps.json)
  │    └─ autostart=true 时拉起悬浮窗(分离进程,pid 文件防重复)
  │         找不到解释器时 → 在 additionalContext 里要求模型调用 tps-setup skill
  │
  └─ MCP server (mcp/launch.mjs → overlay/tps_server.py,stdio 换行分隔 JSON-RPC)
       ├─ launcher 解析解释器后把 stdio 原样透传给 Python server
       ├─ tps_status 快照:复用与悬浮窗相同的采集逻辑(tail 请求日志 + 轮询 usage 库)
       └─ tps_session_stats:按 tps.state.json 的会话 ID 直接查询 model_usage 表

悬浮窗 (overlay/tps_monitor.py, tkinter)
  ├─ tail ~/.zcode/cli/log/zcode-YYYY-MM-DD.jsonl
  │    model.request.started → 进行中行(●,实时计时)
  └─ 轮询 model_usage 表(只读 WAL,1.5s/次)
       completed 行 → 按 traceId+开始时间就近配对,补 dur/tok/s/TTFT,滚动保留 10 条
```

- **解释器解析**:单一实现 `lib/python.mjs`,被 hook、MCP launcher、`tps-setup`、
  `start.mjs` 四处共用;`.mcp.json` 只写 `command: node`,不再出现任何解释器路径。
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

**Q:提示找不到 Python,或 `tps_*` 工具不出现?**

A:先让模型运行 `tps-setup` skill —— 它会列出所有已探测的候选与淘汰原因,引导定位或安装。
常见根因:Windows 上 `python.exe` 只是 Microsoft Store 占位符(退出码 49);macOS 用的是
Xcode 自带 `/usr/bin/python3`(无 tkinter);Linux 没装 `python3-tk`。装好后重开会话,
MCP 工具才会加载。

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
