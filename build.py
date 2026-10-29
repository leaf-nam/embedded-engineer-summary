#!/usr/bin/env python3
"""요약집 마크다운(content/summary.md)을 챕터 > 절 > 개념 단위 정적 페이지로 분리해 site/ 에 생성한다.

사용법
  python build.py                # site/ 생성
  python build.py --stubs        # 모든 페이지의 확장 노트(extra/<slug>.md) 빈 파일 생성
  python build.py path/to/x.md   # 다른 원본 파일 사용
"""
import html, json, pathlib, re, shutil, sys
import markdown

ROOT = pathlib.Path(__file__).parent
EXTRA, OUT, ASSETS = ROOT / "extra", ROOT / "site", ROOT / "assets"
EXAMS = ROOT / "content" / "exams.json"
ALL_EXAMS, EXAM_MAP = [], {}
EXAM_BY_YEAR = []
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


FENCE = re.compile(r"```([\w+-]*)\n(.*?)```", re.S)


def split_question(q):
    """문제에서 코드 블록을 분리해 (한 줄 요약, 코드 목록)으로 만든다."""
    codes = [m.group(2).rstrip("\n") for m in FENCE.finditer(q)]
    prompt = FENCE.sub(" ", q)
    prompt = " ".join(prompt.split())
    return prompt, codes


def load_exams(order):
    """content/exams.json 을 읽어 개념별·연도별 기출 문항 맵을 만든다."""
    global ALL_EXAMS, EXAM_MAP, EXAM_BY_YEAR
    if not EXAMS.exists():
        return
    data = json.loads(EXAMS.read_text(encoding="utf-8"))
    nodes = {n.title: n for n in order}
    exam_map, all_items = {}, []
    for exam in data.get("exams", []):
        year = exam.get("year")
        label = exam.get("label") or f"{year}년"
        year_items = []
        for item in exam.get("items", []):
            key = item.get("concept", "")
            node = None
            if key:
                node = nodes.get(key)
                if node is None:
                    print(f"경고: 기출 개념을 찾을 수 없습니다: {key}")
            answer = item.get("answer", "")
            if isinstance(answer, list):
                answer = "\n".join(answer)
            prompt, codes = split_question(item.get("question", ""))
            entry = {
                "year": year,
                "label": label,
                "no": item.get("no"),
                "question": prompt,
                "code": codes,
                "answer": answer,
                "note": item.get("note", ""),
                "node": node,
            }
            if node is not None:
                exam_map.setdefault(key, []).append(entry)
            all_items.append(entry)
            year_items.append(entry)
        if year_items:
            EXAM_BY_YEAR.append({"year": year, "label": label, "items": year_items})
    ALL_EXAMS, EXAM_MAP = all_items, exam_map
    EXAM_BY_YEAR.sort(key=lambda e: e["year"] or 0)


def exam_years(node):
    return sorted({e["year"] for e in EXAM_MAP.get(node.title, []) if e.get("year")}, reverse=True)


def year_link(year, cls="badge"):
    return f'<a class="{cls}" href="exams-{year}.html" title="{year}년 기출">{year}</a>'


def badges_html(years):
    ys = sorted({y for y in years if y}, reverse=True)
    if not ys:
        return ""
    return '<span class="badges">' + "".join(year_link(y) for y in ys) + "</span>"


def exam_count(node):
    """해당 항목과 하위 항목에 연결된 기출 문항 수."""
    return sum(len(EXAM_MAP.get(n.title, [])) for n in (node, *walk(node)))


def count_pill(node, cls="toc-count"):
    c = exam_count(node)
    if not c:
        return ""
    return f'<span class="{cls}" title="기출 {c}문항">{c}</span>'


def code_html(entry):
    return "".join(
        f'<pre class="q-code"><code>{html.escape(c)}</code></pre>'
        for c in entry.get("code", [])
    )


def exam_html(node):
    items = sorted(
        EXAM_MAP.get(node.title, []),
        key=lambda e: (-(e.get("year") or 0), e.get("no") or 0),
    )
    if not items:
        return ""
    blocks = []
    for e in items:
        no = f'Q{e["no"]}. ' if e.get("no") else ""
        blocks.append(
            f'<details class="qa"><summary>{year_link(e["year"])}'
            f'<span class="q">{no}{html.escape(e["question"])}</span></summary>'
            f'<div class="a">{code_html(e)}{render(e["answer"])}</div></details>'
        )
    return (
        f'<section class="exams"><h2>기출 문제 <span class="count">{len(items)}</span></h2>'
        + "".join(blocks)
        + "</section>"
    )


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
__SRC__</main>
<script>if(innerWidth<860)document.querySelector('.toc').open=false</script>
</body></html>"""


def link(n, cls=""):
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{n.slug}.html">{html.escape(n.title)}</a>'


def nav_link(n):
    return (
        f'<a href="{n.slug}.html"><span class="t">{html.escape(n.title)}</span>'
        f"{count_pill(n)}</a>"
    )


def nav_html(root, cur):
    here = cur.chapter() if cur.level else None
    out = ["<ul>"]
    for ch in root.children:
        on = ' class="on"' if ch is here else ""
        out.append(f"<li{on}>{nav_link(ch)}")
        if ch is here and ch.children:
            out.append("<ul>")
            for s in ch.children:
                cls = "on" if s is cur or s is cur.parent else ""
                out.append(f'<li class="{cls}">{nav_link(s)}')
                if (s is cur or s is cur.parent) and s.children:
                    out.append("<ul>")
                    for c in s.children:
                        ccls = "on" if c is cur else ""
                        out.append(f'<li class="{ccls}">{nav_link(c)}</li>')
                    out.append("</ul>")
                out.append("</li>")
            out.append("</ul>")
        out.append("</li>")
    out.append("</ul>")
    if ALL_EXAMS:
        out.append(
            f'<p class="nav-exam"><a href="exams.html">기출 문제 모아보기</a>'
            f'<span>{len(ALL_EXAMS)}</span></p>'
        )
    return "".join(out)


def kids_html(node):
    if not node.children:
        return ""
    items = "".join(
        f'<li><span class="kid-head">{link(c)}{count_pill(c)}{badges_html(exam_years(c))}</span>'
        f'<span>{html.escape(excerpt(c))}</span></li>'
        for c in node.children
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
                .replace("__BODY__", body).replace("__PAGER__", "").replace("__SRC__", ""))
        (OUT / "index.html").write_text(page, encoding="utf-8")
        print(f"경고: 원본 파일이 없습니다: {SRC} → 빈 플레이스홀더 페이지 생성 → {OUT}")
        return
    root = parse(SRC.read_text(encoding="utf-8"))
    assign_slugs(root)
    order = list(walk(root))
    site = html.escape(root.title or "학습 노트")
    load_exams(order)

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
                .replace("__BODY__", body).replace("__PAGER__", pager)
                .replace("__SRC__", f'<p class="src">확장 노트 파일: <code>extra/{node.slug}.md</code></p>'))
        (OUT / f"{node.slug}.html").write_text(page, encoding="utf-8")

    # 홈
    home = f"<h1>{site}</h1>" + (f'<p class="sub">{html.escape(root.subtitle)}</p>' if root.subtitle else "")
    if ALL_EXAMS:
        years = sorted({e["year"] for e in ALL_EXAMS if e.get("year")})
        home += (
            f'<p class="exam-link"><a href="exams.html">기출 문제 모아보기</a>'
            f'<span>{len(ALL_EXAMS)}문항 · {len(years)}개 연도</span></p>'
        )
    home += render(root.body) if root.body else ""
    for ch in root.children:
        secs = "".join(f"<li>{link(s)}{count_pill(s)}</li>" for s in ch.children)
        home += f'<section class="chap"><h2>{link(ch)}{count_pill(ch)}</h2>' + (f"<ul>{secs}</ul>" if secs else f"<p>{html.escape(excerpt(ch))}</p>") + "</section>"
    write(root, home, "", "", site)

    for i, n in enumerate(order):
        crumbs, p = [f'<a href="index.html">홈</a>'], n.parent
        chain = []
        while p and p.level:
            chain.append(p)
            p = p.parent
        crumbs += [link(a) for a in reversed(chain)]
        crumb_html = '<nav class="crumbs">' + " / ".join(crumbs) + "</nav>"
        body = (
            f"<h1>{html.escape(n.title)}{badges_html(exam_years(n))}</h1>"
            + render(n.body) + exam_html(n) + kids_html(n) + extra_html(n.slug)
        )
        prev_ = f'<a class="prev" href="{order[i-1].slug}.html"><small>이전</small>{html.escape(order[i-1].title)}</a>' if i else "<span></span>"
        next_ = f'<a class="next" href="{order[i+1].slug}.html"><small>다음</small>{html.escape(order[i+1].title)}</a>' if i < len(order) - 1 else "<span></span>"
        write(n, body, crumb_html, f'<nav class="pager">{prev_}{next_}</nav>', f"{html.escape(n.title)} · {site}")

    if EXAM_BY_YEAR:
        total = len(ALL_EXAMS)
        years_desc = sorted(EXAM_BY_YEAR, key=lambda e: e["year"], reverse=True)
        # 연도 목록
        cards = "".join(
            f'<li><a href="exams-{y["year"]}.html"><strong>{html.escape(y["label"])}</strong>'
            f'<span>{len(y["items"])}문항</span>'
            f'<em>{len({e["node"].title for e in y["items"] if e["node"]})}개 개념 연결</em></a></li>'
            for y in years_desc
        )
        body = (
            "<h1>기출 문제</h1>"
            f'<p class="sub">2015–2025년 실기 복원문제 {total}문항을 연도별로 정리했습니다. '
            "연도를 선택하면 문제와 정답을 볼 수 있습니다.</p>"
            f'<ul class="year-grid">{cards}</ul>'
        )
        crumbs = '<nav class="crumbs"><a href="index.html">홈</a> / 기출 문제</nav>'
        page = (PAGE.replace("__TITLE__", f"기출 문제 · {site}").replace("__SITE__", site)
                .replace("__NAV__", nav_html(root, root)).replace("__CRUMBS__", crumbs)
                .replace("__BODY__", body).replace("__PAGER__", "").replace("__SRC__", ""))
        (OUT / "exams.html").write_text(page, encoding="utf-8")

        # 연도별 페이지
        for idx, y in enumerate(years_desc):
            year = y["year"]
            items = sorted(y["items"], key=lambda e: e.get("no") or 0)
            tabs = '<nav class="year-tabs">' + "".join(
                f'<a class="{"on" if y2["year"] == year else ""}" href="exams-{y2["year"]}.html">'
                f'{y2["year"]}</a>'
                for y2 in years_desc
            ) + "</nav>"
            cards = ""
            for e in items:
                no = f'Q{e["no"]}.' if e.get("no") else "Q."
                note = f'<p class="q-note">{html.escape(e["note"])}</p>' if e["note"] else ""
                concept = f'<p class="to-concept">{link(e["node"])}</p>' if e["node"] else ""
                cards += (
                    f'<article class="exam-card" id="q{e.get("no")}"><header>'
                    f'<span class="q-no">{no}</span></header>'
                    f'<p class="q-text">{html.escape(e["question"])}</p>{note}'
                    f'<details class="qa"><summary>답 보기</summary>'
                    f'<div class="a">{code_html(e)}{render(e["answer"])}</div></details>{concept}</article>'
                )
            prev_ = (f'<a class="prev" href="exams-{years_desc[idx-1]["year"]}.html"><small>이전 연도</small>'
                     f'{years_desc[idx-1]["year"]}년 실기</a>') if idx else "<span></span>"
            next_ = (f'<a class="next" href="exams-{years_desc[idx+1]["year"]}.html"><small>다음 연도</small>'
                     f'{years_desc[idx+1]["year"]}년 실기</a>') if idx < len(years_desc) - 1 else "<span></span>"
            body = (
                f"<h1>{html.escape(y['label'])} 기출</h1>"
                f'<p class="sub">{len(items)}문항 · 임베디드기사 실기 복원문제</p>{tabs}{cards}'
            )
            crumbs = ('<nav class="crumbs"><a href="index.html">홈</a> / '
                      '<a href="exams.html">기출 문제</a> / ' + html.escape(y["label"]) + "</nav>")
            page = (PAGE.replace("__TITLE__", f"{y['label']} 기출 · {site}").replace("__SITE__", site)
                    .replace("__NAV__", nav_html(root, root)).replace("__CRUMBS__", crumbs)
                    .replace("__BODY__", body)
                    .replace("__PAGER__", f'<nav class="pager">{prev_}{next_}</nav>')
                    .replace("__SRC__", ""))
            (OUT / f"exams-{year}.html").write_text(page, encoding="utf-8")

    print(f"페이지 {len(order) + 1 + 1 + len(EXAM_BY_YEAR) if EXAM_BY_YEAR else len(order) + 1}개 생성 → {OUT}")


build()
