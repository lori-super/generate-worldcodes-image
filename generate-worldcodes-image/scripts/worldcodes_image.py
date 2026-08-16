#!/usr/bin/env python3
"""Generate or edit images through WorldCodes gpt-image-2."""

from __future__ import annotations

import argparse
import base64
import binascii
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
import zlib
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


DEFAULT_BASE_URL = "https://worldcodes.online/v1"
DEFAULT_MODEL = "gpt-image-2"
KEY_ENV = "WORLDCODES_API_KEY"
BASE_URL_ENV = "WORLDCODES_BASE_URL"
MODEL_ENV = "WORLDCODES_IMAGE_MODEL"

SIZE_PRESETS = {
    "1k": "1024x1024",
    "1k-square": "1024x1024",
    "1k-landscape": "1536x1024",
    "1k-portrait": "1024x1536",
    "2k": "2048x2048",
    "2k-square": "2048x2048",
    "2k-landscape": "2048x1152",
    "2k-portrait": "1152x2048",
    "4k": "3840x2160",
    "4k-landscape": "3840x2160",
    "4k-portrait": "2160x3840",
}
FORMAT_EXTENSIONS = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}
REQUEST_ID_HEADERS = ("x-request-id", "x-oneapi-request-id", "cf-ray")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


class UserError(RuntimeError):
    """An error safe to show to the user."""


class CompletedRequestError(UserError):
    """A 2xx response failed while being read and may already be billed."""

    def __init__(self, message: str, response_request_id: str | None):
        super().__init__(message)
        self.response_request_id = response_request_id


class NoRedirectHandler(HTTPRedirectHandler):
    """Reject redirects so bearer credentials never cross origins or schemes."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


NO_REDIRECT_OPENER = build_opener(NoRedirectHandler())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="通过 WorldCodes gpt-image-2 文生图或图生图。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--prompt", required=True, help="生成或编辑指令")
    parser.add_argument("--image", type=Path, help="参考图；提供后自动使用图片编辑接口")
    parser.add_argument("--mask", type=Path, help="可选蒙版；必须与 --image 一起使用")
    parser.add_argument(
        "--size",
        default="1k",
        help="1k/2k/4k 快捷值、方向快捷值、auto 或合法的 宽x高",
    )
    parser.add_argument(
        "--quality",
        choices=("auto", "low", "medium", "high"),
        default="auto",
    )
    parser.add_argument(
        "--output-format",
        choices=("png", "jpeg", "webp"),
        default="png",
    )
    parser.add_argument(
        "--output-compression",
        type=int,
        help="JPEG/WebP 压缩值 0–100；PNG 不支持",
    )
    parser.add_argument(
        "--background",
        choices=("auto", "opaque"),
        help="可选背景设置；gpt-image-2 不支持 transparent",
    )
    parser.add_argument("--count", type=int, default=1, help="顺序发送的独立请求数，1–10")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("."),
        help="输出文件或目录；目录内自动生成带时间戳的文件名",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get(BASE_URL_ENV, DEFAULT_BASE_URL),
        help=f"API Base URL；也可用 {BASE_URL_ENV}",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get(MODEL_ENV, DEFAULT_MODEL),
        help=f"模型名；也可用 {MODEL_ENV}",
    )
    parser.add_argument("--timeout", type=float, default=300.0, help="单次请求超时秒数")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有输出文件")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验并显示脱敏请求摘要，不读取 Key、不联网",
    )
    return parser.parse_args()


def normalize_base_url(raw_url: str) -> str:
    raw_url = raw_url.strip()
    try:
        parsed = urlsplit(raw_url)
    except ValueError as exc:
        raise UserError(f"Base URL 无效：{exc}") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise UserError("Base URL 必须是完整的 HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise UserError("Base URL 不得包含账号、密码、查询参数或片段")
    if parsed.scheme == "http" and parsed.hostname not in LOOPBACK_HOSTS:
        raise UserError("远程 Base URL 必须使用 HTTPS；HTTP 仅允许本机回环测试")
    path = parsed.path.rstrip("/")
    if not path.endswith("/v1"):
        path = f"{path}/v1" if path else "/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def normalize_size(raw_size: str) -> str:
    normalized = raw_size.strip().lower().replace("×", "x")
    if normalized == "auto":
        return normalized
    normalized = SIZE_PRESETS.get(normalized, normalized)
    match = re.fullmatch(r"(\d+)x(\d+)", normalized)
    if not match:
        raise UserError("尺寸应为 1k/2k/4k 快捷值、auto 或 宽x高")
    width, height = map(int, match.groups())
    if width <= 0 or height <= 0:
        raise UserError("宽和高必须大于 0")
    if max(width, height) > 3840:
        raise UserError("gpt-image-2 最长边不能超过 3840px")
    if width % 16 or height % 16:
        raise UserError("宽和高都必须是 16px 的倍数")
    if max(width, height) / min(width, height) > 3:
        raise UserError("长短边比例不能超过 3:1")
    pixels = width * height
    if not 655_360 <= pixels <= 8_294_400:
        raise UserError("总像素数必须在 655,360–8,294,400 之间")
    return f"{width}x{height}"


def image_content_type(path: Path) -> str:
    with path.open("rb") as handle:
        signature = handle.read(16)
    for prefix, content_type in IMAGE_SIGNATURES:
        if signature.startswith(prefix):
            return content_type
    if signature.startswith(b"RIFF") and signature[8:12] == b"WEBP":
        return "image/webp"
    raise UserError(f"仅支持 PNG、JPEG 或 WebP 图片：{path}")


def validate_args(args: argparse.Namespace) -> tuple[str, str]:
    if not args.prompt.strip():
        raise UserError("提示词不能为空")
    if args.mask and not args.image:
        raise UserError("--mask 必须与 --image 一起使用")
    input_metadata: dict[str, dict[str, Any]] = {}
    for label, path in (("参考图", args.image), ("蒙版", args.mask)):
        if path and (not path.exists() or not path.is_file()):
            raise UserError(f"{label}不存在或不是文件：{path}")
        if path:
            try:
                if path.stat().st_size >= 50 * 1024 * 1024:
                    raise UserError(f"{label}必须小于 50MB：{path}")
                content_type = image_content_type(path)
                expected_format = {
                    "image/png": "png",
                    "image/jpeg": "jpeg",
                    "image/webp": "webp",
                }[content_type]
                input_metadata[label] = inspect_output_image(
                    path.read_bytes(), expected_format
                )
            except OSError as exc:
                raise UserError(f"无法读取{label}：{path}：{exc}") from exc
    if args.mask:
        image_metadata = input_metadata["参考图"]
        mask_metadata = input_metadata["蒙版"]
        comparable = ("format", "width", "height")
        if any(image_metadata[key] != mask_metadata[key] for key in comparable):
            raise UserError("蒙版必须与参考图格式相同、尺寸一致")
        if not mask_metadata["has_alpha"]:
            raise UserError("蒙版必须包含 Alpha 通道")
    if not 1 <= args.count <= 10:
        raise UserError("--count 必须在 1–10 之间")
    if args.timeout <= 0:
        raise UserError("--timeout 必须大于 0")
    if args.output_compression is not None:
        if not 0 <= args.output_compression <= 100:
            raise UserError("--output-compression 必须在 0–100 之间")
        if args.output_format == "png":
            raise UserError("PNG 不支持 --output-compression；请改用 jpeg 或 webp")
    return normalize_base_url(args.base_url), normalize_size(args.size)


def request_fields(args: argparse.Namespace, size: str) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "model": args.model,
        "prompt": args.prompt.strip(),
        "size": size,
        "quality": args.quality,
        "n": 1,
        "response_format": "b64_json",
    }
    if args.output_format != "png":
        fields["output_format"] = args.output_format
    if args.output_compression is not None:
        fields["output_compression"] = args.output_compression
    if args.background:
        fields["background"] = args.background
    return fields


def build_multipart(
    fields: dict[str, Any], image: Path, mask: Path | None
) -> tuple[bytes, str]:
    boundary = f"----CodexWorldCodes{uuid4().hex}"
    chunks: list[bytes] = []

    def add_line(value: str) -> None:
        chunks.append(value.encode("utf-8"))

    for name, value in fields.items():
        add_line(f"--{boundary}\r\n")
        add_line(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
        add_line(f"{value}\r\n")

    for field_name, path in (("image", image), ("mask", mask)):
        if path is None:
            continue
        mime_type = image_content_type(path)
        safe_name = path.name.replace('"', "_")
        add_line(f"--{boundary}\r\n")
        add_line(
            f'Content-Disposition: form-data; name="{field_name}"; '
            f'filename="{safe_name}"\r\n'
        )
        add_line(f"Content-Type: {mime_type}\r\n\r\n")
        chunks.append(path.read_bytes())
        add_line("\r\n")

    add_line(f"--{boundary}--\r\n")
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def request_id(headers: Any) -> str | None:
    for name in REQUEST_ID_HEADERS:
        value = headers.get(name)
        if value:
            return str(value)
    return None


def redact(text: str, key: str) -> str:
    return text.replace(key, "[REDACTED]") if key else text


def post_request(
    endpoint: str,
    body: bytes,
    content_type: str,
    api_key: str,
    timeout: float,
) -> tuple[bytes, str | None]:
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": content_type,
            "Accept": "application/json",
            "User-Agent": "generate-worldcodes-image/1.0",
        },
    )
    try:
        response = NO_REDIRECT_OPENER.open(request, timeout=timeout)
    except HTTPError as exc:
        response_request_id = request_id(exc.headers)
        try:
            raw_error = exc.read(16_384).decode("utf-8", errors="replace")
        except (HTTPException, OSError):
            raw_error = "<错误响应体读取不完整>"
        raw_error = redact(raw_error, api_key)
        suffix = f"，request_id={response_request_id}" if response_request_id else ""
        retry_note = "；未自动重试，请先确认是否已计费" if exc.code >= 500 else ""
        raise UserError(
            f"WorldCodes HTTP {exc.code}{suffix}{retry_note}：{raw_error}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise UserError(f"WorldCodes 连接失败：{exc}；未自动重试，请先确认是否已计费") from exc
    response_request_id = request_id(response.headers)
    try:
        with response:
            raw = response.read()
    except (HTTPException, OSError) as exc:
        suffix = f"，request_id={response_request_id}" if response_request_id else ""
        raise CompletedRequestError(
            f"WorldCodes HTTP 2xx 响应读取中断{suffix}；请勿盲目重试",
            response_request_id,
        ) from exc
    return raw, response_request_id


def parse_api_payload(
    raw: bytes, api_key: str, response_request_id: str | None
) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        snippet = redact(raw[:500].decode("utf-8", errors="replace"), api_key)
        suffix = f"，request_id={response_request_id}" if response_request_id else ""
        raise UserError(f"API 返回的不是有效 JSON{suffix}：{snippet}") from exc
    if not isinstance(payload, dict):
        raise UserError("API JSON 响应不是对象")
    if payload.get("error"):
        error_text = redact(json.dumps(payload["error"], ensure_ascii=False), api_key)
        suffix = f"，request_id={response_request_id}" if response_request_id else ""
        raise UserError(f"API 返回错误{suffix}：{error_text}")
    return payload


def decode_base64(value: str) -> bytes:
    if value.startswith("data:"):
        try:
            value = value.split(",", 1)[1]
        except IndexError as exc:
            raise UserError("API 返回了无效的 data URL") from exc
    compact = re.sub(r"\s+", "", value)
    compact += "=" * (-len(compact) % 4)
    try:
        return base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UserError("API 返回的 b64_json 无法解码") from exc


def download_image(url: str, timeout: float) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise UserError("API 返回了无效图片 URL")
    if parsed.scheme == "http" and parsed.hostname not in LOOPBACK_HOSTS:
        raise UserError("API 返回的远程图片 URL 未使用 HTTPS")
    request = Request(url, headers={"User-Agent": "generate-worldcodes-image/1.0"})
    try:
        response = NO_REDIRECT_OPENER.open(request, timeout=timeout)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise UserError(f"下载 API 返回的图片 URL 失败：{exc}") from exc
    try:
        with response:
            return response.read()
    except (HTTPException, OSError) as exc:
        raise UserError(f"下载 API 返回的图片 URL 响应不完整：{exc}") from exc


def extract_images(payload: dict[str, Any], timeout: float) -> list[bytes]:
    raw_items: list[Any]
    if isinstance(payload.get("data"), list):
        raw_items = payload["data"]
    elif isinstance(payload.get("b64_json"), str):
        raw_items = [payload]
    else:
        raw_items = []

    images: list[bytes] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("b64_json"), str):
            images.append(decode_base64(item["b64_json"]))
        elif isinstance(item.get("url"), str):
            images.append(download_image(item["url"], timeout))
    if not images:
        raise UserError("API 响应中没有 b64_json 或图片 URL")
    return images


def png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 45 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise UserError("API 返回的 PNG 结构无效")
    offset = 8
    width = height = bit_depth = color_type = interlace = 0
    saw_ihdr = saw_idat = saw_iend = saw_plte = idat_ended = False
    idat_chunks: list[bytes] = []
    while offset + 12 <= len(data):
        chunk_length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + chunk_length
        chunk_end = data_end + 4
        if chunk_end > len(data):
            raise UserError("API 返回的 PNG 数据被截断")
        chunk_data = data[data_start:data_end]
        expected_crc = int.from_bytes(data[data_end:chunk_end], "big")
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise UserError("API 返回的 PNG CRC 校验失败")
        if not saw_ihdr:
            if chunk_type != b"IHDR" or chunk_length != 13:
                raise UserError("API 返回的 PNG 缺少合法 IHDR")
            width = int.from_bytes(chunk_data[0:4], "big")
            height = int.from_bytes(chunk_data[4:8], "big")
            bit_depth = chunk_data[8]
            color_type = chunk_data[9]
            if chunk_data[10] != 0 or chunk_data[11] != 0:
                raise UserError("API 返回的 PNG 压缩或过滤方法无效")
            interlace = chunk_data[12]
            if interlace not in {0, 1}:
                raise UserError("API 返回的 PNG 隔行模式无效")
            saw_ihdr = True
        elif chunk_type == b"IHDR":
            raise UserError("API 返回的 PNG 包含重复 IHDR")
        if saw_idat and chunk_type != b"IDAT":
            idat_ended = True
        if chunk_type == b"PLTE":
            if (
                saw_plte
                or saw_idat
                or color_type in {0, 4}
                or chunk_length == 0
                or chunk_length % 3
                or chunk_length > 768
                or (color_type == 3 and bit_depth <= 8 and chunk_length // 3 > 2**bit_depth)
            ):
                raise UserError("API 返回的 PNG 调色板无效")
            saw_plte = True
        if chunk_type == b"IDAT":
            if idat_ended:
                raise UserError("API 返回的 PNG IDAT 分块不连续")
            saw_idat = True
            idat_chunks.append(chunk_data)
        if chunk_type == b"IEND":
            if chunk_length != 0 or chunk_end != len(data):
                raise UserError("API 返回的 PNG IEND 无效")
            saw_iend = True
            break
        offset = chunk_end
    if not (saw_ihdr and saw_idat and saw_iend) or width <= 0 or height <= 0:
        raise UserError("API 返回的 PNG 结构不完整")
    valid_depths = {
        0: {1, 2, 4, 8, 16},
        2: {8, 16},
        3: {1, 2, 4, 8},
        4: {8, 16},
        6: {8, 16},
    }
    if color_type not in valid_depths or bit_depth not in valid_depths[color_type]:
        raise UserError("API 返回的 PNG 色彩类型或位深无效")
    if color_type == 3 and not saw_plte:
        raise UserError("API 返回的索引 PNG 缺少调色板")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    bits_per_pixel = channels * bit_depth
    if interlace == 0:
        passes = [(width, height)]
    else:
        passes = []
        for start_x, start_y, step_x, step_y in (
            (0, 0, 8, 8),
            (4, 0, 8, 8),
            (0, 4, 4, 8),
            (2, 0, 4, 4),
            (0, 2, 2, 4),
            (1, 0, 2, 2),
            (0, 1, 1, 2),
        ):
            pass_width = (
                (width - start_x + step_x - 1) // step_x
                if width > start_x
                else 0
            )
            pass_height = (
                (height - start_y + step_y - 1) // step_y
                if height > start_y
                else 0
            )
            if pass_width and pass_height:
                passes.append((pass_width, pass_height))
    row_layout: list[tuple[int, int]] = []
    expected_bytes = 0
    for pass_width, pass_height in passes:
        row_bytes = (pass_width * bits_per_pixel + 7) // 8
        row_layout.append((row_bytes, pass_height))
        expected_bytes += (row_bytes + 1) * pass_height
    compressed = b"".join(idat_chunks)
    try:
        decoder = zlib.decompressobj()
        inflated = decoder.decompress(compressed, expected_bytes + 1)
        if decoder.unconsumed_tail or len(inflated) > expected_bytes:
            raise UserError("API 返回的 PNG 解压数据超出预期")
        if len(inflated) < expected_bytes:
            inflated += decoder.flush(expected_bytes - len(inflated) + 1)
    except zlib.error as exc:
        raise UserError("API 返回的 PNG IDAT 无法解压") from exc
    if (
        len(inflated) != expected_bytes
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise UserError("API 返回的 PNG 像素数据不完整")
    inflated_offset = 0
    for row_bytes, row_count in row_layout:
        for _ in range(row_count):
            if inflated[inflated_offset] > 4:
                raise UserError("API 返回的 PNG 行过滤器无效")
            inflated_offset += row_bytes + 1
    return width, height


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    start_of_frame = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    if not data.startswith(b"\xff\xd8"):
        raise UserError("API 返回的 JPEG 缺少 SOI")
    index = 2
    dimensions: tuple[int, int] | None = None
    frame_marker: int | None = None
    frame_components: set[int] = set()
    in_scan = False
    saw_scan = False
    scan_data_bytes = 0
    while index < len(data):
        if in_scan:
            marker_offset = data.find(b"\xff", index)
            if marker_offset < 0:
                break
            scan_data_bytes += marker_offset - index
            index = marker_offset
        elif data[index] != 0xFF:
            raise UserError("API 返回的 JPEG 标记结构无效")
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            break
        marker = data[index]
        index += 1
        if marker == 0x00:
            if not in_scan:
                raise UserError("API 返回的 JPEG 包含非法填充字节")
            scan_data_bytes += 1
            continue
        if marker in range(0xD0, 0xD8):
            if not in_scan:
                raise UserError("API 返回的 JPEG 重启标记位置无效")
            continue
        if marker == 0xD9:
            if not (dimensions and saw_scan and scan_data_bytes) or index != len(data):
                raise UserError("API 返回的 JPEG EOI 位置无效")
            return dimensions
        if in_scan:
            in_scan = False
        if marker == 0x01:
            continue
        if marker == 0xD8:
            raise UserError("API 返回的 JPEG 包含重复 SOI")
        if index + 2 > len(data):
            break
        segment_length = int.from_bytes(data[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            break
        if marker in start_of_frame:
            if dimensions:
                raise UserError("API 返回的 JPEG 包含重复 SOF")
            if segment_length < 11:
                raise UserError("API 返回的 JPEG SOF 结构无效")
            precision = data[index + 2]
            if precision not in {8, 12}:
                raise UserError("API 返回的 JPEG 采样精度无效")
            component_count = data[index + 7]
            if not 1 <= component_count <= 4 or segment_length != 8 + 3 * component_count:
                raise UserError("API 返回的 JPEG SOF 分量无效")
            components: set[int] = set()
            for component_index in range(component_count):
                component_offset = index + 8 + 3 * component_index
                component_id = data[component_offset]
                sampling = data[component_offset + 1]
                quantization_table = data[component_offset + 2]
                horizontal, vertical = sampling >> 4, sampling & 0x0F
                if (
                    component_id in components
                    or not 1 <= horizontal <= 4
                    or not 1 <= vertical <= 4
                    or quantization_table > 3
                ):
                    raise UserError("API 返回的 JPEG SOF 分量参数无效")
                components.add(component_id)
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            if width > 0 and height > 0:
                dimensions = (width, height)
                frame_marker = marker
                frame_components = components
            else:
                raise UserError("API 返回的 JPEG 尺寸无效")
        if marker == 0xDA:
            if not dimensions:
                raise UserError("API 返回的 JPEG 在 SOF 前出现 SOS")
            if segment_length < 8:
                raise UserError("API 返回的 JPEG SOS 结构无效")
            scan_components = data[index + 2]
            if not 1 <= scan_components <= 4 or segment_length != 6 + 2 * scan_components:
                raise UserError("API 返回的 JPEG SOS 分量无效")
            scan_component_ids: set[int] = set()
            for component_index in range(scan_components):
                component_offset = index + 3 + 2 * component_index
                component_id = data[component_offset]
                table_selectors = data[component_offset + 1]
                if (
                    component_id not in frame_components
                    or component_id in scan_component_ids
                    or table_selectors >> 4 > 3
                    or table_selectors & 0x0F > 3
                ):
                    raise UserError("API 返回的 JPEG SOS 分量引用无效")
                scan_component_ids.add(component_id)
            spectral_offset = index + 3 + 2 * scan_components
            spectral_start = data[spectral_offset]
            spectral_end = data[spectral_offset + 1]
            approximation = data[spectral_offset + 2]
            if (
                spectral_start > spectral_end
                or spectral_end > 63
                or approximation >> 4 > 13
                or approximation & 0x0F > 13
                or (
                    frame_marker == 0xC0
                    and (spectral_start, spectral_end, approximation) != (0, 63, 0)
                )
            ):
                raise UserError("API 返回的 JPEG SOS 扫描参数无效")
            saw_scan = True
            in_scan = True
        index += segment_length
    raise UserError("API 返回的 JPEG 缺少真实 EOI")


def webp_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 25 or int.from_bytes(data[4:8], "little") + 8 != len(data):
        raise UserError("API 返回的 WebP 结构无效")
    offset = 12
    chunks: list[tuple[bytes, bytes]] = []
    while offset + 8 <= len(data):
        chunk_type = data[offset : offset + 4]
        chunk_length = int.from_bytes(data[offset + 4 : offset + 8], "little")
        data_start = offset + 8
        data_end = data_start + chunk_length
        next_offset = data_end + (chunk_length % 2)
        if next_offset > len(data):
            raise UserError("API 返回的 WebP 数据被截断")
        chunks.append((chunk_type, data[data_start:data_end]))
        offset = next_offset
    if offset != len(data):
        raise UserError("API 返回的 WebP 分块无效")
    if not chunks:
        raise UserError("API 返回的 WebP 没有图像分块")

    def bitstream_dimensions(chunk_type: bytes, payload: bytes) -> tuple[int, int]:
        if (
            chunk_type == b"VP8L"
            and len(payload) >= 8
            and payload[0] == 0x2F
            and payload[4] >> 5 == 0
        ):
            b0, b1, b2, b3 = payload[1:5]
            width = 1 + b0 + ((b1 & 0x3F) << 8)
            height = 1 + (b1 >> 6) + (b2 << 2) + ((b3 & 0x0F) << 10)
        elif (
            chunk_type == b"VP8 "
            and len(payload) > 10
            and payload[0] & 1 == 0
            and payload[3:6] == b"\x9d\x01\x2a"
        ):
            first_partition_size = (
                (payload[0] >> 5) | (payload[1] << 3) | (payload[2] << 11)
            )
            if first_partition_size < 4 or len(payload) <= 10 + first_partition_size:
                raise UserError("API 返回的 WebP VP8 分区不完整")
            width = int.from_bytes(payload[6:8], "little") & 0x3FFF
            height = int.from_bytes(payload[8:10], "little") & 0x3FFF
        else:
            raise UserError("API 返回的 WebP 位流无效")
        if width <= 0 or height <= 0:
            raise UserError("API 返回的 WebP 尺寸无效")
        return width, height

    first_type, first_payload = chunks[0]
    bitstreams = [chunk for chunk in chunks if chunk[0] in {b"VP8 ", b"VP8L"}]
    if first_type == b"VP8X":
        if (
            len(first_payload) != 10
            or first_payload[0] & 0xC1
            or first_payload[1:4] != b"\x00\x00\x00"
            or not bitstreams
        ):
            raise UserError("API 返回的扩展 WebP 缺少实际图像位流")
        width = 1 + int.from_bytes(first_payload[4:7], "little")
        height = 1 + int.from_bytes(first_payload[7:10], "little")
        for bitstream_type, payload in bitstreams:
            if bitstream_dimensions(bitstream_type, payload) != (width, height):
                raise UserError("API 返回的 WebP 画布与位流尺寸不一致")
    elif first_type in {b"VP8 ", b"VP8L"}:
        width, height = bitstream_dimensions(first_type, first_payload)
    else:
        raise UserError("API 返回的 WebP 首分块无效")
    if width <= 0 or height <= 0:
        raise UserError("API 返回的 WebP 尺寸无效")
    return width, height


def inspect_output_image(data: bytes, expected_format: str) -> dict[str, Any]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        actual_format = "png"
        width, height = png_dimensions(data)
        has_alpha = data[25] in {4, 6}
    elif data.startswith(b"\xff\xd8\xff"):
        actual_format = "jpeg"
        width, height = jpeg_dimensions(data)
        has_alpha = False
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        actual_format = "webp"
        width, height = webp_dimensions(data)
        has_alpha = False
        offset = 12
        while offset + 8 <= len(data):
            chunk_type = data[offset : offset + 4]
            chunk_length = int.from_bytes(data[offset + 4 : offset + 8], "little")
            payload_start = offset + 8
            payload_end = payload_start + chunk_length
            payload = data[payload_start:payload_end]
            if chunk_type == b"ALPH":
                has_alpha = True
            elif chunk_type == b"VP8X" and payload and payload[0] & 0x10:
                has_alpha = True
            elif chunk_type == b"VP8L" and len(payload) >= 5 and payload[4] & 0x10:
                has_alpha = True
            offset = payload_end + (chunk_length % 2)
    else:
        raise UserError("API 返回的内容不是有效 PNG、JPEG 或 WebP 图片")
    if width <= 0 or height <= 0:
        raise UserError("API 返回的图片尺寸无效")
    if actual_format != expected_format:
        raise UserError(
            f"API 返回格式为 {actual_format}，与请求的 {expected_format} 不一致"
        )
    return {
        "format": actual_format,
        "width": width,
        "height": height,
        "has_alpha": has_alpha,
    }


def output_paths(
    output: Path, count: int, output_format: str, overwrite: bool
) -> list[Path]:
    extension = FORMAT_EXTENSIONS[output_format]
    output_text = str(output)
    directory_mode = (
        output_text.endswith((os.sep, "/"))
        or (output.exists() and output.is_dir())
        or (not output.exists() and not output.suffix)
    )
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    unique_suffix = uuid4().hex[:8]
    paths: list[Path] = []
    if directory_mode:
        for index in range(count):
            suffix = f"-{index + 1:02d}" if count > 1 else ""
            paths.append(
                output
                / f"worldcodes-image-{timestamp}-{unique_suffix}{suffix}{extension}"
            )
    else:
        valid_extensions = {extension}
        if output_format == "jpeg":
            valid_extensions.add(".jpeg")
        if output.suffix.lower() not in valid_extensions:
            raise UserError(
                f"输出扩展名与 {output_format} 不一致；应使用 "
                f"{'/'.join(sorted(valid_extensions))}"
            )
        for index in range(count):
            path = output
            if count > 1:
                path = output.with_name(f"{output.stem}-{index + 1:02d}{output.suffix}")
            paths.append(path)
    if not overwrite:
        existing = [str(path) for path in paths if path.exists()]
        if existing:
            raise UserError(f"输出文件已存在；使用 --overwrite 才可覆盖：{', '.join(existing)}")
    return [path.absolute() for path in paths]


def prepare_output_directories(paths: list[Path]) -> None:
    for parent in {path.parent for path in paths}:
        parent.mkdir(parents=True, exist_ok=True)
        probe = parent / f".worldcodes-write-test-{uuid4().hex}"
        try:
            with probe.open("xb"):
                pass
        finally:
            if probe.exists():
                probe.unlink()


def write_image(path: Path, image_bytes: bytes, overwrite: bool) -> None:
    if not overwrite:
        try:
            descriptor = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666
            )
        except FileExistsError as exc:
            raise UserError(f"输出文件已存在：{path}") from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(image_bytes)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            if path.exists():
                path.unlink()
            raise
        return

    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(image_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    args = parse_args()
    saved: list[str] = []
    image_records: list[dict[str, Any]] = []
    request_ids: list[str] = []
    warnings: list[str] = []
    completed_http_requests = 0
    current_output: str | None = None
    try:
        base_url, size = validate_args(args)
        paths = output_paths(args.output, args.count, args.output_format, args.overwrite)
        mode = "edit" if args.image else "generate"
        endpoint = f"{base_url}/images/{'edits' if args.image else 'generations'}"
        fields = request_fields(args, size)

        if args.dry_run:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "mode": mode,
                        "endpoint": endpoint,
                        "fields": fields,
                        "image": str(args.image.resolve()) if args.image else None,
                        "mask": str(args.mask.resolve()) if args.mask else None,
                        "outputs": [str(path) for path in paths],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        api_key = os.environ.get(KEY_ENV, "").strip()
        if not api_key:
            raise UserError(
                f"缺少环境变量 {KEY_ENV}；请在运行环境中安全设置，勿把 Key 写进命令或 Skill"
            )
        prepare_output_directories(paths)

        for index, path in enumerate(paths):
            current_output = str(path)
            if args.image:
                body, content_type = build_multipart(fields, args.image, args.mask)
            else:
                body = json.dumps(fields, ensure_ascii=False).encode("utf-8")
                content_type = "application/json"
            raw, response_request_id = post_request(
                endpoint, body, content_type, api_key, args.timeout
            )
            completed_http_requests += 1
            if response_request_id:
                request_ids.append(response_request_id)
            payload = parse_api_payload(raw, api_key, response_request_id)
            images = extract_images(payload, args.timeout)
            if len(images) != 1:
                raise UserError(
                    f"第 {index + 1} 次请求返回 {len(images)} 张图片；脚本预期 n=1，未写盘"
                )
            metadata = inspect_output_image(images[0], args.output_format)
            write_image(path, images[0], args.overwrite)
            saved.append(str(path))
            image_records.append({"path": str(path), **metadata})
            if size != "auto":
                expected_width, expected_height = map(int, size.split("x"))
                if (metadata["width"], metadata["height"]) != (
                    expected_width,
                    expected_height,
                ):
                    warnings.append(
                        f"{path.name} 实际尺寸为 {metadata['width']}x{metadata['height']}，"
                        f"与请求的 {size} 不一致"
                    )
            current_output = None

        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": mode,
                    "model": args.model,
                    "size": size,
                    "quality": args.quality,
                    "files": saved,
                    "images": image_records,
                    "request_ids": request_ids,
                    "warnings": warnings,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (UserError, OSError) as exc:
        if isinstance(exc, CompletedRequestError):
            completed_http_requests += 1
            if (
                exc.response_request_id
                and exc.response_request_id not in request_ids
            ):
                request_ids.append(exc.response_request_id)
        error: dict[str, Any] = {"ok": False, "error": str(exc)}
        if completed_http_requests:
            error["completed_http_requests"] = completed_http_requests
            error["billing_warning"] = "已有请求收到 HTTP 2xx，可能已计费；请勿盲目重试"
        if request_ids:
            error["request_ids"] = request_ids
        if saved:
            error["files"] = saved
        if current_output:
            error["current_output"] = current_output
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
