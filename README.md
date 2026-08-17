<div align="center">

# 🎨 WorldCodes Image 2 Skill

**让 Codex 通过 WorldCodes `gpt-image-2` 直接完成文生图、图生图与蒙版编辑。**

[![Codex Skill](https://img.shields.io/badge/Codex-Skill-111827?style=for-the-badge&logo=openai&logoColor=white)](./generate-worldcodes-image/SKILL.md)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![GPT Image 2](https://img.shields.io/badge/GPT--Image--2-10A37F?style=for-the-badge)](https://developers.openai.com/api/docs/models/gpt-image-2)
[![1K–4K](https://img.shields.io/badge/Resolution-1K--4K-F97316?style=for-the-badge)](#尺寸)

纯 Python 标准库 · 无第三方依赖 · Key 不落盘 · 默认异步任务 · 保留同步模式

</div>

## 效果预览

<table>
  <tr>
    <td align="center" width="50%"><strong>文生图</strong></td>
    <td align="center" width="50%"><strong>图生图</strong></td>
  </tr>
  <tr>
    <td><img src="./docs/images/text-to-image.png" alt="文生图：白色背景上的橙色纸飞机"></td>
    <td><img src="./docs/images/image-to-image.png" alt="图生图：蓝天背景中的橙色纸飞机"></td>
  </tr>
  <tr>
    <td align="center">文字生成橙色纸飞机</td>
    <td align="center">保留主体，将背景编辑为蓝天白云</td>
  </tr>
</table>

## 能做什么

| 能力 | 说明 |
| --- | --- |
| ✨ 文生图 | 调用 `/v1/images/generations` 从提示词生成图片 |
| 🖼️ 图生图 | 自动调用 `/v1/images/edits`，基于单张参考图重绘或编辑 |
| 🎭 蒙版编辑 | 校验蒙版格式、尺寸与 Alpha 通道后执行局部修改 |
| 🔭 1K–4K | 内置横版、竖版、方形快捷尺寸，也支持合法自定义尺寸 |
| 📦 多种格式 | 支持 PNG、JPEG、WebP 输出与 JPEG/WebP 压缩参数 |
| 📦 批量生成 | `--count` 顺序发送多个独立的 `n=1` 请求，计费行为更清晰 |
| ⏳ 异步任务 | 默认提交 Relay 任务并轮询结果，避免客户端长连接触发 524 |
| 🔁 幂等恢复 | 为任务生成 `Idempotency-Key`，异常时可恢复原任务而不重复入队 |
| 🛡️ 安全输出 | 拒绝远程 HTTP 和重定向，不回显 Key，并校验返回图片结构 |

## 环境要求

- Codex Desktop 或其他支持 Skills 的 Codex 环境
- Python 3.9+
- 拥有 `gpt-image-2` 权限的 WorldCodes API Key
- 无第三方 Python 依赖

## 快速安装

### 1. 克隆并安装 Skill

```bash
git clone https://github.com/lori-super/generate-worldcodes-image.git worldcodes-image-skill
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R worldcodes-image-skill/generate-worldcodes-image "${CODEX_HOME:-$HOME/.codex}/skills/"
```

重新打开 Codex 任务后，即可通过 `$generate-worldcodes-image` 调用。

### 2. 配置 API Key

从 [WorldCodes](https://worldcodes.online) 获取 Key，并在启动 Codex 的环境中设置：

```bash
export WORLDCODES_API_KEY="YOUR_WORLDCODES_API_KEY"
```

> [!IMPORTANT]
> 不要把真实 Key 写入仓库、README、`SKILL.md` 或脚本。项目已默认忽略 `.env`，但仍建议使用系统密钥管理或安全的环境变量注入方式。

## 在 Codex 中使用

文生图：

```text
使用 $generate-worldcodes-image 生成一张 4K 横版赛博朋克城市海报，雨夜，霓虹灯，无文字。
```

图生图：

```text
使用 $generate-worldcodes-image，参考 /absolute/path/input.png，保留主体与构图，把背景改成暖白色，输出 2K 横图。
```

蒙版局部编辑：

```text
使用 $generate-worldcodes-image，以 input.png 为参考图、mask.png 为蒙版，只把蒙版区域改成蓝色陶瓷花瓶。
```

## 直接运行脚本

文生图：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/generate-worldcodes-image/scripts/worldcodes_image.py" \
  --prompt "一只橙色纸飞机，纯白背景，摄影棚柔光" \
  --mode async \
  --size 1k \
  --quality auto \
  --output /absolute/path/to/outputs/
```

图生图：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/generate-worldcodes-image/scripts/worldcodes_image.py" \
  --image /absolute/path/to/input.png \
  --prompt "保留主体，把背景改成清澈蓝天" \
  --mode async \
  --size 2k-landscape \
  --output /absolute/path/to/outputs/edited.png
```

保留原同步调用：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/generate-worldcodes-image/scripts/worldcodes_image.py" \
  --prompt "一张极简公园导览图" \
  --mode sync \
  --output /absolute/path/to/outputs/park.png
```

先校验参数、不联网也不计费：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/generate-worldcodes-image/scripts/worldcodes_image.py" \
  --prompt "测试提示词" \
  --size 4k-portrait \
  --output /absolute/path/to/outputs/ \
  --dry-run
```

## 尺寸

| 快捷值 | 实际尺寸 |
| --- | --- |
| `1k` / `1k-square` | `1024×1024` |
| `1k-landscape` / `1k-portrait` | `1536×1024` / `1024×1536` |
| `2k` / `2k-square` | `2048×2048` |
| `2k-landscape` / `2k-portrait` | `2048×1152` / `1152×2048` |
| `4k` / `4k-landscape` | `3840×2160` |
| `4k-portrait` | `2160×3840` |
| `auto` | 由服务端决定 |

也可直接传入 `宽x高`。脚本会检查最长边、16 像素倍数、总像素量及最大 `3:1` 比例。

> [!NOTE]
> 2K、4K、自定义尺寸及质量档位是否可用，仍取决于 WorldCodes Key 所属模型分组和路由配置。

## 设计原则

- Key 只从 `WORLDCODES_API_KEY` 读取，不作为命令行参数传递。
- 默认请求 `response_format=b64_json`，只将解码后的图片写入本地。
- 默认 `--mode async`：使用 `Prefer: respond-async` 提交任务，再查询状态与结果；Relay 上游仍同步执行。
- `--mode sync` 保留原同步接口行为，便于兼容尚未部署任务接口的 Relay。
- 不自动重复提交生图 POST；异步查询发生临时网络错误或 5xx 时只重试 GET。
- 异步任务使用 `Idempotency-Key`。恢复时必须复用完全相同的参数和同一 Key；`unknown` 状态不得换 Key 自动重生。
- 多张图片按顺序独立请求，任务 ID、应用 request ID 与 Cloudflare Ray ID 分别写入结构化摘要。
- 参考图、蒙版和响应图片均做格式与结构校验。
- 自定义远程 Base URL 必须使用 HTTPS；本机回环地址可使用 HTTP 测试。

> [!WARNING]
> HTTP 524 是代理等待源站响应超时，不是客户端 `--timeout` 太短，也不代表等待 120 秒后即可安全重试。优先使用异步模式；若任务状态为 `unknown`，先核对 Relay 日志和计费记录。

## 项目结构

```text
.
├── README.md
├── docs/images/                  # README 示例图片
└── generate-worldcodes-image/    # 可直接安装的 Codex Skill
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── references/api.md
    └── scripts/worldcodes_image.py
```

## 参考

- [WorldCodes gpt-image-2 接入指南](https://worldcodes.online/config-guide?family=gpt-image-2&model=gpt-image-2)
- [OpenAI GPT Image 2 模型页](https://developers.openai.com/api/docs/models/gpt-image-2)
- [OpenAI 图片生成与编辑指南](https://developers.openai.com/api/docs/guides/image-generation)

---

<div align="center">
  <sub>非 WorldCodes 或 OpenAI 官方项目。请自行关注 API 计费、配额与内容政策。</sub>
</div>
