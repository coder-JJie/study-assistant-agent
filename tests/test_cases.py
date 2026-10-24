# -*- coding: utf-8 -*-
"""
tests/test_cases.py — 端到端自测（逐项验证课程的三个 must-have）

运行：
    python tests/test_cases.py

覆盖：
    A 工具级   直接调用 mcp_server 里三个技能的纯逻辑实现（技能 ≥2 个）
    B 协议级   通过真实 MCP(stdio) 协议发现并调用工具（上下文集成）
    C 循环级   mock 模式下编排循环完整跑通：工具调用 → 结果回填 → 最终回答
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows 控制台默认 GBK，强制 UTF-8 输出避免打印 emoji/中文报错
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream and getattr(_stream, "encoding", "") and "utf" not in _stream.encoding.lower():
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    flag = "✅" if ok else "❌"
    print(f"{flag} {name}" + (f" — {detail}" if detail else ""))


DEMO_PDF = PROJECT_ROOT / "data" / "sample_reading.pdf"
DEMO_CSV = PROJECT_ROOT / "data" / "courses.csv"


# ---------------------------------------------------------------- A. 工具级
def test_tools_direct() -> None:
    from mcp_server import _fetch_webpage_impl, _query_csv_impl, _summarize_pdf_impl

    if DEMO_PDF.exists():
        out = _summarize_pdf_impl(str(DEMO_PDF), "zh", 2000)
        check("A1 summarize_pdf 直接调用", "抽取的正文" in out and len(out) > 100, out.splitlines()[0][:70])
    else:
        check("A1 summarize_pdf 直接调用", False, "缺少 data/sample_reading.pdf")

    if DEMO_CSV.exists():
        out = _query_csv_impl(str(DEMO_CSV), "周一")
        check("A2 query_csv 直接调用（关键词筛选）", "高等数学" in out, out.splitlines()[0])
    else:
        check("A2 query_csv 直接调用（关键词筛选）", False, "缺少 data/courses.csv")

    # 用肯定连不通的地址验证错误分支（离线环境也不阻塞）
    out = _fetch_webpage_impl("http://127.0.0.1:9/nope", 200)
    check("A3 fetch_webpage 错误分支安全返回", "抓取网页失败" in out, out[:60])


# ------------------------------------------------- B. 协议级（真实 MCP)
async def test_mcp_protocol() -> None:
    from mcp_client import MCPClient

    async with MCPClient() as client:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        check("B1 通过 MCP 发现工具（≥3 个技能）", len(tools) >= 3, f"发现: {', '.join(names)}")

        funcs = client.tools_to_functions(tools)
        ok_schema = all(
            f.get("type") == "function" and "parameters" in f.get("function", {})
            for f in funcs
        )
        check("B2 MCP schema 桥接为 OpenAI function calling", ok_schema)

        if DEMO_PDF.exists():
            out = await client.call_tool("summarize_pdf", {"file_path": str(DEMO_PDF)})
            check("B3 通过 MCP 协议调用 summarize_pdf", out.startswith("文档:"), out.splitlines()[0][:60])
        if DEMO_CSV.exists():
            out = await client.call_tool("query_csv", {"file_path": str(DEMO_CSV), "question": "周四"})
            check("B4 通过 MCP 协议调用 query_csv", "计算机网络" in out, out.splitlines()[0])

        out = await client.call_tool("fetch_webpage", {"url": "http://127.0.0.1:9/x"})
        check("B5 通过 MCP 协议调用 fetch_webpage（错误分支）", "抓取网页失败" in out, out[:60])


# -------------------------------------------------------------- C. 循环级
async def test_agent_loop_mock() -> None:
    from agent import run_agent

    if not DEMO_PDF.exists():
        check("C1 mock 编排循环（PDF）", False, "缺演示 PDF")
        return

    answer, log = await run_agent(f"请总结这份 PDF：{DEMO_PDF}", backend="mock", return_log=True)
    loop_ok = any("调用工具 summarize_pdf" in line for line in log)
    check(
        "C1 mock 编排循环（PDF：调用→回填→最终回答）",
        loop_ok and bool(answer) and "mock 模式的最终回答" in answer,
        "; ".join(log[:2]).replace("\n", " ")[:90],
    )

    answer2, log2 = await run_agent(f"请查询 CSV {DEMO_CSV}：周四有哪些课？", backend="mock", return_log=True)
    check(
        "C2 mock 编排循环（CSV：工具调用→回填→最终回答）",
        any("调用工具 query_csv" in line for line in log2) and bool(answer2),
        "; ".join(log2[:2]).replace("\n", " ")[:90],
    )


# ------------------------------------------------- D. 动态读取环境变量
async def test_dynamic_env_key() -> None:
    """网页运行中才填 Key 也能被识别（回归测试，修复"导入时读死 Key"的 bug）。"""
    import agent as agent_mod

    old = os.environ.get("LLM_API_KEY")
    os.environ["LLM_API_KEY"] = "sk-fake-for-test"
    try:
        outcome: str
        try:
            # 假 Key 会走 openai 分支并快速失败/超时——正好证明不再落到 mock
            outcome = await asyncio.wait_for(
                agent_mod.run_agent("你好", backend="auto", verbose=False), timeout=15
            )
        except TimeoutError:
            outcome = "（openai 分支尝试联网超时，说明已识别到 Key 并进入 openai 后端）"
        except Exception as exc:  # noqa: BLE001 —— 鉴权/网络错误均属"已识别 Key"
            outcome = type(exc).__name__
        bad = any(k in str(outcome) for k in ("（mock", "未检测到 LLM_API_KEY"))
        check("D1 运行中填入的 API Key 能被动态识别（不再误判为 mock）", not bad, str(outcome)[:70])
    finally:
        if old is None:
            os.environ.pop("LLM_API_KEY", None)
        else:
            os.environ["LLM_API_KEY"] = old


def main() -> int:
    print("=" * 60)
    print(" 学习资料助理 · 端到端自测")
    print("=" * 60)
    print("\n[A] 工具级（三个技能的直接逻辑）")
    test_tools_direct()
    print("\n[B] 协议级（真实 MCP stdio 链接）")
    asyncio.run(test_mcp_protocol())
    print("\n[C] 循环级（mock 编排循环）")
    asyncio.run(test_agent_loop_mock())
    print("\n[D] 配置读取（动态识别 API Key）")
    asyncio.run(test_dynamic_env_key())

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"结果: {passed}/{total} 通过")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"   ❌ {name} — {detail}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
