# WorldCodes gpt-image-2 API 参考

## 连接

- 默认 API Base URL：`https://worldcodes.online/v1`
- 鉴权：`Authorization: Bearer $WORLDCODES_API_KEY`
- 文生图：`POST /v1/images/generations`，JSON 请求体
- 图生图/编辑：`POST /v1/images/edits`，`multipart/form-data` 请求体
- 原接口默认同步返回 JSON；Relay 额外支持 `Prefer: respond-async` 的本地异步任务包装。上游仍同步执行。
- WorldCodes 上游也支持 `stream=true` 的 SSE；随 Skill 提供的脚本不启用 SSE。
- 图片响应请求 `response_format=b64_json`。
- 脚本拒绝远程 HTTP 和 API 重定向，避免 Bearer Key 跨域或降级传输。

## 核心字段

文生图：`model`、`prompt`、`size`、`quality`、`n=1`、`response_format=b64_json`。

图片编辑：以上字段加 `image` 文件；局部修改可再加 `mask` 文件。WorldCodes 官方示例使用单个 `image` 字段。

参考图和蒙版均须小于 50MB。使用蒙版时，它必须与参考图格式、尺寸一致，并包含 Alpha 通道；脚本会在请求前校验。

常用可选字段：`output_format`（`png`、`jpeg`、`webp`）、`output_compression`（JPEG/WebP 的 0–100）、`background`（`auto` 或 `opaque`）。`gpt-image-2` 不支持透明背景。WorldCodes 公开定价元数据当前主要列出 `auto/high` 质量；`low/medium` 若被特定 Key 路由拒绝，应改用 `auto` 或 `high`。

## gpt-image-2 尺寸约束

- 最长边不超过 3840px。
- 两条边都必须是 16px 的倍数。
- 长短边比例不超过 3:1。
- 总像素数为 655,360–8,294,400。
- 常用值：`1024x1024`、`1536x1024`、`1024x1536`、`2048x2048`、`2048x1152`、`3840x2160`、`2160x3840`、`auto`。

WorldCodes 的公开示例固定使用 `1024x1024`；2K/4K 按 gpt-image-2 兼容尺寸发送。若特定 Key 或路由返回 400，先核对该 Key 的模型分组和计费规则，不要盲目重试。

## 同步响应

典型响应为：

```json
{
  "created": 0,
  "data": [
    {"b64_json": "..."}
  ]
}
```

脚本也兼容 `data[].url` 和顶层 `b64_json`。`--mode sync` 保留该行为。

## Relay 异步任务

脚本默认 `--mode async`，仍向原图片端点 POST，但增加：

```http
Prefer: respond-async
Idempotency-Key: <1–128 位可见 ASCII>
```

异步模式必须使用 `response_format=b64_json`、`n=1`，且不能与 `stream=true` 同时使用。正常提交返回：

```http
HTTP/1.1 202 Accepted
Location: /v1/images/tasks/imgjob_<32位任务标识>
Preference-Applied: respond-async
Retry-After: 2
```

```json
{
  "id": "imgjob_0123456789abcdef0123456789abcdef",
  "object": "image.task",
  "status": "queued",
  "request_id": "...",
  "created_at": 0,
  "expires_at": 0,
  "expired": false
}
```

查询与取结果：

```text
GET /v1/images/tasks/:id
GET /v1/images/tasks/:id/result
```

状态为 `queued`、`in_progress`、`succeeded`、`failed`、`unknown`。只有 `succeeded` 才读取 `/result`；结果体与同步 Images JSON 完全相同。未完成时结果端点返回 409，过期后返回 410。

同一用户令牌以同一 `Idempotency-Key` 提交语义相同的请求，会返回原任务；同 Key 对应不同请求返回 409。图片编辑的 multipart boundary 可变化，但字段、文件内容与顺序必须保持一致。

脚本默认生成 Key，并在错误 JSON 中保留当前 Key。需要恢复时，完整复用原参数与同一 `--idempotency-key`；不要换 Key。`unknown` 是终态，Relay 不会自动重跑上游。

应用请求 ID 从 `x-oneapi-request-id` 或 `x-request-id` 读取；`cf-ray` 单独记录为 Cloudflare Ray ID，不当作业务 request ID。

## 524

524 表示代理已经连接源站，但等待源站响应超时；少数大请求也可能是代理向源站写请求体超时。调大客户端 `--timeout` 不能改变代理层期限，也不代表“等 120 秒即可安全重试”。

- 同步 POST 收到 524：任务和计费状态未知，先查 Relay/Cloudflare/上游日志。
- 异步 POST 尚未拿到任务 ID：保留错误 JSON 中的幂等键，确认 Relay 已部署异步接口后，只能用完全相同请求和同一 Key 恢复。
- 已拿到任务 ID：继续查询原任务；不要换 Key 创建新任务。

## SSE 说明

启用流式时，即使 HTTP 为 200，也要处理 `event: error`；只在收到 `[DONE]` 后视为完整结束。完成事件可能为 `image_generation.completed` 或 `image_edit.completed`，其中包含最终 `b64_json`。当前脚本不启用流式，避免把中间预览误当成最终图；流式也不是可断线后查询的异步任务。

## 来源

- [WorldCodes gpt-image-2 接入指南](https://worldcodes.online/config-guide?family=gpt-image-2&model=gpt-image-2)
- [OpenAI gpt-image-2 模型页](https://developers.openai.com/api/docs/models/gpt-image-2)
- [OpenAI 图片生成与编辑指南](https://developers.openai.com/api/docs/guides/image-generation)
