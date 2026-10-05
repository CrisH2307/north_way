"""The checks. Each one compares two or more sources and says, in plain words,
what disagrees, where each number came from, and who can fix it.

Nothing here writes to any file. Dana's own rules decide which source wins:
  - stock: the Books are right (but they lag after a container lands)
  - price: the sheet (Prices (auto) tab) is right
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .load import OLD_NW_CODE, sku_base

DANA, SAM, BRIDGE = "Dana", "Sam", "Bridge"


@dataclass
class Issue:
    check: str                 # short check name
    who: str                   # who can fix it
    sku: str
    product: str
    problem: str               # one plain sentence
    action: str                # what to do
    evidence: list = field(default_factory=list)   # (source, what it says)
    rows: list = field(default_factory=list)       # optional table rows for grouped issues


def run_all(data):
    sheet, books, web = data["sheet"], data["books"], data["web"]
    names = {p["sku"]: p["name"] for p in sheet.products}
    books_by_base, matched_by_pattern = match_books_to_sheet(sheet, books)
    issues = []
    # Order = order on the page: what loses sales first, quick fixes next, long lists last.
    issues += arrived_not_in_books(sheet, books_by_base, web, names, data["books_as_of"])
    issues += no_price(sheet, web, names)
    issues += price_program_blocked(sheet, names)
    issues += website_price_differs(sheet, web, names)
    issues += duplicate_skus(sheet, web, names)
    issues += bridge_gaps(web, data["bridge"])
    issues += old_codes_missing_from_sheet(matched_by_pattern, names)
    return issues


# ---------------------------------------------------------------- matching

def match_books_to_sheet(sheet, books):
    """Find the Books 'piece' item for each sheet SKU.

    Three ways, in order: same code, the sheet's Old Books SKU column, or the
    older NW-XXX### pattern (e.g. NW-HTW152 = HTW-152), which Sam said isn't
    always written in the sheet. Never matched by product name.
    """
    old_col = {p["old_books_sku"]: p["sku"] for p in sheet.products if p["old_books_sku"]}
    by_base, by_pattern = {}, []
    for item in books:
        if item["type"] != "Inventory Part":
            continue
        code = item["item"]
        if sku_base(code) == code:
            base = code
        elif code in old_col:
            base = old_col[code]
        elif OLD_NW_CODE.match(code):
            m = OLD_NW_CODE.match(code)
            base = f"{m.group(1)}-{m.group(2)}"
            by_pattern.append((base, code))
        else:
            continue
        by_base[base] = item
    return by_base, by_pattern


def web_rows_for(web, base):
    return [w for w in web if sku_base(w["sku"]) == base and w["status"] != "archived"]


def the_price_row(sheet, base):
    rows = sheet.prices.get(base, [])
    return rows[0] if len(rows) == 1 else None


# ---------------------------------------------------------------- 1. stock

def arrived_not_in_books(sheet, books_by_base, web, names, books_as_of):
    """Shipments logged in the sheet that the Books don't show yet (Marco's 'fifty cases')."""
    out = []
    for s in sheet.shipments:
        noted = "not in books" in str(s["notes"] or "").lower()
        if s["cases"] is None and not noted:
            continue                      # older rows: no case count, assumed already entered
        book = books_by_base.get(s["sku"])
        qty = book["qty"] if book else None
        if qty not in (0, None) and not noted:
            continue
        pieces = (s["cases"] or 0) * (s["pcs_per_case"] or 0)
        shown = "no matching item" if book is None else f"{qty or 0:g}"
        site = ", ".join(f"{w['store']} {w['pack']}: {w['stock']:g}" for w in web_rows_for(web, s["sku"]))
        out.append(Issue(
            "Arrived but not in the Books", SAM, s["sku"], names.get(s["sku"], ""),
            f"{s['cases']} cases ({pieces:,} pieces) are in the warehouse, but the Books "
            f"show {shown} and the website copies the Books.",
            "Enter this shipment into the Books. Until then, staff can sell it but every screen says 0.",
            [("Sheet, Shipments tab", f"arrived '{s['arrived']}', {s['cases']} cases x {s['pcs_per_case']} pcs, note: {s['notes'] or '-'}"),
             (f"Books ({books_as_of})", f"{book['item']}: {shown} on hand" if book else shown),
             ("Websites (stock via Bridge)", site or "not listed")]))
    return out


# ---------------------------------------------------------------- 2. price

def website_price_differs(sheet, web, names):
    """Website prices are typed by hand; the sheet is updated every night.
    One grouped item: Sam works through it as a list."""
    pcs_per_box = {p["sku"]: p["pcs_per_box"] for p in sheet.products}
    rows = []
    for w in web:
        base = sku_base(w["sku"])
        price = the_price_row(sheet, base)
        if w["status"] == "archived" or not price or price["status"] != "priced":
            continue                      # unpriced / blocked / duplicates: see their own checks
        sheet_price = price[w["pack"]]
        size_note = ""
        if w["pack"] == "box" and w["pack_size"] and pcs_per_box.get(base) and w["pack_size"] != pcs_per_box[base]:
            size_note = f" (site box of {w['pack_size']}, sheet box of {pcs_per_box[base]})"
        if sheet_price is None or (w["price"] is not None and abs(w["price"] - sheet_price) < 0.01 and not size_note):
            continue
        rows.append([w["sku"], names.get(base, ""), w["store"], f"{w['pack']}{size_note}",
                     f"{w['price']:,.2f}" if w["price"] is not None else "-", f"{sheet_price:,.2f}"])
    if not rows:
        return []
    products = len({sku_base(r[0]) for r in rows})
    return [Issue("Website price differs from the sheet", SAM, "", f"{products} products",
                  f"{len(rows)} website prices don't match the sheet.",
                  "Change each website price to the sheet price (Dana: 'sheet, always the sheet').",
                  rows=[["SKU", "Product", "Store", "Pack", "Website", "Sheet"]] + sorted(rows))]


# ---------------------------------------------------------------- 3. no price

def first_category_row(sheet, category):
    """The row the price program actually uses: the first one with exactly this name."""
    return next((r for r in sheet.category_rows if r[1] == category), None)


def no_price(sheet, web, names):
    """No price in the sheet. First rule out the sheet's own cause (an empty category row
    above the real one, confirmed by Sam); only then is it a price Dana has to decide."""
    out = []
    notes = {p["sku"]: p["notes"] for p in sheet.products}
    category = {p["sku"]: p["category"] for p in sheet.products}
    for base, rows in sorted(sheet.prices.items()):
        if not any(r["status"] == "not_priced" for r in rows):
            continue
        cat = category.get(base)
        first = first_category_row(sheet, cat)
        real = next((r for r in sheet.category_rows if r[1] == cat and r[2]), None)
        if first and real and first[2] is None:
            out.append(Issue("Empty category row hides the real one", SAM, base, names.get(base, ""),
                             f"The Categories tab has an empty '{cat}' row (row {first[0]}) above the real one (row {real[0]}). "
                             "The price program reads the empty row, so this product gets no price.",
                             f"Delete the empty '{cat}' row (row {first[0]}) in the Categories tab.",
                             [("Sheet, Categories", f"row {first[0]}: '{cat}', no multipliers"),
                              ("Sheet, Categories", f"row {real[0]}: '{cat}', " + ", ".join(f"{m:g}" for m in real[2])),
                              ("Sheet, Prices (auto)", "no price")]))
            continue
        site = ", ".join(f"{w['store']} {w['pack']}: ${w['price']:,.2f}" for w in web_rows_for(web, base))
        out.append(Issue("No price set", DANA, base, names.get(base, ""),
                         "The price program has no price for this product, so staff have to ask you each time.",
                         "Decide the price (piece / dozen / box) so it's the same for every customer.",
                         [("Sheet, Prices (auto)", "no price"),
                          ("Sheet, Products notes", notes.get(base) or "-"),
                          ("Websites", site or "not listed")]))
    return out


# ---------------------------------------------------------------- 4. blocked

def price_program_blocked(sheet, names):
    """Cause (confirmed by Sam): the Products category must match a Categories row exactly."""
    out = []
    known = [c for c, _ in sheet.categories]
    category = {p["sku"]: p["category"] for p in sheet.products}
    for base, rows in sorted(sheet.prices.items()):
        if not any(r["status"] == "blocked" for r in rows):
            continue
        cat = category.get(base)
        close = closest_category(cat, known)
        problem = "The price program couldn't price this product."
        if cat not in known:
            problem += f" Its category '{cat}' isn't spelled exactly like any Categories row."
        out.append(Issue("Price program blocked", SAM, base, names.get(base, ""), problem,
                         f"Change the category in the Products tab to '{close}'." if close else
                         "Check the category in the Products tab against the Categories tab.",
                         [("Sheet, Prices (auto)", "blocked, no price"),
                          ("Sheet, Products", f"category typed as {cat!r}"),
                          ("Sheet, Categories", f"closest row: {close!r}" if close else "no close match")]))
    # Categories listed twice. The program uses the first row; Dana confirmed the later
    # (second) Furniture row is the current one, so products there are priced on the old rate.
    for name, rows in old_rate_categories(sheet).items():
        old, *newer = rows
        current = newer[-1]
        skus = sorted(p["sku"] for p in sheet.products if p["category"] == name)
        fmt = lambda r: ", ".join(f"{m:g}" for m in r[2])
        out.append(Issue("Category listed twice", SAM, skus[0] if len(skus) == 1 else "", name,
                         f"'{name}' is in the Categories tab twice. The price program uses the first row (old rate), "
                         f"so {', '.join(skus) or 'no products'} {'is' if len(skus) == 1 else 'are'} priced on the old rate. "
                         f"Dana confirmed row {current[0]} is current.",
                         f"Delete row {old[0]} ({fmt(old)}) in the Categories tab.",
                         [(f"Row {old[0]}, old (used now)", fmt(old)), (f"Row {current[0]}, current", fmt(current))]))
    return out


def old_rate_categories(sheet):
    """{category: [rows...]} for categories with more than one row of multipliers."""
    seen = defaultdict(list)
    for r in sheet.category_rows:
        if r[2]:
            seen[r[1]].append(r)
    return {k: v for k, v in seen.items() if len(v) > 1}


def closest_category(cat, known):
    c = str(cat or "").strip().lower()
    for k in known:
        if k.strip().lower() == c:
            return k
    for k in known:
        if k.lower() in c or c in k.lower():
            return k
    return None


# ---------------------------------------------------------------- 5. duplicates

def duplicate_skus(sheet, web, names):
    out = []
    by_sku = defaultdict(list)
    for p in sheet.products:
        by_sku[p["sku"]].append(p)
    for sku, rows in by_sku.items():
        if len(rows) > 1:
            out.append(Issue("Same SKU on two products", DANA, sku, " / ".join(r["name"] for r in rows),
                             f"The sheet uses {sku} for {len(rows)} different products, so neither gets a price.",
                             "Decide which product keeps this SKU; Sam gives the other a new one.",
                             [("Sheet, Products", f"{r['name']} (box of {r['pcs_per_box']}), note: {r['notes'] or '-'}") for r in rows]))
    by_web = defaultdict(list)
    for w in web:
        by_web[(w["store"], w["sku"])].append(w)
    dupes = [rows for _, rows in sorted(by_web.items()) if len(rows) > 1]
    if dupes:
        box12 = sum({r["pack"] for r in rows} == {"dozen", "box"} for rows in dupes)
        table = [["SKU", "Listing", "Status", "Price", "Stock"]]
        for rows in dupes:
            for r in rows:
                pack = r["pack"] + (f" of {r['pack_size']}" if r["pack"] == "box" else "")
                table.append([r["sku"], f"{r['title']} - {pack}", r["status"] or "-", f"{r['price']:,.2f}", f"{r['stock']:g}"])
        out.append(Issue("Same SKU on two website listings", SAM, "", f"{len(dupes)} SKUs",
                         f"{box12} of these are products whose box holds 12: the box code (-12) is the same "
                         "as the dozen code, so one SKU has two listings and two prices.",
                         "For each: decide with Dana whether 'Dozen' and 'Box of 12' are the same thing. "
                         "If yes, remove one listing; if not, give the box its own SKU.",
                         rows=table))
    return out


# ---------------------------------------------------------------- 6. bridge

def bridge_gaps(web, bridge, stale_after_days=7):
    mapped = {b["variant_id"] for b in bridge}
    unmapped = [w for w in web if w["variant_id"] not in mapped and w["status"] != "archived"]
    out = []
    if unmapped:
        out.append(Issue("Website listing not connected to the Books", BRIDGE, "", f"{len(unmapped)} listings",
                         "Bridge has no mapping for these listings, so their website stock never updates.",
                         "Add these mappings in Bridge (Dana has the login). This tool does not change Bridge.",
                         rows=[["Store", "SKU", "Listing", "Website stock"]] +
                              [[w["store"], w["sku"], f"{w['title']} - {w['pack']}", f"{w['stock']:g}"] for w in unmapped]))
    dates = [datetime.strptime(b["last_synced"], "%Y-%m-%d %H:%M") for b in bridge]
    latest = max(dates)
    stale = [(b, d) for b, d in zip(bridge, dates) if d < latest - timedelta(days=stale_after_days)]
    if stale:
        by_id = {w["variant_id"]: w for w in web}
        out.append(Issue("Bridge mapping hasn't synced recently", BRIDGE, "", f"{len(stale)} listings",
                         f"Most listings synced on {latest:%Y-%m-%d}; these haven't synced for months, so their website stock may be frozen.",
                         "Check these mappings in Bridge (Dana has the login). This tool does not change Bridge.",
                         rows=[["Store", "SKU", "Last synced"]] +
                              [[b["store"], by_id.get(b["variant_id"], {}).get("sku", f"variant {b['variant_id']}"), f"{d:%Y-%m-%d}"]
                               for b, d in sorted(stale, key=lambda x: x[1])]))
    return out


# ---------------------------------------------------------------- 7. housekeeping

def old_codes_missing_from_sheet(matched_by_pattern, names):
    if not matched_by_pattern:
        return []
    return [Issue("Old Books code not in the sheet", SAM, "", f"{len(matched_by_pattern)} products",
                  "The Books still use an old code that isn't written in the sheet's 'Old Books SKU' column. "
                  "This tool matched them by the NW-XXX### pattern.",
                  "Add the old code to the 'Old Books SKU' column so anyone can find the product in the Books.",
                  rows=[["Sheet SKU", "Product", "Code in the Books"]] +
                       [[base, names.get(base, "(not in sheet)"), code] for base, code in sorted(matched_by_pattern)])]
