#!/usr/bin/env python3
"""Render the submission draft as a standalone HTML page for PDF/DOCX export.

TDS takes an uploaded pdf/doc/docx, so the markdown draft needs a document form.
Handles only the constructs draft.md actually uses: headings, paragraphs, lists,
blockquotes, fenced code, images with italic captions, tables, and inline
emphasis/code/links.

Usage:  python3 tds/tools/draft2doc.py tds/draft.md tds/submission.html
"""

from __future__ import annotations

import html
import re
import sys

TITLE = "Act on the Verdict. Stream the Rest."
SUBTITLE = "How we cut median LLM time-to-act from 1.33s to 0.65s by putting the decision fields first"
AUTHOR = "Nikolai Turusin"

STYLE = """
@page { size: A4; margin: 20mm 18mm; }
* { box-sizing: border-box; }
body {
  font-family: Charter, Georgia, "Times New Roman", serif;
  font-size: 11.5pt; line-height: 1.55; color: #111; background: #fff;
  margin: 0 auto; max-width: 165mm;
}
header.title { margin-bottom: 26px; padding-bottom: 18px; border-bottom: 1.5px solid #111; }
h1 { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 24pt; line-height: 1.15;
     letter-spacing: -0.01em; margin: 0 0 10px; }
.subtitle { font-size: 13pt; color: #444; margin: 0 0 12px; line-height: 1.4; }
.byline { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 10pt; color: #666;
          text-transform: uppercase; letter-spacing: 0.1em; margin: 0; }
h2 { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 12pt; letter-spacing: 0.12em;
     text-transform: uppercase; color: #3730A3; margin: 30px 0 12px; padding-top: 12px;
     border-top: 1.5px solid #111; page-break-after: avoid; }
h3 { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 14pt; margin: 22px 0 8px;
     page-break-after: avoid; }
p { margin: 0 0 11px; }
ul, ol { margin: 0 0 12px; padding-left: 22px; }
li { margin-bottom: 5px; }
blockquote { margin: 12px 0; padding: 10px 14px; background: #F4F4EE; border-left: 3px solid #B9B9AE;
             font-size: 10.5pt; color: #333; page-break-inside: avoid; }
blockquote p:last-child { margin-bottom: 0; }
code { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 0.85em;
       background: #F1F1EA; padding: 1px 4px; border-radius: 3px; }
pre { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 8.8pt; line-height: 1.45;
      background: #F4F4EE; border: 1px solid #E2E2D8; border-radius: 4px; padding: 10px 12px;
      overflow-wrap: break-word; white-space: pre-wrap; margin: 0 0 12px;
      page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: inherit; }
figure { margin: 16px 0; page-break-inside: avoid; }
figure img { display: block; width: 100%; height: auto; border: 1px solid #E2E2D8; border-radius: 3px; }
figcaption { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 9pt; color: #555;
             margin-top: 6px; line-height: 1.4; }
table { width: 100%; border-collapse: collapse; font-size: 10pt; margin: 0 0 14px;
        page-break-inside: avoid; }
th { text-align: left; font-family: "Helvetica Neue", Arial, sans-serif; font-size: 8.5pt;
     text-transform: uppercase; letter-spacing: 0.07em; color: #555;
     border-bottom: 1.5px solid #999; padding: 6px 8px; }
td { border-bottom: 1px solid #E2E2D8; padding: 6px 8px; vertical-align: top; }
a { color: #3730A3; }
"""


def inline(text: str) -> str:
    """Markdown inline markup to HTML, escaping everything else."""
    placeholders: list[str] = []

    def stash(markup: str) -> str:
        placeholders.append(markup)
        return f"\x00{len(placeholders) - 1}\x00"

    # code spans first: their contents must not be treated as markup
    text = re.sub(r"`([^`]+)`", lambda m: stash(f"<code>{html.escape(m.group(1))}</code>"), text)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: stash(f'<a href="{html.escape(m.group(2))}">{html.escape(m.group(1))}</a>'),
        text,
    )
    text = html.escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)

    for index, markup in enumerate(placeholders):
        text = text.replace(f"\x00{index}\x00", markup)
    return text


def render(markdown: str) -> str:
    out: list[str] = []
    lines = markdown.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("```"):
            language = stripped[3:].strip()
            i += 1
            body: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            klass = f' class="language-{language}"' if language else ""
            out.append(f"<pre><code{klass}>{html.escape(chr(10).join(body))}</code></pre>")
            continue

        if stripped.startswith("### "):
            out.append(f"<h3>{inline(stripped[4:])}</h3>")
            i += 1
            continue

        if stripped.startswith("## "):
            out.append(f"<h2>{inline(stripped[3:])}</h2>")
            i += 1
            continue

        # image, optionally followed by an italic caption paragraph
        image = re.match(r"!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if image:
            alt, src = html.escape(image.group(1)), html.escape(image.group(2))
            caption = ""
            if i + 2 < len(lines) and lines[i + 2].strip().startswith("*Figure"):
                # unwrap exactly the italic pair; inner **bold** must survive
                caption = inline(re.sub(r"^\*(.*)\*$", r"\1", lines[i + 2].strip()))
                i += 2
            out.append(
                f'<figure><img src="{src}" alt="{alt}">'
                + (f"<figcaption>{caption}</figcaption>" if caption else "")
                + "</figure>"
            )
            i += 1
            continue

        if stripped.startswith("|"):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    rows.append(cells)
                i += 1
            head, *body_rows = rows
            thead = "".join(f"<th>{inline(c)}</th>" for c in head)
            tbody = "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body_rows
            )
            out.append(f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>")
            continue

        if stripped.startswith("> "):
            quote: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip("> ").rstrip())
                i += 1
            out.append(f"<blockquote><p>{inline(' '.join(quote))}</p></blockquote>")
            continue

        bullet = re.match(r"^(\-|\d+\.)\s+", stripped)
        if bullet:
            ordered = not stripped.startswith("-")
            items: list[str] = []
            while i < len(lines) and re.match(r"^\s*(\-|\d+\.)\s+", lines[i]):
                item = re.sub(r"^\s*(\-|\d+\.)\s+", "", lines[i]).rstrip()
                i += 1
                # continuation lines are indented
                while i < len(lines) and lines[i].startswith("  ") and lines[i].strip():
                    item += " " + lines[i].strip()
                    i += 1
                items.append(item)
            tag = "ol" if ordered else "ul"
            body = "".join(f"<li>{inline(it)}</li>" for it in items)
            out.append(f"<{tag}>{body}</{tag}>")
            continue

        # paragraph: join until a blank line
        para: list[str] = []
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{2,3} |```|\||> |!\[|\-\s|\d+\.\s)", lines[i].strip()
        ):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(' '.join(para))}</p>")

    return "\n".join(out)


def build(markdown: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(TITLE)}</title>
<style>{STYLE}</style></head>
<body>
<header class="title">
  <h1>{html.escape(TITLE)}</h1>
  <p class="subtitle">{html.escape(SUBTITLE)}</p>
  <p class="byline">{html.escape(AUTHOR)}</p>
</header>
{render(markdown)}
</body></html>
"""


if __name__ == "__main__":
    source, target = sys.argv[1], sys.argv[2]
    page = build(open(source, encoding="utf-8").read())
    open(target, "w", encoding="utf-8").write(page)
    print(f"{target}: {len(page)} chars")
