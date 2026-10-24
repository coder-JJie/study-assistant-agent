# -*- coding: utf-8 -*-
"""
mcp_client.py — MCP 客户端与 function calling 桥接层（样板代码，按氛围编程约束由 AI 生成）

职责：
  1. 通过 MCP 的 stdio 传输协议拉起并连接 mcp_server.py；
  2. list_tools_as_dict()：把 MCP 工具 schema 转换为 OpenAI 兼容的
     function calling「tools」数组（这就是 Agent 大脑与本地工具之间的桥）；
  3. call_tool()：通过 MCP 协议调用服务器上的工具并汇总返回文本。

直接运行本文件会做一次端到端自测（连接 → 发现工具 → 真实调用工具）:
    python mcp_client.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SERVER_SCRIPT = str(PROJECT_ROOT / "mcp_server.py")

# Windows 控制台默认 GBK，强制 UTF-8 输出避免打印 emoji/中文报错
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream and getattr(_stream, "encoding", "") and "utf" not in _stream.encoding.lower():
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


class MCPClient:
    """封装一次 stdio MCP 会话，提供同步/异步两种调用方式。"""

    def __init__(
        self,
        server_script: str = DEFAULT_SERVER_SCRIPT,
        server_args: Optional[list[str]] = None,
    ) -> None:
        self.server_script = server_script
        self.server_args = server_args or []
        self._exit_stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    # ------------------------------------------------------------------ 异步
    async def connect(self) -> "MCPClient":
        """建立与 MCP server 的 stdio 连接（必须成对调用 close/异步上下文）。"""
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[self.server_script, *self.server_args],
            cwd=str(PROJECT_ROOT),
            env=None,  # 继承当前进程环境
        )
        stdio_transport = await self._exit_stack.enter_async_context(stdio_client(server_params))
        read_stream, write_stream = stdio_transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        self.session = session
        return self

    async def close(self) -> None:
        await self._exit_stack.aclose()
        self.session = None

    async def list_tools(self):
        """列出服务器上的全部 MCP 工具。"""
        assert self.session is not None, "请先调用 connect()"
        result = await self.session.list_tools()
        return result.tools

    async def call_tool(self, name: str, arguments: Optional[dict[str, Any]] = None) -> str:
        """按名字调用 MCP 工具，把服务器返回的各种内容汇总为纯文本。"""
        assert self.session is not None, "请先调用 connect()"
        result = await self.session.call_tool(name, arguments or {})
        parts: list[str] = []
        for content in result.content:
            if getattr(content, "type", None) == "text":
                parts.append(getattr(content, "text", "") or "")
            elif getattr(content, "type", None) == "image":
                parts.append(
                    f"[图片内容，媒体类型: {getattr(getattr(content, 'data', None), 'media_type', 'unknown')}]"
                )
            else:
                parts.append(str(content))
        text = "\n".join(p for p in parts if p)
        if getattr(result, "is_error", False):
            return f"[工具 {name} 执行出错]\n{text or '(无错误详情)'}"
        return text if text else f"(工具 {name} 没有返回文本)"

    def tools_to_functions(self, tools) -> list[dict[str, Any]]:
        """
        MCP 工具列表 → OpenAI 兼容 function calling 的 tools 数组。

        这一步就是题目里『标准 LLM function calling 桥接 MCP』的落点：
        MCP 的 input_schema（JSON Schema）原样塞进 OpenAI 的 parameters 字段。
        """
        functions: list[dict[str, Any]] = []
        for tool in tools:
            schema = dict(tool.input_schema or {"type": "object", "properties": {}})
            functions.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": schema,
                    },
                }
            )
        return functions

    # ------------------------------------------------------------------ 同步
    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    def list_tools_sync(self):
        async def _inner():
            async with self:
                return await self.list_tools()
        return self._run(_inner())

    def call_tool_sync(self, name: str, arguments: Optional[dict[str, Any]] = None) -> str:
        async def _inner():
            async with self:
                return await self.call_tool(name, arguments)
        return self._run(_inner())

    def tools_to_functions_sync(self) -> list[dict[str, Any]]:
        async def _inner():
            async with self:
                return self.tools_to_functions(await self.list_tools())
        return self._run(_inner())

    def __await__(self):  # 支持 async with MCPClient() as client:
        return self.connect().__await__()

    async def __aenter__(self) -> "MCPClient":
        return await self.connect()

    async def __aexit__(self, *exc_info) -> None:
        await self.close()


# ---------------------------------------------------------------------------
# 端到端自测：python mcp_client.py
# ---------------------------------------------------------------------------
async def _selftest() -> int:
    print("=" * 60)
    print("[自测] 启动 MCP 客户端，连接", DEFAULT_SERVER_SCRIPT)
    print("=" * 60)
    async with MCPClient() as client:
        tools = await client.list_tools()
        print(f"\n✅ 通过 MCP 发现 {len(tools)} 个工具：")
        for t in tools:
            print(f"   - {t.name}: {(t.description or '')[:50]}")

        functions = client.tools_to_functions(tools)
        print(f"\n✅ 已桥接为 {len(functions)} 个 function calling 工具，第 1 个的 schema：")
        print(json.dumps(functions[0]["function"], ensure_ascii=False, indent=2)[:800])

        # 用演示数据实调第一个能力（存在才测，不存在提示即可）
        demo_pdf = PROJECT_ROOT / "data" / "sample_reading.pdf"
        demo_csv = PROJECT_ROOT / "data" / "courses.csv"
        if demo_pdf.exists():
            print("\n✅ 通过 MCP 协议调用 summarize_pdf：")
            print((await client.call_tool("summarize_pdf", {"file_path": str(demo_pdf)}))[:400])
        if demo_csv.exists():
            print("\n✅ 通过 MCP 协议调用 query_csv：")
            print(await client.call_tool("query_csv", {"file_path": str(demo_csv), "question": "周一"}))
    print("\n[自测] 完成 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_selftest()))
