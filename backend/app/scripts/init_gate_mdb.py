from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pyodbc


DEFAULT_ACCESS_POINTS: list[tuple[int, str]] = [
    (1, "entry"),
    (2, "exit"),
    (3, "wicket_north"),
    (4, "wicket_lake"),
    (5, "wicket_admin"),
    (6, "wicket_forest"),
]


def _escape_ps(value: str) -> str:
    return value.replace("'", "''")


def create_mdb_file(path: Path, force: bool) -> None:
    if path.exists() and not force:
        return

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    script = f"""
$ErrorActionPreference = 'Stop'
$path = '{_escape_ps(str(path))}'
if (Test-Path -LiteralPath $path) {{
  Remove-Item -LiteralPath $path -Force
}}
$catalog = New-Object -ComObject ADOX.Catalog
$null = $catalog.Create("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$path;Jet OLEDB:Engine Type=5")
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)


def connect(path: Path) -> pyodbc.Connection:
    conn_str = f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={path}"
    return pyodbc.connect(conn_str)


def table_exists(cursor: pyodbc.Cursor, name: str) -> bool:
    row = cursor.tables(table=name, tableType="TABLE").fetchone()
    return row is not None


def ensure_schema(path: Path) -> None:
    with connect(path) as conn:
        cursor = conn.cursor()

        if not table_exists(cursor, "Users"):
            cursor.execute(
                """
                CREATE TABLE Users (
                    id AUTOINCREMENT PRIMARY KEY,
                    last_name TEXT(100),
                    first_name TEXT(100),
                    is_visitor YESNO,
                    created_at DATETIME
                )
                """
            )

        if not table_exists(cursor, "Keys"):
            cursor.execute(
                """
                CREATE TABLE Keys (
                    id AUTOINCREMENT PRIMARY KEY,
                    user_id INTEGER,
                    key_type TEXT(50),
                    key_value TEXT(64),
                    valid_from DATETIME,
                    valid_to DATETIME,
                    is_blocked YESNO
                )
                """
            )
            cursor.execute("CREATE UNIQUE INDEX idx_keys_type_value ON Keys (key_type, key_value)")

        if not table_exists(cursor, "AccessPoints"):
            cursor.execute(
                """
                CREATE TABLE AccessPoints (
                    id AUTOINCREMENT PRIMARY KEY,
                    name TEXT(255)
                )
                """
            )

        if not table_exists(cursor, "AccessPermissions"):
            cursor.execute(
                """
                CREATE TABLE AccessPermissions (
                    id AUTOINCREMENT PRIMARY KEY,
                    user_id INTEGER,
                    access_point_id INTEGER,
                    is_permanent YESNO
                )
                """
            )
            cursor.execute("CREATE UNIQUE INDEX idx_perm_user_access ON AccessPermissions (user_id, access_point_id)")

        for point_id, name in DEFAULT_ACCESS_POINTS:
            cursor.execute("SELECT id FROM AccessPoints WHERE id = ?", (point_id,))
            if cursor.fetchone() is None:
                cursor.execute("INSERT INTO AccessPoints (id, name) VALUES (?, ?)", (point_id, name))

        conn.commit()


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[3]
    default_path = repo_root / "config.mdb"

    parser = argparse.ArgumentParser(description="Create and initialize Gate config.mdb for local testing.")
    parser.add_argument("--path", type=Path, default=default_path, help=f"Target .mdb path (default: {default_path})")
    parser.add_argument("--force", action="store_true", help="Recreate database file if it already exists.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = args.path.resolve()

    create_mdb_file(db_path, force=args.force)
    ensure_schema(db_path)
    print(f"Gate MDB initialized: {db_path}")


if __name__ == "__main__":
    main()
