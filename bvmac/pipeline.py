"""Ingest local or newly downloaded BVMAC bulletin PDFs into SQLite."""
import re
import warnings
from datetime import date, timedelta
from pathlib import Path

import pdfplumber

from . import database, download, extract
from .config import DEFAULT_DB, DEFAULT_FOLDER


def process_folder(folder=DEFAULT_FOLDER, db_path=DEFAULT_DB, force=False):
    paths = sorted(Path(folder).glob("*.pdf"))
    print(f"{len(paths)} PDF(s) found in {folder}")
    con = database.connect(db_path)
    summary = {"processed": 0, "already_in_database": 0, "failed": 0}
    for path in paths:
        if not force and any(
            con.execute(f'SELECT 1 FROM "{table}" WHERE source_file = ? LIMIT 1', (path.name,)).fetchone()
            for table in database.DATASETS
        ):
            summary["already_in_database"] += 1
            print(f"ALREADY IN DATABASE {path.name}")
            continue
        match = re.search(r"(\d{4})(\d{2})(\d{2})", path.stem)
        fallback = "-".join(match.groups()) if match else None
        if fallback is None:
            legacy = re.search(r"(\d{2})-(\d{2})-(\d{4})", path.stem)
            if legacy:
                day_part, month_part, year_part = legacy.groups()
                fallback = f"{year_part}-{month_part}-{day_part}"
        try:
            with pdfplumber.open(path) as pdf:
                day = extract.bulletin_date(pdf, path.name)
                bulletin_text = "\n".join(extract._page_text(page) for page in pdf.pages)
                extraction_warnings = []
                datasets = extract.extract_bulletin(pdf, errors=extraction_warnings)
            for warning in extraction_warnings:
                print(f"WARNING {path.name}: extractor {warning}")
            bulletin_compact = extract._compact_text(bulletin_text)
            if fallback and fallback != day:
                print(f"WARNING {path.name}: filename date {fallback} differs from bulletin date {day}; using bulletin date")
            if len(datasets["equities"]) < 3:
                print(f"WARNING {path.name}: only {len(datasets['equities'])} equity rows")
            if not any(not frame.empty for frame in datasets.values()):
                print(f"WARNING {path.name}: no usable dataset rows; skipped")
                continue
            for dataset_name, frame in datasets.items():
                if "isin" not in frame:
                    continue
                invalid = sorted({value for value in frame["isin"].dropna()
                                  if not extract.isin_checksum_valid(value)})
                if invalid:
                    print(f"WARNING {path.name}: {dataset_name} contains {len(invalid)} ISIN(s) with invalid checksum: "
                          + ", ".join(invalid[:10]))
            if not force:
                found = con.execute("SELECT COUNT(*) FROM equities WHERE date = ?", (day,)).fetchone()[0]
                if found:
                    continue
            database.save_bulletin(con, datasets, day, path.name)
            summary["processed"] += 1
            counts = ", ".join(f"{len(frame)} {key}" for key, frame in datasets.items())
            print(f"OK {path.name} -> {day}: {counts}")
            if len(datasets["bond_quotes"]) == 0:
                print(f"WARNING {path.name}: no bond quote rows extracted; check source table layout")
            for asset_class, labels in {
                    "sovereign": ("OBLIGATIONSDESETATS", "OBLIGATIONSETATS", "OBLIGATIONDETATS"),
                    "regional": ("OBLIGATIONSREGIONALES",),
                    "corporate": ("OBLIGATIONSPRIVEES",),
            }.items():
                if any(label in bulletin_compact for label in labels) and not (datasets["bond_quotes"]["asset_class"] == asset_class).any():
                    print(f"WARNING {path.name}: {asset_class} bond quote table was not extracted")
            if "BVMAC-AS" in bulletin_text and datasets["index"].empty:
                print(f"WARNING {path.name}: BVMAC-AS appears chart-only and was not extracted")
            if "CAPITALISATIONBOURSIERE" in bulletin_compact and datasets["issuer_snapshots"].empty:
                print(f"WARNING {path.name}: issuer capitalization table was not extracted")
            listed = re.search(r"(\d+)\s+LIGNES?\s+OBLIGATAIRES", bulletin_text)
            if listed and len(datasets["bond_issues"]) < int(listed.group(1)):
                print(f"WARNING {path.name}: bulletin lists {listed.group(1)} bond lines, "
                      f"but {len(datasets['bond_issues'])} issue rows were extracted")
        except Exception as exc:
            summary["failed"] += 1
            con.rollback()
            print(f"ERROR {path.name}: {exc}")
    for table in database.DATASETS:
        n = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        print(f"Database holds {n} {table} rows")
    con.close()
    return summary


def update(start=None, end=None, folder=DEFAULT_FOLDER, db_path=DEFAULT_DB, force=False):
    if start is None:
        if not Path(db_path).expanduser().is_file():
            raise ValueError("Database is empty. Supply --start YYYY-MM-DD for the initial history.")
        con = database.connect(db_path)
        last = con.execute("SELECT MAX(date) FROM equities").fetchone()[0]
        con.close()
        if last is None:
            raise ValueError("Database is empty. Supply --start YYYY-MM-DD for the initial history.")
        start = date.fromisoformat(last) + timedelta(days=1)
    end = end or date.today()
    start_day, end_day = download.to_date(start), download.to_date(end)
    if start_day > end_day:
        raise ValueError("start must be on or before end")
    downloads = download.download_range(start_day, end_day, folder, force=force)
    processed = process_folder(folder, db_path, force)
    if downloads["errors"]:
        warnings.warn(f"{len(downloads['errors'])} bulletin download(s) failed; the requested history may be incomplete")
    if processed["failed"]:
        warnings.warn(f"{processed['failed']} bulletin file(s) could not be processed; returned data may be incomplete")
    return {"downloads": downloads, "processing": processed}

