#!/usr/bin/env python3
"""Render draft.md as a page to copy-paste into the Medium editor.

Medium has no tables and keeps only simple markup on paste, so this:
  - turns the risk/policy table into a bulleted list,
  - swaps the two numeric tables for PNGs rendered from medium/table-*.html,
  - points every image at its raw GitHub URL so Medium can fetch it on paste,
  - moves the provider links into a closing Resources section (a DSC requirement).

Usage:  python3 tds/tools/md2medium.py tds/draft.md medium/article.html
"""

from __future__ import annotations

import html
import re
import sys

RAW = "https://raw.githubusercontent.com/nturusin/nturusin.github.io/tds-v2/"
BLOG_URL = "https://nturusin.github.io/act-on-the-verdict.html"
REPO_URL = "https://github.com/nturusin/llm-streaming-early-commit"

TITLE = "Halving LLM time-to-act by reordering your JSON schema"
SUBTITLE = "How we act on a classifier's verdict before the structured response finishes streaming: 2.03s to 0.99s at the median"

COVER = ("tds/figures/cover-featured.jpg",
         "A car waits at a barrier gate whose light is already green and whose boom is lifting.",
         "Image by the author, generated with ChatGPT.")

# Tables Medium cannot render, keyed by their header row.
TABLE_IMAGES = {
    ("", "Median", "p90"): (
        "medium/img/table-latency.png",
        "Table: median and p90 latency on the production path over 288,298 live requests. "
        "Time to early verdict: 0.99s median, 1.29s p90. Time to complete response: 2.03s median, 2.50s p90.",
        "Latency on the production path. Image by the author."),
    ("Compared with the current schema", "Category changed"): (
        "medium/img/table-experiment.png",
        "Table: share of 400 replayed production requests whose category changed compared with the current schema. "
        "Same schema run again: 1.8%. Old order with confidence last: 7.8%. Placebo with explanations shuffled: 7.3%.",
        "How often the category changed when the same requests were replayed with a different schema. Image by the author."),
}

RESOURCES = [
    ("Code and tests for this article", [("llm-streaming-early-commit", REPO_URL)]),
    ("Partial-JSON streaming libraries", [
        ("Instructor: partial responses", "https://python.useinstructor.com/concepts/partial/"),
        ("Vercel AI SDK: streamObject", "https://ai-sdk.dev/v5/cookbook/node/stream-object"),
        ("partial-json", "https://www.npmjs.com/package/partial-json"),
    ]),
]

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Medium paste page</title>
<style>
:root {{ --ink:#1A1C22; --mut:#5C6470; --line:#E2E2D8; --accent:#3730A3; --bg:#FAFAF8; --code:#F2F2EC; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --ink:#E9EAEE; --mut:#A6ACB8; --line:#333845; --accent:#B4B2FF; --bg:#101217; --code:#1C1F27; }} }}
:root[data-theme="dark"] {{ --ink:#E9EAEE; --mut:#A6ACB8; --line:#333845; --accent:#B4B2FF; --bg:#101217; --code:#1C1F27; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:18px/1.7 Charter, Georgia, serif; }}
.bar {{ position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line); padding:12px 16px;
        font:14px/1.5 system-ui, sans-serif; display:flex; gap:12px; align-items:center; flex-wrap:wrap; z-index:2; }}
.bar button {{ font:600 14px system-ui, sans-serif; padding:8px 14px; border-radius:8px; border:1px solid var(--accent);
               background:var(--accent); color:var(--bg); cursor:pointer; }}
.bar .status {{ color:var(--mut); }}
.head, article {{ max-width:700px; margin:0 auto; padding:0 16px; }}
.head {{ padding-top:24px; border-bottom:1px dashed var(--line); padding-bottom:16px; }}
.head .label {{ font:12px system-ui, sans-serif; letter-spacing:.08em; text-transform:uppercase; color:var(--mut); }}
.head .t {{ font:700 30px/1.25 system-ui, sans-serif; margin:4px 0 8px; }}
.head .s {{ font:20px/1.4 system-ui, sans-serif; color:var(--mut); margin:0; }}
h2 {{ font:700 26px/1.3 system-ui, sans-serif; margin:40px 0 8px; }}
pre {{ background:var(--code); padding:14px 16px; border-radius:6px; overflow-x:auto; font:14px/1.5 Menlo, monospace; }}
code {{ font-family:Menlo, monospace; font-size:.85em; background:var(--code); padding:1px 4px; border-radius:3px; }}
pre code {{ background:none; padding:0; font-size:inherit; }}
figure {{ margin:28px 0; }}
figure img {{ width:100%; height:auto; display:block; }}
figcaption {{ font:14px/1.5 system-ui, sans-serif; color:var(--mut); text-align:center; margin-top:8px; }}
a {{ color:var(--accent); }}
</style></head>
<body>
<div class="bar">
  <button id="copy">Copy article body</button>
  <span class="status" id="status">Paste it into a new Medium story, below the title and subtitle.</span>
</div>
<div class="head">
  <div class="label">Type these into Medium by hand (title, then subtitle)</div>
  <p class="t">{title}</p>
  <p class="s">{subtitle}</p>
</div>
<article id="body">
{body}
</article>
<script>
document.getElementById("copy").addEventListener("click", function () {{
  var range = document.createRange();
  range.selectNodeContents(document.getElementById("body"));
  var sel = window.getSelection();
  sel.removeAllRanges(); sel.addRange(range);
  var ok = false;
  try {{ ok = document.execCommand("copy"); }} catch (e) {{}}
  document.getElementById("status").textContent = ok
    ? "Copied. Now paste into Medium (Cmd+V)."
    : "Copy failed: the text is selected, press Cmd+C.";
}});
</script>
</body></html>
"""


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)\*(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def figure(src: str, alt: str, caption: str) -> str:
    return (f'<figure><img src="{RAW}{src}" alt="{html.escape(alt)}">'
            f"<figcaption>{inline(caption)}</figcaption></figure>")


def build(source: str) -> str:
    lines = source.split("\n")
    out = [figure(*COVER)]
    provider_links: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("## "):
            out.append(f"<h2>{inline(line[3:].strip())}</h2>")
            i += 1
            continue
        if line.startswith("```"):
            j = i + 1
            while not lines[j].startswith("```"):
                j += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(lines[i + 1:j]), quote=False)}</code></pre>")
            i = j + 1
            continue
        if line.startswith("!["):
            alt, src = re.match(r"!\[(.*)\]\((.+)\)", line).groups()
            j = i + 1
            while not lines[j].strip():
                j += 1
            out.append(figure("tds/" + src, alt, lines[j].strip().strip("*")))
            i = j + 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"-+", c) for c in cells):
                    rows.append(cells)
                i += 1
            head, *rest = rows
            if tuple(head) in TABLE_IMAGES:
                out.append(figure(*TABLE_IMAGES[tuple(head)]))
            else:  # Risk | Policy
                items = "".join(f"<li><strong>{inline(r)}.</strong> {inline(p)}</li>" for r, p in rest)
                out.append(f"<ul>{items}</ul>")
            continue
        if re.match(r"(\d+\.|-) ", line):
            ordered = line[0].isdigit()
            items = []
            while i < len(lines) and re.match(r"(\d+\.|-) ", lines[i]):
                items.append(re.sub(r"^(\d+\.|-) ", "", lines[i]))
                i += 1
            if items[0].startswith("**OpenAI**"):
                provider_links = items
                continue
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"(#|```|!\[|\||\d+\. |- )", lines[i]):
            para.append(lines[i])
            i += 1
        text = " ".join(para)
        if text.endswith("plan to ship:"):
            text = text[:-1] + "; the Resources section below links each provider's documentation."
        out.append(f"<p>{inline(text)}</p>")

    out.append("<h2>Resources</h2>")
    for label, links in RESOURCES:
        refs = ", ".join(f'<a href="{u}">{html.escape(t)}</a>' for t, u in links)
        out.append(f"<p><strong>{label}:</strong> {refs}</p>")
    out.append("<p><strong>Provider documentation:</strong></p>")
    out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in provider_links) + "</ul>")
    out.append(f'<p><em>Originally published on my blog: <a href="{BLOG_URL}">nturusin.github.io</a>.</em></p>')
    return PAGE.format(title=html.escape(TITLE), subtitle=html.escape(SUBTITLE), body="\n".join(out))


if __name__ == "__main__":
    source, target = sys.argv[1], sys.argv[2]
    page = build(open(source, encoding="utf-8").read())
    open(target, "w", encoding="utf-8").write(page)
    print(f"{target}: {len(page)} chars")
