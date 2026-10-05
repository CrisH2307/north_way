# Northway hub

One place for Northway's team, built on the six export files. It links every product
across the sheet, the Books, both websites and Bridge, gives each one its own ID, and
shows each person what they need:

- **Dana**: only what she can act on; she decides on the page (a price, which product keeps a shared SKU) and each decision becomes a task for Sam
- **Sam**: a to-do list of fixes, one per product, each with the source of every number; a tick is confirmed only when a newer export no longer shows the problem
- **Priya**: look up a product by SKU, name or old code: stock, the sheet price and the customer's discount on one screen
- **Marco**: what has arrived but isn't in the Books yet

It only reads the exports. The one thing it writes is its own `northway.db` (ticks, Dana's decisions, activity). Set `NORTHWAY_DB` to use another file.

The take-home brief from Velox is in `BRIEF.md`.

## Run it (about 2 minutes)

Needs Python 3.9+.

```bash
pip install -r requirements.txt
python app.py path/to/exports        # default: ./exports
```

Open http://localhost:5000 and pick a person. No passwords.

A printable one-page report is also available: `python check.py path/to/exports`.

Tests: `EXPORTS=path/to/exports python -m unittest`

## How it's built

- `northway/load.py`: reads each export and handles its mess in code (title rows, TOTAL row, merged headers, `$` prices, blank variant titles, mixed dates)
- `northway/checks.py`: the rules, using Dana's own (Books = stock, sheet = price)
- `northway/model.py`: the catalogue: one ID per product, links to every source, tasks, customer discounts
- `northway/store.py`: task ticks (with the export they were made against), Dana's decisions and the activity log
- `app.py` + `templates/`: the screens
