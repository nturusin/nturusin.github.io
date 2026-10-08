"""Rebuild the blog article body from tds/draft.md, keeping the blog's head, cover, CSS figures and script."""
import html, re, sys
from pathlib import Path

draft, page = Path(sys.argv[1]).read_text(), Path(sys.argv[2])
old = page.read_text()

def grab(pattern):
    m = re.search(pattern, old, re.S); assert m, pattern; return m.group(0)

figs = {
    "fig1.png": grab(r'<figure class="fig quiet" id="fig1">.*?</figure>'),
    "fig2.png": grab(r'<figure class="fig sheet" id="fig2">.*?</figure>'),
    "fig3.png": grab(r'<figure class="fig quiet" id="fig3">.*?</figure>'),
    "fig4-override.png": grab(r'<div class="orace".*?\n  </div>'),
}
parser_pre = grab(r'<pre class="code" aria-label="Python decision parser, condensed">.*?</pre>')
reflist = grab(r'<ul class="reflist">.*?</ul>')

def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)\*(?!\w)", r"<i>\1</i>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
    return t

def hl_json(code):
    def tok(m):
        cls = "k" if m.group(2) else "s"
        return f'<span class="{cls}">{m.group(1)}</span>{m.group(2) or ""}'
    return re.sub(r'("(?:[^"\\]|\\.)*")(\s*:)?', tok, html.escape(code, quote=False))

def caption(text, title):
    text = re.sub(r"^Figure \d+ — ", "", text).replace(" Image by the author.", "")
    first, _, rest = text.partition(". ")
    first = first.rstrip(".")
    if first == title and rest:
        first, _, rest = rest.partition(". ")
        first = first.rstrip(".")
    return f"<b>{inline(first)}.</b>" + (f" {inline(rest)}" if rest else "")

def slug(t):
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")

body, toc, lines, i, first_p = [], [], draft.split("\n"), 0, True
def emit_fig(markup):
    body.append("</div>\n\n<div class=\"wide\">\n  " + markup + "\n</div>\n\n<div class=\"wrap\">")

while i < len(lines):
    ln = lines[i]
    if not ln.strip():
        i += 1; continue
    if ln.startswith("## "):
        t = ln[3:].strip(); toc.append((slug(t), t))
        body.append(f'  <h2 id="{slug(t)}">{inline(t)}</h2>'); i += 1; continue
    if ln.startswith("```"):
        lang = ln[3:].strip(); j = i + 1
        while not lines[j].startswith("```"): j += 1
        code = "\n".join(lines[i + 1:j]); i = j + 1
        if lang == "python":
            body.append("  " + parser_pre)
        else:
            body.append(f'  <pre class="code" aria-label="JSON example"{' style="white-space:pre-wrap"' if max(map(len, code.split(chr(10)))) > 90 else ''}>{hl_json(code)}</pre>')
        continue
    if ln.startswith("!["):
        src = re.search(r"\(figures/([^)]+)\)", ln).group(1)
        j = i + 1
        while not lines[j].strip(): j += 1
        cap = lines[j].strip().strip("*")
        markup = figs[src]
        if "<figcaption>" in markup:
            title = re.search(r'<div class="ft">(.*?)</div>', markup).group(1)
            markup = re.sub(r"<figcaption>.*?</figcaption>", lambda _: f"<figcaption>{caption(cap, title)}</figcaption>", markup, flags=re.S)
            emit_fig(markup)
        else:
            body.append("  " + markup)
        i = j + 1; continue
    if ln.startswith("|"):
        rows = []
        while i < len(lines) and lines[i].startswith("|"):
            cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            if not all(re.fullmatch(r"-+", c) for c in cells): rows.append(cells)
            i += 1
        head, *rest = rows
        cls = "numbers opnotes" if head[0] == "Risk" else "numbers"
        th = "".join(f"<th>{inline(c)}</th>" for c in head)
        def td(c):
            m = re.fullmatch(r"\*\*(.+)\*\*", c)
            return f'<td class="big">{inline(m.group(1))}</td>' if m else f"<td>{inline(c)}</td>"
        trs = "\n".join("      <tr>" + "".join(td(c) for c in r) + "</tr>" for r in rest)
        body.append(f'  <table class="{cls}">\n    <thead><tr>{th}</tr></thead>\n    <tbody>\n{trs}\n    </tbody>\n  </table>')
        continue
    if re.match(r"(\d+\.|-) ", ln):
        ordered = ln[0].isdigit(); items = []
        while i < len(lines) and re.match(r"(\d+\.|-) ", lines[i]):
            items.append(re.sub(r"^(\d+\.|-) ", "", lines[i])); i += 1
        if not ordered and items[0].startswith("**OpenAI**"):
            body.append("  " + reflist); continue
        tag, cls = ("ol", "gotchas") if ordered else ("ul", "gotchas")
        lis = "\n".join(f"    <li>{inline(x)}</li>" for x in items)
        body.append(f'  <{tag} class="{cls}">\n{lis}\n  </{tag}>'); continue
    para = [ln]; i += 1
    while i < len(lines) and lines[i].strip() and not re.match(r"(#|```|!\[|\||\d+\. |- )", lines[i]):
        para.append(lines[i]); i += 1
    text = inline(" ".join(para))
    if text.endswith(":") and len(text) < 80 and i < len(lines) - 2:
        body.append(f'  <p class="codenote">{text}</p>')
    else:
        body.append(f'  <p{" style=\"margin-top:30px\"" if first_p else ""}>{text}</p>')
    first_p = False

article = "<article>\n<div class=\"wrap\">\n\n  <details class=\"tocm\">\n    <summary>Contents</summary>\n" + \
    "\n".join(f'    <a href="#{s}">{html.escape(t)}</a>' for s, t in toc) + "\n  </details>\n\n" + \
    "\n".join(body) + "\n</div>\n</article>"
article = re.sub(r'<div class="wrap">\s*</div>\s*', "", article)
nav = '<nav class="toc" aria-label="Contents">\n  <div class="tt">Contents</div>\n' + \
    "\n".join(f'  <a href="#{s}">{html.escape(t)}</a>' for s, t in toc) + "\n</nav>"

new = re.sub(r'<nav class="toc".*?</nav>', lambda m: nav, old, count=1, flags=re.S)
new = re.sub(r"<article>.*?</article>", lambda m: article, new, count=1, flags=re.S)
page.write_text(new)
print(f"{len(toc)} sections, {len(body)} blocks")
