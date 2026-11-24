"""Extract BVMAC tables from official daily bulletin PDFs.

Extraction targets the table structures observed in the 18 Nov 2025 and
18 Nov 2026 bulletins. Raw text is retained alongside parsed values where
practical; unsupported/poorly extracted tables are reported by the pipeline.
"""
import re
import statistics
import unicodedata
from datetime import datetime

import pandas as pd


EQUITY_COLUMNS = [
    "issuer", "isin", "mnemo", "short_name", "previous_close",
    "previous_date", "bid_volume", "ask_volume", "volume", "value_fcfa",
    "transactions", "status", "open", "close", "limit_high", "limit_low",
    "change_pct", "reference_price", "year_high", "year_low", "ytd_pct", "isin_valid",
]
QUOTE_COLUMNS = [
    "issuer", "title", "isin", "mnemo", "previous_date", "previous_close_pct",
    "previous_close_fcfa", "nominal_fcfa", "accrued_coupon_fcfa", "bid_volume",
    "ask_volume", "volume", "value_fcfa", "transactions", "status", "open_pct",
    "close_pct", "limit_high_pct", "limit_low_pct", "change_pct",
    "reference_price_fcfa", "asset_class", "source_page", "isin_valid",
]
BOND_COLUMNS = [
    "issuer", "title", "isin", "mnemo", "coupon_pct", "first_listing_date",
    "amount_issued_fcfa", "listed_units", "face_value_fcfa", "price_pct",
    "maturity_years", "repayment_type", "coupon_frequency", "previous_coupon_date",
    "next_coupon_date", "outstanding_fcfa", "yield_pct", "turnover_pct",
    "asset_class", "source_page", "isin_valid",
]
FUND_COLUMNS = [
    "management_company", "custodian", "fund_name", "category", "frequency",
    "nav_origin", "nav_previous", "nav_previous_date", "nav_current",
    "nav_current_date", "inception_date", "return_since_inception_pct",
    "change_previous_pct", "source_page",
]
ISSUER_COLUMNS = [
    "issuer", "isin", "mnemo", "short_name", "close", "listed_float_units",
    "total_units", "last_dividend", "dividend_year", "dividend_date",
    "liquidity_3m_pct", "earnings_per_share", "pe_ratio",
    "market_cap_float_fcfa", "market_cap_total_fcfa", "source_page", "isin_valid",
]
LEGACY_SHARE_ISINS = {
    "SEMC": "CM0000010009", "SAFACAM": "CM0000010017",
    "SOCAPALM": "CM0000010025", "SIAT GABON": "GA0000010033",
}

MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
    "decembre": 12,
}


def clean_text(value):
    if value is None:
        return None
    value = " ".join(str(value).replace("\xa0", " ").split())
    return value or None


def _page_tables(page):
    """Extract a page's tables once; the bulletin contains many pages/tables."""
    if not hasattr(page, "_bvmac_tables"):
        page._bvmac_tables = page.extract_tables()
    return page._bvmac_tables


def _page_text(page):
    if not hasattr(page, "_bvmac_text"):
        page._bvmac_text = page.extract_text() or ""
    return page._bvmac_text


def number(value):
    """Parse French/English numbers. Missing bulletin markers become None."""
    if value is None:
        return None
    text = str(value).replace("\xa0", " ").replace("−", "-").replace("–", "-")
    text = text.replace(" ", "").strip().replace("%", "")
    if not text or text.upper() in {"NC", "ND", "-", "—", "SP"}:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        if text.count(",") > 1:
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    if text.endswith("-"):
        text = "-" + text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _date(value):
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(r"\s+", "", text)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y",
                "%d/%m/%y", "%d-%m-%y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _isin(value, issuer=None):
    """Read a printed ISIN; return it unchanged even when its check digit is bad."""
    text = re.sub(r"\s+", "", (clean_text(value) or "").upper())
    matches = re.findall(r"(?=[A-Z]{2}[A-Z0-9]{9}\d)[A-Z]{2}[A-Z0-9]{9}\d", text)
    valid = next((candidate for candidate in matches if isin_checksum_valid(candidate)), None)
    return valid or (matches[0] if matches else None)


def isin_checksum_valid(value):
    """Validate the ISO 6166/Luhn checksum of a printed ISIN."""
    isin = re.sub(r"\s+", "", str(value or "").upper())
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", isin):
        return False
    expanded = "".join(str(int(char, 36)) if char.isalpha() else char for char in isin)
    total = 0
    double = False
    for char in reversed(expanded):
        digit = int(char) * (2 if double else 1)
        total += digit // 10 + digit % 10
        double = not double
    return total % 10 == 0


def _has_isin_shape(value):
    return bool(value and re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", value))


def bulletin_date(pdf, filename=None):
    for page in pdf.pages[:3]:
        text = _page_text(page)
        numeric = re.search(r"\bDU\s+(\d{1,2})/(\d{1,2})/(\d{4})", text, re.I)
        if numeric:
            day, month, year = numeric.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        match = re.search(r"(?:DU|du)\s+(\d{1,2})\s+([A-Za-zéûô]+)\s+(\d{4})", text, re.I)
        if match:
            month = MONTHS.get(match.group(2).lower())
            if month:
                return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(1)):02d}"
        match = re.search(r"BOC[-_ ](\d{4})(\d{2})(\d{2})", text, re.I)
        if match:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    if filename:
        match = re.search(r"(\d{4})(\d{2})(\d{2})", str(filename))
        if match:
            return _date(f"{match.group(1)}-{match.group(2)}-{match.group(3)}")
        match = re.search(r"(\d{2})-(\d{2})-(\d{4})", str(filename))
        if match:
            return _date(f"{match.group(1)}/{match.group(2)}/{match.group(3)}")
    raise ValueError("Could not determine bulletin date from its pages or filename")


def _table_rows(pdf, page_number, min_columns):
    page = pdf.pages[page_number]
    for table in _page_tables(page):
        for row in table:
            cells = [clean_text(cell) for cell in row]
            if len(cells) >= min_columns:
                yield cells


def extract_equities(pdf):
    rows = []
    for cells in _table_rows(pdf, 1, 21):
        isin = _isin(cells[1], cells[0])
        if _has_isin_shape(isin):
            cells = (cells + [None] * 21)[:21]
            row = dict(zip(EQUITY_COLUMNS, cells))
            row["isin"] = isin
            row["isin_valid"] = isin_checksum_valid(isin)
            for key in ("previous_close", "bid_volume", "ask_volume", "volume", "value_fcfa",
                        "transactions", "open", "close", "limit_high", "limit_low",
                        "change_pct", "reference_price", "year_high", "year_low", "ytd_pct"):
                row[key] = number(row[key])
            row["previous_date"] = _date(row["previous_date"])
            row["transactions"] = int(row["transactions"]) if row["transactions"] is not None else None
            rows.append(row)
    if rows:
        return pd.DataFrame(rows, columns=EQUITY_COLUMNS)

    # 2023 bulletins print the share board as aligned text rather than a PDF
    # table. Read values from the stable column positions on the landscape page.
    page = pdf.pages[1]
    words = sorted(page.extract_words(), key=lambda w: (w["top"], w["x0"]))
    lines = []
    for word in words:
        if not lines or abs(word["top"] - lines[-1][0]["top"]) > 4.0:
            lines.append([word])
        else:
            lines[-1].append(word)

    def cell(line, left, right):
        return clean_text(" ".join(w["text"] for w in line if left <= w["x0"] < right))

    for line in lines:
        isin = _isin(cell(line, 120, 168))
        if not _has_isin_shape(isin):
            continue
        row_words = [word for word in words if abs(word["top"] - line[0]["top"]) <= 8]
        name = cell(row_words, 191, 242)
        row = {
            "issuer": name, "isin": isin,
            "isin_valid": isin_checksum_valid(isin),
            "mnemo": re.sub(r"\s+", "", cell(row_words, 166, 190) or ""),
            "short_name": name, "previous_close": number(cell(row_words, 235, 269)),
            "previous_date": _date(cell(row_words, 268, 315)),
            "bid_volume": number(cell(row_words, 315, 337)), "ask_volume": number(cell(row_words, 337, 370)),
            "volume": number(cell(row_words, 370, 386)), "value_fcfa": number(cell(row_words, 386, 429)),
            "transactions": number(cell(row_words, 429, 442)), "status": cell(row_words, 442, 450),
            "open": number(cell(row_words, 450, 490)), "close": number(cell(row_words, 490, 540)),
            "limit_high": number(cell(row_words, 546, 584)), "limit_low": number(cell(row_words, 584, 644)),
            "change_pct": number(cell(row_words, 644, 670)),
            "reference_price": number(cell(row_words, 670, 710)),
            "year_high": number(cell(row_words, 710, 737)), "year_low": number(cell(row_words, 737, 788)),
            "ytd_pct": number(cell(row_words, 788, 842)),
        }
        rows.append(row)
    if rows:
        return pd.DataFrame(rows, columns=EQUITY_COLUMNS)

    # 2020–2021 bulletins use a legacy fixing table and omit ISINs. Preserve
    # the quoted observations and attach known ISINs from BVMAC's identifiers.
    for table in _page_tables(pdf.pages[1]):
        for raw in table:
            cells = [clean_text(cell) for cell in raw]
            if not cells or not cells[0] or not re.fullmatch(r"10\d{2}", cells[0]):
                continue
            if len(cells) >= 36:  # 2020 table cells are split across columns.
                name, reference, close = cells[11], cells[14], cells[17]
                bid, ask, volume, change, status = cells[20], cells[23], cells[27], cells[30], cells[35]
            elif len(cells) >= 15:  # 2021 fixing table.
                name, reference, close = cells[7], cells[8], cells[9]
                bid, ask, volume, change, status = cells[10], cells[11], cells[12], cells[13], cells[14]
            else:
                continue
            key = (name or "").upper()
            mnemo = {"SAFACAM": "SAF", "SOCAPALM": "SOCAP", "SIAT GABON": "SIAT"}.get(key, key)
            rows.append({
                "issuer": name, "isin": LEGACY_SHARE_ISINS.get(key), "mnemo": mnemo,
                "isin_valid": isin_checksum_valid(LEGACY_SHARE_ISINS.get(key)) if LEGACY_SHARE_ISINS.get(key) else None,
                "short_name": name, "previous_close": number(reference), "previous_date": None,
                "bid_volume": number(bid), "ask_volume": number(ask), "volume": number(volume),
                "value_fcfa": None, "transactions": None, "status": status,
                "open": None, "close": number(close), "limit_high": None, "limit_low": None,
                "change_pct": number(change), "reference_price": number(reference),
                "year_high": None, "year_low": None, "ytd_pct": None,
            })
    return pd.DataFrame(rows, columns=EQUITY_COLUMNS)


def _page_class(text):
    upper = _compact_text(text)
    if "OBLIGATIONSDESETATS" in upper or "OBLIGATIONSETATS" in upper or "OBLIGATIONDETATS" in upper:
        return "sovereign"
    if "OBLIGATIONSREGIONALES" in upper:
        return "regional"
    if "OBLIGATIONSPRIVEES" in upper:
        return "corporate"
    return None


def _section_at(page, y):
    section = None
    for line in _positioned_lines(page):
        if line[0]["top"] > y:
            break
        label = _compact_text(" ".join(word["text"] for word in line))
        if "OBLIGATIONSPRIVEES" in label:
            section = "corporate"
        elif "OBLIGATIONSREGIONALES" in label:
            section = "regional"
        elif any(term in label for term in ("OBLIGATIONSDESETATS", "OBLIGATIONSETATS", "OBLIGATIONDETATS")):
            section = "sovereign"
    return section


def _compact_text(text):
    folded = unicodedata.normalize("NFKD", (text or "").upper())
    return re.sub(r"[^A-Z0-9]", "", "".join(c for c in folded if not unicodedata.combining(c)))


def _grid_rows(page):
    """Read positioned text by the bulletin's own vertical cell rules.

    pdfplumber's table finder misses some BOC editions even though the PDF
    contains the vertical rules. These rules provide stable cell boundaries;
    unlike character-gap splitting, spaces inside values such as grouped FCFA
    amounts remain inside their original cell.
    """
    if hasattr(page, "_bvmac_grid_rows"):
        return page._bvmac_grid_rows
    chars = sorted(page.chars, key=lambda char: (char["top"], char["x0"]))
    lines = []
    for char in chars:
        if not lines or abs(char["top"] - lines[-1][0]["top"]) > 2.5:
            lines.append([char])
        else:
            lines[-1].append(char)

    edges = [edge for edge in page.edges if edge.get("orientation") == "v" and edge["height"] > 8]
    output = []
    section = _page_class(_page_text(page))
    for line in lines:
        y = statistics.median(char["top"] for char in line)
        normalized_line = _compact_text("".join(char["text"] for char in line))
        if "OBLIGATIONSPRIVEES" in normalized_line:
            section = "corporate"
        elif "OBLIGATIONSREGIONALES" in normalized_line:
            section = "regional"
        elif "OBLIGATIONSETATS" in normalized_line or "OBLIGATIONSDESETATS" in normalized_line:
            section = "sovereign"

        x_values = []
        for edge in edges:
            top, bottom = sorted((edge["top"], edge["bottom"]))
            if top - 1 <= y <= bottom + 1:
                x_values.append((edge["x0"] + edge["x1"]) / 2)
        boundaries = []
        for x in sorted(x_values):
            if not boundaries or x - boundaries[-1] > 0.9:
                boundaries.append(x)
            else:
                boundaries[-1] = (boundaries[-1] + x) / 2
        if len(boundaries) < 4:
            continue

        cells = [""] * (len(boundaries) - 1)
        for char in line:
            center = (char["x0"] + char["x1"]) / 2
            for index, (left, right) in enumerate(zip(boundaries, boundaries[1:])):
                if left - 0.8 <= center < right + 0.8:
                    cells[index] += char["text"]
                    break
        cells = [clean_text(value) for value in cells]
        output.append((y, cells, section))
    page._bvmac_grid_rows = output
    return output


def _positioned_lines(page):
    """Group individually positioned PDF glyphs into visual rows."""
    words = sorted(page.extract_words(), key=lambda word: (word["top"], word["x0"]))
    lines = []
    for word in words:
        if not lines or abs(word["top"] - lines[-1][0]["top"]) > 2.5:
            lines.append([word])
        else:
            lines[-1].append(word)
    return lines


def _line_cell(line, left, right):
    return clean_text(" ".join(
        word["text"] for word in line if left <= word["x0"] < right
    ))


def _line_isin(line):
    # In these PDFs even the letters and digits of the ISIN are separate glyphs.
    glyphs = [(character, word["x0"]) for word in line for character in word["text"]]
    match = re.search(r"[A-Z]{2}[A-Z0-9]{9}\d", "".join(char for char, _ in glyphs))
    return (match.group(0), glyphs[match.start()][1]) if match else (None, None)


def _join_glyphs(value):
    """Join PDF text rendered one character at a time, preserving word gaps."""
    tokens = (value or "").split()
    result = []
    singles = []
    def flush_singles():
        if len(singles) >= 3:
            joined = "".join(singles)
            if joined in {"ETATDUCONGO", "ETATDUGABON", "ETATDUCAMEROUN", "ETATDUTCHAD"}:
                joined = joined.replace("ETATDU", "ETAT DU ")
            elif joined == "LAREGIONALE":
                joined = "LA REGIONALE"
            result.append(joined)
        else:
            result.extend(singles)
        singles.clear()

    for token in tokens:
        if len(token) == 1 and token.isalpha():
            singles.append(token)
        else:
            if singles:
                flush_singles()
            result.append(token)
    if singles:
        flush_singles()
    text = clean_text(" ".join(result)) or ""
    text = re.sub(r"\s+([,./%\-])", r"\1", text)
    text = re.sub(r"([,./%\-])\s+", r"\1", text)
    text = re.sub(r"(?<=\d)\s+(?=\d{3}(?:\D|$))", "", text)
    return clean_text(text)


def _coordinate_bond_quotes(page, page_number):
    """Fallback for the 2025 quote pages whose ruled tables aren't extractable."""
    rows = {}
    for line in _positioned_lines(page):
        isin, isin_x = _line_isin(line)
        if not _has_isin_shape(isin):
            continue
        y = line[0]["top"]
        asset_class = _section_at(page, y)
        if asset_class is None:
            row_label = _compact_text(" ".join(word["text"] for word in line))
            if "BDEAC" in row_label:
                asset_class = "regional"
            elif any(name in row_label for name in ("ALIOS", "ACEP", "SNPC", "EOSAF", "GSEZ")):
                asset_class = "corporate"
            elif "ETAT" in row_label:
                asset_class = "sovereign"
        if asset_class is None:
            continue
        if asset_class == "sovereign":
            bands = {
                "issuer": (38, 96), "title": (98, 191), "mnemo": (242, 267),
                "previous_date": (268, 315), "previous_close_pct": (315, 339),
                "previous_close_fcfa": (339, 377.5), "nominal_fcfa": (377.5, 432),
                "accrued_coupon_fcfa": (432, 478), "bid_volume": (478, 510),
                "ask_volume": (510, 537), "volume": (537, 584), "value_fcfa": (584, 606),
                "transactions": (606, 613), "status": (613, 639), "open_pct": (635, 660),
                "close_pct": (660, 685), "limit_high_pct": (685, 713),
                "limit_low_pct": (713, 746), "change_pct": (746, 773),
                "reference_price_fcfa": (773, 842),
            }
        else:
            if asset_class == "regional":
                bands = {
                    "issuer": (38, 74), "title": (72, 163), "mnemo": (210, 237),
                    "previous_date": (237, 283), "previous_close_pct": (283, 320),
                    "previous_close_fcfa": (321, 365.5), "nominal_fcfa": (365.5, 405),
                    "accrued_coupon_fcfa": (405, 450), "bid_volume": (450, 492),
                    "ask_volume": (492, 529), "volume": (529, 586), "value_fcfa": (586, 605),
                    "transactions": (605, 613), "status": (613, 636), "open_pct": (636, 661),
                    "close_pct": (661, 684), "limit_high_pct": (685, 713),
                    "limit_low_pct": (713, 740), "change_pct": (740, 772),
                    "reference_price_fcfa": (772, 842),
                }
            else:
                bands = {
                    "issuer": (38, 123), "title": (120, 222), "mnemo": (274, 303),
                    "previous_date": (303, 347), "previous_close_pct": (347, 373),
                    "previous_close_fcfa": (373, 412.5), "nominal_fcfa": (412.5, 469),
                    "accrued_coupon_fcfa": (469, 509), "bid_volume": (509, 537),
                    "ask_volume": (537, 565), "volume": (565, 594), "value_fcfa": (594, 614),
                    "transactions": (614, 621), "status": (621, 642), "open_pct": (642, 665),
                    "close_pct": (665, 690), "limit_high_pct": (690, 721),
                    "limit_low_pct": (721, 750), "change_pct": (750, 781),
                    "reference_price_fcfa": (782, 842),
                }
        row = {key: _line_cell(line, *band) for key, band in bands.items()}
        row["issuer"] = _join_glyphs(row["issuer"])
        row["title"] = _join_glyphs(row["title"])
        row["mnemo"] = re.sub(r"\s+", "", row["mnemo"] or "") or None
        row["isin"] = isin
        row["isin_valid"] = isin_checksum_valid(isin)
        row["previous_date"] = _date(row["previous_date"])
        for key in bands:
            if key not in {"issuer", "title", "mnemo", "previous_date", "status"}:
                row[key] = number(row[key])
        row["asset_class"] = asset_class
        row["source_page"] = page_number + 1
        rows[isin] = row
    return list(rows.values())


def extract_bond_quotes(pdf, bond_issues=None):
    rows = []
    for page_number, page in enumerate(pdf.pages):
        page_class = _page_class(_page_text(page))
        page_start = len(rows)
        for table in _page_tables(page):
            table_class = _page_class(" ".join(str(c or "") for r in table[:2] for c in r)) or page_class
            asset_class = table_class
            for raw in table:
                cells = [clean_text(cell) for cell in raw]
                label = " ".join(c or "" for c in cells).upper()
                if "OBLIGATIONS PRIVEES" in label or "OBLIGATIONS PRIVÉES" in label:
                    asset_class = "corporate"
                    continue
                if "OBLIGATIONS REGIONALES" in label:
                    asset_class = "regional"
                    continue
                if "OBLIGATIONS DES ETATS" in label or "OBLIGATIONS ETATS" in label:
                    asset_class = "sovereign"
                    continue
                isin = _isin(cells[2], cells[0]) if len(cells) > 2 else None
                if len(cells) < 21 or not _has_isin_shape(isin) or not cells[3]:
                    continue
                cells = (cells + [None] * 21)[:21]
                row = {
                    "issuer": cells[0], "title": cells[1], "isin": isin, "mnemo": cells[3],
                    "previous_date": _date(cells[4]), "previous_close_pct": number(cells[5]),
                    "previous_close_fcfa": number(cells[6]), "nominal_fcfa": number(cells[7]),
                    "accrued_coupon_fcfa": number(cells[8]), "bid_volume": number(cells[9]),
                    "ask_volume": number(cells[10]), "volume": number(cells[11]),
                    "value_fcfa": number(cells[12]), "transactions": number(cells[13]),
                    "status": cells[14], "open_pct": number(cells[15]),
                    "close_pct": number(cells[16]), "limit_high_pct": number(cells[17]),
                    "limit_low_pct": number(cells[18]), "change_pct": number(cells[19]),
                    "reference_price_fcfa": number(cells[20]), "asset_class": asset_class,
                    "source_page": page_number + 1,
                    "isin_valid": isin_checksum_valid(isin),
                }
                rows.append(row)
        if page_number in (2, 3) and len(rows) == page_start:
            rows.extend(_coordinate_bond_quotes(page, page_number))
        # Some recent bulletins draw the quote board with PDF vector rules.
        # pdfplumber does not return a table for those pages, so read the cells
        # using the rules and let these directly printed values take priority.
        page_text_compact = _compact_text(_page_text(page))
        native_isins = {row.get("isin") for row in rows[page_start:]
                        if row.get("isin") and isin_checksum_valid(row["isin"])}
        if "COURS" in page_text_compact or "OBLIGATIONS" in page_text_compact:
            for _, cells, grid_class in _grid_rows(page):
                isin = re.sub(r"\s+", "", cells[2] or "") if len(cells) > 2 else ""
                if len(cells) != 21 or not _has_isin_shape(isin):
                    continue
                if isin in native_isins:
                    continue
                if grid_class is None:
                    issuer_compact = _compact_text(cells[0])
                    grid_class = ("sovereign" if "ETAT" in issuer_compact else
                                  "regional" if "BDEAC" in issuer_compact else
                                  "corporate" if any(name in issuer_compact for name in ("ALIOS", "ACEP", "SNPC", "EOSAF", "GSEZ")) else None)
                rows.append({
                    "issuer": cells[0], "title": cells[1], "isin": isin,
                    "mnemo": cells[3], "previous_date": _date(cells[4]),
                    "previous_close_pct": number(cells[5]),
                    "previous_close_fcfa": number(cells[6]),
                    "nominal_fcfa": number(cells[7]),
                    "accrued_coupon_fcfa": number(cells[8]),
                    "bid_volume": number(cells[9]), "ask_volume": number(cells[10]),
                    "volume": number(cells[11]), "value_fcfa": number(cells[12]),
                    "transactions": number(cells[13]), "status": cells[14],
                    "open_pct": number(cells[15]), "close_pct": number(cells[16]),
                    "limit_high_pct": number(cells[17]), "limit_low_pct": number(cells[18]),
                    "change_pct": number(cells[19]),
                    "reference_price_fcfa": number(cells[20]),
                    "asset_class": grid_class or page_class,
                    "source_page": page_number + 1,
                    "isin_valid": isin_checksum_valid(isin),
                })
    known_issues = {
        row["isin"]: row for row in (bond_issues if bond_issues is not None else extract_bond_issues(pdf)).to_dict("records")
        if row.get("isin")
    }
    # A single ISIN can be seen by the table, coordinate, and grid readers.
    # Keep the last occurrence: grid rows are appended last and preserve the
    # bulletin's printed values without reconstructing them from percentages.
    deduplicated = {}
    for row in rows:
        key = row.get("mnemo") or row.get("isin") or (row.get("title"), row.get("source_page"))
        existing = deduplicated.get(key)
        if existing is None or (not existing.get("isin_valid") and row.get("isin_valid")):
            deduplicated[key] = row
    rows = list(deduplicated.values())
    for row in rows:
        reference = known_issues.get(row["isin"], {})
        if reference.get("issuer"):
            row["issuer"] = reference["issuer"]
        elif row["asset_class"] == "regional":
            row["issuer"] = "BDEAC"
        elif row["asset_class"] == "corporate":
            row["issuer"] = "ALIOS FINANCE"
        row["title"] = _join_glyphs(row["title"])
    if not rows and len(pdf.pages) > 1:
        # Early BOC format: numbered bonds and short quote fields on page 2.
        for table in _page_tables(pdf.pages[1]):
            for raw in table:
                cells = [clean_text(cell) for cell in raw]
                if len(cells) < 15 or not cells[0] or not re.fullmatch(r"20\d{2}", cells[0]) or not cells[1]:
                    continue
                if len(cells) >= 16:  # 2021 table contains an extra empty cell.
                    bid, ask, volume, change, status = cells[11], cells[12], cells[13], cells[14], cells[15]
                else:  # 2020 table.
                    bid, ask, volume, change, status = cells[10], cells[11], cells[12], cells[13], cells[14]
                title = cells[1]
                upper = title.upper()
                asset_class = "regional" if "BDEAC" in upper else (
                    "corporate" if any(x in upper for x in ("ALIOS", "GSEZ", "EOSAF")) else "sovereign")
                nominal, previous_pct, close_pct = number(cells[2]), number(cells[3]), number(cells[4])
                rows.append({
                    "issuer": None, "title": title, "isin": None, "mnemo": title,
                    "previous_date": None, "previous_close_pct": previous_pct,
                    "previous_close_fcfa": None,
                    "nominal_fcfa": nominal, "accrued_coupon_fcfa": number(cells[5]),
                    "bid_volume": number(bid), "ask_volume": number(ask), "volume": number(volume),
                    "value_fcfa": None, "transactions": None, "status": status,
                    "open_pct": None, "close_pct": close_pct, "limit_high_pct": None,
                    "limit_low_pct": None, "change_pct": number(change),
                    "reference_price_fcfa": None,
                    "asset_class": asset_class, "source_page": 2,
                    "isin_valid": None,
                })
    return pd.DataFrame(rows, columns=QUOTE_COLUMNS)


def extract_bond_issues(pdf):
    rows = []
    for page_number, page in enumerate(pdf.pages):
        text = _page_text(page)
        compact_text = _compact_text(text)
        if "OBLIGATIONS" not in compact_text:
            continue
        page_start = len(rows)
        for table in _page_tables(page):
            table_header = " ".join(str(c or "") for r in table[:2] for c in r).upper()
            has_issue_terms = (
                ("TAUX" in table_header and "FACIAL" in table_header)
                or ("MONTANT" in table_header and "LEVE" in table_header)
                or ("ENCOURS" in table_header and "COTATION" in table_header)
            )
            if not has_issue_terms:
                continue
            asset_class = _page_class(table_header) or _page_class(text)
            for raw in table:
                cells = [clean_text(cell) for cell in raw]
                isin = _isin(cells[2], cells[0]) if len(cells) > 2 else None
                if len(cells) < 18 or not _has_isin_shape(isin) or not cells[3]:
                    continue
                cells = (cells + [None] * 18)[:18]
                row = {
                    "issuer": cells[0], "title": cells[1], "isin": isin, "mnemo": cells[3],
                    "coupon_pct": number(cells[4]), "first_listing_date": _date(cells[5]),
                    "amount_issued_fcfa": number(cells[6]), "listed_units": number(cells[7]),
                    "face_value_fcfa": number(cells[8]), "price_pct": number(cells[9]),
                    "maturity_years": number(cells[10]), "repayment_type": cells[11],
                    "coupon_frequency": cells[12], "previous_coupon_date": _date(cells[13]),
                    "next_coupon_date": _date(cells[14]), "outstanding_fcfa": number(cells[15]),
                    "yield_pct": number(cells[16]), "turnover_pct": number(cells[17]),
                    "asset_class": asset_class, "source_page": page_number + 1,
                    "isin_valid": isin_checksum_valid(isin),
                }
                rows.append(row)
        issue_layout = (
            "TAUXFACIAL" in compact_text or "MONTANTLEVE" in compact_text
            or "ENCOURS" in compact_text and "COTATION" in compact_text
        )
        if issue_layout:
            table_isins = {row.get("isin") for row in rows[page_start:]
                           if row.get("isin") and isin_checksum_valid(row["isin"])}
            for _, cells, grid_class in _grid_rows(page):
                isin = re.sub(r"\s+", "", cells[2] or "") if len(cells) > 2 else ""
                if len(cells) != 18 or not _has_isin_shape(isin):
                    continue
                if isin in table_isins:
                    continue
                if grid_class is None:
                    issuer_compact = _compact_text(cells[0])
                    grid_class = ("sovereign" if "ETAT" in issuer_compact else
                                  "regional" if "BDEAC" in issuer_compact else
                                  "corporate" if any(name in issuer_compact for name in ("ALIOS", "ACEP", "SNPC", "EOSAF", "GSEZ")) else None)
                rows.append({
                    "issuer": cells[0], "title": cells[1], "isin": isin,
                    "mnemo": cells[3], "coupon_pct": number(cells[4]),
                    "first_listing_date": _date(cells[5]),
                    "amount_issued_fcfa": number(cells[6]), "listed_units": number(cells[7]),
                    "face_value_fcfa": number(cells[8]), "price_pct": number(cells[9]),
                    "maturity_years": number(cells[10]), "repayment_type": cells[11],
                    "coupon_frequency": cells[12], "previous_coupon_date": _date(cells[13]),
                    "next_coupon_date": _date(cells[14]), "outstanding_fcfa": number(cells[15]),
                    "yield_pct": number(cells[16]), "turnover_pct": number(cells[17]),
                    "asset_class": grid_class or _page_class(text),
                    "source_page": page_number + 1,
                    "isin_valid": isin_checksum_valid(isin),
                })
    # Prefer grid rows over table rows when both readers see the same ISIN.
    by_isin = {}
    no_isin = []
    for row in rows:
        key = row.get("mnemo") or row.get("isin")
        if key:
            existing = by_isin.get(key)
            if existing is None or (not existing.get("isin_valid") and row.get("isin_valid")):
                by_isin[key] = row
        else:
            no_isin.append(row)
    return pd.DataFrame([*by_isin.values(), *no_isin], columns=BOND_COLUMNS)


def extract_funds(pdf):
    rows = []
    for page_number, page in enumerate(pdf.pages):
        frequency = None
        text = _page_text(page)
        if "OPCVM" not in text.upper():
            continue
        for table in _page_tables(page):
            for cells in table:
                cells = [clean_text(cell) for cell in cells]
                section = " ".join(cell or "" for cell in cells).lower()
                nonempty = [cell for cell in cells if cell]
                if len(nonempty) <= 2 and "quotid" in section:
                    frequency = "daily"
                    continue
                if len(nonempty) <= 2 and "hebdom" in section:
                    frequency = "weekly"
                    continue
                if len(nonempty) <= 2 and "mensuel" in section:
                    frequency = "monthly"
                    continue
                if len(nonempty) <= 2 and "trimestr" in section:
                    frequency = "quarterly"
                    continue
                if len(cells) == 12:
                    if not cells[2] or cells[2].upper() == "OPCVM":
                        continue
                    if not (cells[6] and re.fullmatch(r"\d{2}/\d{2}/\d{4}", cells[6])):
                        continue
                    rows.append({
                        "management_company": cells[0], "custodian": cells[1],
                        "fund_name": cells[2], "category": cells[3],
                        "frequency": frequency, "nav_origin": number(cells[4]),
                        "nav_previous": number(cells[5]), "nav_previous_date": _date(cells[6]),
                        "nav_current": number(cells[7]), "nav_current_date": _date(cells[8]),
                        "inception_date": _date(cells[9]),
                        "return_since_inception_pct": number(cells[10]),
                        "change_previous_pct": number(cells[11]), "source_page": page_number + 1,
                    })
                elif len(cells) >= 28:
                    # 2025 layout has merged cells expanded into 28 columns.
                    name = cells[3]
                    if not name or not (cells[10] and re.fullmatch(r"\d{2}/\d{2}/\d{4}", cells[10])):
                        continue
                    rows.append({
                        "management_company": cells[0], "custodian": cells[2],
                        "fund_name": name, "category": cells[4], "frequency": frequency,
                        "nav_origin": number(cells[5]), "nav_previous": number(cells[7]),
                        "nav_previous_date": _date(cells[10]), "nav_current": number(cells[13]),
                        "nav_current_date": _date(cells[16]), "inception_date": _date(cells[19]),
                        "return_since_inception_pct": number(cells[22]),
                        "change_previous_pct": number(cells[25]), "source_page": page_number + 1,
                    })
    return pd.DataFrame(rows, columns=FUND_COLUMNS).drop_duplicates(
        ["management_company", "custodian", "fund_name", "frequency", "nav_current_date"], keep="last")


def extract_issuer_snapshots(pdf, equities=None):
    rows = []
    equity_reference = {
        row["isin"]: row for row in (equities if equities is not None else extract_equities(pdf)).to_dict("records")
        if row.get("isin")
    }
    for page_number, page in enumerate(pdf.pages):
        text = _page_text(page)
        if "CAPITALISATIONBOURSIERE" not in _compact_text(text):
            continue
        page_start = len(rows)
        for table in _page_tables(page):
            header = " ".join(str(cell or "") for raw in table[:2] for cell in raw).upper()
            if "CAPITALISATION" not in header or "CODE ISIN" not in header:
                continue
            for raw in table:
                cells = [clean_text(cell) for cell in raw]
                isin = _isin(cells[1], cells[0]) if len(cells) > 1 else None
                if len(cells) < 15 or not _has_isin_shape(isin) or not cells[2]:
                    continue
                cells = (cells + [None] * 15)[:15]
                row = {
                    "issuer": cells[0], "isin": isin, "mnemo": cells[2], "short_name": cells[3],
                    "close": number(cells[4]), "listed_float_units": number(cells[5]),
                    "total_units": number(cells[6]), "last_dividend": number(cells[7]),
                    "dividend_year": cells[8], "dividend_date": _date(cells[9]),
                    "liquidity_3m_pct": number(cells[10]), "earnings_per_share": number(cells[11]),
                    "pe_ratio": number(cells[12]), "market_cap_float_fcfa": number(cells[13]),
                    "market_cap_total_fcfa": number(cells[14]), "source_page": page_number + 1,
                "isin_valid": isin_checksum_valid(isin),
                }
                rows.append(row)
        if "CODEISIN" in _compact_text(text) and "CAPITALISATION" in _compact_text(text):
            table_isins = {row.get("isin") for row in rows[page_start:] if row.get("isin")}
            for _, cells, _ in _grid_rows(page):
                isin = re.sub(r"\s+", "", cells[1] or "") if len(cells) > 1 else ""
                if len(cells) != 15 or not _has_isin_shape(isin) or isin in table_isins:
                    continue
                rows.append({
                    "issuer": cells[0], "isin": isin, "mnemo": cells[2],
                    "short_name": cells[3], "close": number(cells[4]),
                    "listed_float_units": number(cells[5]), "total_units": number(cells[6]),
                    "last_dividend": number(cells[7]), "dividend_year": cells[8],
                    "dividend_date": _date(cells[9]), "liquidity_3m_pct": number(cells[10]),
                    "earnings_per_share": number(cells[11]), "pe_ratio": number(cells[12]),
                    "market_cap_float_fcfa": number(cells[13]),
                    "market_cap_total_fcfa": number(cells[14]), "source_page": page_number + 1,
                })
        if page_number == 4 and len(rows) == page_start:
            # The equity capitalization table on this edition is drawn as
            # positioned text, while the bond issue table below is extractable.
            for line in _positioned_lines(page):
                if line[0]["top"] > 240:
                    continue
                isin, _ = _line_isin(line)
                if not _has_isin_shape(isin):
                    continue
                values = {
                    "issuer": _line_cell(line, 38, 96),
                    "isin": isin,
                    "mnemo": _line_cell(line, 165, 202),
                    "short_name": _line_cell(line, 202, 256),
                    "close": _line_cell(line, 255, 302),
                    "listed_float_units": _line_cell(line, 301, 357),
                    "total_units": _line_cell(line, 357, 400),
                    "last_dividend": _line_cell(line, 400, 442),
                    "dividend_year": _line_cell(line, 442, 480),
                    "dividend_date": _line_cell(line, 480, 528),
                    "liquidity_3m_pct": _line_cell(line, 528, 590),
                    "earnings_per_share": _line_cell(line, 590, 633),
                    "pe_ratio": _line_cell(line, 633, 660),
                    "market_cap_float_fcfa": _line_cell(line, 660, 740),
                    "market_cap_total_fcfa": _line_cell(line, 742, 806),
                    "source_page": page_number + 1,
                    "isin_valid": isin_checksum_valid(isin),
                }
                values["issuer"] = _join_glyphs(values["issuer"])
                values["short_name"] = _join_glyphs(values["short_name"])
                values["mnemo"] = re.sub(r"\s+", "", values["mnemo"] or "") or None
                values["dividend_date"] = _date(values["dividend_date"])
                reference = equity_reference.get(isin, {})
                for key in ("issuer", "mnemo", "short_name"):
                    if reference.get(key):
                        values[key] = reference[key]
                for key in ("close", "listed_float_units", "total_units", "last_dividend",
                            "liquidity_3m_pct", "earnings_per_share", "pe_ratio",
                            "market_cap_float_fcfa", "market_cap_total_fcfa"):
                    values[key] = number(values[key])
                rows.append(values)
    return pd.DataFrame(rows, columns=ISSUER_COLUMNS).drop_duplicates(
        ["isin", "source_page"], keep="last")


def extract_bulletin(pdf, errors=None):
    extractors = {
        "equities": (extract_equities, EQUITY_COLUMNS),
        "index": (extract_index, ["index_name", "value", "change_pct"]),
        "bond_issues": (extract_bond_issues, BOND_COLUMNS),
        "funds": (extract_funds, FUND_COLUMNS),
    }
    result, warnings = {}, []
    for name, (extractor, columns) in extractors.items():
        try:
            result[name] = extractor(pdf)
        except Exception as exc:
            warnings.append(f"{name}: {type(exc).__name__}: {exc}")
            result[name] = pd.DataFrame(columns=columns)
    try:
        result["bond_quotes"] = extract_bond_quotes(pdf, bond_issues=result["bond_issues"])
    except Exception as exc:
        warnings.append(f"bond_quotes: {type(exc).__name__}: {exc}")
        result["bond_quotes"] = pd.DataFrame(columns=QUOTE_COLUMNS)
    try:
        result["issuer_snapshots"] = extract_issuer_snapshots(pdf, equities=result["equities"])
    except Exception as exc:
        warnings.append(f"issuer_snapshots: {type(exc).__name__}: {exc}")
        result["issuer_snapshots"] = pd.DataFrame(columns=ISSUER_COLUMNS)
    if errors is not None:
        errors.extend(warnings)
    return result


def extract_index(pdf):
    rows = []
    for table in _page_tables(pdf.pages[0]):
        for row in table:
            cells = [clean_text(cell) for cell in row]
            if len(cells) >= 2 and cells[0] and "BVMAC-AS" in cells[0].upper():
                value = number(cells[1])
                if value is not None:
                    rows.append({"index_name": "BVMAC-AS", "value": value, "change_pct": None})
            elif len(cells) >= 2 and cells[0] and "VARIATION JOUR" in cells[0].upper() and rows:
                rows[-1]["change_pct"] = number(cells[1])
    if rows:
        return pd.DataFrame(rows, columns=["index_name", "value", "change_pct"])
    # Some editions print the index as aligned PDF text rather than a table.
    page = pdf.pages[0]
    words = sorted(page.extract_words(), key=lambda w: (w["top"], w["x0"]))
    lines = []
    for word in words:
        if not lines or abs(word["top"] - lines[-1][0]["top"]) > 2.5:
            lines.append([word])
        else:
            lines[-1].append(word)
    index_value, daily_change = None, None
    for line in lines:
        left = "".join(w["text"] for w in line if 320 <= w["x0"] < 450).upper()
        right = " ".join(w["text"] for w in line if 475 <= w["x0"] < 530)
        value = number(right)
        if "BVMAC-AS" in left and value is not None:
            index_value = value
        elif "VARIATIONJOUR" in re.sub(r"\s+", "", left) and value is not None:
            daily_change = value
    if index_value is not None:
        return pd.DataFrame([{
            "index_name": "BVMAC-AS", "value": index_value, "change_pct": daily_change,
        }], columns=["index_name", "value", "change_pct"])
    # Older layout shows the index only as a raster chart, so its value cannot
    # be recovered as selectable text.
    return pd.DataFrame(columns=["index_name", "value", "change_pct"])

