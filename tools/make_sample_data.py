# -*- coding: utf-8 -*-
"""
tools/make_sample_data.py — 生成演示数据（可重复运行）

生成：
    data/sample_reading.pdf  （演示 PDF：一段英文人工智能阅读材料）
    data/courses.csv         （演示课表：本周课程安排）

运行：
    python tools/make_sample_data.py
"""
from __future__ import annotations

import csv
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

READING_TEXT = """\
Introduction to Artificial Intelligence
A Short Reading for Students

Chapter 1. What Is Artificial Intelligence?

Artificial intelligence (AI) is the field of study that aims to build machines
that can perform tasks which normally require human intelligence. These tasks
include understanding language, recognizing images, playing games, and making
decisions. The term "artificial intelligence" was first used in 1956 at the
Dartmouth conference, where researchers wanted to discover how machines could
be made to use language, form abstractions, and solve problems.

Chapter 2. Machine Learning: The Engine of Modern AI

Most of today's AI systems are powered by machine learning (ML). Instead of
being explicitly programmed with rules, an ML system learns patterns from data.
A model is trained on many examples, and after training it can make predictions
about new, unseen examples. For example, an email classifier is trained on
thousands of emails that are already labeled as spam or not spam.

Supervised learning uses labeled data, while unsupervised learning finds
patterns without labels. A third category, reinforcement learning, lets an
agent improve its behavior by receiving rewards or penalties from the
environment. Deep learning is a special kind of machine learning based on
neural networks with many layers.

Chapter 3. Large Language Models

Large language models (LLMs) are neural networks trained on enormous amounts
of text. They learn to predict the next word in a sentence, which surprisingly
is enough to produce fluent, coherent text. Models like ChatGPT are based on
the transformer architecture, which uses an attention mechanism to focus on
the most relevant parts of the input.

LLMs can summarize documents, answer questions, write code, and translate
between languages. However, they also have limitations: they can generate
confident but incorrect statements, a problem called hallucination. They may
also reflect biases in their training data, so outputs should always be
checked by humans.

Chapter 4. AI in Everyday Life and Education

AI already surrounds us: recommendation systems in online stores, navigation
apps, face recognition on phones, and translation tools. In education, AI can
act as a personal tutor, give instant feedback, and summarize long readings
for students. Using AI responsibly means verifying its output, protecting
personal data, and understanding that it is a tool, not a replacement for
human judgment.

Key Terms

artificial intelligence, machine learning, supervised learning, unsupervised
learning, reinforcement learning, deep learning, neural network, large
language model, transformer, attention mechanism, hallucination.

Questions for Discussion

1. What is the difference between supervised and unsupervised learning?
2. Why can large language models produce incorrect statements?
3. How can AI tools help students, and what are the risks?
"""


def make_pdf(text: str = READING_TEXT, out: pathlib.Path | None = None) -> pathlib.Path:
    import pymupdf  # PyMuPDF（2.x 推荐命名）

    out = out or (DATA / "sample_reading.pdf")
    DATA.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4 纵向
    lines = text.splitlines()
    chunk: list[str] = []
    for idx, line in enumerate(lines):
        chunk.append(line)
        too_long = len("\n".join(chunk)) > 2600
        is_last = idx == len(lines) - 1
        if too_long or is_last:
            rect = pymupdf.Rect(50, 50, 545, 800)
            page.insert_textbox(rect, "\n".join(chunk), fontsize=11, fontname="helv")
            if not is_last:
                page = doc.new_page(width=595, height=842)
            chunk = []

    doc.save(out)
    doc.close()
    print(f"已生成: {out}")
    return out


def make_csv(out: pathlib.Path | None = None) -> pathlib.Path:
    out = out or (DATA / "courses.csv")
    DATA.mkdir(parents=True, exist_ok=True)

    rows = [
        ["周几", "节次", "课程", "地点", "教师"],
        ["周一", "1-2", "高等数学", "A-101", "王老师"],
        ["周一", "3-4", "大学英语", "B-203", "李老师"],
        ["周二", "1-2", "数据结构", "C-302", "张老师"],
        ["周三", "5-6", "软件工程", "D-401", "陈老师"],
        ["周三", "7-8", "体育", "操场", "刘老师"],
        ["周四", "3-4", "计算机网络", "C-308", "赵老师"],
        ["周五", "1-2", "操作系统", "B-105", "孙老师"],
        ["周五", "5-6", "人工智能导论", "A-501", "周老师"],
    ]
    with open(out, "w", newline="", encoding="utf-8-sig") as fp:
        csv.writer(fp).writerows(rows)
    print(f"已生成: {out}")
    return out


if __name__ == "__main__":
    make_pdf()
    make_csv()
