import sqlite3
import os

# Check what's actually in the database
DB_PATH = "oslo_parcel.db"
print(f"Looking for DB at: {os.path.abspath(DB_PATH)}")
print(f"File exists: {os.path.exists(DB_PATH)}")

if os.path.exists(DB_PATH):
    conn   = sqlite3.connect(DB_PATH)
    tables = [t[0] for t in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    conn.close()
    print(f"Tables found: {tables}")
else:
    print("File not found at this path")