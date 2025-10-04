
import streamlit as st
import sqlite3
import pandas as pd
from io import BytesIO
import qrcode
from PIL import Image
from datetime import date, timedelta

DB_PATH = "library.db"

# ---------- DB helpers ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    with open("schema.sql", "r", encoding="utf-8") as f:
        schema = f.read()
    conn = get_conn()
    with conn:
        conn.executescript(schema)
    conn.close()

def fetch_df(query, params=()):
    conn = get_conn()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def run_write(query, params=()):
    conn = get_conn()
    with conn:
        conn.execute(query, params)
    conn.close()

def run_write_return_id(query, params=()):
    conn = get_conn()
    with conn:
        cur = conn.execute(query, params)
        new_id = cur.lastrowid
    conn.close()
    return new_id

# ---------- Derived helpers ----------
def availability_of_copy(copy_id):
    # If any open transaction exists (no return_date), copy is Issued
    df = fetch_df("SELECT * FROM transactions WHERE copy_id=? AND (return_date IS NULL OR return_date='')", (copy_id,))
    return "Issued" if len(df) > 0 else "Available"

def issued_to(copy_id):
    df = fetch_df("""
        SELECT m.name FROM transactions t
        JOIN members m ON m.id = t.member_id
        WHERE t.copy_id=? AND (t.return_date IS NULL OR t.return_date='')
        ORDER BY t.id DESC LIMIT 1
    """, (copy_id,))
    return df['name'].iloc[0] if len(df)>0 else ""

def ensure_default_locations():
    # Preload compartments 1..45 if empty
    df = fetch_df("SELECT COUNT(*) AS c FROM locations")
    if df['c'].iloc[0] == 0:
        conn = get_conn()
        with conn:
            for i in range(1, 46):
                conn.execute("INSERT INTO locations(location_id, description) VALUES(?,?)",
                             (f"Compartment {i}", ""))
        conn.close()

# ---------- UI ----------
st.set_page_config(page_title="KEN Library", layout="wide")
st.title("📚 KEN Library System")

# Sidebar nav
page = st.sidebar.radio("Go to", [
    "Dashboard",
    "Search",
    "Books",
    "Copies",
    "Members",
    "Issue / Return",
    "Locations",
    "Import / Export",
])

# One-time DB init
if 'db_inited' not in st.session_state:
    init_db()
    ensure_default_locations()
    st.session_state['db_inited'] = True

# ---------- Dashboard ----------
if page == "Dashboard":
    col1, col2, col3 = st.columns(3)
    total_titles = fetch_df("SELECT COUNT(*) AS c FROM books")['c'].iloc[0]
    total_copies = fetch_df("SELECT COUNT(*) AS c FROM copies")['c'].iloc[0]
    issued_now = fetch_df("SELECT COUNT(*) AS c FROM transactions WHERE (return_date IS NULL OR return_date='')")['c'].iloc[0]

    with col1:
        st.metric("Total Titles", total_titles)
    with col2:
        st.metric("Total Copies", total_copies)
    with col3:
        st.metric("Issued Now (open)", issued_now)

    # Titles by Genre
    genre_df = fetch_df("SELECT genre AS Genre, COUNT(*) AS Titles FROM books GROUP BY genre ORDER BY Titles DESC")
    st.subheader("Titles by Genre")
    st.bar_chart(genre_df, x="Genre", y="Titles")

    # Overdue list
    st.subheader("Overdue")
    overdue = fetch_df("""
        SELECT t.id AS Issue_ID, c.accession_no, b.title, m.name AS member, t.issue_date, t.due_date
        FROM transactions t
        JOIN copies c ON c.id = t.copy_id
        JOIN books b ON b.id = c.book_id
        JOIN members m ON m.id = t.member_id
        WHERE (t.return_date IS NULL OR t.return_date='') AND t.due_date IS NOT NULL AND DATE(t.due_date) < DATE('now')
        ORDER BY t.due_date ASC
    """)
    st.dataframe(overdue)

# ---------- Search ----------
elif page == "Search":
    q = st.text_input("Type part of a title to search")
    if q:
        res = fetch_df("""
            SELECT b.title, b.author, b.genre, b.default_location, c.accession_no,
                   COALESCE(NULLIF(?,''), '') as query
            FROM books b
            LEFT JOIN copies c ON c.book_id = b.id
            WHERE LOWER(b.title) LIKE LOWER(?) OR LOWER(b.author) LIKE LOWER(?)
            ORDER BY b.title
        """, (q, f"%{q}%", f"%{q}%"))
    else:
        res = fetch_df("""
            SELECT b.title, b.author, b.genre, b.default_location, c.accession_no
            FROM books b LEFT JOIN copies c ON c.book_id = b.id
            ORDER BY b.title
            LIMIT 50
        """)
    st.dataframe(res)

# ---------- Books ----------
elif page == "Books":
    st.subheader("Add a Book")
    with st.form("add_book"):
        title = st.text_input("Title*", key="title")
        author = st.text_input("Author", key="author")
        genre = st.text_input("Genre", key="genre")
        publisher = st.text_input("Publisher", key="publisher")
        year = st.text_input("Year", key="year")
        isbn = st.text_input("ISBN", key="isbn")
        default_location = st.text_input("Default Location (e.g., Compartment 12)", key="defloc")
        notes = st.text_area("Notes", key="notes")
        submitted = st.form_submit_button("Add Book")
        if submitted and title.strip():
            run_write("""
                INSERT OR IGNORE INTO books(title, author, genre, publisher, year, isbn, default_location, notes)
                VALUES(?,?,?,?,?,?,?,?)
            """, (title.strip(), author, genre, publisher, year, isbn, default_location, notes))
            st.success("Book added.")

    st.subheader("All Books")
    books = fetch_df("SELECT id, title, author, genre, default_location FROM books ORDER BY title")
    st.dataframe(books)

# ---------- Copies ----------
elif page == "Copies":
    st.subheader("Add a Copy")
    books = fetch_df("SELECT id, title FROM books ORDER BY title")
    if len(books)==0:
        st.info("Add a book first on the Books page.")
    else:
        with st.form("add_copy"):
            book_title = st.selectbox("Book", options=books['title'].tolist())
            accession_no = st.text_input("Accession No (e.g., KEN-00001)")
            cond = st.selectbox("Condition", ["Good","Worn","Damaged"])
            acquired_date = st.date_input("Acquired Date", value=date.today())
            purchase_price = st.text_input("Purchase Price (optional)")
            current_location = st.text_input("Current Location (e.g., Compartment 12)")
            submit = st.form_submit_button("Add Copy")
            if submit:
                book_id = int(books.loc[books['title']==book_title, 'id'].iloc[0])
                run_write("""
                    INSERT OR IGNORE INTO copies(accession_no, book_id, condition, acquired_date, purchase_price, current_location)
                    VALUES(?,?,?,?,?,?)
                """, (accession_no.strip() if accession_no else None, book_id, cond, str(acquired_date), purchase_price or None, current_location or None))
                st.success("Copy added.")

    st.subheader("All Copies (with status)")
    copies = fetch_df("""
        SELECT c.id, c.accession_no, b.title, c.current_location
        FROM copies c JOIN books b ON b.id = c.book_id
        ORDER BY b.title
    """)
    # compute availability quickly
    if len(copies)>0:
        copies['Availability'] = copies['id'].apply(lambda cid: availability_of_copy(int(cid)))
        copies['Issued To'] = copies['id'].apply(lambda cid: issued_to(int(cid)))
    st.dataframe(copies)

    st.subheader("Download QR for a Copy")
    copy_list = fetch_df("SELECT id, accession_no, (SELECT title FROM books WHERE books.id=copies.book_id) as title FROM copies")
    if len(copy_list)>0:
        opt = st.selectbox("Choose copy", options=copy_list['accession_no'].fillna("N/A").tolist())
        if opt:
            row = copy_list.loc[copy_list['accession_no']==opt].iloc[0]
            qr_text = f"KEN|{row['accession_no']}|{row['title']}"
            if st.button("Generate QR"):
                img = qrcode.make(qr_text)
                st.image(img, caption=qr_text)
                buf = BytesIO()
                img.save(buf, format="PNG")
                st.download_button("Download QR PNG", data=buf.getvalue(), file_name=f"{row['accession_no']}.png", mime="image/png")

# ---------- Members ----------
elif page == "Members":
    st.subheader("Add a Member")
    with st.form("add_member"):
        name = st.text_input("Name*")
        phone = st.text_input("Phone")
        email = st.text_input("Email")
        notes = st.text_area("Notes")
        s = st.form_submit_button("Add Member")
        if s and name.strip():
            run_write("INSERT INTO members(name, phone, email, notes) VALUES(?,?,?,?)",
                      (name.strip(), phone, email, notes))
            st.success("Member added.")

    st.subheader("All Members")
    ms = fetch_df("SELECT id, name, phone, email FROM members ORDER BY name")
    st.dataframe(ms)

# ---------- Issue / Return ----------
elif page == "Issue / Return":
    st.subheader("Issue a Book")
    # copies available
    avail = fetch_df("""
        SELECT c.id, c.accession_no, b.title FROM copies c
        JOIN books b ON b.id = c.book_id
        WHERE c.id NOT IN (SELECT copy_id FROM transactions WHERE return_date IS NULL OR return_date='')
        ORDER BY b.title
    """)
    mems = fetch_df("SELECT id, name FROM members ORDER BY name")

    with st.form("issue_form"):
        copy_choice = st.selectbox("Copy (only available listed)", options=avail['accession_no'].tolist() if len(avail)>0 else [])
        member_choice = st.selectbox("Member", options=mems['name'].tolist() if len(mems)>0 else [])
        issue_date = st.date_input("Issue Date", value=date.today())
        due_date = st.date_input("Due Date", value=date.today()+timedelta(days=14))
        s = st.form_submit_button("Issue")
        if s:
            if len(avail)==0 or len(mems)==0:
                st.error("Need at least one available copy and one member.")
            else:
                copy_id = int(avail.loc[avail['accession_no']==copy_choice, 'id'].iloc[0])
                member_id = int(mems.loc[mems['name']==member_choice, 'id'].iloc[0])
                run_write("""INSERT INTO transactions(copy_id, member_id, issue_date, due_date) VALUES(?,?,?,?)""",
                          (copy_id, member_id, str(issue_date), str(due_date)))
                st.success("Issued.")

    st.subheader("Return a Book")
    open_tx = fetch_df("""
        SELECT t.id, c.accession_no, b.title, m.name AS member, t.issue_date, t.due_date
        FROM transactions t
        JOIN copies c ON c.id = t.copy_id
        JOIN books b ON b.id = c.book_id
        JOIN members m ON m.id = t.member_id
        WHERE t.return_date IS NULL OR t.return_date=''
        ORDER BY t.id DESC
    """)
    if len(open_tx)>0:
        idx = st.selectbox("Open issues", options=open_tx['id'].tolist(),
                           format_func=lambda i: f"{int(i)} – {open_tx.loc[open_tx['id']==i, 'accession_no'].iloc[0]} – {open_tx.loc[open_tx['id']==i, 'title'].iloc[0]} ({open_tx.loc[open_tx['id']==i, 'member'].iloc[0]})")
        if st.button("Mark Returned Today"):
            run_write("UPDATE transactions SET return_date = DATE('now') WHERE id=?", (int(idx),))
            st.success("Returned.")

    st.subheader("All Transactions (latest 200)")
    tx = fetch_df("""
        SELECT t.id, c.accession_no, b.title, m.name AS member, t.issue_date, t.due_date, t.return_date
        FROM transactions t
        JOIN copies c ON c.id = t.copy_id
        JOIN books b ON b.id = c.book_id
        JOIN members m ON m.id = t.member_id
        ORDER BY t.id DESC LIMIT 200
    """)
    st.dataframe(tx)

# ---------- Locations ----------
elif page == "Locations":
    st.subheader("Add / Edit Locations")
    locs = fetch_df("SELECT id, location_id, description FROM locations ORDER BY id")
    st.dataframe(locs, use_container_width=True)
    with st.form("add_loc"):
        lid = st.text_input("Location ID (e.g., Compartment 12)")
        desc = st.text_input("Description")
        s = st.form_submit_button("Add Location")
        if s and lid.strip():
            run_write("INSERT OR IGNORE INTO locations(location_id, description) VALUES(?,?)", (lid.strip(), desc))
            st.success("Location added.")

# ---------- Import / Export ----------
elif page == "Import / Export":
    st.subheader("Import Books (CSV)")
    up = st.file_uploader("Upload CSV with columns: Title, Author, Genre, Default_Location (optional)", type=["csv"])
    if up is not None:
        imp = pd.read_csv(up)
        ok = 0
        for _, r in imp.iterrows():
            title = str(r.get("Title","")).strip()
            if not title: 
                continue
            author = str(r.get("Author",""))
            genre = str(r.get("Genre",""))
            defloc = str(r.get("Default_Location",""))
            run_write("""
                INSERT OR IGNORE INTO books(title, author, genre, default_location)
                VALUES(?,?,?,?)
            """, (title, author, genre, defloc))
            ok += 1
        st.success(f"Imported {ok} titles.")

    st.subheader("Export CSVs")
    if st.button("Export Books"):
        df = fetch_df("SELECT * FROM books ORDER BY title")
        st.download_button("Download Books.csv", data=df.to_csv(index=False), file_name="Books.csv", mime="text/csv")
    if st.button("Export Copies"):
        df = fetch_df("SELECT * FROM copies ORDER BY id")
        st.download_button("Download Copies.csv", data=df.to_csv(index=False), file_name="Copies.csv", mime="text/csv")
    if st.button("Export Members"):
        df = fetch_df("SELECT * FROM members ORDER BY name")
        st.download_button("Download Members.csv", data=df.to_csv(index=False), file_name="Members.csv", mime="text/csv")
    if st.button("Export Transactions"):
        df = fetch_df("SELECT * FROM transactions ORDER BY id DESC")
        st.download_button("Download Transactions.csv", data=df.to_csv(index=False), file_name="Transactions.csv", mime="text/csv")
    if st.button("Export Locations"):
        df = fetch_df("SELECT * FROM locations ORDER BY id")
        st.download_button("Download Locations.csv", data=df.to_csv(index=False), file_name="Locations.csv", mime="text/csv")
