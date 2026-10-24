# -*- coding: utf-8 -*-
"""
app.py — 网页演示界面（Streamlit，样板代码由 AI 生成）

运行：
    streamlit run app.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

import streamlit as st
from dotenv import dotenv_values

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def reload_env_file() -> None:
    """每次页面运行都重读 .env：

    - .env 里的【非空】值会覆盖旧环境变量 → 填/改 Key 后不用重启 streamlit，点一次运行即生效；
    - .env 里的【空值】不覆盖已有环境变量 → 不会误清掉 PyCharm 运行配置里设的变量。
    """
    for key, val in dotenv_values(PROJECT_ROOT / ".env").items():
        if val is not None and val.strip():
            os.environ[key] = val


reload_env_file()

from agent import run_agent  # noqa: E402

UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="学习资料助理 Agent", page_icon="📚", layout="wide")
st.title("📚 学习资料助理 · MCP + Function Calling Agent")
st.caption(
    "单一用途 Agent：总结本地 PDF / 抓取网页 / 查询课程表 CSV。"
    "外部能力通过 MCP 协议调用，大脑（LLM）决定何时调用哪个工具。"
)

with st.sidebar:
    st.header("⚙️ 运行配置")
    backend = st.selectbox(
        "后端",
        ["auto", "openai", "mock"],
        index=0,
        help="auto=有 Key 用真实模型，否则 mock；mock=纯离线演示编排循环",
    )
    api_key = st.text_input("LLM_API_KEY（覆盖 .env）", type="password")
    if backend == "mock" and api_key:
        st.warning("⚠️ 后端选了 `mock`：即使填了 Key 也不会调用真实模型，请改为 `auto` 或 `openai`。")
    api_base = st.text_input("API Base", value=os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1"))
    model = st.text_input("模型", value=os.getenv("LLM_MODEL", "deepseek-chat"))
    with st.expander("🔎 环境诊断（每次运行实时读取）"):
        _k = (os.getenv("LLM_API_KEY") or "").strip()
        if _k:
            st.success(f"环境变量 LLM_API_KEY 已设置（{len(_k)} 位：`{_k[:6]}…{_k[-4:]}`）")
        else:
            st.error("环境变量 LLM_API_KEY 未设置")
        if api_key:
            st.write(f"✅ 侧边栏 Key 输入框：已填写（`{api_key[:3]}…{api_key[-2:]}`）")
        else:
            st.warning("⭕ 侧边栏 Key 输入框：为空（在上面填入后，点一次任意“运行”按钮即生效）")
        st.write(f"- API Base：`{os.getenv('LLM_API_BASE') or '(未设置，用默认)'}`")
        st.write(f"- 模型：`{os.getenv('LLM_MODEL') or '(未设置，用默认)'}`")
        _env_file = PROJECT_ROOT / ".env"
        st.write(f"- .env 文件：{'✅ ' + str(_env_file) if _env_file.exists() else '⚠️ 不存在（应放在项目根目录 study-assistant-agent/.env）'}")
        st.write(f"- 当前后端选择：`{backend}`（auto=有 Key 用真实模型）")
        st.caption("看不到本面板＝运行的还是旧代码，请完全停止进程后重新 streamlit run app.py")
    st.divider()
    st.markdown("**演示数据**")
    st.markdown("- `data/sample_reading.pdf`：英文阅读材料")
    st.markdown("- `data/courses.csv`：本周课表")


def _run(prompt_text: str) -> tuple[str, list[str]]:
    """把侧边栏配置注入环境变量，跑一次编排循环。"""
    if api_key:
        os.environ["LLM_API_KEY"] = api_key
    if api_base:
        os.environ["LLM_API_BASE"] = api_base
    if model:
        os.environ["LLM_MODEL"] = model
    try:
        answer, log = asyncio.run(run_agent(prompt_text, backend=backend, return_log=True))
        return answer, log
    except Exception as exc:  # noqa: BLE001
        return f"运行出错：{exc}", []


def _show(answer: str, log: list[str]) -> None:
    with st.expander("🔍 编排过程（工具调用日志）", expanded=bool(log)):
        for line in log:
            st.code(line, language=None)
    st.markdown("### 💬 回答")
    st.markdown(answer)


tabs = st.tabs(["💬 自由对话", "📄 PDF 总结", "🌐 网页抓取", "📊 CSV 查询"])

with tabs[0]:
    st.subheader("让助理帮你做点事")
    question = st.text_area("输入问题", placeholder="例如：请总结 data/sample_reading.pdf 并给出读书笔记")
    if st.button("🚀 运行", key="dq"):
        if question.strip():
            answer, log = _run(question.strip())
            _show(answer, log)
        else:
            st.warning("请先输入问题")

with tabs[1]:
    st.subheader("上传并总结本地 PDF")
    up = st.file_uploader("选择 PDF 文件", type=["pdf"], key="pdfup")
    saved: pathlib.Path | None = None
    if up is not None:
        saved = UPLOAD_DIR / f"user_{up.name}"
        saved.write_bytes(up.getvalue())
        st.success(f"已保存：{saved}")
    st.markdown("或使用演示材料：`data/sample_reading.pdf`")
    pdf_extra = st.text_area("附加要求（可选）", placeholder="例如：重点总结第三章，并列出 5 个要点")
    if st.button("📄 总结这份 PDF", key="pdfgo"):
        target = str(saved) if saved is not None else str(PROJECT_ROOT / "data" / "sample_reading.pdf")
        prompt_text = f"请总结这份 PDF 材料：{target}。要求给出 200 字以内摘要和 3~5 条要点。{pdf_extra}".strip()
        answer, log = _run(prompt_text)
        _show(answer, log)

with tabs[2]:
    st.subheader("抓取并提炼网页要点")
    url = st.text_input("网页 URL", placeholder="https://example.com/article")
    web_extra = st.text_area("附加要求（可选）", placeholder="例如：总结全文并列出论点")
    if st.button("🌐 抓取这个网页", key="webgo"):
        if url.strip():
            prompt_text = f"请抓取这个网页并提炼要点：{url.strip()}。{web_extra}".strip()
            answer, log = _run(prompt_text)
            _show(answer, log)
        else:
            st.warning("请先输入 URL")

with tabs[3]:
    st.subheader("查询课程表 / 成绩 CSV")
    csv_files = sorted((PROJECT_ROOT / "data").glob("*.csv"))
    options = [str(f) for f in csv_files] or ["（未找到 CSV，请先运行 tools/make_sample_data.py）"]
    csv_path = st.selectbox("CSV 文件", options)
    csv_q = st.text_input("查询问题", placeholder="例如：周一有哪些课？")
    if st.button("📊 查询 CSV", key="csvgo"):
        if csv_q.strip():
            prompt_text = f"请查询 CSV 文件 {csv_path}，回答：{csv_q.strip()}"
            answer, log = _run(prompt_text)
            _show(answer, log)
        else:
            st.warning("请先输入查询问题")
