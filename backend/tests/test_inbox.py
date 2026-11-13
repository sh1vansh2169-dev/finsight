"""Statement inbox: statements saved into a folder are staged for review (synthetic files only)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from conftest import sign_up
from domain.test_statements import pdf_bytes, xlsx_bytes
from moneyos.api.app import create_app
from moneyos.config import DataMode, Settings
from moneyos.db.session import init_db
from moneyos.db.tables import ImportBatch, TransactionRecord, User
from moneyos.db.tenancy import system_session, user_session
from moneyos.domain.classify import load_rules
from moneyos.services.inbox import DONE, FAILED, Inbox

CSV = b"Date,Description,Amount\n03/03/2026,RENT GREENVIEW APTS,-22000.00\n05/03/2026,ACME CORP SALARY,85000.00\n"


@pytest.fixture
def setup(database_url, tmp_path):
    factory = init_db(database_url, DataMode.REAL)

    def add_user(email):
        with system_session(factory) as s:
            user = User(email=email)
            s.add(user)
            s.commit()
            return user.id

    yield factory, tmp_path / "inbox", add_user
    factory.kw["bind"].dispose()


def batches(factory, user_id):
    with user_session(factory, user_id) as s:
        return [(b.filename, b.status, b.new_rows) for b in s.scalars(select(ImportBatch).order_by(ImportBatch.id))]


def test_a_saved_statement_is_staged_for_review_never_added(setup, rules):
    factory, folder, add_user = setup
    uid = add_user("you@example.com")
    inbox = Inbox(folder, factory, rules)
    folder.mkdir()
    (folder / "march.csv").write_bytes(CSV)

    first = inbox.scan()  # just seen: it might still be downloading
    assert first.waiting == ["march.csv"] and first.staged == []
    second = inbox.scan()  # same size as last time: complete
    assert [name for name, _ in second.staged] == ["march.csv"]

    assert batches(factory, uid) == [("march.csv", "previewed", 2)]
    with system_session(factory) as s:
        assert s.scalar(select(func.count()).select_from(TransactionRecord)) == 0  # nothing added without review
    assert not (folder / "march.csv").exists() and (folder / DONE / "march.csv").exists()
    assert inbox.scan().staged == []  # never read twice


def test_a_file_still_being_written_waits(setup, rules):
    factory, folder, add_user = setup
    add_user("you@example.com")
    inbox = Inbox(folder, factory, rules)
    folder.mkdir()
    (folder / "big.csv").write_bytes(CSV[:30])
    inbox.scan()
    (folder / "big.csv").write_bytes(CSV)  # grew since the last scan
    assert inbox.scan().staged == []
    assert [n for n, _ in inbox.scan().staged] == ["big.csv"]


def test_subfolders_name_the_account_and_every_format_works(setup, rules):
    factory, folder, add_user = setup
    uid = add_user("you@example.com")
    inbox = Inbox(folder, factory, rules)
    (folder / "HDFC Savings").mkdir(parents=True)
    (folder / "HDFC Savings" / "jan.xlsx").write_bytes(xlsx_bytes())
    (folder / "PhonePe").mkdir()
    (folder / "PhonePe" / "jan.pdf").write_bytes(pdf_bytes())
    inbox.scan()
    assert len(inbox.scan().staged) == 2
    with user_session(factory, uid) as s:
        rows = s.scalars(select(ImportBatch)).all()
        assert sorted(b.account_override for b in rows) == ["HDFC Savings", "PhonePe"]
    assert (folder / DONE / "HDFC Savings" / "jan.xlsx").exists() and (folder / DONE / "PhonePe" / "jan.pdf").exists()


def test_unreadable_files_are_set_aside_with_the_reason(setup, rules):
    factory, folder, add_user = setup
    add_user("you@example.com")
    inbox = Inbox(folder, factory, rules)
    folder.mkdir()
    (folder / "locked.pdf").write_bytes(pdf_bytes(encrypt=True))
    (folder / "notes.csv").write_bytes(b"When,What\n1,2\n")
    inbox.scan()
    result = inbox.scan()
    assert sorted(name for name, _ in result.failed) == ["locked.pdf", "notes.csv"]
    note = (folder / FAILED / "locked.pdf.txt").read_text(encoding="utf-8")
    assert "password-protected" in note
    assert (folder / FAILED / "locked.pdf").exists() and not (folder / "locked.pdf").exists()


def test_partial_downloads_and_temporary_files_are_ignored(setup, rules):
    factory, folder, add_user = setup
    add_user("you@example.com")
    inbox = Inbox(folder, factory, rules)
    folder.mkdir()
    for name in ("statement.csv.crdownload", "statement.part", "~$book.xlsx", ".hidden.csv", "readme.txt"):
        (folder / name).write_bytes(CSV)
    inbox.scan()
    result = inbox.scan()
    assert result.staged == [] and result.failed == [] and result.waiting == []


def test_a_second_file_with_the_same_name_does_not_overwrite(setup, rules):
    factory, folder, add_user = setup
    add_user("you@example.com")
    inbox = Inbox(folder, factory, rules)
    folder.mkdir()
    for content in (CSV, CSV.replace(b"22000", b"23000")):
        (folder / "march.csv").write_bytes(content)
        inbox.scan()
        inbox.scan()
    assert sorted(p.name for p in (folder / DONE).iterdir()) == ["march (1).csv", "march.csv"]


def test_statements_go_only_to_the_right_ledger(setup, rules):
    factory, folder, add_user = setup
    folder.mkdir()
    (folder / "march.csv").write_bytes(CSV)

    no_one = Inbox(folder, factory, rules)
    no_one.scan()
    assert "no account yet" in no_one.scan().note and (folder / "march.csv").exists()  # left in place

    asha, ravi = add_user("asha@example.com"), add_user("ravi@example.com")
    ambiguous = Inbox(folder, factory, rules)
    ambiguous.scan()
    assert "more than one account" in ambiguous.scan().note and (folder / "march.csv").exists()

    named = Inbox(folder, factory, rules, user_email="Ravi@Example.com")
    named.scan()
    assert len(named.scan().staged) == 1
    assert batches(factory, ravi) == [("march.csv", "previewed", 2)] and batches(factory, asha) == []


def test_the_running_app_watches_the_inbox(database_url, tmp_path):
    folder = tmp_path / "inbox"
    settings = Settings(database_url=database_url, watch_dir=folder)
    with TestClient(create_app(settings)) as client:  # "with" runs startup, which starts the watcher
        sign_up(client)
        status = client.get("/api/v1/imports/inbox").json()
        assert status["enabled"] is True and status["folder"] == str(folder.resolve())
        (folder / "march.csv").write_bytes(CSV)
        watcher = client.app.state.inbox_watcher
        watcher.inbox.scan()  # instead of waiting for the background timer
        watcher.inbox.scan()
        listed = client.get("/api/v1/imports").json()
        assert [(b["filename"], b["status"]) for b in listed] == [("march.csv", "previewed")]
        batch_id = listed[0]["id"]
        assert client.post(f"/api/v1/imports/{batch_id}/commit").json()["inserted_rows"] == 2  # the user's choice
    assert client.app.state.inbox_watcher._stop.is_set()  # stopped with the app
    client.app.state.session_factory.kw["bind"].dispose()


def test_the_inbox_is_off_unless_configured(database_url):
    with TestClient(create_app(Settings(database_url=database_url))) as client:
        sign_up(client)
        assert client.get("/api/v1/imports/inbox").json() == {"enabled": False, "folder": None, "note": None, "waiting": []}
        assert client.app.state.inbox_watcher is None
    client.app.state.session_factory.kw["bind"].dispose()


@pytest.fixture
def rules():
    return load_rules()
