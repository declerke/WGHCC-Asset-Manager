"""
WGHCC IT Asset & Inventory System · v6.0 Final Edition
Windsor Golf Hotel & Country Club — IT Department
"""

import os, sys, hashlib, sqlite3, uuid, webbrowser
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

import customtkinter as ctk
from tkinter import ttk, messagebox, filedialog
import tkinter as tk
import pandas as pd
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════
APP_TITLE = "WGHCC IT Asset & Inventory System"
DB_FILE   = "wghcc_inventory.db"

CATEGORIES = [
    "Desktop Computers","Laptops","Monitors","Keyboards","Mice",
    "Network Equipment","Cables","Storage Devices","Audio Equipment",
    "Video Equipment","Printers","Scanners","Mobile Devices","Servers",
    "UPS Systems","Tools","Accessories","Software","Other",
]

# ══════════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════
class ItemCondition(Enum):
    NEW="New"; GOOD="Good"; FAIR="Fair"; POOR="Poor"
    OBSOLETE="Obsolete"; NON_FUNCTIONAL="Non-Functional"; UNDER_REPAIR="Under Repair"

class ItemStatus(Enum):
    AVAILABLE="Available"; BORROWED="Borrowed"; MISSING="Missing"
    RESERVED="Reserved"; RETIRED="Retired"

@dataclass
class ITInventoryItem:
    item_id:str; name:str; category:str; quantity:int
    condition:str; status:str; brand:str; model:str
    serial_number:str; purchase_date:str; purchase_price:float
    warranty_expiry:str; supplier:str; specifications:str
    location:str; assigned_to:str; notes:str
    minimum_stock:int; date_added:str; last_updated:str

    @staticmethod
    def generate_id() -> str:
        import time
        return f"WGHCC-IT-{int(time.time()*1000)%1_000_000:06d}"

    def age_years(self) -> float:
        try:
            return (datetime.now() - datetime.strptime(self.purchase_date, "%Y-%m-%d")).days / 365.25
        except Exception:
            return 0.0

    def depreciation(self, rate: float = 0.30) -> dict:
        if self.category == "Software" or self.purchase_price <= 0:
            return {"current": self.purchase_price, "accumulated": 0.0}
        cv = max(0.0, self.purchase_price * ((1 - rate) ** self.age_years()))
        return {"current": round(cv, 2), "accumulated": round(self.purchase_price - cv, 2)}

    def warranty_days(self) -> Optional[int]:
        try:
            return (datetime.strptime(self.warranty_expiry, "%Y-%m-%d") - datetime.now()).days
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE MANAGER
# ══════════════════════════════════════════════════════════════════════════════
class DatabaseManager:
    def __init__(self, db_file: str = DB_FILE):
        self.db_file = db_file
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._migrate()
        self._ensure_admin()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS inventory(
                item_id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT,
                quantity INTEGER DEFAULT 1, condition TEXT, status TEXT,
                brand TEXT, model TEXT, serial_number TEXT UNIQUE,
                purchase_date TEXT, purchase_price REAL DEFAULT 0,
                warranty_expiry TEXT, supplier TEXT, specifications TEXT,
                location TEXT, assigned_to TEXT, notes TEXT,
                minimum_stock INTEGER DEFAULT 1, date_added TEXT, last_updated TEXT
            );
            CREATE TABLE IF NOT EXISTS users(
                user_id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'staff',
                created_at TEXT NOT NULL, created_by TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS audit_log(
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL, username TEXT NOT NULL,
                action TEXT NOT NULL, item_id TEXT, item_name TEXT,
                field_changed TEXT, old_value TEXT, new_value TEXT
            );
            CREATE TABLE IF NOT EXISTS maintenance_log(
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL, item_name TEXT,
                service_date TEXT NOT NULL, service_type TEXT,
                description TEXT, cost REAL DEFAULT 0,
                performed_by TEXT, next_service_date TEXT,
                logged_by TEXT, logged_at TEXT
            );
        """)
        self.conn.commit()

    def _migrate(self):
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(audit_log)")}
        if "username" not in cols:
            self.conn.execute("DROP TABLE IF EXISTS audit_log")
            self.conn.execute("""
                CREATE TABLE audit_log(
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL, username TEXT NOT NULL,
                    action TEXT NOT NULL, item_id TEXT, item_name TEXT,
                    field_changed TEXT, old_value TEXT, new_value TEXT
                )
            """)
            self.conn.commit()

    def _ensure_admin(self):
        if not self.conn.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
            h, s = self._hash("admin123")
            self.conn.execute(
                "INSERT INTO users(user_id,username,password_hash,salt,role,"
                "created_at,created_by,is_active,must_change_password)VALUES(?,?,?,?,?,?,?,1,1)",
                (str(uuid.uuid4()), "admin", h, s, "admin",
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "system")
            )
            self.conn.commit()

    @staticmethod
    def _hash(password: str, salt: bytes = None) -> Tuple[str, str]:
        if salt is None:
            salt = os.urandom(32)
        elif isinstance(salt, str):
            salt = bytes.fromhex(salt)
        key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100_000)
        return key.hex(), salt.hex()

    def authenticate(self, username: str, password: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM users WHERE username=? AND is_active=1", (username,)
        ).fetchone()
        if not row:
            return None
        h, _ = self._hash(password, bytes.fromhex(row["salt"]))
        return dict(row) if h == row["password_hash"] else None

    def get_users(self) -> List[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT user_id,username,role,created_at,is_active,must_change_password "
            "FROM users ORDER BY username"
        ).fetchall()]

    def add_user(self, username: str, password: str, role: str, created_by: str) -> bool:
        try:
            h, s = self._hash(password)
            self.conn.execute(
                "INSERT INTO users(user_id,username,password_hash,salt,role,"
                "created_at,created_by,is_active,must_change_password)VALUES(?,?,?,?,?,?,?,1,1)",
                (str(uuid.uuid4()), username, h, s, role,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"), created_by)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def set_user_active(self, user_id: str, active: bool):
        self.conn.execute("UPDATE users SET is_active=? WHERE user_id=?", (int(active), user_id))
        self.conn.commit()

    def change_password(self, username: str, new_pw: str):
        h, s = self._hash(new_pw)
        self.conn.execute(
            "UPDATE users SET password_hash=?,salt=?,must_change_password=0 WHERE username=?",
            (h, s, username)
        )
        self.conn.commit()

    def log(self, username: str, action: str, item_id: str = "", item_name: str = "",
            field: str = "", old: str = "", new: str = ""):
        self.conn.execute(
            "INSERT INTO audit_log(timestamp,username,action,item_id,item_name,"
            "field_changed,old_value,new_value)VALUES(?,?,?,?,?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username, action,
             item_id, item_name, field, old, new)
        )
        self.conn.commit()

    def get_audit_log(self, limit: int = 2000) -> List[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM audit_log ORDER BY log_id DESC LIMIT ?", (limit,)
        ).fetchall()]

    def get_items(self) -> List[ITInventoryItem]:
        return [ITInventoryItem(**dict(r)) for r in
                self.conn.execute("SELECT * FROM inventory ORDER BY name").fetchall()]

    def add_item(self, item: ITInventoryItem, by: str) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO inventory VALUES(" + ",".join(["?"] * 20) + ")",
                tuple(asdict(item).values())
            )
            self.conn.commit()
            self.log(by, "ADD", item.item_id, item.name)
            return True
        except sqlite3.Error:
            return False

    def update_item(self, item: ITInventoryItem, by: str, orig: ITInventoryItem) -> bool:
        item.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.conn.execute("""
                UPDATE inventory SET name=?,category=?,quantity=?,condition=?,status=?,
                brand=?,model=?,serial_number=?,purchase_date=?,purchase_price=?,
                warranty_expiry=?,supplier=?,specifications=?,location=?,assigned_to=?,
                notes=?,minimum_stock=?,last_updated=? WHERE item_id=?
            """, (item.name, item.category, item.quantity, item.condition, item.status,
                  item.brand, item.model, item.serial_number, item.purchase_date,
                  item.purchase_price, item.warranty_expiry, item.supplier, item.specifications,
                  item.location, item.assigned_to, item.notes, item.minimum_stock,
                  item.last_updated, item.item_id))
            self.conn.commit()
            skip = {"item_id", "date_added", "last_updated"}
            for f in asdict(orig):
                if f not in skip and str(getattr(orig, f)) != str(getattr(item, f)):
                    self.log(by, "EDIT", item.item_id, item.name, f,
                             str(getattr(orig, f)), str(getattr(item, f)))
            return True
        except sqlite3.Error:
            return False

    def delete_item(self, item_id: str, item_name: str, by: str):
        self.conn.execute("DELETE FROM inventory WHERE item_id=?", (item_id,))
        self.conn.commit()
        self.log(by, "DELETE", item_id, item_name)

    def import_excel(self, filename: str, by: str) -> Tuple[int, int, List[str]]:
        try:
            df = pd.read_excel(filename, dtype=str).fillna("")
            df.columns = [c.lower().replace(" ", "_") for c in df.columns]
            ok, fail, errors = 0, 0, []
            existing = {i.serial_number for i in self.get_items() if i.serial_number}
            for idx, row in df.iterrows():
                if not row.get("name") or not row.get("category"):
                    fail += 1; errors.append(f"Row {idx+2}: missing name/category"); continue
                sn = row.get("serial_number", "")
                if sn and sn in existing:
                    fail += 1; errors.append(f"Row {idx+2}: duplicate serial '{sn}'"); continue
                try:
                    item = ITInventoryItem(
                        item_id=ITInventoryItem.generate_id(), name=row.get("name", ""),
                        category=row.get("category", "Other"),
                        quantity=int(row.get("quantity", 1) or 1),
                        condition=row.get("condition", "Good"),
                        status=row.get("status", "Available"),
                        brand=row.get("brand", ""), model=row.get("model", ""),
                        serial_number=sn, purchase_date=row.get("purchase_date", ""),
                        purchase_price=float(row.get("purchase_price", 0) or 0),
                        warranty_expiry=row.get("warranty_expiry", ""),
                        supplier=row.get("supplier", ""),
                        specifications=row.get("specifications", ""),
                        location=row.get("location", "IT Office"),
                        assigned_to=row.get("assigned_to", ""),
                        notes=row.get("notes", ""),
                        minimum_stock=int(row.get("minimum_stock", 1) or 1),
                        date_added=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        last_updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    if self.add_item(item, by):
                        ok += 1
                    else:
                        fail += 1; errors.append(f"Row {idx+2}: DB insert failed")
                except (ValueError, TypeError) as e:
                    fail += 1; errors.append(f"Row {idx+2}: {e}")
            return ok, fail, errors
        except Exception as e:
            return 0, 0, [str(e)]

    def add_maintenance(self, item_id: str, item_name: str, svc_date: str, svc_type: str,
                        desc: str, cost: float, performed_by: str, next_date: str, logged_by: str):
        self.conn.execute(
            "INSERT INTO maintenance_log(item_id,item_name,service_date,service_type,description,"
            "cost,performed_by,next_service_date,logged_by,logged_at)VALUES(?,?,?,?,?,?,?,?,?,?)",
            (item_id, item_name, svc_date, svc_type, desc, cost, performed_by, next_date,
             logged_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        self.conn.commit()
        self.log(logged_by, "MAINTENANCE", item_id, item_name, "service_type", "", svc_type)

    def get_maintenance(self) -> List[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM maintenance_log ORDER BY log_id DESC"
        ).fetchall()]

    def close(self):
        if self.conn:
            self.conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
_TREE_STYLE_APPLIED = False

def export_items_to_excel(items: List[ITInventoryItem], filename: str) -> None:
    """Export selected inventory items to an Excel workbook."""
    pd.DataFrame([asdict(item) for item in items]).to_excel(filename, index=False)


def apply_treeview_style():
    global _TREE_STYLE_APPLIED
    mode = ctk.get_appearance_mode()
    style = ttk.Style()
    if mode == "Dark":
        bg, fg, sel, hbg, hfg = "#2b2b2b", "#f0f0f0", "#1a5c1a", "#1e1e1e", "#cccccc"
    else:
        bg, fg, sel, hbg, hfg = "#ffffff", "#1a1a1a", "#004d00", "#e8f5e9", "#013220"
    style.configure("App.Treeview", background=bg, foreground=fg, fieldbackground=bg,
                    rowheight=28, font=("Calibri", 10), borderwidth=0)
    style.map("App.Treeview", background=[("selected", sel)], foreground=[("selected", "white")])
    style.configure("App.Treeview.Heading", background=hbg, foreground=hfg,
                    font=("Calibri", 10, "bold"), relief="flat", padding=(8, 5))
    style.map("App.Treeview.Heading", relief=[("active", "flat")])
    _TREE_STYLE_APPLIED = True


def make_tree(parent, columns: list, widths: dict) -> ttk.Treeview:
    apply_treeview_style()
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(frame, columns=columns, show="headings",
                        style="App.Treeview", selectmode="browse")
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    for col in columns:
        tree.heading(col, text=col, anchor="w")
        tree.column(col, width=widths.get(col, 120), anchor="w", minwidth=50)
    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return tree


def sortable(tree: ttk.Treeview, col: str, reverse: bool):
    data = [(tree.set(r, col), r) for r in tree.get_children("")]
    try:
        data.sort(key=lambda t: float(str(t[0]).replace("KES", "").replace(",", "").strip()),
                  reverse=reverse)
    except ValueError:
        data.sort(key=lambda t: t[0].lower(), reverse=reverse)
    for i, (_, r) in enumerate(data):
        tree.move(r, "", i)
    tree.heading(col, command=lambda: sortable(tree, col, not reverse))


# ══════════════════════════════════════════════════════════════════════════════
#  CHANGE PASSWORD DIALOG
# ══════════════════════════════════════════════════════════════════════════════
class ChangePasswordDialog(ctk.CTkToplevel):
    def __init__(self, parent, db: DatabaseManager, username: str, forced: bool = False):
        super().__init__(parent)
        self.db = db
        self.username = username
        self.title("Change Password")
        self.geometry("400x320")
        self.resizable(False, False)
        self.grab_set()
        self.lift()

        pad = {"padx": 30, "pady": 8}
        if forced:
            ctk.CTkLabel(self, text="You must set a new password before continuing.",
                         text_color="#e67e22", wraplength=340).pack(**pad)

        ctk.CTkLabel(self, text="New Password:").pack(**pad)
        self.pw1 = ctk.CTkEntry(self, show="*", width=300)
        self.pw1.pack(**pad)
        ctk.CTkLabel(self, text="Confirm Password:").pack(**pad)
        self.pw2 = ctk.CTkEntry(self, show="*", width=300)
        self.pw2.pack(**pad)

        ctk.CTkButton(self, text="Save Password", command=self._save, width=200).pack(pady=15)

    def _save(self):
        p1, p2 = self.pw1.get().strip(), self.pw2.get().strip()
        if len(p1) < 6:
            messagebox.showerror("Error", "Password must be at least 6 characters.", parent=self)
            return
        if p1 != p2:
            messagebox.showerror("Error", "Passwords do not match.", parent=self)
            return
        self.db.change_password(self.username, p1)
        messagebox.showinfo("Success", "Password changed successfully.", parent=self)
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
#  FORGOT PASSWORD DIALOG
# ══════════════════════════════════════════════════════════════════════════════
RECOVERY_CODE = "WGHCC-IT-RESET"

class ForgotPasswordDialog(ctk.CTkToplevel):
    def __init__(self, parent, db: DatabaseManager):
        super().__init__(parent)
        self.db = db
        self.title("Reset Password")
        self.geometry("420x380")
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self._step = 1
        self._build()

    def _build(self):
        pad = {"padx": 40, "pady": 8}

        ctk.CTkLabel(self, text="Reset Account Password",
                     font=("Garamond", 16, "bold")).pack(pady=(24, 4))
        ctk.CTkLabel(self,
                     text="Enter the recovery code, then choose a username\nand set a new password.",
                     font=("Calibri", 11), text_color="gray", justify="center").pack(pady=(0, 12))

        ctk.CTkLabel(self, text="Recovery Code:", anchor="w").pack(**pad, anchor="w")
        self.code_entry = ctk.CTkEntry(self, width=320, placeholder_text="Enter recovery code")
        self.code_entry.pack(**pad)

        ctk.CTkLabel(self, text="Username to reset:", anchor="w").pack(**pad, anchor="w")
        users = [u["username"] for u in db.get_users()]
        self.user_select = ctk.CTkComboBox(self, values=users, width=320)
        if users:
            self.user_select.set(users[0])
        self.user_select.pack(**pad)

        ctk.CTkLabel(self, text="New Password (min 6 chars):", anchor="w").pack(**pad, anchor="w")
        self.new_pw = ctk.CTkEntry(self, width=320, show="*")
        self.new_pw.pack(**pad)

        self.msg = ctk.CTkLabel(self, text="", text_color="#e74c3c")
        self.msg.pack(pady=4)

        ctk.CTkButton(self, text="Reset Password", width=200, command=self._reset).pack(pady=8)

    def _reset(self):
        code     = self.code_entry.get().strip()
        username = self.user_select.get().strip()
        new_pw   = self.new_pw.get()

        if code != RECOVERY_CODE:
            self.msg.configure(text="Incorrect recovery code.", text_color="#e74c3c")
            return
        if not username:
            self.msg.configure(text="Select a username.", text_color="#e74c3c")
            return
        if len(new_pw) < 6:
            self.msg.configure(text="Password must be at least 6 characters.", text_color="#e74c3c")
            return

        self.db.change_password(username, new_pw)
        self.msg.configure(
            text=f"Password for '{username}' reset successfully.",
            text_color="#2ecc71"
        )
        self.after(1800, self.destroy)


# ══════════════════════════════════════════════════════════════════════════════
#  LOGIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════
class LoginWindow(ctk.CTkToplevel):
    def __init__(self, parent, db: DatabaseManager, on_success):
        super().__init__(parent)
        self.db = db
        self.on_success = on_success
        self.title(APP_TITLE)
        self.geometry("420x520")
        self.resizable(False, False)
        self.lift()
        self.focus_force()
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)

        # Branding
        ctk.CTkLabel(self, text="WGHCC",
                     font=("Garamond", 36, "bold"), text_color="#004d00").grid(
            row=0, column=0, pady=(50, 0))
        ctk.CTkLabel(self, text="Windsor Golf Hotel & Country Club",
                     font=("Calibri", 13)).grid(row=1, column=0)
        ctk.CTkLabel(self, text="IT Asset Management System",
                     font=("Calibri", 11), text_color="gray").grid(row=2, column=0, pady=(0, 30))

        # Form
        ctk.CTkLabel(self, text="Username", anchor="w").grid(row=3, column=0, padx=60, sticky="w")
        self.username_var = ctk.CTkEntry(self, width=300, placeholder_text="Enter username")
        self.username_var.grid(row=4, column=0, padx=60, pady=(0, 12))

        ctk.CTkLabel(self, text="Password", anchor="w").grid(row=5, column=0, padx=60, sticky="w")

        # Password row: entry + show/hide toggle
        pw_row = ctk.CTkFrame(self, fg_color="transparent")
        pw_row.grid(row=6, column=0, padx=60, pady=(0, 2))
        self.password_var = ctk.CTkEntry(pw_row, width=258, show="*",
                                         placeholder_text="Enter password")
        self.password_var.pack(side="left")
        self._pw_visible = False
        ctk.CTkButton(pw_row, text="Show", width=38, height=28,
                      fg_color="gray40", hover_color="gray30",
                      font=("Calibri", 10),
                      command=self._toggle_pw).pack(side="left", padx=(4, 0))

        # Forgot password link
        ctk.CTkButton(self, text="Forgot password?", fg_color="transparent",
                      text_color=("gray50", "gray60"),
                      font=("Calibri", 10, "underline"), height=18,
                      command=self._forgot_pw).grid(row=7, column=0, pady=(2, 0))

        self.error_label = ctk.CTkLabel(self, text="", text_color="#e74c3c")
        self.error_label.grid(row=8, column=0, pady=(2, 0))

        ctk.CTkButton(self, text="Sign In", width=300, height=40,
                      font=("Calibri", 13, "bold"),
                      command=self._login).grid(row=9, column=0, padx=60, pady=16)

        ctk.CTkLabel(self, text="Default: admin / admin123",
                     font=("Calibri", 10), text_color="gray").grid(row=10, column=0)

        self.username_var.bind("<Return>", lambda e: self.password_var.focus())
        self.password_var.bind("<Return>", lambda e: self._login())
        self.username_var.focus()

    def _toggle_pw(self):
        self._pw_visible = not self._pw_visible
        self.password_var.configure(show="" if self._pw_visible else "*")
        # Update button text on the sibling widget
        pw_row = self.password_var.master
        for w in pw_row.winfo_children():
            if isinstance(w, ctk.CTkButton):
                w.configure(text="Hide" if self._pw_visible else "Show")

    def _forgot_pw(self):
        ForgotPasswordDialog(self, self.db)

    def _login(self):
        username = self.username_var.get().strip()
        password = self.password_var.get()
        if not username or not password:
            self.error_label.configure(text="Please enter username and password.")
            return
        user = self.db.authenticate(username, password)
        if not user:
            self.error_label.configure(text="Invalid username or password.")
            return
        if user["must_change_password"]:
            dlg = ChangePasswordDialog(self, self.db, username, forced=True)
            self.wait_window(dlg)
            # Password was changed — ask user to sign in again with the new one
            self.password_var.delete(0, "end")
            self.error_label.configure(
                text="Password updated. Please sign in with your new password.",
                text_color="#2ecc71"
            )
            self.password_var.focus()
            return
        self.db.log(username, "LOGIN")
        logged_in_user = dict(self.db.conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone())
        self.destroy()
        self.on_success(logged_in_user)


# ══════════════════════════════════════════════════════════════════════════════
#  ITEM DIALOG  (Add / Edit)
# ══════════════════════════════════════════════════════════════════════════════
class ItemDialog(ctk.CTkToplevel):
    def __init__(self, parent, db: DatabaseManager, by: str,
                 item: Optional[ITInventoryItem] = None, on_saved=None):
        super().__init__(parent)
        self.db = db
        self.by = by
        self.item = item
        self.on_saved = on_saved
        self.title("Edit Asset" if item else "Add New Asset")
        self.geometry("700x760")
        self.resizable(True, True)
        self.grab_set()
        self.lift()
        self._build()
        if item:
            self._load()

    def _field(self, frame, label, row, col, widget_type="entry", values=None, colspan=1):
        ctk.CTkLabel(frame, text=label + ":", anchor="w").grid(
            row=row * 2, column=col, columnspan=colspan, sticky="w", padx=10, pady=(8, 0))
        if widget_type == "entry":
            w = ctk.CTkEntry(frame, width=260 if colspan == 1 else 550)
        elif widget_type == "combo":
            w = ctk.CTkComboBox(frame, values=values or [], width=260 if colspan == 1 else 550)
        elif widget_type == "text":
            w = ctk.CTkTextbox(frame, height=70, width=550)
        else:
            w = ctk.CTkEntry(frame, width=260)
        w.grid(row=row * 2 + 1, column=col, columnspan=colspan, sticky="ew", padx=10, pady=(0, 2))
        return w

    def _build(self):
        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        scroll.columnconfigure((0, 1), weight=1)

        self.f_name     = self._field(scroll, "Name *",          0, 0)
        self.f_category = self._field(scroll, "Category *",      0, 1, "combo", CATEGORIES)
        self.f_brand    = self._field(scroll, "Brand",           1, 0)
        self.f_model    = self._field(scroll, "Model",           1, 1)
        self.f_serial   = self._field(scroll, "Serial Number",   2, 0)
        self.f_quantity = self._field(scroll, "Quantity",        2, 1)
        self.f_condition= self._field(scroll, "Condition",       3, 0, "combo",
                                      [c.value for c in ItemCondition])
        self.f_status   = self._field(scroll, "Status",         3, 1, "combo",
                                      [s.value for s in ItemStatus])
        self.f_price    = self._field(scroll, "Purchase Price (KES)", 4, 0)
        self.f_pdate    = self._field(scroll, "Purchase Date (YYYY-MM-DD)", 4, 1)
        self.f_warranty = self._field(scroll, "Warranty Expiry (YYYY-MM-DD)", 5, 0)
        self.f_supplier = self._field(scroll, "Supplier",        5, 1)
        self.f_location = self._field(scroll, "Location",        6, 0)
        self.f_assigned = self._field(scroll, "Assigned To",     6, 1)
        self.f_minstock = self._field(scroll, "Minimum Stock",   7, 0)
        self.f_specs    = self._field(scroll, "Specifications",  8, 0, "text", colspan=2)
        self.f_notes    = self._field(scroll, "Notes",           9, 0, "text", colspan=2)

        # Defaults
        self.f_quantity.insert(0, "1")
        self.f_minstock.insert(0, "1")
        self.f_condition.set("Good")
        self.f_status.set("Available")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkButton(btn_frame, text="Save", width=140,
                      command=self._save).pack(side="right", padx=5)
        ctk.CTkButton(btn_frame, text="Cancel", width=100, fg_color="gray",
                      command=self.destroy).pack(side="right", padx=5)

    def _set(self, widget, value):
        if isinstance(widget, ctk.CTkTextbox):
            widget.delete("1.0", "end")
            widget.insert("1.0", str(value or ""))
        elif isinstance(widget, ctk.CTkComboBox):
            widget.set(str(value or ""))
        else:
            widget.delete(0, "end")
            widget.insert(0, str(value or ""))

    def _get(self, widget) -> str:
        if isinstance(widget, ctk.CTkTextbox):
            return widget.get("1.0", "end-1c").strip()
        return widget.get().strip()

    def _load(self):
        d = asdict(self.item)
        self._set(self.f_name,     d["name"])
        self._set(self.f_category, d["category"])
        self._set(self.f_brand,    d["brand"])
        self._set(self.f_model,    d["model"])
        self._set(self.f_serial,   d["serial_number"])
        self._set(self.f_quantity, d["quantity"])
        self._set(self.f_condition,d["condition"])
        self._set(self.f_status,   d["status"])
        self._set(self.f_price,    d["purchase_price"])
        self._set(self.f_pdate,    d["purchase_date"])
        self._set(self.f_warranty, d["warranty_expiry"])
        self._set(self.f_supplier, d["supplier"])
        self._set(self.f_location, d["location"])
        self._set(self.f_assigned, d["assigned_to"])
        self._set(self.f_minstock, d["minimum_stock"])
        self._set(self.f_specs,    d["specifications"])
        self._set(self.f_notes,    d["notes"])

    def _save(self):
        name     = self._get(self.f_name)
        category = self._get(self.f_category)
        if not name or not category:
            messagebox.showerror("Validation", "Name and Category are required.", parent=self)
            return
        try:
            qty      = int(self._get(self.f_quantity) or 1)
            price    = float(self._get(self.f_price) or 0)
            minstock = int(self._get(self.f_minstock) or 1)
        except ValueError:
            messagebox.showerror("Validation", "Quantity, Price and Min Stock must be numeric.",
                                 parent=self)
            return

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = dict(
            name=name, category=category, quantity=qty,
            condition=self._get(self.f_condition), status=self._get(self.f_status),
            brand=self._get(self.f_brand), model=self._get(self.f_model),
            serial_number=self._get(self.f_serial),
            purchase_date=self._get(self.f_pdate), purchase_price=price,
            warranty_expiry=self._get(self.f_warranty), supplier=self._get(self.f_supplier),
            specifications=self._get(self.f_specs), location=self._get(self.f_location),
            assigned_to=self._get(self.f_assigned), notes=self._get(self.f_notes),
            minimum_stock=minstock,
        )

        if self.item:
            updated = ITInventoryItem(
                item_id=self.item.item_id, date_added=self.item.date_added,
                last_updated=now, **data
            )
            ok = self.db.update_item(updated, self.by, self.item)
        else:
            new_item = ITInventoryItem(
                item_id=ITInventoryItem.generate_id(), date_added=now, last_updated=now, **data
            )
            ok = self.db.add_item(new_item, self.by)

        if ok:
            if self.on_saved:
                self.on_saved()
            self.destroy()
        else:
            messagebox.showerror("Error", "Failed to save — check for duplicate serial number.",
                                 parent=self)


# ══════════════════════════════════════════════════════════════════════════════
#  MAINTENANCE DIALOG
# ══════════════════════════════════════════════════════════════════════════════
class MaintenanceDialog(ctk.CTkToplevel):
    def __init__(self, parent, db: DatabaseManager, by: str,
                 item_id: str, item_name: str, on_saved=None):
        super().__init__(parent)
        self.db = db
        self.by = by
        self.item_id = item_id
        self.item_name = item_name
        self.on_saved = on_saved
        self.title(f"Log Maintenance — {item_name}")
        self.geometry("500x520")
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self._build()

    def _row(self, label, row):
        ctk.CTkLabel(self, text=label + ":").grid(row=row, column=0, sticky="w", padx=20, pady=5)

    def _build(self):
        self.columnconfigure(1, weight=1)
        fields = [
            ("Service Date (YYYY-MM-DD)", "entry"),
            ("Service Type", "combo"),
            ("Description", "text"),
            ("Cost (KES)", "entry"),
            ("Performed By", "entry"),
            ("Next Service Date (YYYY-MM-DD)", "entry"),
        ]
        types = ["Repair", "Replacement", "Upgrade", "Inspection", "Cleaning",
                 "Software Update", "Other"]
        self.widgets = {}
        for i, (label, wtype) in enumerate(fields):
            self._row(label, i)
            if wtype == "entry":
                w = ctk.CTkEntry(self, width=280)
            elif wtype == "combo":
                w = ctk.CTkComboBox(self, values=types, width=280)
                w.set("Repair")
            else:
                w = ctk.CTkTextbox(self, height=80, width=280)
            w.grid(row=i, column=1, padx=20, pady=5, sticky="ew")
            self.widgets[label] = w

        self.widgets["Service Date (YYYY-MM-DD)"].insert(
            0, datetime.now().strftime("%Y-%m-%d"))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=len(fields), column=0, columnspan=2, pady=15)
        ctk.CTkButton(btns, text="Save Record", command=self._save).pack(side="left", padx=10)
        ctk.CTkButton(btns, text="Cancel", fg_color="gray",
                      command=self.destroy).pack(side="left", padx=10)

    def _get(self, key) -> str:
        w = self.widgets[key]
        if isinstance(w, ctk.CTkTextbox):
            return w.get("1.0", "end-1c").strip()
        return w.get().strip()

    def _save(self):
        svc_date = self._get("Service Date (YYYY-MM-DD)")
        svc_type = self._get("Service Type")
        if not svc_date or not svc_type:
            messagebox.showerror("Validation", "Service Date and Type are required.", parent=self)
            return
        try:
            cost = float(self._get("Cost (KES)") or 0)
        except ValueError:
            messagebox.showerror("Validation", "Cost must be a number.", parent=self)
            return
        self.db.add_maintenance(
            self.item_id, self.item_name, svc_date, svc_type,
            self._get("Description"), cost,
            self._get("Performed By"),
            self._get("Next Service Date (YYYY-MM-DD)"),
            self.by
        )
        if self.on_saved:
            self.on_saved()
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
#  USER DIALOG  (Admin panel)
# ══════════════════════════════════════════════════════════════════════════════
class UserDialog(ctk.CTkToplevel):
    def __init__(self, parent, db: DatabaseManager, created_by: str, on_saved=None):
        super().__init__(parent)
        self.db = db
        self.created_by = created_by
        self.on_saved = on_saved
        self.title("Create New User")
        self.geometry("400x380")
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self._build()

    def _build(self):
        pad = {"padx": 40, "pady": 6}
        ctk.CTkLabel(self, text="Username:").pack(**pad, anchor="w")
        self.username = ctk.CTkEntry(self, width=300)
        self.username.pack(**pad)
        ctk.CTkLabel(self, text="Password (min 6 chars):").pack(**pad, anchor="w")
        self.pw = ctk.CTkEntry(self, width=300, show="*")
        self.pw.pack(**pad)
        ctk.CTkLabel(self, text="Role:").pack(**pad, anchor="w")
        self.role = ctk.CTkComboBox(self, values=["staff", "admin"], width=300)
        self.role.set("staff")
        self.role.pack(**pad)
        ctk.CTkButton(self, text="Create User", width=200, command=self._save).pack(pady=20)

    def _save(self):
        username = self.username.get().strip()
        password = self.pw.get()
        role     = self.role.get()
        if not username:
            messagebox.showerror("Error", "Username is required.", parent=self); return
        if len(password) < 6:
            messagebox.showerror("Error", "Password must be at least 6 characters.", parent=self)
            return
        if not self.db.add_user(username, password, role, self.created_by):
            messagebox.showerror("Error", f"Username '{username}' already exists.", parent=self)
            return
        messagebox.showinfo("Created", f"User '{username}' created. They must set a new password on first login.",
                            parent=self)
        if self.on_saved:
            self.on_saved()
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED ITEM CACHE  — one DB hit per mutation, not per view switch
# ══════════════════════════════════════════════════════════════════════════════
class ItemCache:
    def __init__(self, db: DatabaseManager):
        self._db = db
        self._items: List[ITInventoryItem] = []
        self._valid = False

    def get(self) -> List[ITInventoryItem]:
        if not self._valid:
            self._items = self._db.get_items()
            self._valid = True
        return self._items

    def invalidate(self):
        self._valid = False


# ══════════════════════════════════════════════════════════════════════════════
#  VIEWS
# ══════════════════════════════════════════════════════════════════════════════

class DashboardView(ctk.CTkFrame):
    def __init__(self, parent, db: DatabaseManager, cache: ItemCache):
        super().__init__(parent, corner_radius=0, fg_color="transparent")
        self.db = db
        self.cache = cache
        # Reused figure objects — created once, cleared on each refresh
        self._fig_left: Optional[Figure] = None
        self._fig_right: Optional[Figure] = None
        self._canvas_left = None
        self._canvas_right = None
        self._build()

    def _build(self):
        # Header
        ctk.CTkLabel(self, text="Dashboard", font=("Garamond", 22, "bold")).pack(
            anchor="w", padx=20, pady=(15, 5))

        # KPI strip
        self.kpi_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.kpi_frame.pack(fill="x", padx=20, pady=5)

        # Charts row
        self.chart_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.chart_frame.pack(fill="both", expand=True, padx=20, pady=5)
        self.chart_frame.columnconfigure((0, 1), weight=1)
        self.chart_frame.rowconfigure(0, weight=1)

        self.chart_left  = ctk.CTkFrame(self.chart_frame)
        self.chart_left.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=5)
        self.chart_right = ctk.CTkFrame(self.chart_frame)
        self.chart_right.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=5)

        # Alerts
        ctk.CTkLabel(self, text="Alerts", font=("Garamond", 14, "bold")).pack(
            anchor="w", padx=20, pady=(5, 0))
        self.alert_frame = ctk.CTkScrollableFrame(self, height=120)
        self.alert_frame.pack(fill="x", padx=20, pady=(0, 10))

    def _kpi_card(self, parent, title: str, value: str, color: str):
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.pack(side="left", expand=True, fill="x", padx=5, pady=5)
        ctk.CTkLabel(card, text=title, font=("Calibri", 11), text_color="gray").pack(pady=(10, 0))
        ctk.CTkLabel(card, text=value, font=("Garamond", 22, "bold"),
                     text_color=color).pack(pady=(0, 10))

    def on_show(self):
        items = self.cache.get()
        # KPIs and alerts render immediately — they're cheap
        self._update_kpis(items)
        self._update_alerts(items)
        # Charts are deferred so the view appears snappy before the heavy work
        self.after(5, lambda: self._update_charts(items))

    def _update_kpis(self, items: list):
        for w in self.kpi_frame.winfo_children():
            w.destroy()
        total    = len(items)
        avail    = sum(1 for i in items if i.status == "Available")
        borrowed = sum(1 for i in items if i.status == "Borrowed")
        value    = sum(i.purchase_price * i.quantity for i in items)
        self._kpi_card(self.kpi_frame, "Total Assets", str(total),          "#004d00")
        self._kpi_card(self.kpi_frame, "Available",    str(avail),          "#2ecc71")
        self._kpi_card(self.kpi_frame, "Borrowed",     str(borrowed),       "#e67e22")
        self._kpi_card(self.kpi_frame, "Total Value",  f"KES {value:,.0f}", "#004d00")

    def _update_charts(self, items: list):
        dark = ctk.get_appearance_mode() == "Dark"
        bg   = "#2b2b2b" if dark else "#ffffff"
        fg   = "#f0f0f0" if dark else "#1a1a1a"
        matplotlib.rcParams.update({
            "figure.facecolor": bg, "axes.facecolor": bg,
            "text.color": fg, "axes.labelcolor": fg, "xtick.color": fg, "ytick.color": fg,
        })

        # ── Category pie (reuse figure) ───────────────────────────────────────
        if self._fig_left is None:
            self._fig_left = Figure(figsize=(4, 3.2), tight_layout=True)
            self._canvas_left = FigureCanvasTkAgg(self._fig_left, master=self.chart_left)
            self._canvas_left.get_tk_widget().pack(fill="both", expand=True)

        self._fig_left.set_facecolor(bg)
        self._fig_left.clear()
        ax1 = self._fig_left.add_subplot(111)
        ax1.set_facecolor(bg)

        cat_counts: Dict[str, int] = {}
        for i in items:
            cat_counts[i.category] = cat_counts.get(i.category, 0) + 1
        if cat_counts:
            top = sorted(cat_counts.items(), key=lambda x: -x[1])[:6]
            others = sum(v for k, v in cat_counts.items() if k not in dict(top))
            if others:
                top.append(("Others", others))
            labels, sizes = zip(*top)
            ax1.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=90,
                    textprops={"color": fg, "fontsize": 8},
                    colors=["#004d00","#1a7a1a","#2e9e2e","#4dbf4d","#80d980","#b3ecb3","#cccccc"])
        ax1.set_title("Assets by Category", color=fg, fontsize=11)
        self._canvas_left.draw()

        # ── Status bar chart (reuse figure) ──────────────────────────────────
        if self._fig_right is None:
            self._fig_right = Figure(figsize=(4, 3.2), tight_layout=True)
            self._canvas_right = FigureCanvasTkAgg(self._fig_right, master=self.chart_right)
            self._canvas_right.get_tk_widget().pack(fill="both", expand=True)

        self._fig_right.set_facecolor(bg)
        self._fig_right.clear()
        ax2 = self._fig_right.add_subplot(111)
        ax2.set_facecolor(bg)

        status_counts = {s.value: 0 for s in ItemStatus}
        for i in items:
            if i.status in status_counts:
                status_counts[i.status] += 1
        bars = ax2.bar(list(status_counts.keys()), list(status_counts.values()),
                       color=["#2ecc71","#e67e22","#e74c3c","#3498db","#95a5a6"])
        ax2.set_title("Asset Status Breakdown", color=fg, fontsize=11)
        ax2.tick_params(axis="x", rotation=20, colors=fg)
        ax2.tick_params(axis="y", colors=fg)
        for spine in ax2.spines.values():
            spine.set_edgecolor(fg)
        for bar, count in zip(bars, status_counts.values()):
            if count > 0:
                ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                         str(count), ha="center", va="bottom", color=fg, fontsize=9)
        self._canvas_right.draw()

    def _update_alerts(self, items: list):
        for w in self.alert_frame.winfo_children():
            w.destroy()
        alerts = []
        for item in items:
            days = item.warranty_days()
            if days is not None and days <= 90:
                color = "#e74c3c" if days <= 0 else "#e67e22"
                label = "EXPIRED" if days <= 0 else f"{days}d left"
                alerts.append((color, f"WARRANTY {label}: {item.name} ({item.item_id})"))
            if item.quantity <= item.minimum_stock and item.minimum_stock > 0:
                alerts.append(("#3498db",
                               f"LOW STOCK: {item.name} — qty {item.quantity} ≤ min {item.minimum_stock}"))
        if alerts:
            for color, msg in alerts:
                ctk.CTkLabel(self.alert_frame, text=f"  ⚠  {msg}",
                             text_color=color, anchor="w").pack(fill="x", pady=1)
        else:
            ctk.CTkLabel(self.alert_frame, text="  ✓  No active alerts.",
                         text_color="#2ecc71", anchor="w").pack(fill="x")


class InventoryView(ctk.CTkFrame):
    def __init__(self, parent, db: DatabaseManager, cache: ItemCache,
                 user: dict, on_data_changed=None):
        super().__init__(parent, corner_radius=0, fg_color="transparent")
        self.db = db
        self.cache = cache
        self.user = user
        self.on_data_changed = on_data_changed
        self._items: List[ITInventoryItem] = []
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Inventory", font=("Garamond", 22, "bold")).pack(
            anchor="w", padx=20, pady=(15, 5))

        # Toolbar
        tb = ctk.CTkFrame(self, fg_color="transparent")
        tb.pack(fill="x", padx=20, pady=5)
        btn_cfg = {"width": 120, "height": 32}
        ctk.CTkButton(tb, text="+ Add Asset",    **btn_cfg, command=self._add).pack(side="left", padx=3)
        ctk.CTkButton(tb, text="✎ Edit",         **btn_cfg, command=self._edit).pack(side="left", padx=3)
        ctk.CTkButton(tb, text="✕ Remove",        **btn_cfg, command=self._remove,
                      fg_color="#c0392b", hover_color="#96281b").pack(side="left", padx=3)
        ctk.CTkButton(tb, text="🔧 Maintenance",  **btn_cfg, command=self._maintenance).pack(
            side="left", padx=3)
        ctk.CTkButton(tb, text="⬇ Import Excel", **btn_cfg, command=self._import).pack(
            side="left", padx=15)
        ctk.CTkButton(tb, text="⬆ Export View",  **btn_cfg, command=self._export).pack(
            side="left", padx=3)
        ctk.CTkButton(tb, text="↻ Template",     **btn_cfg, fg_color="gray",
                      command=self._template).pack(side="left", padx=3)

        # Filters
        filt = ctk.CTkFrame(self, fg_color="transparent")
        filt.pack(fill="x", padx=20, pady=3)
        ctk.CTkLabel(filt, text="Search:").pack(side="left", padx=(0, 5))
        self.search_var = ctk.CTkEntry(filt, width=220, placeholder_text="Name, serial, location…")
        self.search_var.pack(side="left", padx=5)
        self.search_var.bind("<KeyRelease>", lambda e: self._filter())

        ctk.CTkLabel(filt, text="Category:").pack(side="left", padx=(15, 5))
        self.cat_filter = ctk.CTkComboBox(filt, values=["All"], width=160,
                                          command=lambda _: self._filter())
        self.cat_filter.set("All")
        self.cat_filter.pack(side="left", padx=5)

        ctk.CTkLabel(filt, text="Status:").pack(side="left", padx=(10, 5))
        self.status_filter = ctk.CTkComboBox(
            filt, values=["All"] + [s.value for s in ItemStatus], width=130,
            command=lambda _: self._filter())
        self.status_filter.set("All")
        self.status_filter.pack(side="left", padx=5)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        ctk.CTkLabel(filt, textvariable=self.status_var, text_color="gray").pack(
            side="right", padx=10)

        # Table
        cols = ["ID", "Name", "Category", "Brand", "Model", "Qty",
                "Price (KES)", "Condition", "Status", "Location", "Assigned To", "Warranty"]
        widths = {"ID": 130, "Name": 220, "Category": 140, "Brand": 110, "Model": 110,
                  "Qty": 50, "Price (KES)": 120, "Condition": 100, "Status": 100,
                  "Location": 120, "Assigned To": 120, "Warranty": 110}
        tree_frame = ctk.CTkFrame(self)
        tree_frame.pack(fill="both", expand=True, padx=20, pady=(5, 10))
        self.tree = make_tree(tree_frame, cols, widths)
        self.tree.tag_configure("low_stock", background="#fff3cd", foreground="#856404")
        self.tree.tag_configure("warn_warranty", background="#fde8e8", foreground="#c0392b")
        self.tree.bind("<Double-1>", lambda e: self._edit())
        for col in cols:
            self.tree.heading(col, text=col,
                              command=lambda c=col: sortable(self.tree, c, False))

    def on_show(self):
        self._items = self.cache.get()
        cats = ["All"] + sorted({i.category for i in self._items})
        self.cat_filter.configure(values=cats)
        self._filter()

    def _filter(self):
        q   = self.search_var.get().lower()
        cat = self.cat_filter.get()
        st  = self.status_filter.get()
        items = self._items
        if q:
            items = [i for i in items if q in (
                i.name + i.serial_number + i.location + i.brand + i.model).lower()]
        if cat != "All":
            items = [i for i in items if i.category == cat]
        if st != "All":
            items = [i for i in items if i.status == st]

        self.tree.delete(*self.tree.get_children())
        for item in items:
            days = item.warranty_days()
            if days is not None and days <= 30:
                tag = "warn_warranty"
            elif item.quantity <= item.minimum_stock:
                tag = "low_stock"
            else:
                tag = ""
            warranty_txt = (f"{days}d" if days is not None and days >= 0
                            else ("Expired" if days is not None else "—"))
            self.tree.insert("", "end", iid=item.item_id, tags=(tag,), values=(
                item.item_id, item.name, item.category, item.brand, item.model,
                item.quantity, f"{item.purchase_price:,.2f}", item.condition,
                item.status, item.location, item.assigned_to, warranty_txt,
            ))
        self.status_var.set(f"Showing {len(items)} of {len(self._items)} items")

    def _selected_item(self) -> Optional[ITInventoryItem]:
        iid = self.tree.focus()
        if not iid:
            return None
        return next((i for i in self._items if i.item_id == iid), None)

    def _add(self):
        ItemDialog(self, self.db, self.user["username"], on_saved=self._refresh)

    def _edit(self):
        item = self._selected_item()
        if not item:
            messagebox.showwarning("No Selection", "Select an asset to edit."); return
        ItemDialog(self, self.db, self.user["username"], item=item, on_saved=self._refresh)

    def _remove(self):
        item = self._selected_item()
        if not item:
            messagebox.showwarning("No Selection", "Select an asset to remove."); return
        if messagebox.askyesno("Confirm Delete",
                               f"Permanently delete '{item.name}'?\nThis cannot be undone."):
            self.db.delete_item(item.item_id, item.name, self.user["username"])
            self._refresh()

    def _maintenance(self):
        item = self._selected_item()
        if not item:
            messagebox.showwarning("No Selection", "Select an asset to log maintenance."); return
        MaintenanceDialog(self, self.db, self.user["username"],
                          item.item_id, item.name, on_saved=self._refresh)

    def _import(self):
        f = filedialog.askopenfilename(filetypes=[("Excel Files", "*.xlsx")],
                                       title="Select Excel File")
        if not f:
            return
        ok, fail, errors = self.db.import_excel(f, self.user["username"])
        msg = f"Imported {ok} items. Failed: {fail}."
        if errors:
            msg += "\n\nFirst errors:\n" + "\n".join(errors[:5])
        messagebox.showinfo("Import Complete", msg)
        self._refresh()

    def _export(self):
        ids = self.tree.get_children()
        if not ids:
            messagebox.showwarning("Export", "Nothing to export."); return
        f = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                          filetypes=[("Excel", "*.xlsx")], title="Export View")
        if not f:
            return
        items = [i for i in self._items if i.item_id in ids]
        export_items_to_excel(items, f)
        messagebox.showinfo("Exported", f"Saved {len(items)} rows to {f}")

    def _template(self):
        f = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                          filetypes=[("Excel", "*.xlsx")], title="Save Template")
        if not f:
            return
        cols = ["name","category","quantity","condition","status","brand","model",
                "serial_number","purchase_date","purchase_price","warranty_expiry",
                "supplier","specifications","location","assigned_to","notes","minimum_stock"]
        pd.DataFrame(columns=cols).to_excel(f, index=False)
        messagebox.showinfo("Template Saved", f"Import template saved to {f}")

    def _refresh(self):
        self.cache.invalidate()   # next get_items() call hits the DB fresh
        self.on_show()
        if self.on_data_changed:
            self.on_data_changed()


class AuditView(ctk.CTkFrame):
    def __init__(self, parent, db: DatabaseManager):
        super().__init__(parent, corner_radius=0, fg_color="transparent")
        self.db = db
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Audit Trail", font=("Garamond", 22, "bold")).pack(
            anchor="w", padx=20, pady=(15, 5))

        tb = ctk.CTkFrame(self, fg_color="transparent")
        tb.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(tb, text="Filter:").pack(side="left", padx=(0, 5))
        self.search = ctk.CTkEntry(tb, width=260, placeholder_text="Username, action, asset…")
        self.search.pack(side="left", padx=5)
        self.search.bind("<KeyRelease>", lambda e: self._filter())
        ctk.CTkButton(tb, text="⬆ Export", width=100,
                      command=self._export).pack(side="right", padx=5)
        self.count_label = ctk.CTkLabel(tb, text="", text_color="gray")
        self.count_label.pack(side="right", padx=10)

        cols = ["#", "Timestamp", "User", "Action", "Asset ID", "Asset Name",
                "Field Changed", "Old Value", "New Value"]
        widths = {"#": 60, "Timestamp": 150, "User": 110, "Action": 100,
                  "Asset ID": 130, "Asset Name": 180, "Field Changed": 130,
                  "Old Value": 150, "New Value": 150}
        tree_frame = ctk.CTkFrame(self)
        tree_frame.pack(fill="both", expand=True, padx=20, pady=(5, 10))
        self.tree = make_tree(tree_frame, cols, widths)
        self.tree.tag_configure("ADD",        foreground="#2ecc71")
        self.tree.tag_configure("DELETE",     foreground="#e74c3c")
        self.tree.tag_configure("EDIT",       foreground="#3498db")
        self.tree.tag_configure("MAINTENANCE",foreground="#9b59b6")
        self._all_rows = []

    def on_show(self):
        self._all_rows = self.db.get_audit_log()
        self._filter()

    def _filter(self):
        q = self.search.get().lower()
        rows = self._all_rows
        if q:
            rows = [r for r in rows if q in (
                r.get("username","") + r.get("action","") +
                r.get("item_name","") + r.get("field_changed","")
            ).lower()]
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            action = r.get("action", "")
            self.tree.insert("", "end", tags=(action,), values=(
                r["log_id"], r["timestamp"], r["username"], action,
                r.get("item_id",""), r.get("item_name",""),
                r.get("field_changed",""), r.get("old_value",""), r.get("new_value",""),
            ))
        self.count_label.configure(text=f"{len(rows)} records")

    def _export(self):
        f = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                          filetypes=[("Excel","*.xlsx")], title="Export Audit Log")
        if not f:
            return
        pd.DataFrame(self._all_rows).to_excel(f, index=False)
        messagebox.showinfo("Exported", f"Audit log exported to {f}")


class MaintenanceView(ctk.CTkFrame):
    def __init__(self, parent, db: DatabaseManager, user: dict):
        super().__init__(parent, corner_radius=0, fg_color="transparent")
        self.db = db
        self.user = user
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Maintenance Log", font=("Garamond", 22, "bold")).pack(
            anchor="w", padx=20, pady=(15, 5))

        tb = ctk.CTkFrame(self, fg_color="transparent")
        tb.pack(fill="x", padx=20, pady=5)
        ctk.CTkButton(tb, text="⬆ Export", width=100, command=self._export).pack(
            side="right", padx=5)
        self.count_label = ctk.CTkLabel(tb, text="", text_color="gray")
        self.count_label.pack(side="right", padx=10)

        cols = ["#", "Asset ID", "Asset Name", "Service Date", "Type",
                "Description", "Cost (KES)", "Performed By", "Next Service", "Logged By"]
        widths = {"#": 50, "Asset ID": 130, "Asset Name": 180, "Service Date": 110,
                  "Type": 110, "Description": 200, "Cost (KES)": 100,
                  "Performed By": 130, "Next Service": 110, "Logged By": 110}
        tree_frame = ctk.CTkFrame(self)
        tree_frame.pack(fill="both", expand=True, padx=20, pady=(5, 10))
        self.tree = make_tree(tree_frame, cols, widths)

    def on_show(self):
        records = self.db.get_maintenance()
        self.tree.delete(*self.tree.get_children())
        for r in records:
            self.tree.insert("", "end", values=(
                r["log_id"], r["item_id"], r.get("item_name",""),
                r["service_date"], r.get("service_type",""),
                r.get("description",""), f"{r.get('cost',0):,.2f}",
                r.get("performed_by",""), r.get("next_service_date",""),
                r.get("logged_by",""),
            ))
        self.count_label.configure(text=f"{len(records)} records")

    def _export(self):
        f = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                          filetypes=[("Excel","*.xlsx")], title="Export Maintenance Log")
        if not f:
            return
        pd.DataFrame(self.db.get_maintenance()).to_excel(f, index=False)
        messagebox.showinfo("Exported", f"Maintenance log exported to {f}")


class AdminView(ctk.CTkFrame):
    def __init__(self, parent, db: DatabaseManager, user: dict):
        super().__init__(parent, corner_radius=0, fg_color="transparent")
        self.db = db
        self.user = user
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="User Administration", font=("Garamond", 22, "bold")).pack(
            anchor="w", padx=20, pady=(15, 5))
        ctk.CTkLabel(self, text="Manage system users. New users must change their password on first login.",
                     text_color="gray").pack(anchor="w", padx=20, pady=(0, 10))

        tb = ctk.CTkFrame(self, fg_color="transparent")
        tb.pack(fill="x", padx=20, pady=5)
        ctk.CTkButton(tb, text="+ Create User", width=130, command=self._create).pack(
            side="left", padx=3)
        ctk.CTkButton(tb, text="✓ Activate",    width=100, command=lambda: self._toggle(True)).pack(
            side="left", padx=3)
        ctk.CTkButton(tb, text="✕ Deactivate",  width=110, command=lambda: self._toggle(False),
                      fg_color="#c0392b", hover_color="#96281b").pack(side="left", padx=3)
        ctk.CTkButton(tb, text="🔑 Reset Password", width=140,
                      command=self._reset_pw).pack(side="left", padx=3)

        cols = ["Username", "Role", "Created", "Active", "Must Change PW"]
        widths = {"Username": 160, "Role": 90, "Created": 160, "Active": 70, "Must Change PW": 120}
        tree_frame = ctk.CTkFrame(self)
        tree_frame.pack(fill="both", expand=True, padx=20, pady=(5, 10))
        self.tree = make_tree(tree_frame, cols, widths)

    def on_show(self):
        self._reload()

    def _reload(self):
        self.tree.delete(*self.tree.get_children())
        for u in self.db.get_users():
            self.tree.insert("", "end", iid=u["user_id"], values=(
                u["username"], u["role"], u["created_at"],
                "Yes" if u["is_active"] else "No",
                "Yes" if u["must_change_password"] else "No",
            ))

    def _selected(self) -> Optional[dict]:
        iid = self.tree.focus()
        if not iid:
            return None
        return next((u for u in self.db.get_users() if u["user_id"] == iid), None)

    def _create(self):
        UserDialog(self, self.db, self.user["username"], on_saved=self._reload)

    def _toggle(self, active: bool):
        u = self._selected()
        if not u:
            messagebox.showwarning("No Selection", "Select a user."); return
        if u["username"] == "admin" and not active:
            messagebox.showerror("Error", "Cannot deactivate the admin account."); return
        self.db.set_user_active(u["user_id"], active)
        self._reload()

    def _reset_pw(self):
        u = self._selected()
        if not u:
            messagebox.showwarning("No Selection", "Select a user."); return
        new_pw = f"Reset{datetime.now().strftime('%d%m')}"
        self.db.change_password(u["username"], new_pw)
        self.db.conn.execute(
            "UPDATE users SET must_change_password=1 WHERE user_id=?", (u["user_id"],))
        self.db.conn.commit()
        messagebox.showinfo("Password Reset",
                            f"Password for '{u['username']}' reset to: {new_pw}\n"
                            "They must change it on next login.")
        self._reload()


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ══════════════════════════════════════════════════════════════════════════════
class MainApp(ctk.CTkToplevel):
    def __init__(self, parent, db: DatabaseManager, user: dict, on_logout):
        super().__init__(parent)
        self.db = db
        self.user = user
        self.on_logout = on_logout
        self.title(APP_TITLE)
        self.geometry("1500x820")
        self.minsize(1200, 700)
        self.lift()
        apply_treeview_style()
        self._build()
        self._show("dashboard")

    def _build(self):
        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Content
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.content.pack(side="left", fill="both", expand=True)

        self._build_sidebar()
        self._build_views()

    def _build_sidebar(self):
        sb = self.sidebar

        # Logo
        ctk.CTkLabel(sb, text="WGHCC", font=("Garamond", 22, "bold"),
                     text_color="#004d00").pack(pady=(25, 0))
        ctk.CTkLabel(sb, text="IT Asset Management",
                     font=("Calibri", 10), text_color="gray").pack()

        ctk.CTkFrame(sb, height=1, fg_color="gray40").pack(fill="x", padx=15, pady=15)

        # User info
        ctk.CTkLabel(sb, text=f"  {self.user['username']}",
                     font=("Calibri", 12, "bold"), anchor="w").pack(fill="x", padx=15)
        role_color = "#e67e22" if self.user["role"] == "admin" else "gray"
        ctk.CTkLabel(sb, text=f"  {self.user['role'].capitalize()}",
                     font=("Calibri", 10), text_color=role_color, anchor="w").pack(fill="x", padx=15)

        ctk.CTkFrame(sb, height=1, fg_color="gray40").pack(fill="x", padx=15, pady=15)

        # Nav buttons
        self._nav_btns: Dict[str, ctk.CTkButton] = {}
        nav_items = [
            ("dashboard",    "📊  Dashboard"),
            ("inventory",    "📦  Inventory"),
            ("audit",        "📋  Audit Trail"),
            ("maintenance",  "🔧  Maintenance"),
        ]
        if self.user["role"] == "admin":
            nav_items.append(("admin", "⚙️  Admin Panel"))

        for key, label in nav_items:
            btn = ctk.CTkButton(
                sb, text=label, anchor="w", height=38,
                fg_color="transparent", hover_color=("#d6ecd6", "#1a4d1a"),
                text_color=("gray10", "gray90"), font=("Calibri", 12),
                command=lambda k=key: self._show(k)
            )
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_btns[key] = btn

        # Spacer
        ctk.CTkFrame(sb, fg_color="transparent").pack(fill="both", expand=True)

        # Theme + Logout
        ctk.CTkFrame(sb, height=1, fg_color="gray40").pack(fill="x", padx=15, pady=10)

        appearance_switch = ctk.CTkSwitch(
            sb, text="Dark Mode",
            command=self._toggle_theme,
            onvalue="Dark", offvalue="Light"
        )
        if ctk.get_appearance_mode() == "Dark":
            appearance_switch.select()
        appearance_switch.pack(padx=20, pady=8)

        ctk.CTkButton(
            sb, text="Change Password", height=32, fg_color="transparent",
            hover_color=("#d6ecd6","#1a4d1a"), font=("Calibri", 11),
            command=self._change_pw
        ).pack(fill="x", padx=10, pady=2)

        ctk.CTkButton(
            sb, text="📖  User Guide", height=32, fg_color="transparent",
            hover_color=("#d6ecd6","#1a4d1a"), font=("Calibri", 11),
            command=lambda: webbrowser.open(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_guide.html"))
        ).pack(fill="x", padx=10, pady=2)

        ctk.CTkButton(
            sb, text="🚪  Logout", height=36, fg_color="#c0392b",
            hover_color="#96281b", font=("Calibri", 12),
            command=self._logout
        ).pack(fill="x", padx=10, pady=(2, 20))

    def _build_views(self):
        cache = ItemCache(self.db)
        self.views: Dict[str, ctk.CTkFrame] = {
            "dashboard":   DashboardView(self.content, self.db, cache),
            "inventory":   InventoryView(self.content, self.db, cache, self.user,
                                         on_data_changed=lambda: self._refresh_if_visible("dashboard")),
            "audit":       AuditView(self.content, self.db),
            "maintenance": MaintenanceView(self.content, self.db, self.user),
        }
        if self.user["role"] == "admin":
            self.views["admin"] = AdminView(self.content, self.db, self.user)

        for v in self.views.values():
            v.place(relwidth=1, relheight=1)
            v.place_forget()

    def _show(self, name: str):
        for key, view in self.views.items():
            if key == name:
                view.place(relwidth=1, relheight=1)
                view.on_show()
            else:
                view.place_forget()
        # Highlight active nav button
        for key, btn in self._nav_btns.items():
            if key == name:
                btn.configure(fg_color=("#c8e6c9", "#1a4d1a"),
                              text_color=("#004d00", "#90ee90"))
            else:
                btn.configure(fg_color="transparent",
                              text_color=("gray10", "gray90"))

    def _refresh_if_visible(self, name: str):
        if name in self.views:
            self.views[name].on_show()

    def _toggle_theme(self):
        new_mode = "Dark" if ctk.get_appearance_mode() == "Light" else "Light"
        ctk.set_appearance_mode(new_mode)
        apply_treeview_style()

    def _change_pw(self):
        ChangePasswordDialog(self, self.db, self.user["username"])

    def _logout(self):
        if messagebox.askyesno("Logout", "Are you sure you want to log out?"):
            self.db.log(self.user["username"], "LOGOUT")
            self.destroy()
            self.on_logout()

    def on_closing(self):
        if messagebox.askokcancel("Quit", "Close the application?"):
            self.db.log(self.user["username"], "LOGOUT")
            self.master.destroy()  # destroy root → exits mainloop


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("green")

    db = DatabaseManager()

    # Single persistent root — never destroyed until the app quits.
    # LoginWindow and MainApp are both CTkToplevel children of this root.
    root = ctk.CTk()
    root.withdraw()

    def show_login():
        win = LoginWindow(root, db, on_success=show_main)
        win.protocol("WM_DELETE_WINDOW", root.destroy)

    def show_main(user):
        win = MainApp(root, db, user, on_logout=show_login)
        win.protocol("WM_DELETE_WINDOW", win.on_closing)

    show_login()
    root.mainloop()
    db.close()
