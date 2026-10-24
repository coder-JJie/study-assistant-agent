# -*- coding: utf-8 -*-
"""
mcp_server.py — 「学习资料助理」的 MCP Server（样板代码，按氛围编程约束由 AI 生成）

通过 Model Context Protocol (MCP) 把三个"技能"暴露给 Agent 的大脑：

  技能1  summarize_pdf : 解析本地 PDF，抽取正文文本（供模型生成摘要/读书笔记）
  技能2  fetch_webpage : 抓取网页正文并提取标题与要点
  技能3  query_csv     : 查询本地 CSV（课程表 / 成绩单等）

参数的 Pydantic 模型（"The Pydantic models for function arguments"）：
  - 注册签名用平铺参数 + pydantic Field/Annotated 描述，MCP SDK 会据此自动
    生成参数 JSON Schema 并做运行时校验；
  - 每个工具入口再用下方显式定义的 Pydantic BaseModel（SummarizePdfArgs /
    FetchWebpageArgs / QueryCsvArgs）做二次校验，双保险，也便于单测复用。

本文件基于 mcp SDK 2.x（MCPServer，FastMCP 在 2.x 中被更名为 MCPServer）。
无需直接手动运行它，agent.py / mcp_client.py 会自动通过 stdio 拉起本进程；
单独运行亦可验证：
    python mcp_server.py
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from mcp.server import MCPServer
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# MCP 服务器实例
# ---------------------------------------------------------------------------
mcp = MCPServer(
    "study-assistant",
    instructions=(
        "学习资料助理的本地技能服务器：负责解析本地 PDF、抓取网页、查询 CSV。"
        "工具只返回原始资料文本，不负责总结——总结由 Agent 大脑（LLM）完成。"
    ),
)

MAX_TEXT_CHARS = 6000  # 单次回填给模型的最大字符数，防止上下文爆炸

# ---------------------------------------------------------------------------
# 通用辅助函数（AI 生成的工具代码）
# ---------------------------------------------------------------------------


def _clean_text(text: str) -> str:
    """清洗抽取出的原始文本：合并空行、去掉多余空白。"""
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _truncate(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    """超长内容截断，避免塞爆模型上下文。"""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n……（内容过长，共 {len(text)} 字符，已截断到前 {limit} 字符）"


# ---------------------------------------------------------------------------
# 技能1：summarize_pdf — 解析本地 PDF
# ---------------------------------------------------------------------------


class SummarizePdfArgs(BaseModel):
    """summarize_pdf 的参数模型（函数入口处用它对入参做 Pydantic 校验）。"""

    file_path: str = Field(description="本地 PDF 文件的路径（绝对或相对路径）")
    language: str = Field(
        default="zh",
        description="希望输出的语言：zh（中文）或 en（英文），默认 zh",
    )


def _summarize_pdf_impl(file_path: str, language: str, max_chars: int) -> str:
    """summarize_pdf 的纯逻辑实现，便于单元测试直接调用。"""
    path = Path(file_path)
    if not path.exists():
        return f"文件不存在：{path}"

    try:
        import pymupdf  # PyMuPDF（2.x 推荐用 pymupdf 命名导入）
    except ImportError:
        return "缺少依赖 PyMuPDF，请先执行: pip install PyMuPDF"

    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:  # noqa: BLE001
        return f"无法打开 PDF（可能已损坏或不是有效 PDF）：{exc}"

    page_texts = [page.get_text() for page in doc]
    total_pages = len(page_texts)
    doc.close()

    raw = _clean_text("\n".join(page_texts))
    if len(raw) < 50:
        return (
            f"该 PDF 共 {total_pages} 页，但抽取到的文字只有 {len(raw)} 个字符——"
            "这通常是扫描版/图片型 PDF（没有文字层），需要 OCR 才能处理，建议换用带文字层的 PDF。"
        )

    return (
        f"文档: {path.name} | 页数: {total_pages} | 正文约 {len(raw)} 字符 | 输出语言: {language}\n\n"
        f"===== 抽取的正文（供总结使用）=====\n{_truncate(raw, max_chars)}"
    )


@mcp.tool(
    name="summarize_pdf",
    description=(
        "解析本地 PDF 文档并抽取正文文本，供 Agent 生成摘要与读书笔记。"
        "调用前需要用户提供本地 PDF 文件的路径。"
    ),
)
def summarize_pdf(
    file_path: Annotated[str, Field(description="本地 PDF 文件的路径（绝对或相对路径）")],
    language: Annotated[str, Field(description="希望输出的语言：zh（中文）或 en（英文）")] = "zh",
) -> str:
    """解析本地 PDF 文档并抽取正文文本。

    注意：注册给 MCP 的是平铺签名（SDK 会据此自动生成 Pydantic 参数模型与
    JSON Schema）；入口处再用显式 Pydantic 模型做一次参数校验，双保险。
    """
    args = SummarizePdfArgs(file_path=file_path, language=language)
    return _summarize_pdf_impl(args.file_path, args.language, MAX_TEXT_CHARS)


# ---------------------------------------------------------------------------
# 技能2：fetch_webpage — 抓取网页
# ---------------------------------------------------------------------------


class FetchWebpageArgs(BaseModel):
    """fetch_webpage 的参数模型。"""

    url: str = Field(description="要抓取的网页完整 URL，例如 https://example.com/page")
    max_chars: int = Field(
        default=MAX_TEXT_CHARS,
        description="返回正文的最大字符数，默认 6000",
    )


def _fetch_webpage_impl(url: str, max_chars: int) -> str:
    """fetch_webpage 的纯逻辑实现，便于单元测试直接调用。"""
    import httpx
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36 study-assistant-agent/1.0"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return f"抓取网页失败：{exc}（请检查网络、URL 是否正确，或目标站点是否设置了反爬）"

    # 用原始字节交给 BeautifulSoup 自动识别编码（对中文 GBK 页面更稳）
    soup = BeautifulSoup(response.content, "html.parser")
    for tag in soup(
        ["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe"]
    ):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else url
    body = _clean_text(soup.get_text("\n", strip=True))
    if not body:
        body = "（页面正文为空：可能是动态渲染页面，需要浏览器渲染引擎才能提取内容。）"

    return f"标题: {title}\n来源 URL: {url}\n\n===== 网页正文 =====\n{_truncate(body, max_chars)}"


@mcp.tool(
    name="fetch_webpage",
    description="抓取指定 URL 的网页，提取标题与清洗后的正文文本，供 Agent 提炼要点。",
)
def fetch_webpage(
    url: Annotated[str, Field(description="要抓取的网页完整 URL，例如 https://example.com/page")],
    max_chars: Annotated[int, Field(description="返回正文的最大字符数，默认 6000")] = MAX_TEXT_CHARS,
) -> str:
    """抓取指定 URL 的网页并提取正文文本。"""
    args = FetchWebpageArgs(url=url, max_chars=max_chars)
    return _fetch_webpage_impl(args.url, args.max_chars)


# ---------------------------------------------------------------------------
# 技能3：query_csv — 查询本地 CSV
# ---------------------------------------------------------------------------


class QueryCsvArgs(BaseModel):
    """query_csv 的参数模型。"""

    file_path: str = Field(description="本地 CSV 文件的路径（绝对或相对路径）")
    question: str = Field(description="用户想从数据中查询的内容，例如「周一有哪些课」")


def _query_csv_impl(file_path: str, question: str) -> str:
    """query_csv 的纯逻辑实现，便于单元测试直接调用。"""
    import pandas as pd

    path = Path(file_path)
    if not path.exists():
        return f"文件不存在：{path}"

    try:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001
        return f"读取 CSV 失败：{exc}"

    header = f"文件: {path.name} | 共 {len(df)} 行 | 列: {'、'.join(str(c) for c in df.columns)}"

    question = (question or "").strip()
    if not question or question in {"列出全部", "全部", "看看", "内容", "表格"}:
        body = df.head(20).to_string(index=False)
        note = "" if len(df) <= 20 else f"\n……（共 {len(df)} 行，仅显示前 20 行）"
        return f"{header}\n{body}{note}"

    # 简单关键词筛选：任一列包含问题关键词的那些行
    mask = df.apply(
        lambda row: row.astype(str).str.contains(question, case=False, regex=False).any(),
        axis=1,
    )
    matched = df[mask]
    if matched.empty:
        return (
            f"{header}\n在 {len(df)} 行数据中没有找到包含「{question}」的记录。"
            "（当前是简单的关键词筛选，更复杂的统计问题请把整张表内容回填给模型分析。）"
        )
    body = matched.head(30).to_string(index=False)
    note = "" if len(matched) <= 30 else f"\n……（匹配 {len(matched)} 行，仅显示前 30 行）"
    return f"{header}\n命中 {len(matched)} 行：\n{body}{note}"


@mcp.tool(
    name="query_csv",
    description="读取本地 CSV 文件并按关键词筛选数据，供 Agent 回答课表/成绩等表格问题。",
)
def query_csv(
    file_path: Annotated[str, Field(description="本地 CSV 文件的路径（绝对或相对路径）")],
    question: Annotated[str, Field(description="用户想从数据中查询的内容，例如「周一有哪些课」")],
) -> str:
    """读取本地 CSV 文件并按关键词筛选数据。"""
    args = QueryCsvArgs(file_path=file_path, question=question)
    return _query_csv_impl(args.file_path, args.question)


# ---------------------------------------------------------------------------
# 启动入口：stdio 传输，被 MCP 客户端（mcp_client.py / agent.py）拉起
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
