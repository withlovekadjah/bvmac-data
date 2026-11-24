# Validation and bulletin fixtures

The automated regression suite contains two kinds of checks:

- parser, database, and download behavior tests that use generated or mocked
  data and run from a clean clone;
- layout regression checks against five real BVMAC bulletins from 2020, 2021,
  2023, 2025, and 2026.

The real bulletin PDFs are not included here. BVMAC's published website terms
permit downloading documents for personal, noncommercial use and restrict
reproduction or redistribution without permission. See the [BVMAC legal
terms](https://www.bvm-ac.org/mentions-legales-de-la-bvmac/). Do not add these
PDFs to a public repository unless you have permission to redistribute them.

When the five expected PDFs are absent, the real-bulletin checks are reported
as skipped. This is expected on GitHub. Users who already have lawful copies
can place those five files in `tests/fixtures/` locally to run the full
regression suite. Run all available tests from the project root with:

```bash
python -m unittest discover -v
```

Earlier local validation against the five PDFs recorded these extracted row
counts. They describe parser output from those specific files, not completeness
of the full historical archive:

| Bulletin date | Shares | Bond quotes | Issue terms | Fund NAVs | Issuer snapshots |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2020-06-22 | 4 | 12 | — | — | — |
| 2021-01-08 | 4 | 10 | — | — | — |
| 2023-11-15 | 6 | 11 | 9 | 29 | 6 |
| 2025-11-18 | 6 | 29 | 29 | 40 | 6 |
| 2026-11-18 | 7 | 33 | 33 | 53 | 7 |

Counts are not a claim that every table in every bulletin layout is fully
supported. Extraction gaps and malformed printed identifiers are reported by
the package and should be reviewed before relying on results.

