"""Excel and PDF statements through the HTTP API (synthetic files only)."""

from domain.test_statements import EXPECTED, pdf_bytes, xlsx_bytes
from test_api import client, make_client  # noqa: F401 - pytest fixtures

UPLOAD = "/api/v1/imports/preview"


def _upload(client, content, name, **form):
    return client.post(UPLOAD, files={"file": (name, content, "application/octet-stream")}, data=form)


def test_excel_then_the_same_statement_as_pdf(client):
    first = _upload(client, xlsx_bytes(), "january.xlsx", account="Demo Savings")
    assert first.status_code == 201, first.text
    rows = first.json()["rows"]
    assert [r["outcome"] for r in rows] == ["new"] * 5
    assert [r["transaction"]["amount"] for r in rows] == [str(e[2]) for e in EXPECTED]
    commit = client.post(f"/api/v1/imports/{first.json()['batch']['id']}/commit")
    assert commit.json()["inserted_rows"] == 5

    # The bank's PDF of the same month: every row is recognised as already recorded.
    again = _upload(client, pdf_bytes(), "january.pdf", account="Demo Savings")
    assert again.status_code == 201, again.text
    assert again.json()["batch"]["duplicate_rows"] == 5
    assert again.json()["batch"]["new_rows"] == 0

    listed = client.get("/api/v1/transactions?limit=50").json()
    assert listed["total"] == 5


def test_unreadable_statements_explain_why(client):
    locked = _upload(client, pdf_bytes(encrypt=True), "locked.pdf")
    assert locked.status_code == 422
    assert "password-protected" in locked.json()["detail"]

    scanned = _upload(client, pdf_bytes(text=False), "scan.pdf")
    assert scanned.status_code == 422 and "scanned" in scanned.json()["detail"]

    old_excel = _upload(client, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 512, "old.xls")
    assert old_excel.status_code == 422 and ".xlsx" in old_excel.json()["detail"]

    # A PDF named .csv is still read as a PDF: the content decides, not the name.
    renamed = _upload(client, pdf_bytes(), "statement.csv", account="Demo Savings")
    assert renamed.status_code == 201 and renamed.json()["batch"]["new_rows"] == 5
