# KEN Library System - simple & safe Streamlit + SQLite app
import os, sqlite3, io, datetime as dt
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KEN Library System", page_icon="📚", layout="wide")

DB_PATH = "library.db"

# ----------------------------- DB helpers -----------------------------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def exec_sql(sql, params=()):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(sql, params)
        con.commit()

def exec_many(sql, rows):
    with get_conn() as con:
        cur = con.cursor()
        cur.executemany(sql, rows)
        con.commit()

def fetch_df(sql, params=()):
    with get_conn() as con:
        return pd.read_sql_query(sql, con, params=params)

# safe read: if table missing/empty, return empty DataFrame instead of crashing
def safe_df(sql, params=()):
    try:
        return fetch_df(sql, params)
    except Exception:
        return pd.DataFrame()

# ----------------------------- Schema & init -----------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS books(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT UNIQUE,
    author TEXT,
    genre TEXT,
    default_location TEXT
);

CREATE TABLE IF NOT EXISTS copies(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER,
    accession_no TEXT UNIQUE,
    current_location TEXT,
    status TEXT DEFAULT 'available',
    FOREIGN KEY(book_id) REFERENCES books(id)
);

CREATE TABLE IF NOT EXISTS members(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT
);

CREATE TABLE IF NOT EXISTS transactions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    copy_id INTEGER,
    member_id INTEGER,
    issue_date TEXT,
    due_date TEXT,
    return_date TEXT,
    FOREIGN KEY(copy_id) REFERENCES copies(id),
    FOREIGN KEY(member_id) REFERENCES members(id)
);

CREATE TABLE IF NOT EXISTS locations(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    description TEXT
);
"""

def init_db():
    with get_conn() as con:
        con.executescript(SCHEMA)

def ensure_default_locations(n=45):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM locations")
        count = cur.fetchone()[0]
        # insert missing Compartment 1..n (keeps existing ones)
        for i in range(1, n+1):
            cur.execute(
                "INSERT OR IGNORE INTO locations(name, description) VALUES(?, ?)",
                (f"Compartment {i}", f"Shelf compartment #{i}"),
            )
        con.commit()

# ----------------------------- Small utilities -----------------------------
def title_bar():
    st.markdown(
        "<h1 style='display:flex;align-items:center;gap:.5rem'>"
        "<span>📚</span> KEN Library System</h1>",
        unsafe_allow_html=True,
    )

def header_stats():
    total_titles = safe_df("SELECT COUNT(*) AS c FROM books")
    total_copies = safe_df("SELECT COUNT(*) AS c FROM copies")
    open_issues = safe_df(
        "SELECT COUNT(*) AS c FROM transactions WHERE return_date IS NULL"
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Titles", int(total_titles.c.iloc[0]) if not total_titles.empty else 0)
    c2.metric("Total Copies", int(total_copies.c.iloc[0]) if not total_copies.empty else 0)
    c3.metric("Issued Now (open)", int(open_issues.c.iloc[0]) if not open_issues.empty else 0)

# ----------------------------- Pages -----------------------------
def page_dashboard():
    title_bar()
    header_stats()

    by_genre = safe_df("""
        SELECT genre, COUNT(*) AS titles
        FROM books
        GROUP BY genre
        ORDER BY titles DESC
    """)
    st.markdown("### Titles by Genre")
    if by_genre.empty:
        st.info("No data yet. Import your CSV on **Import / Export**.")
    else:
        st.bar_chart(by_genre.set_index("genre"))

def page_books():
    st.subheader("Books")

    # list
    df = safe_df("SELECT id, title, author, genre, default_location FROM books ORDER BY title")
    st.dataframe(df, use_container_width=True, height=400)

    st.divider()
    st.markdown("### Add / Update (single)")
    with st.form("add_book"):
        t = st.text_input("Title*")
        a = st.text_input("Author")
        g = st.text_input("Genre")
        loc = st.text_input("Default_Location (e.g., Compartment 1)")
        submitted = st.form_submit_button("Save / Update")
        if submitted and t.strip():
            with get_conn() as con:
                con.execute("""
                    INSERT INTO books(title, author, genre, default_location)
                    VALUES(?,?,?,?)
                    ON CONFLICT(title) DO UPDATE SET
                      author=excluded.author,
                      genre=excluded.genre,
                      default_location=excluded.default_location
                """, (t.strip(), a.strip(), g.strip(), loc.strip()))
            st.success("Saved.")
            st.rerun()

def page_copies():
    st.subheader("Copies")
    df = safe_df("""
        SELECT c.id, b.title, c.accession_no, c.current_location, c.status
        FROM copies c
        JOIN books b ON b.id = c.book_id
        ORDER BY b.title
    """)
    if df.empty:
        st.info("No copies yet. Add a copy below.")
    else:
        st.dataframe(df, use_container_width=True, height=400)

    st.markdown("### Add a Copy")
    books_list = safe_df("SELECT id, title FROM books ORDER BY title")
    if books_list.empty:
        st.warning("Add books first (Books page or Import / Export).")
        return
    book_label = st.selectbox("Select book", books_list["title"].tolist())
    book_id = int(books_list.loc[books_list["title"] == book_label, "id"].iloc[0])
    acc = st.text_input("Accession No (must be unique)")
    cur_loc = st.text_input("Current Location (e.g., Compartment 5)")
    if st.button("Add Copy"):
        if acc.strip():
            try:
                exec_sql(
                    "INSERT INTO copies(book_id, accession_no, current_location, status) VALUES(?,?,?, 'available')",
                    (book_id, acc.strip(), cur_loc.strip()),
                )
                st.success("Copy added.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("That accession number already exists.")

def page_members():
    st.subheader("Members")
    df = safe_df("SELECT id, name, email FROM members ORDER BY name")
    st.dataframe(df, use_container_width=True, height=350)
    st.markdown("### Add member")
    n = st.text_input("Name")
    e = st.text_input("Email")
    if st.button("Save Member"):
        if n.strip():
            exec_sql("INSERT INTO members(name, email) VALUES(?,?)", (n.strip(), e.strip()))
            st.success("Saved.")
            st.rerun()

def page_issue_return():
    st.subheader("Issue / Return")

    # Copies available to issue
    copies = safe_df("""
        SELECT c.id, b.title || ' — ' || IFNULL(c.accession_no,'') AS label
        FROM copies c JOIN books b ON b.id = c.book_id
        WHERE c.status='available'
        ORDER BY b.title
    """)
    members = safe_df("SELECT id, name FROM members ORDER BY name")

    with st.expander("Issue a Copy", expanded=True):
        if copies.empty or members.empty:
            st.info("Need at least one available copy and one member.")
        else:
            sel = st.selectbox("Copy", copies["label"].tolist())
            copy_id = int(copies.loc[copies["label"] == sel, "id"].iloc[0])
            mem_name = st.selectbox("Member", members["name"].tolist())
            mem_id = int(members.loc[members["name"] == mem_name, "id"].iloc[0])
            due = st.date_input("Due date", dt.date.today() + dt.timedelta(days=14))
            if st.button("Issue"):
                with get_conn() as con:
                    con.execute("UPDATE copies SET status='issued' WHERE id=?", (copy_id,))
                    con.execute("""
                        INSERT INTO transactions(copy_id, member_id, issue_date, due_date, return_date)
                        VALUES(?,?,?,?,NULL)
                    """, (copy_id, mem_id, dt.date.today().isoformat(), due.isoformat()))
                    con.commit()
                st.success("Issued.")
                st.rerun()

    st.divider()
    # Open issues
    open_tx = safe_df("""
        SELECT t.id, b.title, c.accession_no, m.name, t.issue_date, t.due_date
        FROM transactions t
        JOIN copies c ON c.id=t.copy_id
        JOIN books b ON b.id=c.book_id
        JOIN members m ON m.id=t.member_id
        WHERE t.return_date IS NULL
        ORDER BY t.issue_date DESC
    """)
    st.markdown("### Open Issues")
    st.dataframe(open_tx, use_container_width=True, height=300)

    with st.expander("Return a Copy"):
        if open_tx.empty:
            st.info("Nothing to return.")
        else:
            labels = (open_tx["title"] + " — " + open_tx["name"] + " — " + open_tx["accession_no"].astype(str)).tolist()
            sel2 = st.selectbox("Select to return", labels)
            tx_id = int(open_tx.iloc[labels.index(sel2)]["id"])
            copy_id = int(safe_df("SELECT copy_id FROM transactions WHERE id=?", (tx_id,)).iloc[0]["copy_id"])
            if st.button("Return"):
                with get_conn() as con:
                    con.execute("UPDATE transactions SET return_date=? WHERE id=?", (dt.date.today().isoformat(), tx_id))
                    con.execute("UPDATE copies SET status='available' WHERE id=?", (copy_id,))
                    con.commit()
                st.success("Returned.")
                st.rerun()

def page_locations():
    st.subheader("Locations")

    locs = safe_df("SELECT name FROM locations ORDER BY id")
    if locs.empty:
        st.info("No locations yet. Go to **Import / Export → Run repair**.")
        return

    loc_name = st.selectbox("Choose a compartment", locs["name"].tolist(), index=0)

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("#### Titles assigned here (by Default_Location)")
        titles = safe_df("""
            SELECT id, title, author, genre
            FROM books
            WHERE default_location = ?
            ORDER BY title
        """, (loc_name,))
        st.dataframe(titles, use_container_width=True, height=350)

    with c2:
        st.markdown("#### Copies currently here")
        copies_here = safe_df("""
            SELECT c.id AS Copy_ID, b.title, c.accession_no, c.status
            FROM copies c
            JOIN books b ON b.id = c.book_id
            WHERE c.current_location = ?
            ORDER BY b.title
        """, (loc_name,))
        st.dataframe(copies_here, use_container_width=True, height=350)

def page_import_export():
    st.subheader("Import / Export")

    # ---- Repair / Initialize DB ----
    st.markdown("### Repair / Initialize database")
    if st.button("Run repair (create tables & 45 compartments)"):
        init_db()
        ensure_default_locations(45)
        st.success("Database ready. You can import your CSV now.")
        st.rerun()

    st.divider()
    st.markdown("### Merge import (no duplicates)")
    st.caption("CSV must have headers exactly: Title,Author,Genre,Default_Location")
    up = st.file_uploader("Upload CSV", type=["csv"])
    if up is not None:
        try:
            df = pd.read_csv(up).fillna("")
            required = {"Title","Author","Genre","Default_Location"}
            if not required.issubset(set(df.columns)):
                st.error(f"CSV must contain columns: {', '.join(required)}")
            else:
                # upsert books by Title
                rows = [(r["Title"].strip(), r["Author"].strip(), r["Genre"].strip(), r["Default_Location"].strip())
                        for _, r in df.iterrows() if str(r["Title"]).strip()]
                with get_conn() as con:
                    con.executemany("""
                        INSERT INTO books(title, author, genre, default_location)
                        VALUES(?,?,?,?)
                        ON CONFLICT(title) DO UPDATE SET
                          author=excluded.author,
                          genre=excluded.genre,
                          default_location=excluded.default_location
                    """, rows)
                    con.commit()
                st.success(f"Imported/updated {len(rows)} titles.")
                st.rerun()
        except Exception as e:
            st.error(f"Could not read CSV: {e}")

    st.divider()
    st.markdown("### Export titles (CSV)")
    if st.button("Download CSV of books"):
        df = safe_df("SELECT title AS Title, author AS Author, genre AS Genre, default_location AS Default_Location FROM books ORDER BY title")
        if df.empty:
            st.info("No books to export.")
        else:
            buff = io.StringIO()
            df.to_csv(buff, index=False)
            st.download_button("Save file", buff.getvalue(), "books_export.csv", "text/csv")

# ----------------------------- Main router -----------------------------
def main():
    init_db()                 # make sure tables exist
    ensure_default_locations(45)

    with st.sidebar:
        st.markdown("### Go to")
        page = st.radio(
            label="",
            options=["Dashboard","Search","Books","Copies","Members","Issue / Return","Locations","Import / Export"],
            index=0
        )

    if page == "Dashboard":
        page_dashboard()
    elif page == "Search":
        st.subheader("Search")
        q = st.text_input("Type part of a title, author, or genre")
        if q.strip():
            res = safe_df("""
                SELECT title, author, genre, default_location
                FROM books
                WHERE title LIKE ? OR author LIKE ? OR genre LIKE ?
                ORDER BY title
            """, (f"%{q}%", f"%{q}%", f"%{q}%"))
            st.dataframe(res, use_container_width=True, height=500)
        else:
            st.info("Type to search.")
    elif page == "Books":
        page_books()
    elif page == "Copies":
        page_copies()
    elif page == "Members":
        page_members()
    elif page == "Issue / Return":
        page_issue_return()
    elif page == "Locations":
        page_locations()
    elif page == "Import / Export":
        page_import_export()

if __name__ == "__main__":
    main()
