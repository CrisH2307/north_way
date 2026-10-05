"""Turn the issues into a page Dana and Sam can read, and a CSV Sam can work through."""
import csv
import html
from collections import Counter
from datetime import datetime

ORDER = ["Dana", "Sam", "Bridge"]
HEADING = {"Dana": "Dana: decide", "Sam": "Sam: fix", "Bridge": "Bridge: for Dana (she has the login)"}
e = html.escape


def write_csv(issues, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Who", "Check", "SKU", "Product", "Problem", "What to do", "Where the numbers came from"])
        for i in issues:
            w.writerow([i.who, i.check, i.sku, i.product, i.problem, i.action,
                        " | ".join(f"{s}: {v}" for s, v in i.evidence)])


def write_html(issues, path, sources):
    counts = Counter(i.who for i in issues)
    sections = []
    for who in ORDER:
        items = [i for i in issues if i.who == who]
        if not items:
            continue
        cards = "\n".join(card(i) for i in items)
        sections.append(f'<section id="{e(who.split()[0].lower())}"><h2>{e(HEADING[who])} '
                        f'<span class="count">{len(items)}</span></h2>{cards}</section>')
    nav = " · ".join(f'<a href="#{e(w.split()[0].lower())}">{e(HEADING[w])} ({counts[w]})</a>' for w in ORDER if counts[w])
    src = " · ".join(e(s) for s in sources)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Northway: what needs fixing</title>
<style>
:root{{--ink:#1d2433;--muted:#5d6678;--line:#e3e6ec;--bg:#f7f8fa;--card:#fff;--accent:#1f5fbf;--warn:#a23b1e}}
body{{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);background:var(--bg)}}
main{{max-width:920px;margin:0 auto;padding:24px 16px 64px}}
h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:19px;margin:36px 0 4px;border-bottom:2px solid var(--ink);padding-bottom:4px}}
.count{{background:var(--ink);color:#fff;border-radius:10px;padding:0 8px;font-size:13px;vertical-align:middle}}
.meta,.intro{{color:var(--muted);margin:4px 0 12px}} nav{{margin:12px 0}} a{{color:var(--accent)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin:12px 0}}
.card h3{{margin:0 0 6px;font-size:16px}} .tag{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}}
.problem{{margin:6px 0}} .action{{margin:8px 0 0;color:var(--warn)}} .action b{{color:var(--ink)}}
table{{border-collapse:collapse;width:100%;margin-top:8px;font-size:13.5px}}
th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}} th{{color:var(--muted);font-weight:600}}
td.src{{white-space:nowrap;color:var(--muted);width:1%}} .foot{{margin-top:40px;font-size:13px}}
@media print{{body{{background:#fff}} .card{{break-inside:avoid}}}}
</style></head><body><main>
<h1>Northway: what needs fixing</h1>
<p class="meta">Nothing was changed. This only reads the files.</p>
<nav>{nav}</nav>
{''.join(sections)}
<p class="meta foot">Read: {src}. Generated {datetime.now():%Y-%m-%d %H:%M}.</p>
</main></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)


def card(i):
    title = " · ".join(x for x in (i.sku, i.product) if x)
    ev = ""
    if i.evidence:
        ev = "<table>" + "".join(f'<tr><td class="src">{e(s)}</td><td>{e(str(v))}</td></tr>' for s, v in i.evidence) + "</table>"
    rows = ""
    if i.rows:
        head, *body = i.rows
        rows = ("<table><tr>" + "".join(f"<th>{e(h)}</th>" for h in head) + "</tr>" +
                "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in r) + "</tr>" for r in body) + "</table>")
    return (f'<div class="card"><div class="tag">{e(i.check)}</div><h3>{e(title)}</h3>'
            f'<p class="problem">{e(i.problem)}</p>{ev}{rows}<p class="action"><b>What to do:</b> {e(i.action)}</p></div>')
