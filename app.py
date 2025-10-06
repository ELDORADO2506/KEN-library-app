# KEN Library App (Streamlit + SQLite)
# Minimal, safe, and self-healing version with location migration + 45 compartments
import os
import io
import sqlite3
from datetime import datetime, timedelta

# ===== one-time migration helper (safe to run many times) =====
import sqlite3

# If DB_PATH already exists in your file, delete this next line OR keep only one of them
DB_PATH = "library.db"   # change only if your DB file is named differently

def _column_exists(db, table, col):
    with sqlite3.connect(db) as c:
        cur = c.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        return col in cols

def ensure_migration():
    with sqlite3.connect(DB_PATH) as c:
        cur = c.cursor()
        # 1) add book_id to transactions if missing
        if not _column_exists(DB_PATH, "transactions", "book_id"):
            cur.execute("ALTER TABLE transactions ADD COLUMN book_id INTEGER")
            # fill book_id from copies (if copies exist)
            cur.execute("""
                UPDATE transactions
                SET book_id = (SELECT book_id FROM copies c WHERE c.id = transactions.copy_id)
                WHERE book_id IS NULL AND copy_id IS NOT NULL
            """)
        # 2) helpful index
        cur.execute("""
            CREATE INDEX IF NOT EXISTS ix_trans_book_open
            ON transactions(book_id) WHERE return_date IS NULL
        """)
        c.commit()

# call it once when app starts
ensure_migration()
# ===== end migration helper =====

import pandas as pd
import streamlit as st

DB_PATH


# --------------------------- DB Helpers --------------------------- #
def get_conn():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def fetch_df(sql, params=()):
    with get_conn() as con:
        return pd.read_sql_query(sql, con, params=params)


def exec_sql(sql, params=()):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(sql, params)
        con.commit()
        return cur.lastrowid


def exec_many(sql, rows):
    with get_conn() as con:
        cur = con.cursor()
        cur.executemany(sql, rows)
        con.commit()


# --------------------------- Schema & Migrations --------------------------- #
def init_db():
    with get_conn() as con:
        cur = con.cursor()

        # Books
        cur.execute("""
            CREATE TABLE IF NOT EXISTS books(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                author TEXT,
                genre TEXT,
                default_location TEXT,
                tags TEXT,
                notes TEXT
            )
        """)

        # Copies
        cur.execute("""
            CREATE TABLE IF NOT EXISTS copies(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER,
                accession_no TEXT,
                status TEXT DEFAULT 'available',                -- 'available' | 'issued'
                current_location TEXT,
                issued_to TEXT,
                issue_date TEXT,
                due_date TEXT,
                FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
            )
        """)

        # Members (very simple for now)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS members(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                phone TEXT,
                email TEXT
            )
        """)

        # Locations (will be healed by migrate_locations)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS locations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                description TEXT
            )
        """)

        con.commit()


def migrate_locations():
    """Ensure 'locations' table exists and has the expected columns."""
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS locations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                description TEXT
            )
        """)
        # verify columns
        cols = [r[1] for r in cur.execute("PRAGMA table_info(locations)").fetchall()]
        if "description" not in cols:
            cur.execute("ALTER TABLE locations ADD COLUMN description TEXT")
        con.commit()


def ensure_default_locations(n=45):
    """Insert Compartment 1..n if they don't exist."""
    migrate_locations()
    with get_conn() as con:
        cur = con.cursor()
        for i in range(1, n + 1):
            cur.execute(
                "INSERT OR IGNORE INTO locations(name, description) VALUES(?, ?)",
                (f"Compartment {i}", f"Shelf compartment #{i}"),
            )
        con.commit()


# --------------------------- UI Helpers --------------------------- #
def titled_number(label, value):
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown(f"### {label}")
    with c2:
        st.markdown(f"## **{value}**")


def selectbox_book(label="Book"):
    df = fetch_df("SELECT id, title, IFNULL(author, '') AS author FROM books ORDER BY title")
    if df.empty:
        st.info("No books yet.")
        return None, None
    options = [f"{row.title} — {row.author}".strip(" —") for _, row in df.iterrows()]
    choice = st.selectbox(label, options)
    idx = options.index(choice)
    return int(df.iloc[idx]["id"]), df.iloc[idx]["title"]


def selectbox_location(label="Location", allow_empty=False):
    df = fetch_df("SELECT name FROM locations ORDER BY id")
    options = df["name"].tolist()
    if allow_empty:
        options = [""] + options
    return st.selectbox(label, options)


# --------------------------- Pages --------------------------- #
import pandas as pd
import streamlit as st
import sqlite3

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def fetch_df(sql, params=()):
    with get_conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)

def page_dashboard():
    st.title("KEN Library System")

    # KPIs
    total_books = fetch_df("SELECT COUNT(*) AS c FROM books")["c"][0]
    issued_now  = fetch_df("SELECT COUNT(*) AS c FROM transactions WHERE return_date IS NULL")["c"][0]
    total_issues = fetch_df("SELECT COUNT(*) AS c FROM transactions")["c"][0]

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Books", total_books)
    c2.metric("Issued Now (open)", issued_now)
    c3.metric("Total Issues Ever", total_issues)

    st.subheader("Genres (table)")
    genre_tbl = fetch_df("""
        SELECT
          COALESCE(genre,'(Uncategorized)') AS Genre,
          COUNT(*) AS Titles,
          SUM(
            EXISTS(
              SELECT 1 FROM transactions t
              WHERE t.book_id = b.id AND t.return_date IS NULL
            )
          ) AS Titles_Issued_Now
        FROM books b
        GROUP BY genre
        ORDER BY Titles DESC, Genre
    """)
    st.dataframe(genre_tbl, use_container_width=True)

    st.markdown("### Pick a genre to see its books")
    genres = ["(All)"] + sorted(genre_tbl["Genre"].unique().tolist())
    pick = st.selectbox("Genre", genres, index=0)

    if pick == "(All)":
        books_in_genre = fetch_df("""
          SELECT b.id, b.title AS Title, b.author AS Author,
                 COALESCE(b.genre,'(Uncategorized)') AS Genre,
                 (SELECT COUNT(*) FROM transactions t
                  WHERE t.book_id=b.id AND t.return_date IS NULL) AS Issued_Now
          FROM books b
          ORDER BY b.title
        """)
    else:
        books_in_genre = fetch_df("""
          SELECT b.id, b.title AS Title, b.author AS Author,
                 COALESCE(b.genre,'(Uncategorized)') AS Genre,
                 (SELECT COUNT(*) FROM transactions t
                  WHERE t.book_id=b.id AND t.return_date IS NULL) AS Issued_Now
          FROM books b
          WHERE COALESCE(b.genre,'(Uncategorized)') = ?
          ORDER BY b.title
        """, (pick,))

    st.dataframe(books_in_genre, use_container_width=True)


def page_search():
    st.title("🔎 Search")
    q = st.text_input("Type a keyword (title/author/genre)")
    if q:
        df = fetch_df("""
            SELECT id, title, author, genre, default_location
            FROM books
            WHERE title LIKE ? OR author LIKE ? OR genre LIKE ?
            ORDER BY title
        """, (f"%{q}%", f"%{q}%", f"%{q}%"))
        st.dataframe(df, use_container_width=True)


def page_books():
    st.title("📖 Books")
    with st.expander("➕ Add a Book"):
        title = st.text_input("Title")
        author = st.text_input("Author")
        genre = st.text_input("Genre")
        default_location = selectbox_location("Default Location", allow_empty=True)
        if st.button("Add Book", type="primary") and title.strip():
            exec_sql("""
                INSERT INTO books(title, author, genre, default_location)
                VALUES (?, ?, ?, ?)
            """, (title.strip(), author.strip(), genre.strip(), default_location))
            st.success("Book added.")
            st.rerun()

    df = fetch_df("SELECT id, title, author, genre, default_location FROM books ORDER BY title")
    st.dataframe(df, use_container_width=True)


def page_copies():
    st.title("📦 Copies")
    with st.expander("➕ Add a Copy"):
        book_id, book_title = selectbox_book()
        acc = st.text_input("Accession / Copy No.")
        loc = selectbox_location("Current Location", allow_empty=True)
        if st.button("Add Copy", type="primary") and book_id:
            exec_sql("""
                INSERT INTO copies(book_id, accession_no, current_location, status)
                VALUES (?, ?, ?, 'available')
            """, (book_id, acc.strip(), loc))
            st.success(f"Copy added for: {book_title}")
            st.rerun()

    df = fetch_df("""
        SELECT c.id, b.title, b.author, c.accession_no, c.status, c.current_location,
               c.issued_to, c.issue_date, c.due_date
        FROM copies c
        JOIN books b ON b.id = c.book_id
        ORDER BY b.title
    """)
    st.dataframe(df, use_container_width=True)


def page_issue_return():
    st.title("🔄 Issue / Return")

    st.subheader("Issue a Copy")
    # available copies
    avail = fetch_df("""
        SELECT c.id, (b.title || CASE WHEN IFNULL(c.accession_no,'')<>'' THEN ' — '|| c.accession_no ELSE '' END) AS label
        FROM copies c JOIN books b ON b.id=c.book_id
        WHERE c.status='available'
        ORDER BY b.title
    """)
    if avail.empty:
        st.info("No available copies.")
    else:
        pick = st.selectbox("Choose copy to issue", avail["label"].tolist())
        copy_id = int(avail.iloc[avail["label"].tolist().index(pick)]["id"])
        issued_to = st.text_input("Issued to (name)")
        days = st.number_input("Days until due", 1, 60, 14)
        if st.button("Issue"):
            today = datetime.now().date()
            due = today + timedelta(days=int(days))
            exec_sql("""
                UPDATE copies
                SET status='issued', issued_to=?, issue_date=?, due_date=?
                WHERE id=?
            """, (issued_to.strip(), str(today), str(due), copy_id))
            st.success("Issued.")
            st.rerun()

    st.subheader("Return a Copy")
    out = fetch_df("""
        SELECT c.id, (b.title || CASE WHEN IFNULL(c.accession_no,'')<>'' THEN ' — '|| c.accession_no ELSE '' END) AS label
        FROM copies c JOIN books b ON b.id=c.book_id
        WHERE c.status='issued'
        ORDER BY b.title
    """)
    if out.empty:
        st.info("No open issues.")
    else:
        pick2 = st.selectbox("Choose copy to return", out["label"].tolist())
        copy_id2 = int(out.iloc[out["label"].tolist().index(pick2)]["id"])
        if st.button("Return"):
            exec_sql("""
                UPDATE copies
                SET status='available', issued_to=NULL, issue_date=NULL, due_date=NULL
                WHERE id=?
            """, (copy_id2,))
            st.success("Returned.")
            st.rerun()


def page_locations():
    st.title("📍 Locations")
    with st.expander("➕ Add a Location"):
        name = st.text_input("Name")
        desc = st.text_input("Description")
        if st.button("Add Location", type="primary") and name.strip():
            exec_sql("INSERT OR IGNORE INTO locations(name, description) VALUES(?, ?)", (name.strip(), desc.strip()))
            st.success("Location added.")
            st.rerun()

    df = fetch_df("SELECT id, name, description FROM locations ORDER BY id")
    st.dataframe(df, use_container_width=True)


def page_import_export():
    st.title("⬆️⬇️ Import / Export")

    st.subheader("Repair / Initialize")
    if st.button("Run repair (recreate tables & 45 compartments)"):
        init_db()
        migrate_locations()
        ensure_default_locations(45)
        st.success("Repair done.")

    st.subheader("Import Books (CSV)")
    st.caption("Expected columns: title, author, genre, default_location (others ignored)")
    up = st.file_uploader("Upload CSV", type=["csv"])
    if up is not None:
        df = pd.read_csv(up)
        needed = {"title", "author", "genre", "default_location"}
        if not needed.issubset(set(c.lower() for c in df.columns)):
            st.error("CSV missing required columns.")
        else:
            # Normalize columns
            cols_map = {c: c.lower() for c in df.columns}
            df.rename(columns=cols_map, inplace=True)
            rows = []
            for _, r in df.iterrows():
                rows.append((
                    str(r.get("title","")).strip(),
                    str(r.get("author","")).strip(),
                    str(r.get("genre","")).strip(),
                    str(r.get("default_location","")).strip()
                ))
            # insert (simple upsert on title+author)
            with get_conn() as con:
                cur = con.cursor()
                cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_books_title_author ON books(title, author)")
                cur.executemany("""
                    INSERT OR IGNORE INTO books(title, author, genre, default_location)
                    VALUES(?, ?, ?, ?)
                """, rows)
                con.commit()
            st.success(f"Imported {len(rows)} rows (existing titles skipped).")

    st.subheader("Export (CSV)")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Export Books"):
            df = fetch_df("SELECT * FROM books ORDER BY title")
            st.download_button("Download books.csv", df.to_csv(index=False).encode("utf-8"), "books.csv", "text/csv")
    with c2:
        if st.button("Export Copies"):
            df = fetch_df("SELECT * FROM copies ORDER BY id")
            st.download_button("Download copies.csv", df.to_csv(index=False).encode("utf-8"), "copies.csv", "text/csv")
    with c3:
        if st.button("Export Locations"):
            df = fetch_df("SELECT * FROM locations ORDER BY id")
            st.download_button("Download locations.csv", df.to_csv(index=False).encode("utf-8"), "locations.csv", "text/csv")


# --------------------------- Main --------------------------- #
def main():
    st.set_page_config(page_title="KEN Library", page_icon="📚", layout="wide")

    # Ensure DB & 45 compartments exist (and columns are correct)
    init_db()
    migrate_locations()
    ensure_default_locations(45)

    with st.sidebar:
        st.markdown("## Go to")
        page = st.radio("", [
            "Dashboard", "Search", "Books", "Copies", "Issue / Return", "Locations", "Import / Export"
        ], index=0)

    pages = {
        "Dashboard": page_dashboard,
        "Search": page_search,
        "Books": page_books,
        "Copies": page_copies,
        "Issue / Return": page_issue_return,
        "Locations": page_locations,
        "Import / Export": page_import_export,
    }
    pages[page]()


if __name__ == "__main__":
    main()
