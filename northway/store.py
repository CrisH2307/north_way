"""The app's own small memory: which tasks people marked done, Dana's decisions, and an activity log.

This is the only thing the app writes, and it writes it to its own file
(northway.db), never to the exports, the Books, Bridge or the websites.
"""
import json
import sqlite3
from datetime import datetime


class Store:
    def __init__(self, path="northway.db"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS task_state (task_id TEXT PRIMARY KEY, status TEXT, by TEXT, at TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS activity (at TEXT, who TEXT, text TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS decision (task_id TEXT PRIMARY KEY, payload TEXT, by TEXT, at TEXT)")
        # Which set of exports was loaded when the task was ticked (older databases lack it).
        cols = [r[1] for r in self.db.execute("PRAGMA table_info(task_state)")]
        if "export" not in cols:
            self.db.execute("ALTER TABLE task_state ADD COLUMN export TEXT")
        self.db.commit()

    def states(self):
        return {r[0]: {"status": r[1], "by": r[2], "at": r[3], "export": r[4]}
                for r in self.db.execute("SELECT task_id, status, by, at, export FROM task_state")}

    def set_status(self, task, status, who, export=None):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.db.execute("INSERT OR REPLACE INTO task_state (task_id, status, by, at, export) VALUES (?, ?, ?, ?, ?)",
                        (task["id"], status, who, now, export))
        verb = "marked fixed" if status == "done" else "reopened"
        self.db.execute("INSERT INTO activity VALUES (?, ?, ?)",
                        (now, who, f"{verb} '{task['title']}' for {task['sku'] or task['product']}"))
        self.db.commit()

    def activity(self, limit=30):
        return [{"at": r[0], "who": r[1], "text": r[2]}
                for r in self.db.execute("SELECT at, who, text FROM activity ORDER BY at DESC LIMIT ?", (limit,))]

    # ---------------------------------------------------------- decisions
    # A decision is Dana's answer (a price, which product keeps a SKU, ...).
    # It is never written into the sheet: it becomes a task for Sam to type in.

    def decisions(self):
        return {r[0]: {"payload": json.loads(r[1]), "by": r[2], "at": r[3]}
                for r in self.db.execute("SELECT task_id, payload, by, at FROM decision")}

    def decide(self, task, payload, who, summary):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.db.execute("INSERT OR REPLACE INTO decision VALUES (?, ?, ?, ?)", (task["id"], json.dumps(payload), who, now))
        self.db.execute("INSERT OR REPLACE INTO task_state (task_id, status, by, at) VALUES (?, ?, ?, ?)", (task["id"], "done", who, now))
        self.db.execute("INSERT INTO activity VALUES (?, ?, ?)", (now, who, f"decided: {summary}"))
        self.db.commit()

    def undo_decision(self, task, who):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.db.execute("DELETE FROM decision WHERE task_id = ?", (task["id"],))
        self.db.execute("DELETE FROM task_state WHERE task_id IN (?, ?)", (task["id"], "d" + task["id"]))
        self.db.execute("INSERT INTO activity VALUES (?, ?, ?)", (now, who, f"changed their mind on {task['sku'] or task['product']}"))
        self.db.commit()
