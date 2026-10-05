"""Run with:  python -m unittest   (expects the export files in ./exports, or set EXPORTS=path)"""
import os
import unittest
from pathlib import Path

from northway.checks import run_all
from northway.load import load_all, load_books, money, sku_base

EXPORTS = Path(os.environ.get("EXPORTS", "exports"))


class Helpers(unittest.TestCase):
    def test_sku_base(self):
        self.assertEqual(sku_base("WCL-101-6"), "WCL-101")
        self.assertEqual(sku_base("SOP-150-CS"), "SOP-150")
        self.assertIsNone(sku_base("NW-HTW152"))      # old code, matched separately

    def test_money(self):
        self.assertEqual(money("$1,220.99"), 1220.99)
        self.assertIsNone(money(""))


@unittest.skipUnless((EXPORTS / "pricing.xlsx").exists(), "export files not found")
class OnRealExports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_all(EXPORTS)
        cls.issues = run_all(cls.data)

    def find(self, check, sku=""):
        return [i for i in self.issues if i.check == check and i.sku == sku]

    def test_books_skips_title_lines_and_total_row(self):
        items, as_of = load_books(EXPORTS / "books_item_list.csv")
        self.assertTrue(all(isinstance(i["id"], int) for i in items))
        self.assertIn("September 29", as_of)

    def test_category_rules_are_not_categories(self):
        names = [c for c, _ in self.data["sheet"].categories]
        self.assertNotIn("3+ box = customer orders three or more boxes of one product", names)

    def test_washcloth_arrived_but_not_in_books(self):         # Priya's 8:12 text
        self.assertEqual(len(self.find("Arrived but not in the Books", "WCL-101")), 1)

    def test_washcloth_box_price_differs(self):                # Priya's 9:06 text
        rows = self.find("Website price differs from the sheet")[0].rows
        self.assertIn(["WCL-101-6", "Classic Washcloth 700", "Northway", "box", "437.77", "412.99"], rows)

    def test_robe_has_no_price(self):                          # Priya's 11:47 text
        self.assertEqual(len(self.find("No price set", "ROB-147")), 1)

    def test_blocked_products_explained_by_category(self):
        for sku in ("PLW-143", "TWL-144", "WIP-145"):
            self.assertIn("isn't spelled exactly", self.find("Price program blocked", sku)[0].problem)

    def test_heading_row_is_not_a_duplicate_category(self):     # Sam: empty Bed Skirt row is a heading
        twice = [i.product for i in self.issues if i.check == "Category listed twice"]
        self.assertEqual(twice, ["Furniture"])

    def test_bed_skirt_is_an_empty_row_not_a_missing_price(self):    # Sam's email; Phin's review
        self.assertEqual(self.find("No price set", "BSK-138"), [])
        issue = self.find("Empty category row hides the real one", "BSK-138")[0]
        self.assertEqual(issue.who, "Sam")
        self.assertIn("row 11", issue.action)

    def test_furniture_priced_on_old_row(self):                      # Dana's email: second row is current
        issue = self.find("Category listed twice", "FUR-137")[0]
        self.assertEqual(issue.who, "Sam")
        self.assertIn("old rate", issue.problem)
        self.assertIn("row 22", issue.action)

    def test_duplicate_sku_in_sheet(self):
        self.assertEqual(len(self.find("Same SKU on two products", "PLW-141")), 1)

    def test_no_costs_in_output(self):                         # Marco and Leo shouldn't see costs
        text = " ".join(str(i) for i in self.issues).lower()
        self.assertNotIn("cost/pc", text)


if __name__ == "__main__":
    unittest.main()
