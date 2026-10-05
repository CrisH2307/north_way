"""The 'ERP in the middle': one catalogue built from all six exports.

Every product gets its own ID (P-001...) and is linked to its rows in the sheet,
the Books, both websites and Bridge. Problems found by checks.py become tasks
for a named person. Nothing here writes to the exports: the Books stay the truth
for stock, the sheet stays the truth for price.
"""
import csv
import hashlib
import re
from collections import defaultdict
from pathlib import Path

from .checks import BRIDGE, DANA, SAM, match_books_to_sheet, old_rate_categories, run_all
from .load import load_all, sku_base

# Task types: verb-first title + one line on why it matters.
TASK_TYPES = {
    "enter_shipment":   ("Enter the shipment in the Books", "Stock is on the shelf, but every screen says 0, so staff can't sell it.", SAM),
    "set_price":        ("Set a price", "No price in the sheet, so Priya has to text Dana on every order.", DANA),
    "fix_category":     ("Fix the category spelling", "The price program needs an exact match, so this product gets no price.", SAM),
    "delete_empty_row": ("Delete the empty category row", "An empty row hides the real one, so the price program gives no price.", SAM),
    "split_sku":        ("Give each product its own SKU", "Two products share one SKU, so neither can be priced or linked.", DANA),
    "remove_category":  ("Delete the old category row", "The price program uses the old row, so these products are priced on the old rate.", SAM),
    "update_web_price": ("Update the website prices", "The website shows different prices from the sheet.", SAM),
    "choose_listing":   ("Choose the real listing", "One SKU is on two website listings with different prices.", SAM),
    "connect_bridge":   ("Connect the listing in Bridge", "Not connected to the Books, so its website stock never updates.", BRIDGE),
    "apply_decision":   ("Apply Dana's decision", "Dana decided; type it into the sheet so everyone sees it.", SAM),
    "record_old_code":  ("Write down the old Books code", "The Books use an old code the sheet doesn't list, so nobody can find it.", SAM),
}
CHECK_TO_TYPE = {
    "Arrived but not in the Books": "enter_shipment",
    "No price set": "set_price",
    "Price program blocked": "fix_category",
    "Empty category row hides the real one": "delete_empty_row",
    "Same SKU on two products": "split_sku",
    "Category listed twice": "remove_category",
}


def task_id(kind, key):
    return hashlib.sha1(f"{kind}|{key}".encode()).hexdigest()[:10]


class Catalogue:
    def __init__(self, exports_dir):
        self.exports_dir = Path(exports_dir)
        d = load_all(exports_dir)
        self.sheet, self.books, self.web, self.bridge = d["sheet"], d["books"], d["web"], d["bridge"]
        self.books_as_of = d["books_as_of"]
        # Fingerprint of this set of exports. A tick is only confirmed by a newer export.
        h = hashlib.sha1()
        for f in sorted(self.exports_dir.iterdir()):
            if f.is_file():
                h.update(f.name.encode() + f.read_bytes())
        self.export_id = h.hexdigest()[:12]
        self.issues = run_all(d)
        self.customers = load_customers(self.exports_dir / "books_customers.csv")
        self._build_products()
        self._build_tasks()

    # ------------------------------------------------------------ products
    def _build_products(self):
        books_by_base, _ = match_books_to_sheet(self.sheet, self.books)
        groups = defaultdict(list)
        for b in self.books:
            if b["bundle_of"]:
                groups[b["bundle_of"]].append(b)
        synced = {b["variant_id"]: b for b in self.bridge}
        old_rate = old_rate_categories(self.sheet)
        sku_count = defaultdict(int)
        for p in self.sheet.products:
            sku_count[p["sku"]] += 1

        self.products = []
        for n, p in enumerate(self.sheet.products, start=1):
            shared = sku_count[p["sku"]] > 1           # e.g. PLW-141: link nothing until Dana chooses
            book = None if shared else books_by_base.get(p["sku"])
            web = [] if shared else [dict(w, bridge=synced.get(w["variant_id"]))
                                     for w in self.web if sku_base(w["sku"]) == p["sku"]]
            prices = self.sheet.prices.get(p["sku"], [])
            arrived = [s for s in self.sheet.shipments if s["sku"] == p["sku"] and s["cases"]]
            self.products.append({
                **p, "id": f"P-{n:03d}", "shared_sku": shared,
                "price": prices[0] if len(prices) == 1 else None,
                "price_status": prices[0]["status"] if prices else "missing",
                "book": book, "book_groups": groups.get(book["id"], []) if book else [],
                "web": web, "arrived": arrived,
                "old_rate": p["category"] in old_rate,   # priced from an old Categories row
            })
        self.by_id = {p["id"]: p for p in self.products}
        self.by_sku = defaultdict(list)
        for p in self.products:
            self.by_sku[p["sku"]].append(p)

    def find(self, q):
        q = (q or "").strip().lower()
        if not q:
            return self.products
        # Also the old codes (sheet's Old Books SKU column and the code the Books use),
        # so a code from an old invoice still finds the product.
        return [p for p in self.products
                if any(q in str(v or "").lower() for v in
                       (p["sku"], p["name"], p["id"], p["category"], p["old_books_sku"],
                        p["book"]["item"] if p["book"] else None))]

    # ------------------------------------------------------------ tasks
    def _build_tasks(self):
        tasks = []
        self.stale_bridge = []

        def add(kind, key, sku, product, detail, sources):
            title, why, who = TASK_TYPES[kind]
            pid = self.by_sku[sku][0]["id"] if sku in self.by_sku else None
            tasks.append({"id": task_id(kind, key), "type": kind, "title": title, "why": why, "who": who,
                          "sku": sku, "product": product, "product_id": pid, "detail": detail, "sources": sources})

        for i in self.issues:
            if i.check in CHECK_TO_TYPE:
                key = i.sku or i.product
                add(CHECK_TO_TYPE[i.check], key, i.sku, i.product, i.problem, i.evidence or table_sources(i.rows))
            elif i.check == "Website price differs from the sheet":
                # One task per product: Sam fixes all its packs in one go.
                by_product = defaultdict(list)
                for r in i.rows[1:]:
                    by_product[sku_base(r[0])].append(r)
                for base, rs in by_product.items():
                    add("update_web_price", base, base, rs[0][1],
                        f"{len(rs)} website price{'s' if len(rs) > 1 else ''} to change: "
                        + ", ".join(f"{store} {pack} {site} to {sheet_p}" for _, _, store, pack, site, sheet_p in rs) + ".",
                        [(f"{store} {pack} ({sku})", f"website {site}, sheet {sheet_p}") for sku, _, store, pack, site, sheet_p in rs])
            elif i.check == "Same SKU on two website listings":
                rows = defaultdict(list)
                for r in i.rows[1:]:
                    rows[r[0]].append(r)
                for sku, rs in rows.items():
                    add("choose_listing", sku, sku_base(sku), rs[0][1].split(" - ")[0],
                        f"{sku} is on {len(rs)} listings.",
                        [(r[1], f"price {r[3]}, stock {r[4]}, {r[2]}") for r in rs])
            elif i.check == "Website listing not connected to the Books":
                for store, sku, listing, stock in i.rows[1:]:
                    add("connect_bridge", f"{store}|{sku}|{listing}", sku_base(sku), listing,
                        f"{store} listing {sku} has no Bridge mapping.",
                        [("Bridge mapping", "no row for this listing"), (f"{store} website", f"stock {stock}")])
            elif i.check == "Bridge mapping hasn't synced recently":
                # Not a task: Sam says these still work and nobody can act on an old date.
                # Kept as one line on the Sources page.
                self.stale_bridge = i.rows[1:]
            elif i.check == "Old Books code not in the sheet":
                for base, name, code in i.rows[1:]:
                    add("record_old_code", base, base, name,
                        f"The Books call {name} '{code}'.",
                        [("Books", code), ("Sheet, Old Books SKU column", "empty")])
        self.tasks = tasks
        self.task_by_id = {t["id"]: t for t in tasks}

    def tasks_for(self, who=None, kind=None, sku=None):
        return [t for t in self.tasks if (not who or t["who"] == who) and (not kind or t["type"] == kind)
                and (not sku or t["sku"] == sku)]

    # ------------------------------------------------------------ sources
    def sources(self):
        linked = {w["variant_id"] for p in self.products for w in p["web"]}
        books_linked = {p["book"]["id"] for p in self.products if p["book"]}
        parts = [b for b in self.books if b["type"] == "Inventory Part"]
        nw = [w for w in self.web if w["store"] == "Northway"]
        mp = [w for w in self.web if w["store"] == "Maple"]
        return [
            ("Dana's sheet", "pricing.xlsx", self.sheet.prices_generated.replace("Generated nightly ", "Prices generated ").split(" - ")[0],
             f"{len(self.products)} products", f"{len(self.products)} in catalogue", "Truth for price"),
            ("The Books", "books_item_list.csv", self.books_as_of.replace("As of ", ""), f"{len(parts)} items + {len(self.books) - len(parts)} dozen/box",
             f"{len(books_linked)} linked", "Truth for stock"),
            ("Northway website", "northway_products_export.csv", "store admin export", f"{len(nw)} listings",
             f"{sum(w['variant_id'] in linked for w in nw)} linked", "Prices typed by hand"),
            ("Maple website", "maple_export.csv", "different export screen", f"{len(mp)} listings",
             f"{sum(w['variant_id'] in linked for w in mp)} linked", "Boxes only"),
            ("Bridge", "bridge_mapping.csv", "settings export", f"{len(self.bridge)} mappings",
             f"{len(self.bridge)} read", "Copies Books stock to the websites"),
            ("Customers", "books_customers.csv", "from the Books",
             f"{len(self.customers)} customers", "discounts read from notes", "Discounts are free text"),
        ]


def table_sources(rows):
    if not rows:
        return []
    head, *body = rows
    return [(r[0], ", ".join(f"{h}: {v}" for h, v in zip(head[1:], r[1:]))) for r in body]


# ---------------------------------------------------------------- customers

# Words used in the discount notes -> the sheet categories they cover.
# "Amenities" = guest toiletries (assumption, written in NOTE.md).
EXCLUSION_WORDS = {
    "soap": {"soap bar"},
    "amenit": {"spa amenity", "shampoo", "lotion", "personal care", "soap bar"},
}

def load_customers(path):
    """Discounts are free text in the Books notes. Read what's clear, flag what isn't."""
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["Customer"].upper() == "WEB CUSTOMER":
                continue                          # Bridge's catch-all for unmatched web orders
            note = r["Notes"] or ""
            low = note.lower()
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", note)
            pct = float(m.group(1)) if m else 0.0
            flags = []
            if "stopped" in low or "used to" in low:
                pct, flags = 0.0, ["Discount stopped (Jan 2026)." if "jan 2026" in low else "Discount stopped."]
            unconfirmed = None
            if "??" in note or "check" in low:
                # Safer to quote no discount than a guessed one.
                unconfirmed, pct = pct, 0.0
                flags.append(f"{unconfirmed:g}% discount not confirmed (\"{note}\"). No discount until Dana confirms.")
            excl = set()
            m2 = re.search(r"not on ([a-z ,]+)", low)
            if m2:
                for word, cats in EXCLUSION_WORDS.items():
                    if word in m2.group(1):
                        excl |= cats
            out.append({"name": r["Customer"], "terms": r["Terms"], "note": note,
                        "pct": pct, "unconfirmed": unconfirmed, "exclude": sorted(excl), "flags": flags})
    names = [c["name"] for c in out]
    for c in out:
        twins = [n for n in names if n != c["name"] and (n.startswith(c["name"]) or c["name"].startswith(n))]
        if twins:
            c["flags"].append(f"Also a customer: {', '.join(twins)}. Confirm which one.")
    return out


def discount_for(customer, category):
    """Returns (percent, reason)."""
    if not customer:
        return 0.0, ""
    cat = str(category or "").strip().lower()
    if cat in customer["exclude"]:
        return 0.0, f"No discount on {cat}"
    if customer["pct"]:
        return customer["pct"], f"{customer['pct']:g}% discount"
    if customer.get("unconfirmed"):
        return 0.0, f"No discount ({customer['unconfirmed']:g}% not confirmed)"
    return 0.0, "No discount"
