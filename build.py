#!/usr/bin/env python3
"""요약집 마크다운(content/summary.md)을 챕터 > 절 > 개념 단위 정적 페이지로 분리해 site/ 에 생성한다.

사용법
  python build.py                # site/ 생성
  python build.py --stubs        # 모든 페이지의 확장 노트(extra/<slug>.md) 빈 파일 생성
  python build.py path/to/x.md   # 다른 원본 파일 사용
"""
import html, pathlib, re, shutil, sys
import markdown

ROOT = pathlib.Path(__file__).parent
EXTRA, OUT, ASSETS = ROOT / "extra", ROOT / "site", ROOT / "assets"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
SRC = pathlib.Path(args[0]) if args else ROOT / "content" / "summary.md"


class Node:
    def __init__(self, level, title, parent=None):
        self.level, self.title, self.parent = level, title, parent
        self.lines, self.children, self.slug, self.subtitle = [], [], "index", ""

    @property
    def body(self):
        return "\n".join(self.lines).strip()

    def chapter(self):
        n = self
        while n.parent and n.parent.level > 0:
            n = n.parent
        return n


def parse(text):
    root = Node(0, "")
    cur, stack = root, [root]
    for line in text.splitlines():
        if re.fullmatch(r"-{3,}", line.strip()):
            continue
        m = re.match(r"^(#{1,3}) +(.+?)\s*$", line)
        if not m:
            cur.lines.append(line)
            continue
        lvl, title = len(m.group(1)), m.group(2)
        if lvl == 1 and not root.title:
            root.title, cur = title, root
            continue
        if lvl == 2 and not root.children and not root.subtitle:
            root.subtitle, cur = title, root
            continue
        while stack[-1].level >= lvl:
            stack.pop()
        node = Node(lvl, title, stack[-1])
        stack[-1].children.append(node)
        stack.append(node)
        cur = node
    return root


def walk(node):
    for c in node.children:
        yield c
        yield from walk(c)


def assign_slugs(root):
    for i, ch in enumerate(root.children, 1):
        ch.slug = f"ch{i}"
        for j, s in enumerate(ch.children, 1):
            s.slug = f"{ch.slug}-{j}"
            for k, c in enumerate(s.children, 1):
                c.slug = f"{s.slug}-{k}"


MATH = re.compile(r"\$\$.+?\$\$|\\\(.+?\\\)", re.S)


def render(md_text):
    store = []

    def keep(m):
        store.append(m.group(0))
        return f"@@M{len(store) - 1}@@"

    t = MATH.sub(keep, md_text)
    t = re.sub(r"^ {2}(?=(\d+\.|[*-]) )", "    ", t, flags=re.M)
    h = markdown.markdown(t, extensions=["tables", "fenced_code", "sane_lists"])
    h = h.replace("<table>", '<div class="tablewrap"><table>').replace("</table>", "</table></div>")
    return re.sub(r"@@M(\d+)@@", lambda m: html.escape(store[int(m.group(1))], quote=False), h)


def excerpt(node, n=64):
    for line in node.lines:
        s = line.strip()
        if not s or s[0] in "|#>" or s.startswith("$$"):
            continue
        s = re.sub(r"^([*-]|\d+[.)]) +", "", s)
        s = re.sub(r"\\\(|\\\)|[*`]", "", s)
        return s if len(s) <= n else s[:n] + "…"
    return ""


def extra_html(slug):
    f = EXTRA / f"{slug}.md"
    if not f.exists():
        return ""
    t = re.sub(r"<!--.*?-->", "", f.read_text(encoding="utf-8"), flags=re.S).strip()
    return f'<section class="extra"><h2>확장 노트</h2>{render(t)}</section>' if t else ""


PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<link rel="stylesheet" href="style.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
 onload="renderMathInElement(document.body,{delimiters:[{left:'$$',right:'$$',display:true},{left:'\\\\(',right:'\\\\)',display:false}]})"></script>
</head><body>
<aside><a class="brand" href="index.html">__SITE__</a>
<details class="toc" open><summary>목차</summary>__NAV__</details></aside>
<main>__CRUMBS__<article>__BODY__</article>__PAGER__
<p class="src">확장 노트 파일: <code>extra/__SLUG__.md</code></p></main>
<script>if(innerWidth<860)document.querySelector('.toc').open=false</script>
</body></html>"""


def link(n, cls=""):
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{n.slug}.html">{html.escape(n.title)}</a>'


def nav_html(root, cur):
    here = cur.chapter() if cur.level else None
    out = ["<ul>"]
    for ch in root.children:
        on = ' class="on"' if ch is here else ""
        out.append(f"<li{on}>{link(ch)}")
        if ch is here and ch.children:
            out.append("<ul>")
            for s in ch.children:
                cls = "on" if s is cur or s is cur.parent else ""
                out.append(f'<li class="{cls}">{link(s)}</li>')
            out.append("</ul>")
        out.append("</li>")
    return "".join(out) + "</ul>"


def kids_html(node):
    if not node.children:
        return ""
    items = "".join(
        f'<li>{link(c)}<span>{html.escape(excerpt(c))}</span></li>' for c in node.children
    )
    label = "세부 개념" if node.level == 2 else "세부 항목"
    return f'<h2 class="kids-h">{label}</h2><ul class="kids">{items}</ul>'


def build():
    if not SRC.exists():
        shutil.rmtree(OUT, ignore_errors=True)
        OUT.mkdir()
        shutil.copy(ASSETS / "style.css", OUT / "style.css")
        (OUT / ".nojekyll").write_text("")
        site = "학습 노트"
        body = ("<h1>학습 노트</h1>"
                "<p>아직 <code>content/summary.md</code> 파일이 없습니다. "
                "요약집 마크다운을 해당 경로에 저장한 뒤 다시 push 하면 자동 배포됩니다.</p>")
        page = (PAGE.replace("__TITLE__", site).replace("__SITE__", site)
                .replace("__NAV__", "").replace("__CRUMBS__", "")
                .replace("__BODY__", body).replace("__PAGER__", "").replace("__SLUG__", "index"))
        (OUT / "index.html").write_text(page, encoding="utf-8")
        print(f"경고: 원본 파일이 없습니다: {SRC} → 빈 플레이스홀더 페이지 생성 → {OUT}")
        return
    root = parse(SRC.read_text(encoding="utf-8"))
    assign_slugs(root)
    order = list(walk(root))
    site = html.escape(root.title or "학습 노트")

    if "--stubs" in sys.argv:
        EXTRA.mkdir(exist_ok=True)
        for n in order:
            f = EXTRA / f"{n.slug}.md"
            if not f.exists():
                f.write_text(f"<!-- {n.title} — 확장 노트 -->\n", encoding="utf-8")
        print(f"확장 노트 파일 {len(order)}개 확인 완료 → {EXTRA}")
        return

    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    shutil.copy(ASSETS / "style.css", OUT / "style.css")
    (OUT / ".nojekyll").write_text("")

    def write(node, body, crumbs, pager, title):
        page = (PAGE.replace("__TITLE__", title).replace("__SITE__", site)
                .replace("__NAV__", nav_html(root, node)).replace("__CRUMBS__", crumbs)
                .replace("__BODY__", body).replace("__PAGER__", pager).replace("__SLUG__", node.slug))
        (OUT / f"{node.slug}.html").write_text(page, encoding="utf-8")

    # 홈
    home = f"<h1>{site}</h1>" + (f'<p class="sub">{html.escape(root.subtitle)}</p>' if root.subtitle else "")
    home += render(root.body) if root.body else ""
    for ch in root.children:
        secs = "".join(f"<li>{link(s)}</li>" for s in ch.children)
        home += f'<section class="chap"><h2>{link(ch)}</h2>' + (f"<ul>{secs}</ul>" if secs else f"<p>{html.escape(excerpt(ch))}</p>") + "</section>"
    write(root, home, "", "", site)

    for i, n in enumerate(order):
        crumbs, p = [f'<a href="index.html">홈</a>'], n.parent
        chain = []
        while p and p.level:
            chain.append(p)
            p = p.parent
        crumbs += [link(a) for a in reversed(chain)]
        crumb_html = '<nav class="crumbs">' + " / ".join(crumbs) + "</nav>"
        body = f"<h1>{html.escape(n.title)}</h1>" + render(n.body) + kids_html(n) + extra_html(n.slug)
        prev_ = f'<a class="prev" href="{order[i-1].slug}.html"><small>이전</small>{html.escape(order[i-1].title)}</a>' if i else "<span></span>"
        next_ = f'<a class="next" href="{order[i+1].slug}.html"><small>다음</small>{html.escape(order[i+1].title)}</a>' if i < len(order) - 1 else "<span></span>"
        write(n, body, crumb_html, f'<nav class="pager">{prev_}{next_}</nav>', f"{html.escape(n.title)} · {site}")

    print(f"페이지 {len(order) + 1}개 생성 → {OUT}")


build()
