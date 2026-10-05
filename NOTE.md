# NOTE: Northway

## What Dana actually needs

The answers exist (Books, sheet, Shipments tab, customer notes), but they disagree and only Dana knows which to trust. So everything goes through her: one washcloth order took 3 questions to Dana and 80 minutes while 6,000 sat in the warehouse. She asked for "one dashboard with everything" but would look first at "what's broken". So: one place in the middle, each person sees their part. I got there by tracing WCL-101 through all six files.

## What I built, and for whom

**Northway hub** (`python app.py exports`): a local web app with one catalogue in the middle. Every product gets its own ID, linked to its rows in all six files (by SKU or old code, never by name).

- **Dana (25):** only what she can act on. She decides on the page (a price, who keeps PLW-141); it becomes a Sam task with the exact change, and Priya can quote it at once, marked "not in the sheet yet". Plus Bridge listings (she has the login).
- **Sam (37):** one task per product, with the source of each number. A tick stays "not confirmed" until a newer export stops showing the problem; if it still shows, the task comes back.
- **Priya:** one lookup (SKU, name or old code): stock incl. "arrived, not in the Books", price, discount. The washcloth order: one lookup, not three texts.
- **Marco:** what's arrived but isn't in the Books yet.

Dana's rules: Books = stock, sheet = price. The hub never edits any source; decisions and ticks live in its own small database. All mess handled in code. No costs, no passwords, no AI.

## What I found

| Found | Count | Who |
|---|---|---|
| In the warehouse, Books show 0 (WCL-101) | 1 | Sam |
| No price: never set (ROB-147, LTN-136) / shared SKU (PLW-141) | 2 / 1 | Dana |
| No price: category typos / empty "Bed Skirt" row read first (BSK-138) | 3 / 1 | Sam |
| Old rate: "Furniture" listed twice, old row used (FUR-137) | 1 | Sam |
| Northway prices differ from the sheet (Maple all match) | 36 (12 products) | Sam |
| Same SKU on two listings (8: box of 12 shares the dozen code) | 9 | Sam |
| Bridge: listings missing / last synced 2024-25 (Sam: they work; a note only) | 22 / 19 | Dana |
| Old Books codes missing from the sheet | 10 | Sam |
| Discounts: Harbourview twins, Aldridge "5%??" (not applied), Riverside stopped, Pinecrest | 4 | Priya |

## Assumptions and what I ignored

- Confirmed by Dana and Sam: exact category match, first matching row wins, second Furniture row is current, Maple CAD = sheet box price.
- Assumed: cases filled + Books at 0 = "arrived, not entered"; "amenities" = shampoo, lotion, personal care, spa amenity, soap. Unclear discounts are shown, not applied.
- Ignored on purpose: USD prices, costs, margins.

## Next, and not building

- **Next:** read the exports nightly (the tick check is ready for it); "copy" buttons for Sam and Priya; an "In Books" column on the Shipments tab.
- **Not building:** anything that writes to the Books, Bridge, the sheet or the websites.

Time: about 4 hours for the first version, plus about 3 hours revising after review.

*Built with AI coding help (Claude); every finding checked against the files; 34 tests.*
