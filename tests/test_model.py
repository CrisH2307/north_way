"""Run with:  python -m unittest   (expects the export files in ./exports, or set EXPORTS=path)"""
import os
import unittest
from pathlib import Path

from northway.model import Catalogue, discount_for

EXPORTS = Path(os.environ.get("EXPORTS", "exports"))


@unittest.skipUnless((EXPORTS / "pricing.xlsx").exists(), "export files not found")
class CatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalogue(EXPORTS)
        cls.customers = {c["name"]: c for c in cls.cat.customers}

    def test_every_product_has_its_own_id(self):
        ids = [p["id"] for p in self.cat.products]
        self.assertEqual(len(ids), len(set(ids)))

    def test_shared_sku_is_not_linked_until_dana_chooses(self):        # PLW-141
        for p in self.cat.by_sku["PLW-141"]:
            self.assertTrue(p["shared_sku"])
            self.assertIsNone(p["book"])

    def test_washcloth_links_to_books_and_website(self):
        p = self.cat.by_sku["WCL-101"][0]
        self.assertEqual(p["book"]["item"], "WCL-101")
        self.assertEqual({w["pack"] for w in p["web"]}, {"piece", "dozen", "box"})

    def test_old_books_code_is_linked(self):                          # NW-HTW152 -> HTW-152
        self.assertEqual(self.cat.by_sku["HTW-152"][0]["book"]["item"], "NW-HTW152")

    def test_pinecrest_gets_no_discount_on_soap(self):                # Priya's 4:02 text
        pct, _ = discount_for(self.customers["Pinecrest Lodge"], "Soap Bar")
        self.assertEqual(pct, 0)
        pct, _ = discount_for(self.customers["Pinecrest Lodge"], "Robe")
        self.assertEqual(pct, 10)

    def test_pinecrest_gets_no_discount_on_amenities(self):           # "not on soap or amenities"
        for cat in ("Shampoo", "Lotion", "Spa Amenity"):
            self.assertEqual(discount_for(self.customers["Pinecrest Lodge"], cat)[0], 0)

    def test_unconfirmed_discount_is_not_applied(self):               # Aldridge "5%??"
        pct, why = discount_for(self.customers["The Aldridge"], "Bath Towel")
        self.assertEqual(pct, 0)
        self.assertIn("not confirmed", why)

    def test_stale_bridge_dates_are_not_tasks(self):                  # Sam: "it still works"
        self.assertEqual(self.cat.tasks_for(kind="check_bridge"), [])
        self.assertEqual(len(self.cat.stale_bridge), 19)

    def test_website_prices_grouped_by_product(self):
        tasks = self.cat.tasks_for(kind="update_web_price")
        self.assertEqual(len(tasks), len({t["sku"] for t in tasks}))
        washcloth = self.cat.tasks_for(kind="update_web_price", sku="WCL-101")[0]
        self.assertIn("437.77 to 412.99", washcloth["detail"])

    def test_search_by_old_code(self):
        self.assertEqual([p["sku"] for p in self.cat.find("SOAP-OLD-7")], ["SOP-134"])

    def test_harbourview_twins_are_flagged(self):                     # Priya's 9:21 text
        self.assertTrue(any("Also a customer" in f for f in self.customers["Harbourview Inn"]["flags"]))

    def test_unclear_and_stopped_discounts_are_flagged(self):
        self.assertTrue(self.customers["The Aldridge"]["flags"])
        self.assertEqual(self.customers["Riverside Suites"]["pct"], 0)

    def test_tasks_have_stable_ids(self):
        again = Catalogue(EXPORTS)
        self.assertEqual([t["id"] for t in self.cat.tasks], [t["id"] for t in again.tasks])


if __name__ == "__main__":
    unittest.main()
