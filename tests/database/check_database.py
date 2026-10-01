"""
Smoke-check connectivity to the configured PostgreSQL/PostGIS database.

Usage: python tests/database/check_database.py [--quiet] [--database-url DATABASE_URL]

"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


def _connection_failure(error: SQLAlchemyError, database: str, username: str) -> tuple[str, str]:
    original_error = getattr(error, "orig", error)
    sqlstate = getattr(original_error, "sqlstate", None) or getattr(
        original_error, "pgcode", None
    )

    if sqlstate == "3D000":
        return "database", f"Database {database!r} does not exist."
    if sqlstate in {"28P01", "28000"}:
        return "user", (
            f"User {username!r} could not authenticate. Check that the role exists, "
            "can log in, and has the configured password."
        )
    if sqlstate is None:
        return "server", "PostgreSQL is not running or is unreachable at the configured host and port."
    return "connection", f"PostgreSQL rejected the connection (SQLSTATE {sqlstate})."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress success output for non-interactive use; failures still go to stderr",
    )
    args = parser.parse_args()

    def report_success(message: str) -> None:
        if not args.quiet:
            print(message)

    repository_root = Path(__file__).resolve().parents[2]
    load_dotenv(repository_root / ".env")
    load_dotenv(repository_root / "server" / ".env", override=False)
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "Database check failed: DATABASE_URL is not set. Add it to the "
            "repository .env or server/.env, or pass --database-url.",
            file=sys.stderr,
        )
        return 2

    try:
        engine = create_engine(database_url)
    except SQLAlchemyError as error:
        print(f"Database check failed at [DATABASE_URL]: {error}", file=sys.stderr)
        return 1

    try:
        try:
            connection = engine.connect()
        except SQLAlchemyError as error:
            stage, message = _connection_failure(
                error,
                engine.url.database or "<unspecified>",
                engine.url.username or "<unspecified>",
            )
            if stage != "server":
                report_success("[OK] PostgreSQL server is running and reachable.")
            print(f"Database check failed at [{stage}]: {message}", file=sys.stderr)
            return 1

        with connection:
            identity = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            report_success("[OK] PostgreSQL server is running and reachable.")
            report_success(f"[OK] Database {identity[0]!r} exists.")
            report_success(f"[OK] User {identity[1]!r} can connect.")

            try:
                postgis = connection.execute(
                    text("""
                        SELECT extension.extversion, namespace.nspname
                        FROM pg_extension AS extension
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = extension.extnamespace
                        WHERE extension.extname = 'postgis'
                    """)
                ).first()
            except SQLAlchemyError as error:
                print(f"Database check failed at [PostGIS]: {error}", file=sys.stderr)
                return 1
            if postgis is None:
                print(
                    "Database check failed at [PostGIS]: extension is not installed "
                    "in this database.",
                    file=sys.stderr,
                )
                return 1

            quoted_schema = connection.dialect.identifier_preparer.quote_schema(postgis[1])
            try:
                postgis_version = connection.exec_driver_sql(
                    f"SELECT {quoted_schema}.PostGIS_Full_Version()"
                ).scalar_one()
            except SQLAlchemyError as error:
                print(f"Database check failed at [PostGIS]: {error}", file=sys.stderr)
                return 1
            report_success(f"[OK] PostGIS extension is active (version {postgis[0]}).")

            try:
                xrs_table = connection.execute(
                    text("""
                        SELECT relation.oid::regclass
                        FROM pg_class AS relation
                        WHERE relation.oid = to_regclass('xrs')
                          AND relation.relkind IN ('r', 'p')
                    """)
                ).scalar_one_or_none()
            except SQLAlchemyError as error:
                print(f"Database check failed at [xrs table]: {error}", file=sys.stderr)
                return 1
            if xrs_table is None:
                print(
                    "Database check failed at [xrs table]: relation 'xrs' was not "
                    "found in the database search path.",
                    file=sys.stderr,
                )
                return 1
            report_success(f"[OK] xrs table exists ({xrs_table}).")
            report_success(f"Database check passed: {postgis_version}")
            return 0
    except SQLAlchemyError as error:
        print(f"Database check failed while querying the connected database: {error}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())