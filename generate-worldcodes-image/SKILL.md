---
name: generate-worldcodes-image
description: 通过 WorldCodes 的 OpenAI Images 兼容接口调用 gpt-image-2，完成文生图、单图参考生成、图片编辑与蒙版局部修改，并把 1K、2K、4K 或自定义合法分辨率的结果保存为本地图片。用于用户提到 WorldCodes、gpt-image-2、文生图、图生图、参考图重绘、图片编辑、局部重绘，或明确要求通过 worldcodes.online 出图时。
---

# WorldCodes Image 2

使用随 Skill 提供的无第三方依赖脚本调用同步 Images API。默认模型为 `gpt-image-2`，默认尺寸为 `1024x1024`，默认只生成 1 张。

## 工作流

1. 将本 `SKILL.md` 所在目录记为 `<skill-dir>`。
2. 确认环境变量 `WORLDCODES_API_KEY` 已存在。不得回显、记录、写入 Skill 或作为命令行参数传递 Key。远程 Base URL 必须使用 HTTPS。
3. 根据输入选择模式：
   - 无参考图：调用文生图端点。
   - 有参考图：添加 `--image <本地路径>`，自动调用图片编辑端点。
   - 有蒙版：同时添加 `--mask <本地路径>`；蒙版不能脱离参考图使用。
4. 用户未指定时使用 `--size 1k --quality auto --count 1`。4K 横图使用 `4k` 或 `4k-landscape`，4K 竖图使用 `4k-portrait`。
5. 将结果写入用户指定目录；未指定时写入当前任务的 `outputs/`。不要写入 Skill 目录。
6. 成功后读取脚本输出的 JSON，核对 `images` 中的实际格式/尺寸及 `warnings`，向用户返回所有绝对路径，并在支持的客户端中直接渲染图片。

## 调用

文生图：

```bash
python3 <skill-dir>/scripts/worldcodes_image.py \
  --prompt "一只橙色纸飞机，纯白背景，摄影棚柔光" \
  --size 1k \
  --quality auto \
  --output /absolute/path/to/outputs/
```

图生图或编辑：

```bash
python3 <skill-dir>/scripts/worldcodes_image.py \
  --image /absolute/path/to/input.png \
  --prompt "保留主体与构图，把背景改成暖白色" \
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

可先用 `--dry-run` 检查端点、参数和输出路径；该模式不会读取 Key、联网或创建输出目录。

## 尺寸与批量

- 可用快捷值：`1k`、`1k-landscape`、`1k-portrait`、`2k`、`2k-landscape`、`2k-portrait`、`4k`、`4k-landscape`、`4k-portrait`、`auto`。
- 也可传入合法的 `宽x高`，例如 `1536x1024`；脚本会校验 gpt-image-2 的边长、像素数、16 像素倍数与 3:1 比例限制，并把中文乘号 `×` 规范为 `x`。
- `--count N` 会顺序发送 N 个独立的 `n=1` 请求，避免隐藏并发；这会产生 N 次计费请求。
- 不自动重试。若发生超时或 5xx，先报告状态码与脱敏 request ID，确认计费情况后再决定是否重试。

## 输出与排障

- API 固定请求 `response_format=b64_json`；脚本只把解码后的图片写盘，不输出 Base64。
- 参考图与蒙版仅接受小于 50MB 的 PNG、JPEG、WebP；蒙版还必须与参考图格式、尺寸一致并包含 Alpha 通道。
- 响应会校验图片格式、结构和实际尺寸。
- 2xx 后若解码或写盘失败，错误 JSON 会保留已完成请求数、request ID 与已保存文件；据此避免重复计费。
- 401/403：检查环境变量、Key 状态与模型权限。
- 400：检查提示词、图片、尺寸、质量和输出格式。
- 413：压缩参考图或降低尺寸。
- 429：检查余额、配额和请求日志。
- 需要核对参数、响应或 SSE 行为时，读取 [references/api.md](references/api.md)。
