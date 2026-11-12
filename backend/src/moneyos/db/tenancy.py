"""Per-user data isolation, enforced for every query.

Every session must say whose data it works with:

* ``session.info["user_id"] = <id>``: queries only ever see that user's rows
  of every ``Owned`` table, and new rows are stamped with that user;
* ``session.info["system"] = True``: unrestricted, for sign-in, migrations
  and admin commands only.

A session with neither refuses to query owned data. Forgetting a filter in
a service can therefore never leak another user's records: the filter is
added here, to every ORM statement, including lazy loads of relationships.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker, with_loader_criteria

from moneyos.db.tables import Base, Owned


class TenancyError(RuntimeError):
    """A session tried to touch owned data without saying whose."""


def _owned_classes() -> list[type]:
    return [m.class_ for m in Base.registry.mappers if issubclass(m.class_, Owned)]


def install(factory: sessionmaker[Session]) -> sessionmaker[Session]:
    owned = _owned_classes()

    @event.listens_for(factory, "do_orm_execute")
    def _restrict(state: ORMExecuteState) -> None:
        info = state.session.info
        if info.get("system"):
            return
        user_id = info.get("user_id")
        if user_id is None:
            raise TenancyError("this session has no user; set session.info['user_id'] (or 'system' for admin work)")
        if state.is_select or state.is_update or state.is_delete:
            # A plain expression, not a lambda: SQLAlchemy caches lambda
            # criteria and does not track default arguments, so a lambda
            # here would reuse the *first* user's id for everyone.
            state.statement = state.statement.options(*(
                with_loader_criteria(cls, cls.user_id == user_id, include_aliases=True)
                for cls in owned
            ))

    @event.listens_for(factory, "before_flush")
    def _stamp(session: Session, _context, _instances) -> None:
        if session.info.get("system"):
            return
        user_id = session.info.get("user_id")
        for obj in list(session.new) + list(session.dirty):
            if not isinstance(obj, Owned):
                continue
            if user_id is None:
                raise TenancyError("cannot save user data from a session with no user")
            if obj.user_id is None:
                obj.user_id = user_id
            elif obj.user_id != user_id:
                raise TenancyError("refusing to save a record that belongs to another user")

    return factory


def user_session(factory: sessionmaker[Session], user_id: int) -> Session:
    session = factory()
    session.info["user_id"] = user_id
    return session


def system_session(factory: sessionmaker[Session]) -> Session:
    session = factory()
    session.info["system"] = True
    return session
