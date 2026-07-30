"""Tiny additive migration — runs at every startup.

`Base.metadata.create_all()` creates *new tables* but never adds *new columns*
to tables that already exist. This helper compares the live database with the
models and issues `ALTER TABLE … ADD COLUMN` for anything missing, so
upgrading the app never requires wiping the database. Works on SQLite and
PostgreSQL. (Only additions — nothing is ever dropped.)
"""
import logging

from sqlalchemy import inspect, text

from app.database import Base, engine

logger = logging.getLogger(__name__)

_TYPE_DEFAULTS = {
    "VARCHAR": "VARCHAR(255)",
}


def _column_ddl(column) -> str:
    coltype = column.type.compile(engine.dialect)
    ddl = f'"{column.name}" {coltype}'
    # Keep it simple and portable: new columns are added as nullable; the ORM
    # fills sensible values for new rows via its Python-side defaults.
    default = column.default.arg if (
        column.default is not None and getattr(column.default, "is_scalar", False)
    ) else None
    if default is not None:
        if isinstance(default, bool):
            ddl += " DEFAULT 1" if default else " DEFAULT 0"
        elif isinstance(default, (int, float)):
            ddl += f" DEFAULT {default}"
        elif isinstance(default, str):
            escaped = default.replace("'", "''")
            ddl += f" DEFAULT '{escaped}'"
    return ddl


def run_additive_migration():
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all will create it
            existing_cols = {c["name"] for c in insp.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                ddl = _column_ddl(column)
                try:
                    conn.execute(text(
                        f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}'))
                    logger.info("Migration: added %s.%s", table.name, column.name)
                except Exception as e:  # pragma: no cover
                    logger.warning("Migration skipped %s.%s: %s",
                                   table.name, column.name, e)


def ensure_receipt_indexes():
    """Enforce receipt-number uniqueness at the database level as a final
    backstop against races (two admins approving at the same instant).

    Uses PARTIAL unique indexes (only where receipt_number <> '') so the many
    empty-string defaults on unpaid rows don't collide. Supported by both
    SQLite (3.8+) and PostgreSQL.
    """
    stmts = [
        # One payment == one receipt number. The payments table is the
        # authoritative ledger, so uniqueness is enforced here. Installments
        # only keep a convenience copy of their latest receipt, so they are
        # intentionally NOT uniquely constrained (a single recorded payment can
        # span several installments and legitimately share its receipt number).
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_receipt_no "
        "ON payments (receipt_number) WHERE receipt_number <> ''",
    ]
    with engine.begin() as conn:
        for s in stmts:
            try:
                conn.execute(text(s))
            except Exception as e:  # pragma: no cover
                logger.warning("Receipt index skipped: %s", e)


def map_legacy_values():
    """One-time value fixes when upgrading from the previous version."""
    with engine.begin() as conn:
        try:
            conn.execute(text(
                "UPDATE applications SET payment_status='fully_paid' "
                "WHERE payment_status='verified'"))
            conn.execute(text(
                "UPDATE applications SET payment_status='partially_paid' "
                "WHERE payment_status='paid'"))
        except Exception as e:  # pragma: no cover
            logger.warning("Legacy value mapping skipped: %s", e)
        # Backfill Roll Numbers for students created before this field existed,
        # so existing data keeps a unique primary identifier.
        try:
            rows = conn.execute(text(
                "SELECT id FROM students WHERE roll_number IS NULL "
                "OR roll_number=''")).fetchall()
            for (sid,) in rows:
                conn.execute(text(
                    "UPDATE students SET roll_number=:r WHERE id=:i"),
                    {"r": f"R-{sid:05d}", "i": sid})
            if rows:
                logger.info("Backfilled %d student roll number(s).", len(rows))
        except Exception as e:  # pragma: no cover
            logger.warning("Roll-number backfill skipped: %s", e)

        # Backfill campus for Payments and PaymentAllocations
        try:
            conn.execute(text("""
                UPDATE payments
                SET campus = (
                    SELECT CASE
                        WHEN a.transferred_from IS NOT NULL AND a.transferred_from != '' THEN a.transferred_from
                        ELSE a.campus
                    END
                    FROM applications a WHERE a.id = payments.application_id
                )
                WHERE campus IS NULL OR campus = ''
            """))
            conn.execute(text("""
                UPDATE payment_allocations
                SET campus = (
                    SELECT CASE
                        WHEN a.transferred_from IS NOT NULL AND a.transferred_from != '' THEN a.transferred_from
                        ELSE a.campus
                    END
                    FROM applications a WHERE a.id = payment_allocations.application_id
                )
                WHERE campus IS NULL OR campus = ''
            """))
        except Exception as e:  # pragma: no cover
            logger.warning("Payment campus backfill skipped: %s", e)
