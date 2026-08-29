"""网页抓取工具：文档查阅、错误搜索。"""

from __future__ import annotations

import re
import urllib.error
import urllib.request

from agent.permission import PermissionDenied, check_tool_permission
from agent.tools import ToolResult, tool

MAX_CONTENT = 16 * 1024  # 16KB text limit


@tool
def web_fetch(url: str, prompt: str = "") -> ToolResult:
    """获取网页内容并提取文本。用于文档查阅、错误信息搜索等。

    url: 完整的 URL（http 或 https）
    prompt: 提示信息，说明需要从页面提取什么（可选）
    """
    if not url.startswith(("http://", "https://")):
        return ToolResult(False, "Error: URL must start with http:// or https://")

    try:
        check_tool_permission("web_fetch", {"url": url})
    except PermissionDenied as e:
        return ToolResult(False, f"Permission denied: {e}")

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Megumin Agent)"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(256 * 1024)  # read max 256KB raw
    except urllib.error.HTTPError as e:
        return ToolResult(False, f"HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        return ToolResult(False, f"Error: {e.reason}")
    except TimeoutError:
        return ToolResult(False, "Error: Request timed out (30s).")
    except Exception as e:
        return ToolResult(False, f"Error: {e}")

    # Decode
    encoding = "utf-8"
    if "charset=" in content_type:
        match = re.search(r"charset=([\w-]+)", content_type)
        if match:
            encoding = match.group(1)

    try:
        text = raw.decode(encoding, errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = raw.decode("utf-8", errors="replace")

    # Strip HTML if needed
    if "html" in content_type.lower():
        text = _strip_html(text)

    # Truncate
    if len(text) > MAX_CONTENT:
        text = text[:MAX_CONTENT] + "\n\n... (truncated)"

    if prompt:
        header = f"[Fetched: {url}]\n[Extract: {prompt}]\n\n"
    else:
        header = f"[Fetched: {url}]\n\n"

    return ToolResult(True, header + text.strip())


def _strip_html(html: str) -> str:
    """简单 HTML 去标签，保留文本结构。"""
    # Remove script and style blocks
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Replace block-level tags with newlines
    html = re.sub(r"<(br|hr|p|div|h[1-6]|li|tr)[^>]*>", "\n", html, flags=re.IGNORECASE)
    # Remove all remaining tags
    html = re.sub(r"<[^>]+>", "", html)
    # Decode common entities
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html = html.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    # Collapse whitespace
    html = re.sub(r"\n{3,}", "\n\n", html)
    html = re.sub(r"[ \t]+", " ", html)
    return html.strip()
