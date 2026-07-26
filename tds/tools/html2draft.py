#!/usr/bin/env python3
"""Convert the self-contained article HTML into a paste-ready markdown draft.

The article's figures are live CSS, so they are replaced with references to the
PNGs exported by tools/export_figures.sh. Everything else becomes native
markdown: WP code blocks, real tables, real lists.

Usage:  python3 tds/tools/html2draft.py act-on-the-verdict.html tds/draft.md
"""

from __future__ import annotations

import html as H
import re
import sys

FIGMAP = {"fig1": "fig1.png", "fig2": "fig2.png", "fig3": "fig3.png"}


def bal(text: str, start: int, tag: str) -> str:
    """Return the balanced <tag>…</tag> region starting at start."""
    o = re.compile(r"<" + tag + r"[\s>]", re.I)
    c = re.compile(r"</" + tag + r">", re.I)
    depth, i = 0, start
    while True:
        mo, mc = o.search(text, i), c.search(text, i)
        if not mc:
            return text[start:]
        if mo and mo.start() < mc.start():
            depth += 1
            i = mo.end()
        else:
            depth -= 1
            i = mc.end()
            if depth == 0:
                return text[start:i]


def inline(s: str) -> str:
    """Convert inline HTML to markdown."""
    s = re.sub(r"<svg.*?</svg>", "", s, flags=re.S)
    # drop empty emphasis/decoration tags (e.g. <i style="width:49%"></i> bars)
    s = re.sub(r"<(i|b|em|strong|span)[^>]*>\s*</\1>", "", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(
        r"<code[^>]*>(.*?)</code>",
        lambda m: "`" + re.sub(r"<[^>]+>", "", m.group(1)) + "`",
        s,
        flags=re.S,
    )
    s = re.sub(r"<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>", r"**\1**", s, flags=re.S)
    s = re.sub(r"<(?:i|em)[^>]*>(.*?)</(?:i|em)>", r"*\1*", s, flags=re.S)
    s = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\*\*\s*\*\*", "", s)          # collapse emptied bold
    s = re.sub(r"[ \t\n]+", " ", H.unescape(s))
    return s.strip()


def cells(row: str) -> list[str]:
    return [inline(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)]


def convert(src: str) -> str:
    body = src[src.index("<article>") : src.index("</article>")]
    out: list[str] = []
    pos = 0
    OPEN = re.compile(r"<(h2|h3|p|pre|figure|table|ul|ol|div)\b[^>]*>", re.I)

    while True:
        m = OPEN.search(body, pos)
        if not m:
            break
        tag, start, attrs = m.group(1).lower(), m.start(), m.group(0)
        frag = bal(body, start, tag)
        pos = start + len(frag)
        cls = (re.search(r'class="([^"]*)"', attrs) or [None, ""])[1] if re.search(r'class="([^"]*)"', attrs) else ""
        classes = cls.split()

        if tag == "div":
            if "part" in classes:
                pn = inline(re.search(r'class="pn">(.*?)</div>', frag, re.S).group(1))
                pq = inline(re.search(r'class="pq">(.*?)</div>', frag, re.S).group(1))
                out.append(f"## {pn} — {pq}")
            elif "pull" in classes:
                out.append("> **" + inline(frag) + "**")
            elif "orace" in classes:
                out.append(
                    "![Timeline: at 0.65s the model commits 04_meals, at 0.90s a human "
                    "changes it to 08_personal, at 1.33s the explanation finishes, at "
                    "1.34s the stale explanation is discarded.](figures/fig4-override.png)"
                )
                out.append(
                    "*Figure 4 — Application state can change while the stream is still open.*"
                )
            elif "phases" in classes:
                for ph in re.findall(r'<div class="phase">(.*?)</div>\s*(?=<div class="phase">|$)', frag, re.S):
                    pt = re.search(r'class="pt">(.*?)</div>', ph, re.S)
                    if pt:
                        out.append("**" + inline(pt.group(1)).upper() + "**")
                    for li in re.findall(r"<li>(.*?)</li>", ph, re.S):
                        out.append("- " + inline(li))
            elif "reflist" in classes or "rh" in classes:
                pos = start + len(m.group(0))
            else:
                pos = start + len(m.group(0))  # transparent wrapper: descend into it
            continue

        if tag in ("h2", "h3"):
            out.append("### " + inline(frag))
        elif tag == "p":
            txt = inline(frag)
            if not txt:
                continue
            if "aside" in classes or "tblnote" in classes:
                out.append("> " + txt)
            elif "codenote" in classes:
                out.append("*" + txt + "*")
            else:
                out.append(txt)
        elif tag == "pre":
            code = H.unescape(re.sub(r"<[^>]+>", "", frag)).strip("\n")
            lang = "python" if re.search(r"\b(def|class|re\.compile)\b", code) else (
                "json" if code.lstrip().startswith("{") else ""
            )
            out.append(f"```{lang}\n{code}\n```")
        elif tag == "figure":
            fid = re.search(r'id="(fig\d)"', attrs)
            if not (fid and fid.group(1) in FIGMAP):
                continue
            n = fid.group(1)[-1]
            alt = re.search(r'aria-label="([^"]*)"', frag)
            cap = re.search(r"<figcaption>(.*?)</figcaption>", frag, re.S)
            ft = re.search(r'class="ft">(.*?)</div>', frag, re.S)
            out.append(f"![{H.unescape(alt.group(1)) if alt else ''}](figures/{FIGMAP[fid.group(1)]})")
            out.append(
                f"*Figure {n} — {inline(ft.group(1)) if ft else ''}. "
                f"{inline(cap.group(1)) if cap else ''}*"
            )
        elif tag == "table":
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", frag, re.S)
            if not rows:
                continue
            hdr = cells(rows[0])
            lines = ["| " + " | ".join(hdr) + " |", "|" + "|".join(["---"] * len(hdr)) + "|"]
            for r in rows[1:]:
                c = cells(r)
                if c:
                    lines.append("| " + " | ".join(c) + " |")
            out.append("\n".join(lines))  # one block: rows must stay contiguous
        elif tag in ("ul", "ol"):
            items = re.findall(r"<li>(.*?)</li>", frag, re.S)
            lines = [
                ("- " if tag == "ul" else f"{i}. ") + inline(li)
                for i, li in enumerate(items, 1)
            ]
            out.append("\n".join(lines))

    md = "\n\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", md) + "\n"


if __name__ == "__main__":
    infile, outfile = sys.argv[1], sys.argv[2]
    md = convert(open(infile, encoding="utf-8").read())
    open(outfile, "w", encoding="utf-8").write(md)
    print(f"{outfile}: {len(md.splitlines())} lines, {len(md)} chars")
