"""Dana decides on the task page; the decision becomes a task for Sam. Uses a temporary database."""
import os
import tempfile
import unittest
from pathlib import Path

EXPORTS = Path(os.environ.get("EXPORTS", "exports"))


@unittest.skipUnless((EXPORTS / "pricing.xlsx").exists(), "export files not found")
class DecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["NORTHWAY_EXPORTS"] = str(EXPORTS)
        os.environ["NORTHWAY_DB"] = str(Path(cls.tmp.name) / "test.db")
        import app as hub
        cls.hub = hub
        cls.c = hub.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.hub.store.db.close()
        cls.tmp.cleanup()

    def as_(self, who):
        self.c.set_cookie("who", who)

    def task(self, kind, sku=None):
        return next(t for t in self.hub.cat.tasks if t["type"] == kind and (not sku or t["sku"] == sku))

    def sam_task_for(self, tid):
        return next((t for t in self.hub.open_tasks() if t.get("decision_of") == tid), None)

    def test_dana_sets_a_price_and_sam_gets_the_exact_values(self):
        t = self.task("set_price", "ROB-147")
        self.as_("dana")
        r = self.c.post(f"/task/{t['id']}", data={"action": "decide", "piece": "42", "dozen": "450", "box": "880"})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn(t["id"], [x["id"] for x in self.hub.open_tasks()])       # Dana's task is done
        sam = self.sam_task_for(t["id"])
        self.assertEqual(sam["who"], "Sam")
        self.assertIn("piece 42.00, dozen 450.00, box 880.00", sam["detail"])

        # Priya can quote it right away, marked as not in the sheet yet
        self.as_("priya")
        page = self.c.get(f"/product/{t['product_id']}").get_data(as_text=True)
        self.assertIn("Not in the sheet yet", page)
        self.assertIn("880.00", page)

        # Changing her mind removes Sam's task and reopens hers
        self.as_("dana")
        self.c.post(f"/task/{t['id']}", data={"action": "undo"})
        self.assertIsNone(self.sam_task_for(t["id"]))
        self.assertIn(t["id"], [x["id"] for x in self.hub.open_tasks()])

    def test_bad_price_is_refused(self):
        t = self.task("set_price", "LTN-136")
        self.as_("dana")
        r = self.c.post(f"/task/{t['id']}", data={"action": "decide", "piece": "abc", "dozen": "1", "box": "1"})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(self.sam_task_for(t["id"]))

    def test_new_sku_must_be_unused(self):
        t = self.task("split_sku", "PLW-141")
        self.as_("dana")
        r = self.c.post(f"/task/{t['id']}", data={"action": "decide", "keep": "Spa Pillows 485", "new_sku": "WCL-101"})
        self.assertEqual(r.status_code, 400)
        self.c.post(f"/task/{t['id']}", data={"action": "decide", "keep": "Spa Pillows 485", "new_sku": "plw-170"})
        self.assertIn("change Premium Pillows 369 from PLW-141 to PLW-170", self.sam_task_for(t["id"])["detail"])

    def test_only_dana_can_decide(self):
        t = self.task("set_price", "ROB-147")
        self.as_("sam")
        self.c.post(f"/task/{t['id']}", data={"action": "decide", "piece": "1", "dozen": "1", "box": "1"})
        self.assertIsNone(self.sam_task_for(t["id"]))

    def test_tick_is_checked_against_the_next_export(self):
        t = self.task("fix_category")
        self.as_("sam")
        self.c.post(f"/task/{t['id']}", data={"status": "done"})
        self.assertEqual(self.hub.tick_state(t), "unconfirmed")
        self.assertNotIn(t["id"], [x["id"] for x in self.hub.open_tasks()])
        # A newer export arrives and still shows the problem: the task comes back.
        real = self.hub.cat.export_id
        try:
            self.hub.cat.export_id = "newer-export"
            self.assertEqual(self.hub.tick_state(t), "still_wrong")
            self.assertIn(t["id"], [x["id"] for x in self.hub.open_tasks()])
            page = self.c.get(f"/task/{t['id']}").get_data(as_text=True)
            self.assertIn("latest export still shows it", page)
        finally:
            self.hub.cat.export_id = real

    def test_dana_tiles_add_up_to_her_headline(self):
        self.as_("dana")
        page = self.c.get("/").get_data(as_text=True)
        mine = self.hub.open_tasks(self.hub.ROLES["dana"]["owns"])
        self.assertIn(f"{len(mine)} waiting for you", page)
        self.assertNotIn("Shipments to enter", page)

    def test_marco_is_not_told_to_check_with_marco(self):
        pid = self.hub.cat.by_sku["WCL-101"][0]["id"]
        self.as_("marco")
        page = self.c.get(f"/product/{pid}").get_data(as_text=True)
        self.assertNotIn("check with Marco", page)
        self.assertIn("Tell Sam", page)

    def test_plain_words_not_raw_status(self):
        self.as_("dana")
        for t in self.hub.cat.tasks:
            self.assertNotIn("not_priced", str(t["sources"]) + t["detail"])


if __name__ == "__main__":
    unittest.main()
