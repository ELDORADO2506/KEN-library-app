
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS locations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  location_id TEXT UNIQUE NOT NULL,
  description TEXT
);

CREATE TABLE IF NOT EXISTS books (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT UNIQUE NOT NULL,
  author TEXT,
  genre TEXT,
  publisher TEXT,
  year TEXT,
  isbn TEXT,
  default_location TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS copies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  accession_no TEXT UNIQUE,
  book_id INTEGER NOT NULL,
  condition TEXT,
  acquired_date TEXT,
  purchase_price REAL,
  current_location TEXT,
  FOREIGN KEY(book_id) REFERENCES books(id)
);

CREATE TABLE IF NOT EXISTS members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  phone TEXT,
  email TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  copy_id INTEGER NOT NULL,
  member_id INTEGER NOT NULL,
  issue_date TEXT NOT NULL,
  due_date TEXT,
  return_date TEXT,
  FOREIGN KEY(copy_id) REFERENCES copies(id),
  FOREIGN KEY(member_id) REFERENCES members(id)
);
