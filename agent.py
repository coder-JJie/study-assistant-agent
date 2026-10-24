# -*- coding: utf-8 -*-
"""
agent.py — 「学习资料助理」的编排循环（本项目的核心工作之一，自己写的部分）

流程（orchestration loop）：
    用户消息 → LLM（夹带 MCP 工具 schema）
    → 模型决定"直接回答 或 调用工具"
    → 需要工具时通过 mcp_client 走 MCP 协议执行
    → 工具结果回填给模型
    → 循环直到模型给出最终答案（最多 AGENT_MAX_ROUNDS 轮）

两种后端：
    openai : 调用真实 LLM API（DeepSeek / 通义 / Kimi 等 OpenAI 兼容接口）
    mock   : 没有 API Key 也能演示循环——用规则模拟模型的"工具调用决策"

用法：
    python agent.py                # 交互式问答
    python agent.py --once "问题"   # 单次问答
    python agent.py --backend mock  # 强制 mock 演示模式
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from mcp_client import MCPClient
from prompt import SYSTEM_PROMPT

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")  # 显式指定 .env 路径，与运行目录无关（PyCharm 友好）

# Windows 控制台默认 GBK，强制 UTF-8 输出避免打印中文/emoji 报错
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream and getattr(_stream, "encoding", "") and "utf" not in _stream.encoding.lower():
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

# 注意：以下三项在每次调用时动态读取，不缓存模块级常量——
# 这样 Streamlit 网页里填的 Key（运行时才写进 os.environ 的）也能被识别到。
# （旧写法 API_KEY = os.getenv(...) 在 import 时读死，导致网页填了 Key 仍被判定为"未检测到"。）

def _env_api_key() -> str:
    return (os.getenv("LLM_API_KEY") or "").strip()


def _env_api_base() -> str:
    return (os.getenv("LLM_API_BASE") or "https://api.deepseek.com/v1").strip().rstrip("/")


def _env_model() -> str:
    return os.getenv("LLM_MODEL", "deepseek-chat")


MAX_ROUNDS = max(1, int(os.getenv("AGENT_MAX_ROUNDS", "6")))

# ---------------------------------------------------------------------------
# mock 后端：无 Key 时模拟"模型决定调用哪个工具"，让编排循环可离线演示
# ---------------------------------------------------------------------------


def _find_pdf(text: str) -> str:
    """从用户话里找 .pdf 路径，找不到就用演示 PDF。"""
    for tok in re.split(r"[\s，。！？；、,]", text):
        if tok.lower().endswith(".pdf") and "." in tok:
            cand = Path(tok.strip("\"'"))
            if not cand.exists():
                cand = PROJECT_ROOT / tok.strip("\"'")
            return str(cand) if cand.exists() else str(PROJECT_ROOT / "data" / "sample_reading.pdf")
    return str(PROJECT_ROOT / "data" / "sample_reading.pdf")


def _find_url(text: str) -> str:
    m = re.search(r"https?://[^\s，。！？）)】\"]+", text)
    return m.group(0) if m else "https://example.com"


def _find_csv(text: str) -> str:
    for tok in re.split(r"[\s，。！？；、,]", text):
        if tok.lower().endswith(".csv") and "." in tok:
            cand = Path(tok.strip("\"'"))
            if not cand.exists():
                cand = PROJECT_ROOT / tok.strip("\"'")
            return str(cand) if cand.exists() else str(PROJECT_ROOT / "data" / "courses.csv")
    return str(PROJECT_ROOT / "data" / "courses.csv")


def _mock_respond(user_input: str, round_index: int, last_tool_output: Optional[str]) -> dict[str, Any]:
    """规则版"模型"：第一轮按关键词决定调哪个工具，之后基于工具结果给最终回答。"""
    if round_index > 1:
        tail = (last_tool_output or "").replace("\n", " ")[:300]
        return {
            "role": "assistant",
            "content": (
                "（mock 模式的最终回答，模拟模型基于工具结果给出总结；"
                "在 .env 配置 LLM_API_KEY 后可获得真实模型的总结。）\n"
                f"上一步工具返回的关键内容：{tail}"
            ),
        }

    low = user_input.lower()
    if any(k in low for k in (".pdf", " pdf", "pdf ")) or "pdf" in low:
        tool, args = "summarize_pdf", {"file_path": _find_pdf(user_input)}
    elif "http" in low:
        tool, args = "fetch_webpage", {"url": _find_url(user_input)}
    elif any(k in low for k in ("csv", "课表", "课程表", "成绩")):
        tool, args = "query_csv", {"file_path": _find_csv(user_input), "question": user_input}
    else:
        return {
            "role": "assistant",
            "content": (
                "（mock 模式的回答）没有检测到需要调用外部技能的需求——PDF、网页、CSV 三个技能都用不上。"
                "配置 LLM_API_KEY 后可以用真实模型回答。"
            ),
        }
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"mock_call_{round_index}",
                "type": "function",
                "function": {"name": tool, "arguments": json.dumps(args, ensure_ascii=False)},
            }
        ],
    }


# ---------------------------------------------------------------------------
# openai 后端：真实 LLM API（OpenAI 兼容接口）
# ---------------------------------------------------------------------------


def _openai_complete(messages: list[dict], tools: list[dict]) -> dict:
    from openai import OpenAI

    # 每次调用动态读取，兼容"网页运行中才填 Key"的场景
    api_key = _env_api_key()
    api_base = _env_api_base()
    model = _env_model()

    client = OpenAI(api_key=api_key, base_url=api_base)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools or None,
        temperature=0.2,
    )
    choice = resp.choices[0].message
    tool_calls = None
    if getattr(choice, "tool_calls", None):
        tool_calls = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                },
            }
            for tc in choice.tool_calls
        ]
    return {"role": "assistant", "content": choice.content, "tool_calls": tool_calls}


# ---------------------------------------------------------------------------
# 编排循环（core）
# ---------------------------------------------------------------------------


async def run_agent(
    user_input: str,
    backend: str = "auto",
    verbose: bool = True,
    return_log: bool = False,
):
    """
    执行一轮完整的编排循环，返回最终回答（return_log=True 时返回 (回答, 日志)）。

    backend: auto / openai / mock
    """
    backend = (backend or "auto").lower()
    api_key = _env_api_key()
    if backend == "auto":
        backend = "openai" if api_key else "mock"

    log: list[str] = []

    def say(msg: str) -> None:
        log.append(msg)
        if verbose:
            print(msg, file=sys.stderr)

    if backend == "mock":
        if api_key:
            say("[提示] 后端被手动设为 mock，不会调用真实模型（即使已配置 Key）。如需真实模型，请把后端改为 auto 或 openai。")
        else:
            say("[提示] 未检测到 LLM_API_KEY，使用 mock 后端演示编排循环（不调用真实模型）。")
    elif not api_key:
        raise RuntimeError("backend=openai 但未设置 LLM_API_KEY（请在 .env 中填写或设环境变量）")
    else:
        say(f"[后端] openai（{_env_model()} @ {_env_api_base()}）")

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]

    async with MCPClient() as client:
        tools = await client.list_tools()
        functions = client.tools_to_functions(tools)
        say(f"[MCP] 已连接技能服务器，发现 {len(tools)} 个工具：{', '.join(t.name for t in tools)}")

        last_tool_output: Optional[str] = None
        for rnd in range(1, MAX_ROUNDS + 1):
            if backend == "openai":
                message = _openai_complete(messages, functions)
            else:
                message = _mock_respond(user_input, rnd, last_tool_output)
            messages.append({k: v for k, v in message.items() if v is not None})

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                answer = message.get("content") or "（模型没有返回内容）"
                say(f"[第{rnd}轮] 模型直接回答，不再调用工具，循环结束。")
                return (answer, log) if return_log else answer

            for call in tool_calls:
                name = call["function"]["name"]
                try:
                    arguments = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                say(f"[第{rnd}轮] 模型决定调用工具 {name}，参数：{json.dumps(arguments, ensure_ascii=False)}")
                result = await client.call_tool(name, arguments)
                last_tool_output = result
                say(f"[第{rnd}轮] 工具 {name} 返回 {len(result)} 字符，已回填给模型。")
                messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": result}
                )

    answer = "（已达到最大工具轮数，模型仍未给出最终答案。请简化问题或调大 AGENT_MAX_ROUNDS。）"
    return (answer, log) if return_log else answer


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    backend = "auto"
    question_once: Optional[str] = None

    if "--backend" in args:
        i = args.index("--backend")
        backend = args[i + 1]
        del args[i : i + 2]
    if "--once" in args:
        i = args.index("--once")
        question_once = args[i + 1]
        del args[i : i + 2]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    if question_once is not None:
        answer = asyncio.run(run_agent(question_once, backend=backend))
        print(answer)
        return

    print("=" * 56)
    print(" 学习资料助理 Agent（MCP + Function Calling）")
    print(f" 后端: {backend} | 模型: {_env_model()} | 最大工具轮数: {MAX_ROUNDS}")
    print(" 示例：请总结 data/sample_reading.pdf")
    print(" 示例：data/courses.csv 里周一有哪些课？")
    print(" 输入 q / exit 退出")
    print("=" * 56)
    while True:
        try:
            question = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见 👋")
            break
        if not question:
            continue
        if question.lower() in {"q", "exit", "quit", "退出"}:
            break
        try:
            answer = asyncio.run(run_agent(question, backend=backend))
            print(f"\n助手> {answer}")
        except Exception as exc:  # noqa: BLE001
            print(f"\n[出错] {exc}")


if __name__ == "__main__":
    main()
