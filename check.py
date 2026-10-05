"""Northway check: read the exports, list what disagrees, write report.html + issues.csv.

Usage:  python check.py [path/to/exports]      (default: ./exports)
"""
import sys
import webbrowser
from pathlib import Path

from northway.checks import run_all
from northway.load import load_all
from northway.report import write_csv, write_html


def main():
    exports = Path(sys.argv[1] if len(sys.argv) > 1 else "exports")
    if not (exports / "pricing.xlsx").exists():
        sys.exit(f"Can't find the export files in '{exports}'. Usage: python check.py path/to/exports")
    data = load_all(exports)
    issues = run_all(data)
    sources = [f"pricing.xlsx ({data['sheet'].prices_generated})",
               f"books_item_list.csv ({data['books_as_of']})",
               "northway_products_export.csv", "maple_export.csv", "bridge_mapping.csv"]
    out = Path("output")
    out.mkdir(exist_ok=True)
    write_html(issues, out / "report.html", sources)
    write_csv(issues, out / "issues.csv")
    print(f"{len(issues)} things need attention. Open {out / 'report.html'}")
    for who in ("Dana", "Sam", "Bridge"):
        print(f"  {who}: {sum(i.who == who for i in issues)}")
    if "--no-open" not in sys.argv:
        webbrowser.open((out / "report.html").resolve().as_uri())


if __name__ == "__main__":
    main()
