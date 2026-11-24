"""Python data access for daily BVMAC market bulletins."""
from pathlib import Path

from .database import (
    load_bond_issues, load_bonds, load_equities, load_funds, load_index,
    load_issuer_snapshots, load_prices,
)
from . import extract as _extract
from .config import DEFAULT_DB, DEFAULT_FOLDER


def update(start=None, end=None, folder=DEFAULT_FOLDER, db_path=DEFAULT_DB, force=False):
    """Download and process local bulletins for a date range."""
    from .pipeline import update as _update
    return _update(start=start, end=end, folder=folder, db_path=db_path, force=force)


def history(symbol, start, end=None, *, db_path=DEFAULT_DB, folder=DEFAULT_FOLDER):
    """Fetch/process the requested period if needed, then return share prices.

    Example: ``bvmac.history("SOCAP", start="2026-01-01")``.
    On first use, the package downloads available official bulletins into its
    private local cache and creates its SQLite database automatically.
    """
    update(start=start, end=end, folder=folder, db_path=db_path)
    return load_prices(symbol, start=start, end=end, db_path=db_path)


def read_bulletin(pdf_path):
    """Read one bulletin PDF directly and return its datasets as DataFrames.

    This does not download files or create a database. For example::

        bulletin = bvmac.read_bulletin(r"C:\\data\\BOC-20261118.pdf")
        shares = bulletin["equities"]
    """
    path = Path(pdf_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(
            f"Bulletin PDF not found at {path}. Check the file path or download the bulletin first."
        )
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        result = _extract.extract_bulletin(pdf)
        result["date"] = _extract.bulletin_date(pdf, path.name)
    return result


def download_data(start=None, end=None, *, db_path=DEFAULT_DB, folder=DEFAULT_FOLDER):
    """Download available bulletins for a date range and build/update the cache.

    Supply ``start`` for the first historical download. Later calls can omit
    it to continue from the newest date already in the local database.
    Returns the path to the local SQLite database.
    """
    update(start=start, end=end, db_path=db_path, folder=folder)
    return Path(db_path)

__all__ = [
    "load_bond_issues", "load_bonds", "load_equities", "load_funds", "load_index",
    "load_issuer_snapshots", "load_prices",
    "download_data", "history", "read_bulletin", "update",
]
__version__ = "0.1.0"

