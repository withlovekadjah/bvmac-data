"""SQLite storage and DataFrame loaders for the standalone BVMAC package."""
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime

import pandas as pd

from .config import DEFAULT_DB
from .extract import BOND_COLUMNS, EQUITY_COLUMNS, FUND_COLUMNS, ISSUER_COLUMNS, QUOTE_COLUMNS

DATASETS = {
    "equities": EQUITY_COLUMNS,
    "bond_quotes": QUOTE_COLUMNS,
    "bond_issues": BOND_COLUMNS,
    "funds": FUND_COLUMNS,
    "issuer_snapshots": ISSUER_COLUMNS,
    "index": ["index_name", "value", "change_pct"],
}
KEYS = {
    "equities": ["date", "mnemo"], "bond_quotes": ["date", "mnemo"],
    "bond_issues": ["date", "mnemo"],
    "funds": ["date", "management_company", "custodian", "fund_name", "frequency", "nav_current_date"],
    "issuer_snapshots": ["date", "mnemo"], "index": ["date", "index_name"],
}


def connect(db_path=DEFAULT_DB):
    db_path = str(db_path)
    if db_path != ":memory:":
        Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    if db_path != ":memory:":
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
    if db_path != ":memory:" and Path(db_path).is_file():
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        needs_migration = False
        for table, columns in DATASETS.items():
            if table not in tables:
                continue
            info = con.execute(f'PRAGMA table_info("{table}")').fetchall()
            existing = {row[1] for row in info}
            primary = {row[1] for row in info if row[5]}
            if any(column not in existing for column in columns) or (table == "funds" and "frequency" not in primary):
                needs_migration = True
                break
        if needs_migration:
            backup = Path(db_path).with_name(
                f"{Path(db_path).stem}.pre-migration-{datetime.now():%Y%m%d-%H%M%S}.bak"
            )
            with closing(sqlite3.connect(backup)) as backup_con:
                con.backup(backup_con)
    for table, columns in DATASETS.items():
        defs = ["date TEXT NOT NULL"]
        for col in columns:
            if col in KEYS[table][1:]:
                typ = "TEXT NOT NULL"
            elif col in {"source_page", "transactions"}:
                typ = "INTEGER"
            elif col in {"issuer", "title", "isin", "mnemo", "short_name", "fund_name",
                         "management_company", "custodian", "category", "frequency", "status",
                         "asset_class", "repayment_type", "coupon_frequency", "previous_date",
                         "first_listing_date", "previous_coupon_date", "next_coupon_date",
                         "nav_previous_date", "nav_current_date", "inception_date", "dividend_date",
                         "dividend_year", "index_name"}:
                typ = "TEXT"
            else:
                typ = "REAL"
            defs.append(f'"{col}" {typ}')
        defs.append("source_file TEXT")
        primary = ", ".join(f'"{key}"' for key in KEYS[table])
        con.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(defs)}, PRIMARY KEY ({primary}))')
        existing = {row[1] for row in con.execute(f'PRAGMA table_info("{table}")')}
        for col in columns:
            if col not in existing:
                typ = "INTEGER" if col in {"source_page", "transactions"} else "REAL"
                if col in {"issuer", "title", "isin", "mnemo", "short_name", "fund_name",
                           "management_company", "custodian", "category", "frequency", "status",
                           "asset_class", "repayment_type", "coupon_frequency", "previous_date",
                           "first_listing_date", "previous_coupon_date", "next_coupon_date",
                           "nav_previous_date", "nav_current_date", "inception_date", "dividend_date",
                           "dividend_year", "index_name"}:
                    typ = "TEXT"
                con.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {typ}')
    _migrate_fund_key(con)
    con.execute("PRAGMA user_version=2")
    return con


def _migrate_fund_key(con):
    """Add frequency to the fund key after connect() has made a backup."""
    info = con.execute('PRAGMA table_info("funds")').fetchall()
    primary = {row[1] for row in info if row[5]}
    if "frequency" in primary:
        return
    cols = ["date", *FUND_COLUMNS, "source_file"]
    definitions = []
    text_columns = {"date", "management_company", "custodian", "fund_name", "frequency",
                    "category", "nav_previous_date", "nav_current_date", "inception_date", "source_file"}
    for col in cols:
        definitions.append(f'"{col}" {"TEXT" if col in text_columns else "REAL"}')
    primary = ', '.join(f'"{key}"' for key in KEYS["funds"])
    con.execute(f'CREATE TABLE funds_migrating ({", ".join(definitions)}, PRIMARY KEY ({primary}))')
    quoted_cols = ", ".join('"' + col + '"' for col in cols)
    con.execute(f'INSERT OR IGNORE INTO funds_migrating ({quoted_cols}) '
                f'SELECT {quoted_cols} FROM funds')
    con.execute('DROP TABLE funds')
    con.execute('ALTER TABLE funds_migrating RENAME TO funds')


def save_bulletin(con, datasets, day, source_file):
    try:
        for table, columns in DATASETS.items():
            frame = datasets[table].copy()
            if frame.empty:
                continue
            frame = frame.reindex(columns=columns)
            required = KEYS[table][1:]
            before = len(frame)
            frame = frame.dropna(subset=required)
            skipped = before - len(frame)
            if skipped:
                print(f"WARNING {source_file}: skipped {skipped} {table} row(s) missing database key fields")
            if frame.empty:
                continue
            con.execute(f'DELETE FROM "{table}" WHERE date = ?', (day,))
            frame.insert(0, "date", day)
            frame["source_file"] = source_file
            sql_columns = ["date"] + columns + ["source_file"]
            marks = ",".join("?" for _ in sql_columns)
            records = frame[sql_columns].astype(object).where(pd.notna(frame[sql_columns]), None).values.tolist()
            con.executemany(
                f'INSERT OR REPLACE INTO "{table}" ({", ".join(sql_columns)}) VALUES ({marks})', records)
        con.commit()
    except Exception:
        con.rollback()
        raise


def _load(table, start=None, end=None, db_path=DEFAULT_DB, symbol=None):
    if str(db_path) != ":memory:" and not Path(db_path).expanduser().is_file():
        raise FileNotFoundError(
            f"BVMAC database not found at {Path(db_path).expanduser()}. "
            "Build it once with bvmac.download_data(start='YYYY-MM-DD'), "
            "or run bvmac-update with a start date."
        )
    con = connect(db_path)
    conditions, values = [], []
    if start:
        conditions.append("date >= ?")
        values.append(pd.Timestamp(start).date().isoformat())
    if end:
        conditions.append("date <= ?")
        values.append(pd.Timestamp(end).date().isoformat())
    if symbol:
        conditions.append("(mnemo = ? OR isin = ?)")
        values.extend([symbol.upper(), symbol.upper()])
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    tie_breakers = ", ".join(f'"{key}"' for key in KEYS[table][1:])
    ordering = f' ORDER BY date, {tie_breakers}' if tie_breakers else ' ORDER BY date'
    try:
        df = pd.read_sql_query(f'SELECT * FROM "{table}"{where}{ordering}', con, params=values)
    finally:
        con.close()
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_equities(symbol=None, start=None, end=None, db_path=DEFAULT_DB):
    """Load daily BVMAC share market observations; filter by Mnemo or ISIN."""
    return _load("equities", start, end, db_path, symbol)


def load_prices(symbol, start=None, end=None, db_path=DEFAULT_DB):
    """Return a price history; BVMAC daily bulletins do not publish daily high/low."""
    df = load_equities(symbol, start, end, db_path)
    if df.empty:
        result = pd.DataFrame(columns=["Open", "Close", "Volume", "Value", "Change %", "Year High", "Year Low"])
        result.index.name = "Date"
        return result
    result = df.set_index("date")[["open", "close", "volume", "value_fcfa", "change_pct", "year_high", "year_low"]]
    result.columns = ["Open", "Close", "Volume", "Value", "Change %", "Year High", "Year Low"]
    result.index.name = "Date"
    return result


def load_index(start=None, end=None, db_path=DEFAULT_DB):
    return _load("index", start, end, db_path)


def load_bonds(symbol=None, start=None, end=None, db_path=DEFAULT_DB):
    """Load daily bond quotes. The symbol can be the bond Mnemo or ISIN."""
    return _load("bond_quotes", start, end, db_path, symbol)


def load_bond_issues(symbol=None, start=None, end=None, db_path=DEFAULT_DB):
    """Load issue terms such as coupon, maturity, and outstanding amount."""
    return _load("bond_issues", start, end, db_path, symbol)


def load_funds(name=None, start=None, end=None, db_path=DEFAULT_DB):
    df = _load("funds", start, end, db_path)
    if name and not df.empty:
        df = df[df["fund_name"].str.contains(name, case=False, na=False)]
    return df


def load_issuer_snapshots(symbol=None, start=None, end=None, db_path=DEFAULT_DB):
    return _load("issuer_snapshots", start, end, db_path, symbol)

