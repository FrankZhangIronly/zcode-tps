# Bilibili 专栏文章草稿 v4（最终录入版）：用 ZCode 实测 DeepSeek v4.1（公测）

> 要求迭代记录：
> 1. v4.1 是**公测**不是内测；
> 2. 标题不体现"作者自制插件"，只写用 ZCode 测速；
> 3. 不提"蹭热度"，插件只顺带：一句简介 + GitHub 链接；正文重心 = v4.1 快；
> 4. 降低 AI 感：口语化、短句、个人化，避免设问/排比/模板化首尾；
> 5. 用户删除：①"在 ZCode 里敲两行命令…评论区晒一个？"整段（含安装命令与结尾）；
>    ②"我平时写代码基本都泡在 ZCode 里…等它开口那一下"整段（悬浮窗描述+289.5 数据句）。
> 最终文章止于 GitHub 链接。录入用标题 A。图片由用户手动粘贴到"结论先说"段后的空行。

## 标题（已定 A）

`DeepSeek v4.1公测，拿ZCode测了下是真的快`（29 字）

## 正文（最终，含空行标记）

```
DeepSeek v4.1 公测了，这两天我把它接进 ZCode 用了不少活，群里看到好多人也在晒，就来说说自己的实测。

结论先说：快，是真快。

【空行：用户在此处粘贴悬浮窗实测截图 docs/bili/overlay-demo.png】

同一天里我顺手对比了手头几个模型，数字都在图里：

- deepseek-v4.1-flash（公测，走 api.deepseek.com/anthropic）：均值 289.5 tok/s，TTFT 均值 0.6s
- deepseek-v4-flash（api.commandcode.ai）：均值 104.3 tok/s，最高冲到 139.2
- GLM-5.3-Flash：均值 47.9 tok/s

v4.1 大概是 v4-flash 的三倍。写长文档、改大段代码这种活，体感差别特别明显——以前是等它吐字，现在是它打得飞快你还得盯着看有没有写歪。

顺带说说那个悬浮窗：ZCode 的开源插件 zcode-tps-overlay，装上自动挂桌面，实时显示每个接口+模型的出词速度和首 token 延迟，数据读的是 ZCode 自己的 usage 库，真实 token 数，不是估的；拖到屏幕边还会自己收起来，不挡窗口。也在用 ZCode 的兄弟可以试试，免费的：

https://github.com/FrankZhangIronly/zcode-tps
```

## 数据核对（来自 14:13:41 悬浮窗实测截图）

| 端点 | 模型 | 均值 tok/s | TTFT 均值 | 最近 tok/s | TTFT |
|---|---|---|---|---|---|
| api.deepseek.com/anthropic | deepseek-v4.1-flash-expires-on-0910（公测） | 289.5 | 0.6s | 283.2 | 0.6s |
| api.commandcode.ai/provider/v1 | deepseek/deepseek-v4-flash | 104.3 | 7.1s | 139.2 | 5.1s |
| open.bigmodel.cn/api/anthropic | GLM-5.3-Flash | 47.9 | 13.6s | 44.5 | 5.3s |

最近请求表 top5 速：152.0 / 145.5 / 139.2 / 134.6 / 133.9 tok/s（deepseek-v4-flash）
