"""Budget storage and monthly utilisation."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moneyos.db.tables import AuditEvent, Budget, TransactionRecord
from moneyos.domain.budgets import BudgetUse, budget_use
from moneyos.domain.models import Status, TxnType
from moneyos.domain.money import from_minor, to_minor
from moneyos.services.errors import InvalidRequestError, NotFoundError


def list_budgets(session: Session) -> list[Budget]:
    return list(session.scalars(select(Budget).order_by(Budget.currency, Budget.category)))


def set_budget(session: Session, category: str, currency: str, limit: Decimal) -> Budget:
    """Create or replace the monthly limit for a category."""
    currency = currency.upper()
    if limit <= 0:
        raise InvalidRequestError("the monthly limit must be positive")
    try:
        minor = to_minor(limit, currency)
    except ValueError as error:
        raise InvalidRequestError(str(error)) from None
    budget = session.scalar(select(Budget).where(Budget.category == category, Budget.currency == currency))
    previous = None
    if budget is None:
        budget = Budget(category=category, currency=currency, limit_minor=minor)
        session.add(budget)
    else:
        previous = str(from_minor(budget.limit_minor, currency))
        budget.limit_minor = minor
    session.flush()
    session.add(
        AuditEvent(actor="user", action="budget_set", entity_type="budget", entity_id=budget.id,
                   details={"category": category, "currency": currency, "limit": str(limit), "previous": previous})
    )
    session.commit()
    return budget


def delete_budget(session: Session, budget_id: int) -> None:
    budget = session.get(Budget, budget_id)
    if budget is None:
        raise NotFoundError(f"budget {budget_id} not found")
    session.add(
        AuditEvent(actor="user", action="budget_deleted", entity_type="budget", entity_id=budget.id,
                   details={"category": budget.category, "currency": budget.currency,
                            "limit": str(from_minor(budget.limit_minor, budget.currency))})
    )
    session.delete(budget)
    session.commit()


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def spent_in_month(session: Session, category: str, currency: str, year: int, month: int) -> Decimal:
    """Purchases minus refunds in a category; failed payments and confirmed duplicates excluded."""
    start, end = month_bounds(year, month)

    def total(txn_type: TxnType) -> int:
        return session.scalar(
            select(func.coalesce(func.sum(TransactionRecord.amount_minor), 0)).where(
                TransactionRecord.category == category,
                TransactionRecord.currency == currency,
                TransactionRecord.txn_type == txn_type.value,
                TransactionRecord.status != Status.FAILED.value,
                TransactionRecord.duplicate_of_id.is_(None),
                TransactionRecord.occurred_on.between(start, end),
            )
        )

    return from_minor(int(total(TxnType.EXPENSE) - total(TxnType.REFUND)), currency)


def utilisation(session: Session, year: int, month: int, as_of: date | None = None) -> list[BudgetUse]:
    as_of = as_of or date.today()
    return [
        budget_use(
            b.category,
            b.currency,
            from_minor(b.limit_minor, b.currency),
            spent_in_month(session, b.category, b.currency, year, month),
            (year, month),
            as_of,
        )
        for b in list_budgets(session)
    ]
