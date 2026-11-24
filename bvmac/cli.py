import argparse

from .config import DEFAULT_DB, DEFAULT_FOLDER
from .pipeline import process_folder, update


def main():
    parser = argparse.ArgumentParser(description="Download and process BVMAC daily bulletins")
    parser.add_argument("--start", help="first bulletin date YYYY-MM-DD (initial history)")
    parser.add_argument("--end", help="last bulletin date YYYY-MM-DD; defaults to today")
    parser.add_argument("--folder", default=str(DEFAULT_FOLDER), help="where bulletin PDFs are stored")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--no-download", action="store_true", help="process only PDFs already in --folder")
    parser.add_argument("--force", action="store_true", help="reprocess dates already in the database")
    args = parser.parse_args()
    if args.no_download:
        if args.start or args.end:
            parser.error("--start and --end cannot be used with --no-download")
        summary = process_folder(args.folder, args.db, args.force)
        return 1 if summary["failed"] else 0
    else:
        summary = update(args.start, args.end, args.folder, args.db, args.force)
        if summary["processing"]["failed"] or summary["downloads"]["errors"]:
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

