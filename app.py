"""Northway hub: one place for Dana, Sam, Priya and Marco, built on the six exports.

Run:  python app.py path/to/exports      then open http://localhost:5000
"""
import os
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path

from flask import Flask, abort, make_response, redirect, render_template, request, url_for

from northway.checks import BRIDGE, DANA, SAM
from northway.model import TASK_TYPES, Catalogue, discount_for
from northway.store import Store

ROLES = OrderedDict([
    ("dana",  {"name": "Dana",  "role": "Owner",     "blurb": "Decisions only you can make", "owns": [DANA, BRIDGE]}),
    ("sam",   {"name": "Sam",   "role": "Admin",     "blurb": "Fixes in the sheet, Books and websites", "owns": [SAM]}),
    ("priya", {"name": "Priya", "role": "Sales",     "blurb": "Stock, price and discount in one place", "owns": []}),
    ("marco", {"name": "Marco", "role": "Warehouse", "blurb": "What's arrived but isn't in the Books", "owns": []}),
])

HERE = Path(__file__).resolve().parent
# Exports: `python app.py path/to/exports` locally; on Vercel the bundled ./exports folder.
if __name__ == "__main__" and len(sys.argv) > 1:
    exports = Path(sys.argv[1])
else:
    exports = Path(os.environ.get("NORTHWAY_EXPORTS", HERE / "exports"))
if not (exports / "pricing.xlsx").exists():
    sys.exit(f"Can't find the export files in '{exports}'. Usage: python app.py path/to/exports")
cat = Catalogue(exports)
# Vercel can only write to /tmp, and it is wiped between instances: ticks there are temporary.
store = Store(os.environ.get("NORTHWAY_DB") or ("/tmp/northway.db" if os.environ.get("VERCEL") else str(HERE / "northway.db")))
# Static files live in public/static: Vercel serves public/ from its CDN, Flask serves it locally.
app = Flask(__name__, static_folder="public/static", static_url_path="/static")


def me():
    return ROLES.get(request.cookies.get("who", ""))


# Decisions only Dana can make, answered on the task page. The answer is never written
# to the sheet: it becomes a task for Sam with the exact change to type in.
DECIDE_TYPES = {"set_price", "split_sku"}
PACKS = (("piece", "Piece"), ("dozen", "Dozen"), ("box", "Box"), ("box3plus", "3+ boxes (each)"))


def decision_text(t, d):
    """What Sam has to type, in words he can follow without asking."""
    if t["type"] == "set_price":
        prices = ", ".join(f"{label.lower()} {d[k]:.2f}" for k, label in PACKS if d.get(k))
        return f"Sheet: add Dana's price for {t['product']} ({t['sku']}): {prices}."
    if t["type"] == "split_sku":
        return (f"Sheet, Products tab: change {d['move']} from {t['sku']} to {d['new_sku']}. "
                f"{d['keep']} keeps {t['sku']}.")
    return ""


def derived_tasks():
    out = []
    for tid, d in store.decisions().items():
        t = cat.task_by_id.get(tid)
        if not t:
            continue
        title, why, who = TASK_TYPES["apply_decision"]
        out.append({**t, "id": "d" + tid, "type": "apply_decision", "title": title, "why": why, "who": who,
                    "detail": decision_text(t, d["payload"]), "decision_of": tid,
                    "sources": [("Decided by", f"{d['by']}, {d['at']}")]})
    return out


def all_tasks():
    return cat.tasks + derived_tasks()


def find_task(tid):
    return cat.task_by_id.get(tid) or next((t for t in derived_tasks() if t["id"] == tid), None)


def price_decision(sku):
    """Dana's price for a product, if she set one here and Sam hasn't put it in the sheet yet."""
    for t in cat.tasks_for(kind="set_price", sku=sku):
        d = store.decisions().get(t["id"])
        if d:
            return d
    return None


def read_decision(t, form):
    """Validate Dana's answer. Returns (payload, summary) or raises ValueError with a short message."""
    if t["type"] == "set_price":
        d = {}
        for k, label in PACKS:
            raw = form.get(k, "").strip().replace("$", "").replace(",", "")
            if not raw:
                if k != "box3plus":
                    raise ValueError(f"Enter a {label.lower()} price.")
                continue
            try:
                d[k] = round(float(raw), 2)
            except ValueError:
                raise ValueError(f"{label} price must be a number.")
            if d[k] <= 0:
                raise ValueError(f"{label} price must be more than 0.")
        return d, f"price for {t['sku']}: piece {d['piece']:.2f}, dozen {d['dozen']:.2f}, box {d['box']:.2f}"
    if t["type"] == "split_sku":
        names = [p["name"] for p in cat.by_sku[t["sku"]]]
        keep = form.get("keep")
        new = form.get("new_sku", "").strip().upper()
        if keep not in names:
            raise ValueError("Choose which product keeps the SKU.")
        if not re.fullmatch(r"[A-Z]{2,5}-\d{2,5}", new):
            raise ValueError("New SKU should look like PLW-170.")
        if new in cat.by_sku or any(d["payload"].get("new_sku") == new for d in store.decisions().values()):
            raise ValueError(f"{new} is already used.")
        move = next(n for n in names if n != keep)
        return {"keep": keep, "move": move, "new_sku": new}, f"{keep} keeps {t['sku']}, {move} becomes {new}"
    raise ValueError("This task has nothing to decide.")


def tick_state(t, states=None, decisions=None):
    """'open', 'decided' (Dana answered, Sam's task carries it), 'unconfirmed' (ticked,
    waiting for a newer export) or 'still_wrong' (ticked, but a newer export still shows it).
    A task that's really fixed disappears: the next export no longer produces it."""
    states = store.states() if states is None else states
    decisions = store.decisions() if decisions is None else decisions
    if t["id"] in decisions:
        return "decided"
    s = states.get(t["id"])
    if not s or s["status"] != "done":
        return "open"
    return "unconfirmed" if s.get("export") == cat.export_id else "still_wrong"


def open_tasks(owners=None, kind=None, sku=None):
    states, decisions = store.states(), store.decisions()
    return [t for t in all_tasks()
            if (not owners or t["who"] in owners) and (not kind or t["type"] == kind)
            and (not sku or t["sku"] == sku) and tick_state(t, states, decisions) in ("open", "still_wrong")]


def unconfirmed_tasks():
    states, decisions = store.states(), store.decisions()
    return [t for t in all_tasks() if tick_state(t, states, decisions) == "unconfirmed"]


# Home figures per person: each one counts that person's own open tasks, so they add up.
TILES = {
    "dana": [("Prices to set", {"set_price"}), ("SKU to split", {"split_sku"}),
             ("Listings to connect in Bridge", {"connect_bridge"})],
    "sam": [("Shipments to enter", {"enter_shipment"}),
            ("Sheet fixes", {"fix_category", "delete_empty_row", "remove_category", "apply_decision", "record_old_code"}),
            ("Website fixes", {"update_web_price", "choose_listing"})],
}


def grouped(tasks):
    by = Counter(t["type"] for t in tasks)
    return [(k, TASK_TYPES[k][0], TASK_TYPES[k][1], by[k]) for k in TASK_TYPES if by[k]]


@app.context_processor
def inject():
    return {"me": me(), "role_key": request.cookies.get("who", ""), "roles": ROLES}


@app.before_request
def need_role():
    if request.endpoint not in ("who", "static") and not me():
        return redirect(url_for("who"))


@app.route("/who", methods=["GET", "POST"])
def who():
    if request.method == "POST" and request.form.get("who") in ROLES:
        resp = make_response(redirect(url_for("home")))
        resp.set_cookie("who", request.form["who"], max_age=60 * 60 * 24 * 365)
        return resp
    return render_template("who.html")


@app.route("/")
def home():
    key = request.cookies["who"]
    if key == "priya":
        return redirect(url_for("products"))
    if key == "marco":
        return render_template("home_marco.html", arrivals=open_tasks(kind="enter_shipment"))
    mine = open_tasks(ROLES[key]["owns"])
    tiles = [(label, sum(1 for t in mine if t["type"] in kinds)) for label, kinds in TILES[key]]
    waiting = unconfirmed_tasks()
    return render_template("home.html", n=len(mine), tiles=tiles, groups=grouped(mine), activity=store.activity(8),
                           waiting=len(waiting), waiting_mine=sum(1 for t in waiting if t["who"] in ROLES[key]["owns"]))


@app.route("/tasks")
def tasks():
    kind = request.args.get("type")
    owners = None if request.args.get("all") else ROLES[request.cookies["who"]]["owns"] or None
    items = open_tasks(owners, kind)
    title = TASK_TYPES[kind][0] if kind in TASK_TYPES else "To do"
    return render_template("tasks.html", items=items, groups=grouped(open_tasks(owners)), title=title, kind=kind)


@app.route("/task/<tid>", methods=["GET", "POST"])
def task(tid):
    t = find_task(tid) or abort(404)
    can_decide = t["type"] in DECIDE_TYPES and me()["name"] == DANA
    error = None
    if request.method == "POST":
        action = request.form.get("action") or request.form.get("status", "done")
        if action == "undo" and can_decide:
            store.undo_decision(t, me()["name"])
            return redirect(url_for("task", tid=tid))
        if action == "decide" and can_decide:
            try:
                payload, summary = read_decision(t, request.form)
            except ValueError as e:
                error = str(e)
            else:
                store.decide(t, payload, me()["name"], summary)
                action = "done"
        elif action in ("done", "open"):
            store.set_status(t, action, me()["name"], cat.export_id if action == "done" else None)
        if not error:
            nxt = [x for x in open_tasks(kind=t["type"]) if x["id"] != tid]
            return redirect(url_for("task", tid=nxt[0]["id"]) if nxt and action == "done"
                            else url_for("tasks", type=t["type"]))
    state = store.states().get(tid)
    decision = store.decisions().get(tid)
    tick = tick_state(t)
    names = [p["name"] for p in cat.by_sku.get(t["sku"], [])] if t["type"] == "split_sku" else []
    return render_template("task.html", t=t, state=state, product=cat.by_id.get(t["product_id"]),
                           can_decide=can_decide, decision=decision, decision_text=decision_text(t, decision["payload"]) if decision else "",
                           names=names, form=request.form, error=error, packs=PACKS, tick=tick), (400 if error else 200)


@app.route("/products")
def products():
    q = request.args.get("q", "")
    rows = [(p, light(p)) for p in cat.find(q)]
    return render_template("products.html", rows=rows, q=q)


@app.route("/product/<pid>")
def product(pid):
    p = cat.by_id.get(pid) or abort(404)
    names = [c["name"] for c in cat.customers]
    cname = request.args.get("customer", "")
    customer = next((c for c in cat.customers if c["name"] == cname), None)
    return render_template("product.html", p=p, v=product_view(p, customer, request.cookies.get("who")), customers=names,
                           customer=customer, tasks=open_tasks(sku=p["sku"]), cat_as_of=cat.books_as_of)


@app.route("/sources")
def sources():
    years = sorted({r[2][:4] for r in cat.stale_bridge})
    return render_template("sources.html", sources=cat.sources(), stale=len(cat.stale_bridge),
                           stale_years="-".join(dict.fromkeys([years[0], years[-1]])) if years else "")


@app.route("/activity")
def activity():
    return render_template("activity.html", items=store.activity(200))


# ------------------------------------------------------------ helpers

def pending_pieces(p):
    """Pieces that arrived but the Books export doesn't show. Based on the data only:
    ticking a task in the app doesn't change what the Books export says."""
    if not any(t["type"] == "enter_shipment" for t in cat.tasks_for(sku=p["sku"])):
        return 0
    return sum((s["cases"] or 0) * (s["pcs_per_case"] or 0) for s in p["arrived"])


def ticked_note(p):
    states = store.states()
    for t in cat.tasks_for(kind="enter_shipment", sku=p["sku"]):
        s = states.get(t["id"])
        if s and s["status"] == "done":
            return f" {s['by']} marked it entered on {s['at'][:10]}; the next Books export will confirm."
    return ""


def light(p):
    """green / amber / red for the product list: can Priya quote it right now?"""
    dana_price = p["price_status"] != "priced" and not p["shared_sku"] and price_decision(p["sku"])
    if (p["shared_sku"] or p["price_status"] != "priced") and not dana_price:
        return "red", "No price"
    qty = p["book"]["qty"] if p["book"] else None
    if not qty:
        return ("amber", "Not entered") if pending_pieces(p) else ("red", "Out of stock")
    if p["old_rate"]:
        return "amber", "Old rate"
    if any(t["type"] in ("update_web_price", "choose_listing") for t in open_tasks(sku=p["sku"])):
        return "amber", "Website price off"
    if dana_price:
        return "amber", "Dana's price"
    return "green", "Ready"


# What to do about stock that arrived but isn't in the Books, depending on who's reading.
ARRIVED_NEXT = {"marco": "Tell Sam it's here.", "sam": "Enter it in the Books.",
                "dana": "Waiting for Sam to enter it.", "priya": "Marco can confirm it's on the shelf."}


def product_view(p, customer, role=None):
    qty = p["book"]["qty"] if p["book"] else None
    pending = pending_pieces(p)
    box = p["pcs_per_box"] or 0
    if p["shared_sku"]:
        stock = ("red", "SKU shared with another product. Waiting for Dana.")
    elif qty:
        stock = ("green", f"{qty:,.0f} pieces in stock ({qty // box:,.0f} boxes)" if box else f"{qty:,.0f} pieces in stock")
    elif pending:
        stock = ("amber", f"0 in the Books, but {pending:,} pieces arrived. Not entered yet. "
                          + ARRIVED_NEXT.get(role, ARRIVED_NEXT["priya"]) + ticked_note(p))
    else:
        stock = ("red", "Out of stock.")

    pct, why = discount_for(customer, p["category"])
    packs = []
    price_note = None
    dana = None if p["shared_sku"] or p["price_status"] == "priced" else price_decision(p["sku"])
    if dana:
        # Dana decided here; Priya can quote it now, clearly marked until it's in the sheet.
        price_note = f"Dana's price from {dana['at'][:10]}. Not in the sheet yet, Sam is adding it."
        names = {"piece": "Piece", "dozen": "Dozen", "box": f"Box of {box}", "box3plus": "3+ boxes (each)"}
        for key, label in names.items():
            v = dana["payload"].get(key)
            if v:
                packs.append({"label": label, "sheet": v, "final": round(v * (1 - pct / 100), 2),
                              "northway": None, "nw_off": False, "maple": None})
        price_msg = None
    elif p["price"] and p["price_status"] == "priced":
        site = {(w["store"], w["pack"]): w["price"] for w in p["web"]}
        for label, key in (("Piece", "piece"), ("Dozen", "dozen"), (f"Box of {box}", "box"), (f"3+ boxes (each)", "box3plus")):
            sheet_price = p["price"][key]
            if sheet_price is None:
                continue
            nw = site.get(("Northway", key)) if key != "box3plus" else None
            packs.append({"label": label, "sheet": sheet_price, "final": round(sheet_price * (1 - pct / 100), 2),
                          "northway": nw, "nw_off": nw is not None and abs(nw - sheet_price) >= 0.01,
                          "maple": site.get(("Maple", key)) if key == "box" else None})
        price_msg = None
        if p["old_rate"]:
            price_note = (f"Priced on the old {p['category']} rate. Dana confirmed the newer, lower rate; "
                          "Sam is fixing the sheet. The price drops after the next nightly run.")
    else:
        price_msg = {"not_priced": "No price yet. Ask Dana.",
                     "blocked": "No price: category typo. Sam is fixing it.",
                     "duplicate_sku": "No price: SKU shared. Waiting for Dana."
                     }.get(p["price_status"], "No price in the sheet.")
        if cat.tasks_for(kind="delete_empty_row", sku=p["sku"]):
            price_msg = "No price: an empty row in the Categories tab. Sam is fixing it."
    if p["shared_sku"] and any(store.decisions().get(t["id"]) for t in cat.tasks_for(kind="split_sku", sku=p["sku"])):
        price_msg = "No price: SKU shared. Dana decided, Sam is updating the sheet."
    return {"stock": stock, "packs": packs, "price_msg": price_msg, "price_note": price_note, "pct": pct, "why": why}


if __name__ == "__main__":
    print(f"Northway hub: {len(cat.products)} products, {len(cat.tasks)} tasks. Open http://localhost:5000")
    app.run(port=5000, debug=False)
