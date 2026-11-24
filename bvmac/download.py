"""Download dated BVMAC official bulletins."""
from datetime import date, datetime, timedelta
import os
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import BASE_URL, DEFAULT_FOLDER

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "bvmac-data/0.1 (+https://github.com/)"})
_SESSION.mount("https://", HTTPAdapter(max_retries=Retry(
    total=3, connect=3, read=3, backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))))


def to_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def bulletin_url(day):
    """Return the most likely official URL for a bulletin date."""
    day = to_date(day)
    return bulletin_url_candidates(day)[0]


def bulletin_url_candidates(day):
    """Try the date-specific naming variants used in BVMAC's PDF archive.

    Through early 2023, examples use ``BOC-BVMAC-DD-MM-YYYY.pdf``. Later
    bulletins use ``BOC-YYYYMMDD.pdf``. The second candidate covers the
    transition period and occasional archive exceptions.
    """
    day = to_date(day)
    compact = f"BOC-{day:%Y%m%d}.pdf"
    legacy = f"BOC-BVMAC-{day:%d-%m-%Y}.pdf"
    names = [legacy, compact] if day < date(2023, 6, 1) else [compact, legacy]
    return [f"{BASE_URL}/{day:%Y/%m}/{name}" for name in names]


def bulletin_filenames(day):
    return [Path(urlparse(url).path).name for url in bulletin_url_candidates(day)]


def _looks_like_complete_pdf(path):
    if not path.is_file() or path.stat().st_size < 20:
        return False
    with path.open("rb") as local_pdf:
        if local_pdf.read(5) != b"%PDF-":
            return False
        local_pdf.seek(max(0, path.stat().st_size - 2048))
        return b"%%EOF" in local_pdf.read()


def download_day(day, folder=DEFAULT_FOLDER, timeout=30, force=False):
    """Download one bulletin. Return its path, or None when no file is published."""
    day = to_date(day)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for filename in bulletin_filenames(day):
        path = folder / filename
        if not force and _looks_like_complete_pdf(path):
            return path
    errors = []
    for url in bulletin_url_candidates(day):
        try:
            response = _SESSION.get(url, timeout=timeout)
            if response.status_code == 404:
                continue
            if not 200 <= response.status_code < 300:
                errors.append(f"{url}: HTTP {response.status_code}")
                continue
            if not response.content.startswith(b"%PDF"):
                errors.append(f"{url}: response was not a PDF")
                continue
            path = folder / Path(urlparse(url).path).name
            temporary = path.with_suffix(path.suffix + ".part")
            try:
                temporary.write_bytes(response.content)
                os.replace(temporary, path)
            finally:
                if temporary.exists():
                    temporary.unlink()
            return path
        except requests.RequestException as exc:
            errors.append(f"{url}: {exc}")
            continue
    if errors:
        raise RuntimeError("No bulletin URL succeeded: " + "; ".join(errors))
    return None


def download_range(start, end, folder=DEFAULT_FOLDER, force=False, verbose=True):
    """Try each weekday in an inclusive range, skipping unpublished bulletins."""
    start, end = to_date(start), to_date(end)
    if end < start:
        raise ValueError("end must be on or after start")
    result = {"saved": 0, "already": 0, "missing": 0, "errors": []}
    day = start
    while day <= end:
        legacy_schedule = day.year < 2023 and day.weekday() in {1, 3}
        if day.weekday() < 5 and not legacy_schedule:
            existed = any(
                _looks_like_complete_pdf(Path(folder) / name)
                for name in bulletin_filenames(day)
            )
            try:
                found = download_day(day, folder, force=force)
                if found is None:
                    result["missing"] += 1
                    if verbose:
                        print(f"NO FILE {day:%Y-%m-%d}")
                elif existed and not force:
                    result["already"] += 1
                    if verbose:
                        print(f"ALREADY IN FOLDER {found.name}")
                else:
                    result["saved"] += 1
                    if verbose:
                        print(f"DOWNLOADED {found.name}")
            except Exception as exc:
                result["errors"].append((day.isoformat(), str(exc)))
                if verbose:
                    print(f"ERROR {day:%Y-%m-%d}: {exc}")
        day += timedelta(days=1)
    summary = {key: value for key, value in result.items() if key != "errors"}
    summary["errors"] = len(result["errors"])
    print("Download finished: " + ", ".join(f"{v} {k}" for k, v in summary.items()))
    return result

