# --- app.py starts here ---
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date

DB_PATH = "library.db"

# ---------------- DB Helpers ----------------
def get_conn():
    return sqlite3.connect(DB_PATH)

def run_write(sql, params=()):
    conn = get_conn()
    with conn:
        conn.execute(sql, params)
    conn.close()

def run_write_many(sql, rows):
    conn = get_conn()
    with conn:
        conn.executemany(sql, rows)
    conn.close()

def fetch_df(sql, params=()):
    conn = get_conn()
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # Books
    cur.execute("""
    CREATE TABLE IF NOT EXISTS books(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT UNIQUE COLLATE NOCASE,
        author TEXT,
        genre TEXT,
        default_location TEXT
    );
    """)

    # Copies (physical)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS copies(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        book_id INTEGER,
        accession_no TEXT,
        current_location TEXT,
        status TEXT DEFAULT 'available',
        FOREIGN KEY(book_id) REFERENCES books(id)
    );
    """)

    # Members
    cur.execute("""
    CREATE TABLE IF NOT EXISTS members(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT
    );
    """)

    # Transactions (issue/return)
    cur.execute("""
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
    """)

    # Locations (compartments)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS locations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        location_id TEXT UNIQUE COLLATE NOCASE,
        description TEXT
    );
    """)

    # Make a unique index on book title (safe upsert)
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_books_title ON books(title COLLATE NOCASE);")

    conn.commit()
    conn.close()

def ensure_default_locations(n=45):
    # Create Compartment 1..n if not present
    existing = fetch_df("SELECT location_id FROM locations")
    have = set(x.lower() for x in existing['location_id'].tolist()) if not existing.empty else set()
    todo = []
    for i in range(1, n+1):
        lid = f"Compartment {i}"
        if lid.lower() not in have:
            todo.append((lid, f"Auto-created slot {i}"))
    if todo:
        run_write_many("INSERT OR IGNORE INTO locations(location_id, description) VALUES(?,?)", todo)

# ------------- UI: Sidebar -------------
def sidebar():
    st.sidebar.title("Go to")
    return st.sidebar.radio("", [
        "Dashboard", "Search", "Books", "Copies", "Members",
        "Issue / Return", "Locations", "Import / Export"
    ])

# ------------- Pages -------------
def page_dashboard():
    st.title("📚 KEN Library System")

    totals = {
        "titles": fetch_df("SELECT COUNT(*) c FROM books")["c"][0],
        "copies": fetch_df("SELECT COUNT(*) c FROM copies")["c"][0],
        "open_issues": fetch_df("SELECT COUNT(*) c FROM transactions WHERE return_date IS NULL")["c"][0],
    }

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Titles", totals["titles"])
    c2.metric("Total Copies", totals["copies"])
    c3.metric("Issued Now (open)", totals["open_issues"])

    by_genre = fetch_df("SELECT IFNULL(genre,'(none)') genre, COUNT(*) c FROM books GROUP BY IFNULL(genre,'(none)') ORDER BY c DESC")
    st.subheader("Titles by Genre")
    if not by_genre.empty:
        st.bar_chart(by_genre.set_index("genre")["c"])
    else:
        st.info("No data yet. Import books to get started.")

def page_search():
    st.subheader("Search")
    q = st.text_input("Search across title/author/genre")
    if q:
        qlike = f"%{q}%"
        df = fetch_df("""
            SELECT id, title, author, genre, default_location
            FROM books
            WHERE title LIKE ? OR author LIKE ? OR genre LIKE ?
            ORDER BY title
        """, (qlike, qlike, qlike))
        st.dataframe(df, use_container_width=True)

def page_books():
    st.subheader("Books")
    df = fetch_df("SELECT id, title, author, genre, default_location FROM books ORDER BY title")
    st.dataframe(df, use_container_width=True)

    st.write("---")
    st.subheader("Add a Book")
    with st.form("add_book"):
        t = st.text_input("Title")
        a = st.text_input("Author")
        g = st.text_input("Genre")
        loc = st.text_input("Default Location (e.g., Compartment 5)")
        s = st.form_submit_button("Add")
        if s and t.strip():
            try:
                run_write("INSERT INTO books(title, author, genre, default_location) VALUES(?,?,?,?)",
                          (t.strip(), a.strip(), g.strip(), loc.strip()))
                st.success("Book added.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("A book with this title already exists.")

def page_copies():
    st.subheader("Copies")
    df = fetch_df("""
        SELECT c.id, b.title, c.accession_no, c.current_location, c.status
        FROM copies c JOIN books b ON b.id = c.book_id
        ORDER BY b.title
    """)
    st.dataframe(df, use_container_width=True)

    st.write("---")
    st.subheader("Add a Copy")
    books = fetch_df("SELECT id, title FROM books ORDER BY title")
    book_map = {row["title"]: row["id"] for _, row in books.iterrows()} if not books.empty else {}

    with st.form("add_copy"):
        sel = st.selectbox("Book", options=list(book_map.keys()) if book_map else ["(no books)"])
        acc = st.text_input("Accession No (unique code)")
        loc = st.text_input("Current Location (e.g., Compartment 5)")
        s = st.form_submit_button("Add Copy")
        if s and book_map and acc.strip():
            run_write("INSERT INTO copies(book_id, accession_no, current_location, status) VALUES(?,?,?,?)",
                      (book_map[sel], acc.strip(), loc.strip(), "available"))
            st.success("Copy added.")
            st.rerun()

def page_members():
    st.subheader("Members")
    df = fetch_df("SELECT id, name, email FROM members ORDER BY name")
    st.dataframe(df, use_container_width=True)

    st.write("---")
    st.subheader("Add Member")
    with st.form("add_member"):
        n = st.text_input("Name")
        e = st.text_input("Email")
        s = st.form_submit_button("Add")
        if s and n.strip():
            run_write("INSERT INTO members(name, email) VALUES(?,?)", (n.strip(), e.strip()))
            st.success("Member added.")
            st.rerun()

def page_issue_return():
    st.subheader("Issue / Return")

    # Issue
    st.markdown("### Issue a Copy")
    copies = fetch_df("""
        SELECT c.id, b.title || ' — ' || IFNULL(c.accession_no,'') AS label
        FROM copies c JOIN books b ON b.id = c.book_id
        WHERE c.status='available'
        ORDER BY b.title
    """)
    members = fetch_df("SELECT id, name FROM members ORDER BY name")
    if copies.empty or members.empty:
        st.info("Need at least one available copy and one member.")
    else:
        copy_map = {row["label"]: row["id"] for _, row in copies.iterrows()}
        mem_map = {row["name"]: row["id"] for _, row in members.iterrows()}
        with st.form("issue_form"):
            csel = st.selectbox("Copy", list(copy_map.keys()))
            msel = st.selectbox("Member", list(mem_map.keys()))
            due = st.date_input("Due date", value=date.today())
            s = st.form_submit_button("Issue")
            if s:
                cid = copy_map[csel]
                mid = mem_map[msel]
                now = datetime.now().date().isoformat()
                run_write("INSERT INTO transactions(copy_id, member_id, issue_date, due_date) VALUES(?,?,?,?)",
                          (cid, mid, now, due.isoformat()))
                run_write("UPDATE copies SET status='issued' WHERE id=?", (cid,))
                st.success("Copy issued.")
                st.rerun()

    # Return
    st.markdown("### Return a Copy")
    open_tx = fetch_df("""
        SELECT t.id, b.title || ' — ' || IFNULL(c.accession_no,'') AS label
        FROM transactions t
        JOIN copies c ON c.id = t.copy_id
        JOIN books b ON b.id = c.book_id
        WHERE t.return_date IS NULL
        ORDER BY t.id DESC
    """)
    if open_tx.empty:
        st.info("No open issues.")
    else:
        tx_map = {row["label"]: row["id"] for _, row in open_tx.iterrows()}
        with st.form("return_form"):
            tsel = st.selectbox("Issued Copy", list(tx_map.keys()))
            s = st.form_submit_button("Return")
            if s:
                tid = tx_map[tsel]
                today = datetime.now().date().isoformat()
                # mark return
                run_write("UPDATE transactions SET return_date=? WHERE id=?", (today, tid))
                # set copy available
                # find copy id
                cdf = fetch_df("SELECT copy_id FROM transactions WHERE id=?", (tid,))
                if not cdf.empty:
                    run_write("UPDATE copies SET status='available' WHERE id=?", (int(cdf.loc[0,"copy_id"]),))
                st.success("Returned.")
                st.rerun()

def page_locations():
    st.subheader("Locations")
    ensure_default_locations(45)

    locs = fetch_df("SELECT id, location_id, description FROM locations ORDER BY id")
    st.dataframe(locs, use_container_width=True)

    st.write("---")
    st.subheader("Browse a Location")
    all_locs = locs['location_id'].tolist()
    sel = st.selectbox("Choose a location", options=all_locs)
    if sel:
        st.markdown(f"### 📍 {sel}")

        titles_here = fetch_df("""
            SELECT b.id AS Book_ID, b.title AS Title, b.author AS Author, b.genre AS Genre
            FROM books b
            WHERE LOWER(IFNULL(b.default_location,'')) = LOWER(?)
            ORDER BY b.title
        """, (sel,))
        st.markdown("**Titles assigned here (Books.default_location):**")
        st.dataframe(titles_here, use_container_width=True)

        copies_here = fetch_df("""
            SELECT c.id AS Copy_ID, c.accession_no, b.title AS Title, b.author AS Author, c.status AS Status
            FROM copies c
            JOIN books b ON b.id = c.book_id
            WHERE LOWER(IFNULL(c.current_location,'')) = LOWER(?)
            ORDER BY b.title
        """, (sel,))
        st.markdown("**Copies currently here (Copies.current_location):**")
        st.dataframe(copies_here, use_container_width=True)

    st.write("---")
    st.subheader("Add a Location")
    with st.form("add_loc"):
        lid = st.text_input("Location ID (e.g., Compartment 12)")
        desc = st.text_input("Description")
        s = st.form_submit_button("Add Location")
        if s and lid.strip():
            run_write("INSERT OR IGNORE INTO locations(location_id, description) VALUES(?,?)",
                      (lid.strip(), desc.strip()))
            st.success("Location added.")
            st.rerun()

def page_import_export():
    st.subheader("Import / Export")

    # ---- Merge import (no duplicates; updates existing titles) ----
    st.markdown("### Merge import (no duplicates)")
    merge_up = st.file_uploader(
        "Upload Books CSV (Title, Author, Genre, Default_Location)",
        type=["csv"],
        key="merge_books",
    )
    if merge_up is not None:
        df = pd.read_csv(merge_up)
        st.write("Uploaded rows:", len(df))
        st.write("Columns:", list(df.columns))

        # Ensure index for upsert
        conn = get_conn()
        with conn:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_books_title ON books(title COLLATE NOCASE);")

            # upsert each row
            for _, r in df.iterrows():
                title = str(r.get("Title", "")).strip()
                if not title:
                    continue
                author = str(r.get("Author", "")).strip()
                genre = str(r.get("Genre", "")).strip()
                defloc = str(r.get("Default_Location", "")).strip()
                conn.execute("""
                    INSERT INTO books(title, author, genre, default_location)
                    VALUES(?,?,?,?)
                    ON CONFLICT(title) DO UPDATE SET
                      author=excluded.author,
                      genre=excluded.genre,
                      default_location=excluded.default_location;
                """, (title, author, genre, defloc))
        conn.close()
        st.success("Merge import complete. Existing titles updated; new titles added.")
        st.rerun()

    # Export books
    st.markdown("### Export books (CSV)")
    if st.button("Download books.csv"):
        df = fetch_df("SELECT title AS Title, author AS Author, genre AS Genre, default_location AS Default_Location FROM books ORDER BY title")
        st.download_button("Save books.csv", data=df.to_csv(index=False), file_name="books.csv", mime="text/csv")

# ------------- Main -------------
def main():
    st.set_page_config(page_title="KEN Library System", page_icon="📚", layout="wide")
    init_db()
    ensure_default_locations(45)

    page = sidebar()
    if page == "Dashboard":
        page_dashboard()
    elif page == "Search":
        page_search()
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
# --- app.py ends here ---


   

       
