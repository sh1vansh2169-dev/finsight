"""Read statements in other formats (Excel, PDF) into the same rows as a CSV.

Every format ends up as a header plus rows of cell text, then goes through
``importer.import_records``: the same validation, the same reasons for rejected
rows, the same duplicate checks and the same preview-then-commit workflow.

What is supported, and what deliberately is not:

* **CSV** as before.
* **Excel .xlsx**: the first sheet. The header row is found even when the
  bank puts a few title lines above it. Formulas are read as the value Excel
  last saved; a formula never calculated by Excel reads as empty.
* **PDF**: statements that contain text (not scans) and whose transactions
  are laid out as a table with recognisable column headings. Scanned
  statements would need OCR, which MoneyOS does not do. Password-protected
  PDFs are refused: MoneyOS does not ask for or handle statement passwords.
* **.xls** (Excel 97-2003) is refused with a message to save as .xlsx or CSV.

The file type is decided by the file's first bytes, never by its name.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable, Iterator
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal

from moneyos.domain.importer import (
    FileImport,
    SchemaError,
    decode_bytes,
    import_records,
    import_text,
    map_columns,
)

Format = Literal["csv", "xlsx", "pdf"]

# Limits on what one upload may make the server do (the 5 MB size cap applies first).
MAX_ROWS = 20_000
MAX_PDF_PAGES = 100
MAX_XLSX_UNCOMPRESSED = 50 * 1024 * 1024  # an .xlsx is a zip; refuse "zip bombs"
HEADER_SEARCH_ROWS = 30  # how far down a sheet the header row may be

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # old .xls, .doc


def detect_format(content: bytes) -> Format:
    """Decide the format from the file's first bytes."""
    if content.startswith(b"%PDF-"):
        return "pdf"
    if content.startswith(b"PK\x03\x04"):
        return "xlsx"
    if content.startswith(_OLE_MAGIC):
        raise SchemaError("this is an old Excel (.xls) file; save it as .xlsx or CSV and import that")
    return "csv"


def import_bytes(
    content: bytes,
    source_file: str,
    *,
    account: str | None = None,
    default_currency: str = "INR",
    day_first: bool = True,
) -> FileImport:
    """Import a CSV, Excel or PDF statement."""
    kind = detect_format(content)
    options = {"account": account, "default_currency": default_currency, "day_first": day_first}
    if kind == "csv":
        return import_text(io.StringIO(decode_bytes(content), newline=""), source_file, **options)
    header, rows = read_xlsx(content) if kind == "xlsx" else read_pdf(content)
    return import_records(header, rows, source_file, **options)


# ------------------------------------------------------------------ shared


def _find_header(rows: Iterable[tuple[int, list[str]]]) -> tuple[list[str], Iterator[tuple[int, list[str]]]]:
    """The first row that maps to the needed columns is the header; the rest follow it."""
    iterator = iter(rows)
    looked = 0
    first_error: SchemaError | None = None
    for _, cells in iterator:
        if any(c.strip() for c in cells):
            try:
                map_columns(cells)
                return cells, iterator
            except SchemaError as error:
                first_error = first_error or error
        looked += 1
        if looked >= HEADER_SEARCH_ROWS:
            break
    raise SchemaError(
        "no header row with a date, a description and an amount (or debit/credit) column was found"
        + (f" in the first {HEADER_SEARCH_ROWS} rows" if looked >= HEADER_SEARCH_ROWS else "")
    ) from first_error


def _records(header: list[str], rows: Iterable[tuple[int, list[str]]]) -> Iterator[tuple[int, dict[str, str]]]:
    """Rows as {header: cell}, skipping repeats of the header (e.g. on each PDF page)."""
    count = 0
    for number, cells in rows:
        if cells == header:
            continue
        count += 1
        if count > MAX_ROWS:
            raise SchemaError(f"the file has more than {MAX_ROWS:,} rows; split it into smaller files")
        padded = cells + [""] * (len(header) - len(cells))
        yield number, {h: padded[i] for i, h in enumerate(header) if h}


# ------------------------------------------------------------------ Excel


def _cell_text(value: Any) -> str:
    """An Excel cell as the text a CSV would have held, keeping amounts exact."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        # repr gives the shortest text that reads back as the same float, which is the
        # number as typed for anything with up to 15 significant digits (all money amounts).
        return format(Decimal(repr(value)), "f")
    if isinstance(value, int):
        return str(value)
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def read_xlsx(content: bytes) -> tuple[list[str], Iterator[tuple[int, dict[str, str]]]]:
    """The first sheet of an .xlsx file as (header, records)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise SchemaError("the file looks like a zip archive but cannot be opened") from None
    with archive:
        if "xl/workbook.xml" not in archive.namelist():
            raise SchemaError("this zip file is not an Excel .xlsx workbook")
        if sum(i.file_size for i in archive.infolist()) > MAX_XLSX_UNCOMPRESSED:
            raise SchemaError("the workbook is too large once unpacked")

    from openpyxl import load_workbook  # imported here: only needed for Excel files

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as error:  # openpyxl raises many types for damaged files
        raise SchemaError(f"the Excel file could not be read ({type(error).__name__})") from None
    sheet = workbook.worksheets[0]
    rows = (
        (number, [_cell_text(v) for v in values])
        for number, values in enumerate(sheet.iter_rows(values_only=True), start=1)
    )
    header, rest = _find_header(rows)
    return header, _records(header, _closing(rest, workbook))


def _closing(rows: Iterator, workbook: Any) -> Iterator:
    try:
        yield from rows
    finally:
        workbook.close()


# ------------------------------------------------------------------ PDF


def _pdf_rows(pages: list[Any]) -> list[tuple[int, list[str]]]:
    """Table rows from every page, numbered in reading order (page by page, top to bottom)."""
    out: list[tuple[int, list[str]]] = []
    for page in pages:
        tables = page.extract_tables()
        for table in tables:
            for cells in table:
                text = [" ".join((c or "").split()) for c in cells]  # wrapped text becomes one line
                if any(text):
                    out.append((len(out) + 1, text))
    return out


def _join_wrapped(header: list[str], rows: Iterable[tuple[int, list[str]]]) -> Iterator[tuple[int, list[str]]]:
    """Statements often wrap a long description onto a row of its own, with no date
    or amount. Join such rows to the transaction above instead of rejecting them."""
    columns = map_columns(header)
    position = {name: header.index(h) for name, h in columns.items()}
    money = [position[k] for k in ("amount", "debit", "credit") if k in position]
    pending: tuple[int, list[str]] | None = None
    for number, cells in rows:
        cells = cells + [""] * (len(header) - len(cells))
        is_continuation = (
            pending is not None
            and not cells[position["date"]]
            and cells[position["description"]]
            and not any(cells[i] for i in money)
            and cells != header
        )
        if is_continuation:
            joined = list(pending[1])
            i = position["description"]
            joined[i] = f"{joined[i]} {cells[i]}".strip()
            pending = (pending[0], joined)
            continue
        if pending is not None:
            yield pending
        pending = (number, cells)
    if pending is not None:
        yield pending


def _lines(page: Any) -> list[tuple[float, float, list[dict[str, Any]]]]:
    """Words on a page grouped into lines: (top, bottom, words left to right)."""
    lines: list[tuple[float, float, list[dict[str, Any]]]] = []
    for word in sorted(page.extract_words(), key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(word["top"] - lines[-1][0]) <= 3:
            top, bottom, words = lines[-1]
            lines[-1] = (top, max(bottom, word["bottom"]), words + [word])
        else:
            lines.append((word["top"], word["bottom"], [word]))
    return [(top, bottom, sorted(words, key=lambda w: w["x0"])) for top, bottom, words in lines]


def _phrases(words: list[dict[str, Any]]) -> list[tuple[str, float, float]]:
    """Words close together form one phrase, such as the heading "Withdrawal Amt": (text, x0, x1)."""
    phrases: list[tuple[str, float, float]] = []
    for w in words:
        gap_limit = (w["bottom"] - w["top"]) * 0.8  # about one space at this font size
        if phrases and w["x0"] - phrases[-1][2] <= gap_limit:
            text, x0, _ = phrases[-1]
            phrases[-1] = (f"{text} {w['text']}", x0, w["x1"])
        else:
            phrases.append((w["text"], w["x0"], w["x1"]))
    return phrases


def _layout_rows(pages: list[Any]) -> tuple[list[str], list[tuple[int, list[str], bool]]]:
    """Read a table drawn without lines, using the header's word positions as columns.

    Each word below the header goes to the column whose span contains its
    centre; neighbouring spans meet halfway between their headings. Each row
    also records whether it sits directly under the row above (for wrapped text).
    """
    header: list[str] | None = None
    bounds: list[float] = []
    rows: list[tuple[int, list[str], bool]] = []
    for page in pages:
        lines = _lines(page)
        # Where this page's own header row is, if it repeats one. Lines above it
        # (bank name, account details) are not transactions.
        start = 0
        for index, (_, _, words) in enumerate(lines):
            phrases = _phrases(words)
            cells = [text for text, _, _ in phrases]
            try:
                map_columns(cells)
            except SchemaError:
                continue
            if header is None:
                header = cells
                bounds = [(phrases[i][2] + phrases[i + 1][1]) / 2 for i in range(len(phrases) - 1)]
            start = index + 1
            break
        if header is None:
            continue  # no header yet: nothing on this page can be read as a row
        last_bottom: float | None = lines[start - 1][1] if start else None  # never continue across pages
        for top, bottom, words in lines[start:]:
            cells = [""] * len(header)
            for w in words:
                column = sum((w["x0"] + w["x1"]) / 2 > b for b in bounds)
                cells[column] = f"{cells[column]} {w['text']}".strip()
            directly_below = last_bottom is not None and top - last_bottom <= (bottom - top) * 1.2
            rows.append((len(rows) + 1, cells, directly_below))
            last_bottom = bottom
    if header is None:
        raise SchemaError("no header row found")
    return header, rows


def _join_layout_wrapped(header: list[str], rows: list[tuple[int, list[str], bool]]) -> Iterator[tuple[int, list[str]]]:
    """Like _join_wrapped, but only joins a line sitting directly under the row above,
    so a page footer further down is never glued onto a description."""
    columns = map_columns(header)
    position = {name: header.index(h) for name, h in columns.items()}
    money = [position[k] for k in ("amount", "debit", "credit") if k in position]
    pending: tuple[int, list[str]] | None = None
    for number, cells, directly_below in rows:
        continues = (
            pending is not None and directly_below and not cells[position["date"]]
            and cells[position["description"]] and not any(cells[i] for i in money)
        )
        if continues:
            joined = list(pending[1])
            i = position["description"]
            joined[i] = f"{joined[i]} {cells[i]}".strip()
            pending = (pending[0], joined)
            continue
        if pending is not None:
            yield pending
        pending = (number, cells)
    if pending is not None:
        yield pending


def _is_password_error(error: BaseException) -> bool:
    """pdfplumber wraps pdfminer's errors; look inside for a password problem."""
    from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect

    seen: BaseException | None = error
    for _ in range(5):
        if seen is None:
            break
        if isinstance(seen, (PDFPasswordIncorrect, PDFEncryptionError)):
            return True
        nested = [a for a in seen.args if isinstance(a, BaseException)]
        seen = nested[0] if nested else seen.__cause__
    return False


def read_pdf(content: bytes) -> tuple[list[str], Iterator[tuple[int, dict[str, str]]]]:
    """Transaction tables in a text PDF as (header, records)."""
    import pdfplumber  # imported here: only needed for PDFs

    try:
        pdf = pdfplumber.open(io.BytesIO(content))
    except Exception as error:
        if _is_password_error(error):
            raise SchemaError(
                "this PDF is password-protected. MoneyOS does not handle statement passwords: "
                "download the statement as CSV or Excel if your bank offers it"
            ) from None
        raise SchemaError(f"the PDF could not be read ({type(error).__name__})") from None

    with pdf:
        if len(pdf.pages) > MAX_PDF_PAGES:
            raise SchemaError(f"the PDF has more than {MAX_PDF_PAGES} pages; import a shorter period")
        if not any((page.extract_text() or "").strip() for page in pdf.pages):
            raise SchemaError(
                "no text was found in this PDF; it looks like a scanned image, which MoneyOS cannot read"
            )
        # First: tables drawn with ruling lines. Then: tables laid out by spacing only.
        try:
            header, rest = _find_header(_pdf_rows(pdf.pages))
            return header, _records(header, _join_wrapped(header, rest))
        except SchemaError:
            pass
        try:
            header, rows = _layout_rows(pdf.pages)
        except SchemaError:
            raise SchemaError(
                "no transaction table was found in this PDF. MoneyOS reads statements whose transactions "
                "are a table with headings such as Date, Description and Amount (or Debit/Credit)"
            ) from None
        return header, _records(header, _join_layout_wrapped(header, rows))
