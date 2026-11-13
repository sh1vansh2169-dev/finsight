"""Statement inbox: statements saved into a folder are picked up automatically.

Nothing logs in anywhere. The user downloads a statement from their bank or
UPI app and saves it into the inbox folder; FinSight notices it, reads it
(CSV, Excel or PDF) and stages it as an import *preview*. The user still
reviews each statement and chooses to add or discard it, as with an upload.

* A file in a subfolder uses the subfolder's name as the account name for
  statements without an account column: ``inbox/HDFC Savings/march.pdf``.
* A file is read only once its size has stayed the same between two scans,
  so a download still in progress is never read half-written.
* Afterwards the file moves to ``done/`` or, if it cannot be read, to
  ``could not read/`` with a ``.txt`` note saying why.
* Partial downloads and hidden or temporary files are ignored.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from moneyos.db.tables import User
from moneyos.db.tenancy import system_session, user_session
from moneyos.domain.classify import Rules
from moneyos.domain.importer import SchemaError
from moneyos.services import imports
from moneyos.services.errors import PayloadTooLargeError

log = logging.getLogger(__name__)

DONE, FAILED = "done", "could not read"
_PARTIAL = (".crdownload", ".part", ".partial", ".tmp", ".download")


@dataclass
class ScanResult:
    staged: list[tuple[str, int]] = field(default_factory=list)  # (file, import batch id)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (file, reason)
    waiting: list[str] = field(default_factory=list)             # still being written
    note: str | None = None                                      # why nothing could be done


def resolve_user(factory: sessionmaker[Session], email: str | None) -> tuple[int | None, str | None]:
    """Whose ledger statements go into: the named user, or the only user there is."""
    with system_session(factory) as session:
        if email:
            uid = session.scalar(select(User.id).where(func.lower(User.email) == email.strip().lower()))
            return (uid, None) if uid else (None, f"no account with the email {email}")
        ids = list(session.scalars(select(User.id).limit(2)))
    if not ids:
        return None, "no account yet: create one in the app first"
    if len(ids) > 1:
        return None, "more than one account: set MONEYOS_WATCH_USER to the email whose ledger the inbox fills"
    return ids[0], None


def _candidates(inbox: Path) -> list[Path]:
    """Statement files in the inbox and its account subfolders (not in done/ or could not read/)."""
    found = []
    for path in sorted(inbox.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(inbox).parts
        if relative[0] in (DONE, FAILED) or len(relative) > 2:
            continue
        name = path.name
        if name.startswith((".", "~$")) or name.lower().endswith(_PARTIAL) or name.lower().endswith(".txt"):
            continue
        found.append(path)
    return found


def _move(path: Path, inbox: Path, folder: str) -> Path:
    """Move ``path`` under ``inbox/folder`` keeping its account subfolder; never overwrite."""
    relative = path.relative_to(inbox)
    target = inbox / folder / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    counter = 1
    while target.exists():
        target = target.with_name(f"{path.stem} ({counter}){path.suffix}")
        counter += 1
    path.replace(target)
    return target


class Inbox:
    """Scans one folder. Keeps the sizes seen at the last scan to know when a file is complete."""

    def __init__(self, folder: Path, factory: sessionmaker[Session], rules: Rules, *, user_email: str | None = None):
        self.folder = Path(folder)
        self.factory, self.rules, self.user_email = factory, rules, user_email
        self._last_seen: dict[Path, int] = {}

    def scan(self) -> ScanResult:
        result = ScanResult()
        self.folder.mkdir(parents=True, exist_ok=True)
        files = _candidates(self.folder)
        sizes = {p: p.stat().st_size for p in files}
        ready = [p for p in files if sizes[p] > 0 and self._last_seen.get(p) == sizes[p]]
        result.waiting = [p.name for p in files if p not in ready]
        self._last_seen = sizes
        if not ready:
            return result
        user_id, problem = resolve_user(self.factory, self.user_email)
        if user_id is None:
            result.note = problem
            return result
        for path in ready:
            self._last_seen.pop(path, None)
            account = path.parent.name if path.parent != self.folder else None
            try:
                content = path.read_bytes()
                with user_session(self.factory, user_id) as session:
                    batch = imports.preview_import(
                        session, filename=path.name, content=content,
                        options=imports.ImportOptions(account=account), rules=self.rules,
                    )
                    batch_id = batch.id
            except (SchemaError, PayloadTooLargeError, ValueError) as error:
                moved = _move(path, self.folder, FAILED)
                moved.with_name(moved.name + ".txt").write_text(
                    f"FinSight could not read {path.name}:\n{error}\n", encoding="utf-8")
                result.failed.append((path.name, str(error)))
                continue
            except OSError as error:  # locked or vanished (e.g. still open in another program): try next time
                log.warning("inbox: could not read %s yet (%s)", path.name, type(error).__name__)
                continue
            _move(path, self.folder, DONE)
            result.staged.append((path.name, batch_id))
        return result


class InboxWatcher:
    """Runs ``Inbox.scan`` every few seconds in a background thread."""

    def __init__(self, inbox: Inbox, interval: float = 5.0):
        self.inbox, self.interval = inbox, interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last: ScanResult | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="finsight-inbox", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.last = self.inbox.scan()
                for name, batch_id in self.last.staged:
                    log.info("inbox: %s is ready to review (import %d)", name, batch_id)
            except Exception:  # never let one bad scan stop the watcher
                log.exception("inbox: scan failed")
            self._stop.wait(self.interval)
