---
name: generate-worldcodes-image
description: 通过 WorldCodes 的 OpenAI Images 兼容接口调用 gpt-image-2，以 Relay 异步任务或原同步模式完成文生图、单图参考生成、图片编辑与蒙版局部修改，并把 1K、2K、4K 或自定义合法分辨率的结果保存为本地图片。用于用户提到 WorldCodes、gpt-image-2、文生图、图生图、参考图重绘、图片编辑、局部重绘，或明确要求通过 worldcodes.online 出图时。
---

# WorldCodes Image 2

使用随 Skill 提供的无第三方依赖脚本调用 Images API。默认模型为 `gpt-image-2`，默认尺寸为 `1024x1024`，默认只生成 1 张。默认使用 Relay 异步任务，明确需要原同步行为时传 `--mode sync`。

异步只改变“客户端等待 Relay”的方式：Relay 上游仍是同步生图。脚本先以 `Prefer: respond-async` 获取任务 ID，再轮询状态和结果，避免客户端到 Relay 的长连接撞到 524。

## 工作流

1. 将本 `SKILL.md` 所在目录记为 `<skill-dir>`。
2. 确认环境变量 `WORLDCODES_API_KEY` 已存在。不得回显、记录、写入 Skill 或作为命令行参数传递 Key。远程 Base URL 必须使用 HTTPS。
3. 根据输入选择图片模式：
   - 无参考图：调用文生图端点。
   - 有参考图：添加 `--image <本地路径>`，自动调用图片编辑端点。
   - 有蒙版：同时添加 `--mask <本地路径>`；蒙版不能脱离参考图使用。
4. 默认使用 `--mode async`。只有用户明确要求同步、或 Relay 尚未部署任务接口时才使用 `--mode sync`。
5. 用户未指定时使用 `--size 1k --quality auto --count 1`。4K 横图使用 `4k` 或 `4k-landscape`，4K 竖图使用 `4k-portrait`。
6. 将结果写入用户指定目录；未指定时写入当前任务的 `outputs/`。不要写入 Skill 目录。
7. 成功后读取脚本输出的 JSON，核对 `request_mode`、`task_ids`、`images`、`warnings`，向用户返回所有绝对路径，并在支持的客户端中直接渲染图片。

## 调用

文生图：

```bash
python3 <skill-dir>/scripts/worldcodes_image.py \
  --prompt "一只橙色纸飞机，纯白背景，摄影棚柔光" \
  --mode async \
  --size 1k \
  --quality auto \
  --output /absolute/path/to/outputs/
```

图生图或编辑：

```bash
python3 <skill-dir>/scripts/worldcodes_image.py \
  --image /absolute/path/to/input.png \
  --prompt "保留主体与构图，把背景改成暖白色" \
  --mode async \
  --size 2k-landscape \
  --output /absolute/path/to/outputs/edited.png
```

蒙版局部修改：

```bash
python3 <skill-dir>/scripts/worldcodes_image.py \
  --image /absolute/path/to/input.png \
  --mask /absolute/path/to/mask.png \
  --prompt "只把蒙版区域改成蓝色陶瓷花瓶" \
  --output /absolute/path/to/outputs/inpaint.png
```

保留原同步行为：

```bash
python3 <skill-dir>/scripts/worldcodes_image.py \
  --prompt "一张极简公园导览图" \
  --mode sync \
  --output /absolute/path/to/outputs/park.png
```

可先用 `--dry-run` 检查端点、参数和输出路径；该模式不会读取 Key、联网或创建输出目录。

## 尺寸与批量

- 可用快捷值：`1k`、`1k-landscape`、`1k-portrait`、`2k`、`2k-landscape`、`2k-portrait`、`4k`、`4k-landscape`、`4k-portrait`、`auto`。
- 也可传入合法的 `宽x高`，例如 `1536x1024`；脚本会校验 gpt-image-2 的边长、像素数、16 像素倍数与 3:1 比例限制，并把中文乘号 `×` 规范为 `x`。
- `--count N` 会顺序发送 N 个独立的 `n=1` 请求，避免隐藏并发；这会产生 N 次计费请求。
- 异步模式会为每次独立请求生成不同的 `Idempotency-Key`。手动传 `--idempotency-key` 时只允许 `--count 1`。
- `--timeout` 只控制单次 HTTP 调用；`--wait-timeout` 控制脚本等待异步任务的总时长，不能延长 Relay 到上游或 Cloudflare 的超时。

## 异步恢复与安全边界

- 脚本不自动重复提交生图 POST。异步状态/结果查询发生临时网络错误或 5xx 时，只会继续 GET 轮询。
- 错误 JSON 若包含 `task_id`，不要换 Key 创建新任务。可用完全相同的参数和输出设置，并带回错误 JSON 中的同一 `--idempotency-key`；Relay 会返回原任务，不会再次入队。
- `status=unknown` 表示上游是否完成、是否计费均不确定。复用同一 Key 只能恢复原任务，不能把它改成重跑；不要换 Key 自动重生。
- HTTP 524 不是“客户端等得不够久”，也不代表服务端要求 120 秒后重试。同步模式收到 524 时，先用 `request_ids`、`cf_rays` 和 Relay 日志核对；异步提交失败时仅按错误 JSON 的恢复提示处理。

## 输出与排障

- API 固定请求 `response_format=b64_json`；脚本只把解码后的图片写盘，不输出 Base64。
- 异步成功输出包含 `task_ids`；应用请求 ID 位于 `request_ids`，Cloudflare Ray ID 单列在 `cf_rays`，两者不能混用。
- 参考图与蒙版仅接受小于 50MB 的 PNG、JPEG、WebP；蒙版还必须与参考图格式、尺寸一致并包含 Alpha 通道。
- 响应会校验图片格式、结构和实际尺寸。
- 2xx 后若解码或写盘失败，错误 JSON 会保留已完成请求数、任务 ID、幂等键、请求 ID 与已保存文件；据此恢复原任务并避免重复计费。
- 401/403：检查环境变量、Key 状态与模型权限。
- 400：检查提示词、图片、尺寸、质量和输出格式。
- 413：压缩参考图或降低尺寸。
- 429：检查余额、配额和请求日志。
- 需要核对参数、响应或 SSE 行为时，读取 [references/api.md](references/api.md)。
