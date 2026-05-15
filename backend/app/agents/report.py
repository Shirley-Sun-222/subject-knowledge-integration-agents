from __future__ import annotations

import html
from pathlib import Path

from ..config import settings
from ..runtime.files import runtime_files
from ..runtime.store import state_store


class ReportAgent:
    def render_markdown(self) -> str:
        data = self.collect_data()
        return _render_markdown(data)

    def generate_markdown(self) -> str:
        report = self.render_markdown()
        runtime_files.report_markdown_path().write_text(report, encoding="utf-8")
        return report

    def collect_data(self) -> dict:
        data = state_store.collect_report_data()
        textbooks = data["textbooks"]
        decisions = data["decisions"]
        original_chars = sum(item["total_chars"] for item in textbooks)
        kept_decisions = [item for item in decisions if item["action"] != "remove"]
        integrated_chars = _estimate_integrated_chars(kept_decisions, data["nodes"], original_chars)
        action_counts = {action: sum(1 for item in decisions if item["action"] == action) for action in ["merge", "keep", "remove"]}
        return {
            "textbooks": textbooks,
            "original_chars": original_chars,
            "integrated_chars": integrated_chars,
            "compression_ratio": integrated_chars / original_chars if original_chars else 0,
            "node_count": data["node_count"],
            "edge_count": data["edge_count"],
            "integrated_node_count": len(kept_decisions),
            "decisions": decisions,
            "action_counts": action_counts,
            "metrics": data["metrics"],
        }

    async def generate_pdf(self) -> Path:
        markdown = self.generate_markdown()
        output = runtime_files.report_pdf_path()
        if settings.pdf_renderer == "playwright":
            try:
                await _html_to_pdf(_markdown_to_html(markdown), output)
                return output
            except Exception:
                pass
        _reportlab_pdf(markdown, output)
        return output


def _render_markdown(data: dict) -> str:
    examples = data["decisions"][:5]
    rows = "\n".join(
        f"| {item['filename']} | {item['title']} | {item['total_chars']} | {item['status']} |"
        for item in data["textbooks"]
    ) or "| 暂无 | 暂无 | 0 | pending |"
    cases = "\n".join(
        f"- `{item['id']}`：{item['action']}，影响 {len(item['affected_nodes'])} 个节点。理由：{item['reason']}"
        for item in examples
    ) or "- 当前尚未生成整合决策。"
    return f"""# 学科知识整合报告

## 1. 整合概览

| 教材数量 | 原始总字数 | 整合后精华字数 | 压缩比 |
| --- | ---: | ---: | ---: |
| {len(data['textbooks'])} | {data['original_chars']} | {data['integrated_chars']} | {data['compression_ratio']:.2%} |

## 2. 教材清单

| 文件名 | 标题 | 字数 | 状态 |
| --- | --- | ---: | --- |
{rows}

## 3. 整合决策摘要

| 合并 | 保留 | 删除 |
| ---: | ---: | ---: |
| {data['action_counts'].get('merge', 0)} | {data['action_counts'].get('keep', 0)} | {data['action_counts'].get('remove', 0)} |

## 4. 知识图谱统计

| 整合前节点数 | 整合后节点数 | 关系数 |
| ---: | ---: | ---: |
| {data['node_count']} | {data['integrated_node_count']} | {data['edge_count']} |

## 5. 重点整合案例

{cases}

## 6. 教学完整性说明

系统优先保留跨教材高频知识点、章节关键概念和关系链路中的前置节点。低置信度删除项会保留决策记录，教师可以通过对话反馈恢复或拆分，避免教学逻辑链路被不可逆地截断。

## 7. 性能与消耗

系统记录 RAG 响应时间和 token 估算，供后续 benchmark 分析。当前最近指标数：{len(data['metrics'])}。
"""


def _markdown_to_html(markdown: str) -> str:
    try:
        import markdown as markdown_lib

        body = markdown_lib.markdown(markdown, extensions=["tables"])
    except Exception:
        body = "<pre>" + html.escape(markdown) + "</pre>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans CJK SC", sans-serif; margin: 40px; color: #172033; line-height: 1.6; }}
h1, h2 {{ color: #1e40af; }}
table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
th, td {{ border: 1px solid #d8e0ef; padding: 8px 10px; text-align: left; }}
th {{ background: #eef4ff; }}
code {{ color: #9a3412; }}
</style>
</head>
<body>{body}</body>
</html>"""


async def _html_to_pdf(document: str, output: Path) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        await page.set_content(document, wait_until="networkidle")
        await page.pdf(path=str(output), format="A4", print_background=True)
        await browser.close()


def _reportlab_pdf(markdown: str, output: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    output.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output), pagesize=A4)
    _, height = A4
    y = height - 40
    for line in markdown.splitlines():
        text = line.encode("latin-1", errors="ignore").decode("latin-1") or " "
        c.drawString(40, y, text[:110])
        y -= 15
        if y < 40:
            c.showPage()
            y = height - 40
    c.save()


def _estimate_integrated_chars(decisions: list[dict], nodes: dict[str, dict], original_chars: int) -> int:
    total = 0
    for decision in decisions:
        result_id = decision.get("result_node") or (decision["affected_nodes"][0] if decision["affected_nodes"] else None)
        node = nodes.get(result_id) if result_id else None
        if not node:
            continue
        limit = 420 if decision["action"] == "merge" else 360
        total += min(len(node["definition"]) + len(node["source_excerpt"]), limit)
    return min(total, int(original_chars * 0.3)) if original_chars else 0
