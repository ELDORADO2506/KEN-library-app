# KEN Library App (Streamlit + SQLite)

## How to run locally
1. Install Python 3.9+
2. Open a terminal in this folder.
3. Create a virtual env (optional but recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
5. Run the app:
   ```bash
   streamlit run app.py
   ```
6. Your browser will open at http://localhost:8501

## First steps in the app
- Go to **Books** to add a title.
- Go to **Copies** to add a physical copy (Accession No, condition, location).
- Go to **Members** to add a borrower.
- Use **Issue / Return** to issue a copy and mark returns.
- **Search** finds books by title/author and shows locations.
- **Dashboard** shows counts, genre chart, and overdue list.

## Deploy (Streamlit Cloud)
1. Put these files in a GitHub repo.
2. On https://streamlit.io/cloud, connect the repo and choose `app.py` as the entry point.
3. Deploy. The app will create `library.db` automatically on first run.

## Importing existing books
- Use the **Import / Export** page to upload a CSV (Title, Author, Genre, Default_Location).

