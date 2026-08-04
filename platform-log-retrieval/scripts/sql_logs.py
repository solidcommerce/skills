#!/usr/bin/env python3
"""SQL Server log query for the Solid Commerce platform.

Queries the SCServicesLogs database (appslogs, weblogs tables) with
parameterized queries, NOLOCK hints, and TOP limits for production safety.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Optional

from _common import load_env

load_env()


def _get_connection():
    """Create a pymssql connection from env vars."""
    import pymssql

    server = os.environ.get("SC_LOGS_DB_SERVER", "")
    user = os.environ.get("SC_LOGS_DB_USER", "")
    password = os.environ.get("SC_LOGS_DB_PASSWORD", "")
    database = os.environ.get("SC_LOGS_DB_NAME", "")

    missing = []
    if not server:
        missing.append("SC_LOGS_DB_SERVER")
    if not user:
        missing.append("SC_LOGS_DB_USER")
    if not password:
        missing.append("SC_LOGS_DB_PASSWORD")
    if not database:
        missing.append("SC_LOGS_DB_NAME")

    if missing:
        print(json.dumps({
            "error": "Missing SQL Server credentials",
            "missing_vars": missing,
            "message": f"Set these environment variables in the .env file: {', '.join(missing)}",
        }), file=sys.stderr)
        sys.exit(1)

    try:
        conn = pymssql.connect(
            server=server,
            user=user,
            password=password,
            database=database,
            login_timeout=10,
            timeout=30,
        )
        return conn
    except pymssql.OperationalError as e:
        error_msg = str(e)
        if "Login failed" in error_msg or "18456" in error_msg:
            print(json.dumps({
                "error": "Authentication failed",
                "message": f"Login failed for user '{user}' on server '{server}'. Check SC_LOGS_DB_* env vars.",
            }), file=sys.stderr)
        else:
            print(json.dumps({
                "error": "SQL Server unreachable",
                "message": f"Could not connect to SQL Server at {server}: {error_msg}",
            }), file=sys.stderr)
        sys.exit(1)


def _validate_query(sql: str) -> None:
    """Ensure the query is a SELECT statement only."""
    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT"):
        raise ValueError("Only SELECT queries are permitted (read-only enforcement)")

    dangerous = ["INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ",
                 "TRUNCATE ", "EXEC ", "EXECUTE ", "MERGE "]
    for keyword in dangerous:
        if keyword in stripped:
            raise ValueError(f"Query contains forbidden keyword: {keyword.strip()}")


def _serialize_value(val: Any) -> Any:
    """Make a value JSON-serializable."""
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return val


def _query_appslogs(conn, company_id: Optional[int], application_id: Optional[int],
                    start_date: Optional[str], end_date: Optional[str],
                    level: Optional[str], keyword: Optional[str],
                    hostname: Optional[str], limit: int) -> dict:
    """Query the appslogs table."""
    start_time = time.time()

    # Clamp limit
    limit = max(1, min(limit, 1000))

    # Build query with parameterized filters
    columns = ("LogDateTime, Application, MessageType, ShortDescription, "
               "HostName, LongDescription, LogType, ThreadId, ThreadName, CompanyId")

    # embed validated limit directly (pymssql has issues parameterizing TOP)
    sql = f"SELECT TOP ({limit}) {columns} FROM appslogs WITH (NOLOCK) WHERE 1=1"
    params: list[Any] = []

    if company_id is not None:
        sql += " AND CompanyId = %s"
        params.append(company_id)
    if application_id is not None:
        sql += " AND Application = %s"
        params.append(application_id)
    if start_date:
        sql += " AND LogDateTime >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND LogDateTime <= %s"
        params.append(end_date)
    if level:
        sql += " AND (LogType = %s OR LogType = %s)"
        params.append(level)
        params.append(level.lower())
    if keyword:
        sql += " AND (ShortDescription LIKE %s OR LongDescription LIKE %s)"
        kw_pattern = f"%{keyword}%"
        params.append(kw_pattern)
        params.append(kw_pattern)
    if hostname:
        sql += " AND HostName = %s"
        params.append(hostname)

    sql += " ORDER BY LogDateTime DESC"

    _validate_query(sql)

    try:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            "metadata": {
                "source": "sql",
                "container_or_table": "appslogs",
                "query_filters": {
                    "company_id": company_id, "application_id": application_id,
                    "start_date": start_date, "end_date": end_date,
                    "level": level, "keyword": keyword, "hostname": hostname,
                },
                "total_results": 0, "truncated": False, "limit_used": limit,
                "query_time_ms": elapsed_ms, "error": str(e),
            },
            "entries": [],
        }

    entries = []
    for row in rows:
        (log_dt, application, msg_type, short_desc, host_name,
         long_desc, log_type, thread_id, thread_name, comp_id) = row

        # Normalize level from LogType or MessageType
        norm_level = log_type or {1: "Error", 2: "Warning", 3: "Info", 4: "Debug", 5: "Trace"}.get(msg_type, "unknown")

        entries.append({
            "source": "sql",
            "container_or_table": "appslogs",
            "timestamp": _serialize_value(log_dt),
            "level": norm_level,
            "service_name": str(application) if application else None,
            "server_name": host_name,
            "company_id": comp_id,
            "short_description": short_desc,
            "long_description": _serialize_value(long_desc),
            "request": None,
            "response": None,
            "thread_id": thread_id,
            "raw_line": None,
        })

    elapsed_ms = int((time.time() - start_time) * 1000)

    return {
        "metadata": {
            "source": "sql",
            "container_or_table": "appslogs",
            "query_filters": {
                "company_id": company_id, "application_id": application_id,
                "start_date": start_date, "end_date": end_date,
                "level": level, "keyword": keyword, "hostname": hostname,
            },
            "total_results": len(entries),
            "truncated": len(entries) >= limit,
            "limit_used": limit,
            "query_time_ms": elapsed_ms,
        },
        "entries": entries,
    }


def _query_weblogs(conn, company_id: Optional[int], application_id: Optional[int],
                   start_date: Optional[str], end_date: Optional[str],
                   keyword: Optional[str], hostname: Optional[str],
                   limit: int) -> dict:
    """Query the weblogs table."""
    start_time = time.time()

    limit = max(1, min(limit, 1000))

    columns = ("LogDateTime, ApplicationID, CallerIP, RequestedMethod, "
               "Notes, HostName, CompanyID, SeatID, DeveloperID")

    sql = f"SELECT TOP ({limit}) {columns} FROM weblogs WITH (NOLOCK) WHERE 1=1"
    params: list[Any] = []

    if company_id is not None:
        sql += " AND CompanyID = %s"
        params.append(company_id)
    if application_id is not None:
        sql += " AND ApplicationID = %s"
        params.append(application_id)
    if start_date:
        sql += " AND LogDateTime >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND LogDateTime <= %s"
        params.append(end_date)
    if keyword:
        sql += " AND (RequestedMethod LIKE %s OR Notes LIKE %s)"
        kw_pattern = f"%{keyword}%"
        params.append(kw_pattern)
        params.append(kw_pattern)
    if hostname:
        sql += " AND HostName = %s"
        params.append(hostname)

    sql += " ORDER BY LogDateTime DESC"

    _validate_query(sql)

    try:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            "metadata": {
                "source": "sql",
                "container_or_table": "weblogs",
                "query_filters": {
                    "company_id": company_id, "application_id": application_id,
                    "start_date": start_date, "end_date": end_date,
                    "keyword": keyword, "hostname": hostname,
                },
                "total_results": 0, "truncated": False, "limit_used": limit,
                "query_time_ms": elapsed_ms, "error": str(e),
            },
            "entries": [],
        }

    entries = []
    for row in rows:
        (log_dt, app_id, caller_ip, req_method,
         notes, host_name, comp_id, seat_id, dev_id) = row

        entries.append({
            "source": "sql",
            "container_or_table": "weblogs",
            "timestamp": _serialize_value(log_dt),
            "level": "Info",  # weblogs don't have log levels
            "service_name": str(app_id) if app_id else None,
            "server_name": host_name,
            "company_id": comp_id,
            "short_description": req_method,
            "long_description": notes,
            "request": None,
            "response": None,
            "thread_id": None,
            "raw_line": None,
            "caller_ip": caller_ip,
            "requested_method": req_method,
            "seat_id": seat_id,
            "developer_id": dev_id,
        })

    elapsed_ms = int((time.time() - start_time) * 1000)

    return {
        "metadata": {
            "source": "sql",
            "container_or_table": "weblogs",
            "query_filters": {
                "company_id": company_id, "application_id": application_id,
                "start_date": start_date, "end_date": end_date,
                "keyword": keyword, "hostname": hostname,
            },
            "total_results": len(entries),
            "truncated": len(entries) >= limit,
            "limit_used": limit,
            "query_time_ms": elapsed_ms,
        },
        "entries": entries,
    }


def _list_tables(conn) -> dict:
    """List available tables in SCServicesLogs."""
    start_time = time.time()
    sql = ("SELECT TOP (100) TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
           "WITH (NOLOCK) WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME")
    _validate_query(sql)

    cursor = conn.cursor()
    cursor.execute(sql)
    rows = cursor.fetchall()

    tables = [row[0] for row in rows]
    elapsed_ms = int((time.time() - start_time) * 1000)

    return {
        "database": os.environ.get("SC_LOGS_DB_NAME", "SCServicesLogs"),
        "tables": tables,
        "total_tables": len(tables),
        "query_time_ms": elapsed_ms,
    }


def _describe_table(conn, table_name: str) -> dict:
    """Show schema for a table."""
    start_time = time.time()

    # Validate table name (prevent injection via table name)
    if not table_name.isalnum() and not all(c.isalnum() or c == '_' for c in table_name):
        return {"error": f"Invalid table name: {table_name}"}

    sql = ("SELECT TOP (100) COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE "
           "FROM INFORMATION_SCHEMA.COLUMNS WITH (NOLOCK) "
           "WHERE TABLE_NAME = %s ORDER BY ORDINAL_POSITION")
    _validate_query(sql)

    cursor = conn.cursor()
    cursor.execute(sql, (table_name,))
    rows = cursor.fetchall()

    columns = []
    for row in rows:
        col_name, data_type, max_length, nullable = row
        columns.append({
            "column_name": col_name,
            "data_type": data_type,
            "max_length": max_length,
            "nullable": nullable,
        })

    elapsed_ms = int((time.time() - start_time) * 1000)

    return {
        "table": table_name,
        "columns": columns,
        "total_columns": len(columns),
        "query_time_ms": elapsed_ms,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query SCServicesLogs SQL Server database for structured log data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --table appslogs --company-id 12345 --start-date "2026-04-02 00:00:00" --level Error
  %(prog)s --table weblogs --company-id 12345 --keyword "GetOrder"
  %(prog)s --list-tables
  %(prog)s --table appslogs --describe
        """,
    )

    parser.add_argument("--table", type=str, choices=["appslogs", "weblogs"],
                        help="Table to query: appslogs or weblogs")
    parser.add_argument("--company-id", type=int, default=None,
                        help="Filter by CompanyId/CompanyID")
    parser.add_argument("--application-id", type=int, default=None,
                        help="Filter by Application/ApplicationID")
    parser.add_argument("--start-date", type=str, default=None,
                        help='Start datetime "YYYY-MM-DD HH:MM:SS"')
    parser.add_argument("--end-date", type=str, default=None,
                        help='End datetime "YYYY-MM-DD HH:MM:SS"')
    parser.add_argument("--level", type=str, default=None,
                        help="Log level filter (for appslogs)")
    parser.add_argument("--keyword", type=str, default=None,
                        help="Search text in descriptions")
    parser.add_argument("--hostname", type=str, default=None,
                        help="Filter by HostName")
    parser.add_argument("--limit", type=int, default=100,
                        help="Max rows 1-1000 (default: 100)")
    parser.add_argument("--list-tables", action="store_true",
                        help="List available tables in SCServicesLogs")
    parser.add_argument("--describe", action="store_true",
                        help="Show table schema (requires --table)")

    args = parser.parse_args()

    if not args.table and not args.list_tables:
        parser.error("Either --table or --list-tables is required")

    conn = None
    try:
        conn = _get_connection()

        if args.list_tables:
            result = _list_tables(conn)
            json.dump(result, sys.stdout, indent=2)
            print()
            sys.exit(0)

        if args.describe:
            if not args.table:
                parser.error("--describe requires --table")
            result = _describe_table(conn, args.table)
            json.dump(result, sys.stdout, indent=2)
            print()
            sys.exit(0)

        if args.table == "appslogs":
            result = _query_appslogs(
                conn,
                company_id=args.company_id,
                application_id=args.application_id,
                start_date=args.start_date,
                end_date=args.end_date,
                level=args.level,
                keyword=args.keyword,
                hostname=args.hostname,
                limit=args.limit,
            )
        elif args.table == "weblogs":
            result = _query_weblogs(
                conn,
                company_id=args.company_id,
                application_id=args.application_id,
                start_date=args.start_date,
                end_date=args.end_date,
                keyword=args.keyword,
                hostname=args.hostname,
                limit=args.limit,
            )
        else:
            parser.error(f"Unknown table: {args.table}")
            return  # unreachable, for type checker

        json.dump(result, sys.stdout, indent=2)
        print()

        if result["metadata"].get("error"):
            sys.exit(1)
        sys.exit(0)

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
