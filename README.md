# BVMAC Data

An independent Python package for reading market data from the BVMAC's daily
*Bulletin Officiel de la Cote*. It does not depend on the BRVM package.

The package downloads bulletin PDFs, stores extracted observations in a local
SQLite file, and returns pandas DataFrames. The archive has two observed
filename patterns: older bulletins use `BOC-BVMAC-DD-MM-YYYY.pdf`; later files
use `BOC-YYYYMMDD.pdf`. The downloader tries the appropriate pattern and falls
back to the other one.

## Install

After release to PyPI, install with one command:

```bash
pip install bvmac-data
```

The package is not published on PyPI yet. To install from a downloaded or
cloned source folder, open a terminal in its root and run
`python -m pip install .`. Python 3.10 or newer is required. A GitHub release
will provide a reviewed source download; PyPI installation will work only
after a separate PyPI release.

## License and reuse

No software license has been selected for this project. Until one is added,
the code remains under its default copyright and this repository does not
grant general permission to reuse, modify, or redistribute it. Please contact
the author for permission. Do not assume that public visibility means the
code is open source.

## Read data already stored on your computer

```python
import bvmac

prices = bvmac.load_prices("SOCAP")
shares = bvmac.load_equities("SOCAP")
index = bvmac.load_index()
bonds = bvmac.load_bonds()
bond_terms = bvmac.load_bond_issues()
funds = bvmac.load_funds()
issuer_facts = bvmac.load_issuer_snapshots()
```

These functions read directly from the package's local SQLite database. They
do not download bulletins or reprocess PDFs. The package finds its standard
database automatically, so you do not need to enter its file path. If the
database is missing, the loader reports that clearly instead of creating an
empty one. Each function also accepts optional `start` and `end` dates.

## Fill or refresh the local database

Downloading and processing bulletins is a separate step. Run it when you want
to build the local database or add newer dates:

```python
import bvmac

bvmac.download_data(start="2025-01-01")
```

This downloads available PDFs, extracts their supported sections, and saves
the results in the local database. It can take time for a large date range.
After it finishes, use the `load_*()` functions above to read the saved data
without downloading again. You can also use `history()` as a convenience when
you specifically want it to check for newer bulletins and then return one
share's prices:

```python
prices = bvmac.history("SOCAP", start="2025-01-01")
```

Use an exchange Mnemo (ticker) or ISIN to identify an instrument.

The package keeps its files outside your current project folder:

```text
Windows: %LOCALAPPDATA%\bvmac-data\
Other systems: ~/bvmac-data/
```

Inside that folder, downloaded PDFs go in `bulletins/` and the database is
`bvmac.db`. You normally do not need to find or manage those files yourself.

## Read one bulletin PDF directly

```python
import bvmac

data = bvmac.read_bulletin(r"C:\\Users\\you\\Downloads\\BOC-20261118.pdf")
shares = data["equities"]
bonds = data["bond_quotes"]
funds = data["funds"]
```

`read_bulletin()` reads that PDF directly and returns pandas DataFrames. It
does not download anything or use the local database. Advanced users can pass
a custom `db_path` to any database loader; otherwise, the standard local cache
is used automatically. Results are pandas DataFrames, with dates returned as
pandas dates.

## What the columns mean

### Shares

`mnemo` is the exchange's short ticker; `isin` is the security's international
identifier. `isin_valid` reports whether the printed ISIN passes its checksum;
invalid printed identifiers are retained with a warning instead of being
silently treated as valid. `open` and `close` are the session's opening and closing prices in
CFA francs. `volume` is the number of shares traded, `value_fcfa` is the total
value traded, and `transactions` is the number of trades. `bid_volume` and
`ask_volume` are the number of shares requested to buy and offered to sell.
`change_pct` is the bulletin's daily percentage change. `year_high` and
`year_low` are the bulletin's high and low prices since January, not the day's
high and low. The daily bulletin does not provide daily high/low prices.

`load_prices()` returns Open, Close, Volume, Value, Change %, Year High, and
Year Low. It does not invent missing daily High and Low values.

### BVMAC-AS index

`load_index()` returns the value and daily percentage change when these can be
read from the bulletin. Some editions show the value only inside a chart, so an
index observation may be unavailable for those dates.

### Bonds

`load_bonds()` returns quote observations, including the previous close, open
and close prices as a percentage of face value, accrued coupon, order-book
volumes, trades, and price limits. `asset_class` identifies sovereign,
regional, or corporate bonds. The bulletin also has a separate issue table;
the initial extractor stores coupon rate, issue size, maturity, repayment
method, coupon dates, outstanding amount, yield, and turnover in a separate
dataset available through `load_bond_issues()`. `source_page` indicates where
the information came from.

Older bulletin layouts may not expose every bond row as readable table text.
The pipeline reports extraction gaps; a missing row should not be interpreted
as proof that no bond exists or traded.

### Funds

`load_funds()` returns previous and current net asset values (NAVs), their
dates, category, update frequency, and the bulletin's return figures. Funds
can be daily, weekly, monthly, or quarterly; the NAV's own date is retained so
users do not mistake a weekly update for a new daily price.

The `frequency` field is part of a fund observation's database key so daily,
weekly, monthly, and quarterly NAVs remain separate. When an older database is
opened after this change, the package makes a `.pre-migration-*.bak` copy before
updating its schema.

### Issuer snapshots

`load_issuer_snapshots()` returns the market capitalization table: last price,
listed float and total shares, last dividend, three-month liquidity, earnings
per share, price/earnings ratio, and float/total market capitalization.
Company profiles and long-form annual financial statements are included in
some bulletins but are not part of the initial daily-data release.

## Data limits

- The official bulletin is the source; this package is an independent PDF
  extractor, not a BVMAC API.
- Not every weekday has a published bulletin. No-trade and missing-data values
  are kept distinct where the bulletin allows it.
- An empty extraction warning means a table layout needs review; it does not
  mean the market had no instruments.
- Historical coverage depends on the availability and extractability of the
  source PDFs. Always check the pipeline summary before relying on a date range.
- This is historical market data, not a live quote feed or investment advice.

## Development

The source project is standalone: package import name `bvmac`, distribution
name `bvmac-data`, command `bvmac-update`.

The test suite includes regression checks against real BVMAC bulletins. Those
PDFs are not included in this public repository because BVMAC's published
website terms restrict redistribution of its documents. The PDF-specific
checks skip when the fixtures are absent; see `VALIDATION.md` for details.

