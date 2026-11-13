"""Excel and PDF statements: synthetic files built in the test, never real ones."""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime
from decimal import Decimal as D

import pytest
from fpdf import FPDF
from openpyxl import Workbook

from moneyos.domain import statements
from moneyos.domain.importer import SchemaError
from moneyos.domain.statements import detect_format, import_bytes

# One synthetic statement: date, description, debit, credit.
ROWS = [
    (date(2026, 1, 3), "RENT GREENVIEW APTS", "22000.00", ""),
    (date(2026, 1, 5), "ACME CORP SALARY", "", "85000.00"),
    (date(2026, 1, 9), "FRESHMART GROCERIES", "1875.56", ""),
    (date(2026, 1, 12), "UPI CHAI POINT", "0.10", ""),
    (date(2026, 1, 15), "REFUND ONLINE STORE", "", "1234567.89"),
]
HEADER = ["Txn Date", "Narration", "Withdrawal Amt", "Deposit Amt"]


def as_tuples(result):
    return [(t.date, t.description, t.amount) for t in result.transactions]


EXPECTED = [
    (date(2026, 1, 3), "RENT GREENVIEW APTS", D("-22000.00")),
    (date(2026, 1, 5), "ACME CORP SALARY", D("85000.00")),
    (date(2026, 1, 9), "FRESHMART GROCERIES", D("-1875.56")),
    (date(2026, 1, 12), "UPI CHAI POINT", D("-0.10")),
    (date(2026, 1, 15), "REFUND ONLINE STORE", D("1234567.89")),
]


def csv_bytes() -> bytes:
    lines = [",".join(HEADER)] + [f"{d:%d/%m/%Y},{desc},{dr},{cr}" for d, desc, dr, cr in ROWS]
    return ("\n".join(lines) + "\n").encode()


def xlsx_bytes(rows=ROWS, preamble=True, numbers_as_floats=True) -> bytes:
    wb = Workbook()
    ws = wb.active
    if preamble:  # banks put titles above the table
        ws.append(["Demo Bank: account statement"])
        ws.append(["Account", "XXXX0001"])
        ws.append([])
    ws.append(HEADER)
    for d, desc, dr, cr in rows:
        value = (lambda x: float(x) if x and numbers_as_floats else x or None)
        ws.append([datetime(d.year, d.month, d.day), desc, value(dr), value(cr)])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def pdf_bytes(rows=ROWS, borders=True, per_page=None, wrap=False, encrypt=False, text=True, footer=False) -> bytes:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=9)
    chunks = [rows[i:i + per_page] for i in range(0, len(rows), per_page)] if per_page else [rows]
    for chunk in chunks:
        pdf.add_page()
        if not text:
            pdf.rect(20, 20, 100, 50, style="F")  # an "image" with no text, like a scan
            continue
        pdf.cell(0, 8, "Demo Bank statement", new_x="LMARGIN", new_y="NEXT")
        with pdf.table(borders_layout="ALL" if borders else "NONE", text_align="LEFT",
                       col_widths=(25, 80, 30, 30)) as table:
            table.row(HEADER)
            for d, desc, dr, cr in chunk:
                if wrap and " " in desc:
                    first, rest = desc.rsplit(" ", 1)  # statements wrap at a space
                    table.row([f"{d:%d/%m/%Y}", first, dr, cr])
                    table.row(["", rest, "", ""])  # the rest of the narration, on its own row
                else:
                    table.row([f"{d:%d/%m/%Y}", desc, dr, cr])
        if footer:
            # Far below the table, and only under the Narration heading: the hard case,
            # since it looks exactly like a wrapped description except for where it sits.
            pdf.set_xy(37, -25)
            pdf.cell(60, 6, "Thank you for banking")
    if encrypt:
        pdf.set_encryption(owner_password="owner-secret", user_password="user-secret")
    return bytes(pdf.output())


# ------------------------------------------------------------------ detection


def test_format_is_decided_by_content_not_name():
    assert detect_format(csv_bytes()) == "csv"
    assert detect_format(xlsx_bytes()) == "xlsx"
    assert detect_format(pdf_bytes()) == "pdf"
    with pytest.raises(SchemaError, match=r"old Excel \(\.xls\)"):
        detect_format(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)


# ------------------------------------------------------------------ same statement, three formats


@pytest.mark.parametrize("make", [csv_bytes, xlsx_bytes, pdf_bytes, lambda: pdf_bytes(borders=False)],
                         ids=["csv", "xlsx", "pdf-lines", "pdf-no-lines"])
def test_every_format_gives_the_same_transactions(make):
    result = import_bytes(make(), "statement", account="Demo Savings")
    assert as_tuples(result) == EXPECTED
    assert result.rejected == []
    assert {t.account for t in result.transactions} == {"Demo Savings"}


# ------------------------------------------------------------------ Excel


def test_excel_amounts_stay_exact():
    # 0.10 and 1,234,567.89 are not exact as binary floats; the cell value must still import exactly.
    result = import_bytes(xlsx_bytes(), "s.xlsx")
    assert [t.amount for t in result.transactions] == [e[2] for e in EXPECTED]


def test_excel_text_cells_work_too():
    rows = [(date(2026, 1, 3), "RENT", "22,000.00", "")]
    result = import_bytes(xlsx_bytes(rows, numbers_as_floats=False), "s.xlsx")
    assert as_tuples(result) == [(date(2026, 1, 3), "RENT", D("-22000.00"))]


def test_excel_rows_keep_their_sheet_row_numbers():
    result = import_bytes(xlsx_bytes(), "s.xlsx")
    assert [t.source_row for t in result.transactions] == [5, 6, 7, 8, 9]  # 3 title lines, then the header


def test_excel_without_a_usable_header_is_refused():
    wb = Workbook()
    wb.active.append(["Name", "Value"])
    wb.active.append(["a", 1])
    out = io.BytesIO()
    wb.save(out)
    with pytest.raises(SchemaError, match="no header row"):
        import_bytes(out.getvalue(), "s.xlsx")


def test_a_zip_that_is_not_a_workbook_is_refused():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("notes.txt", "hello")
    with pytest.raises(SchemaError, match="not an Excel"):
        import_bytes(out.getvalue(), "s.xlsx")


def test_a_workbook_that_unpacks_to_something_huge_is_refused():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/worksheets/sheet1.xml", b"\0" * (statements.MAX_XLSX_UNCOMPRESSED + 1))
    content = out.getvalue()
    assert len(content) < 1024 * 1024  # small on disk...
    with pytest.raises(SchemaError, match="too large once unpacked"):  # ...but not once unpacked
        import_bytes(content, "s.xlsx")


def test_row_limit(monkeypatch):
    monkeypatch.setattr(statements, "MAX_ROWS", 3)
    with pytest.raises(SchemaError, match="more than 3 rows"):
        import_bytes(xlsx_bytes(), "s.xlsx")


# ------------------------------------------------------------------ PDF


def test_pdf_tables_across_pages_with_repeated_headers():
    result = import_bytes(pdf_bytes(per_page=2), "s.pdf")
    assert as_tuples(result) == EXPECTED
    assert result.rejected == []


def test_pdf_descriptions_wrapped_onto_their_own_row_are_joined():
    result = import_bytes(pdf_bytes(wrap=True), "s.pdf")
    assert as_tuples(result) == EXPECTED
    assert result.rejected == []


def test_pdf_without_ruling_lines_across_pages_with_wrapped_text():
    result = import_bytes(pdf_bytes(borders=False, per_page=2, wrap=True), "s.pdf")
    assert as_tuples(result) == EXPECTED
    assert result.rejected == []


def test_a_footer_is_never_glued_onto_a_description():
    # Without lines, the footer is read as a row of its own. It has no date, so it is shown as a
    # rejected row with its reason, never merged into the last transaction or imported.
    result = import_bytes(pdf_bytes(borders=False, per_page=2, footer=True), "s.pdf")
    assert as_tuples(result) == EXPECTED
    assert [" ".join(v for v in r.raw.values() if v) for r in result.rejected] == [
        "Thank you for banking"] * 3  # one per page; page titles are skipped
    assert {r.reason for r in result.rejected} == {"missing amount"}


def test_password_protected_pdfs_are_refused_without_asking_for_the_password():
    with pytest.raises(SchemaError, match="password-protected"):
        import_bytes(pdf_bytes(encrypt=True), "s.pdf")


def test_scanned_pdfs_are_refused_with_a_reason():
    with pytest.raises(SchemaError, match="scanned image"):
        import_bytes(pdf_bytes(text=False), "s.pdf")


def test_pdf_without_a_transaction_table_is_refused():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "Dear customer, your statement is attached separately. Thank you.")
    with pytest.raises(SchemaError, match="no transaction table"):
        import_bytes(bytes(pdf.output()), "letter.pdf")


def test_pdf_page_limit(monkeypatch):
    monkeypatch.setattr(statements, "MAX_PDF_PAGES", 1)
    with pytest.raises(SchemaError, match="more than 1 pages"):
        import_bytes(pdf_bytes(per_page=2), "s.pdf")


def test_damaged_files_are_refused_cleanly():
    with pytest.raises(SchemaError, match="PDF could not be read"):
        import_bytes(b"%PDF-1.7\nthis is not really a pdf", "s.pdf")
    with pytest.raises(SchemaError):
        import_bytes(b"PK\x03\x04garbage", "s.xlsx")
