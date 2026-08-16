# WorldCodes gpt-image-2 API 参考

## 连接

- 默认 API Base URL：`https://worldcodes.online/v1`
- 鉴权：`Authorization: Bearer $WORLDCODES_API_KEY`
- 文生图：`POST /v1/images/generations`，JSON 请求体
- 图生图/编辑：`POST /v1/images/edits`，`multipart/form-data` 请求体
- WorldCodes 同时支持同步 JSON 与 `stream=true` 的 SSE；随 Skill 提供的脚本使用同步 JSON。
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

脚本也兼容 `data[].url` 和顶层 `b64_json`。HTTP 错误时读取 `x-request-id`、`x-oneapi-request-id` 或 `cf-ray`，但不打印 Key。

## SSE 说明

启用流式时，即使 HTTP 为 200，也要处理 `event: error`；只在收到 `[DONE]` 后视为完整结束。完成事件可能为 `image_generation.completed` 或 `image_edit.completed`，其中包含最终 `b64_json`。当前脚本不启用流式，避免把中间预览误当成最终图。

## 来源

- [WorldCodes gpt-image-2 接入指南](https://worldcodes.online/config-guide?family=gpt-image-2&model=gpt-image-2)
- [OpenAI gpt-image-2 模型页](https://developers.openai.com/api/docs/models/gpt-image-2)
- [OpenAI 图片生成与编辑指南](https://developers.openai.com/api/docs/guides/image-generation)
