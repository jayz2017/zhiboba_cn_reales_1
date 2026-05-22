from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class SqlAsset:
    name: str
    relative_path: str

    def read_text(self, base_dir: Path) -> str:
        path = base_dir / self.relative_path
        return path.read_text(encoding="utf-8")


DDL_ASSETS: tuple[SqlAsset, ...] = (
    SqlAsset(name="init_schema", relative_path="app/db/ddl/001_init_schema.sql"),
)

DML_INSERT_ASSETS: tuple[SqlAsset, ...] = (
    SqlAsset(name="seed_data", relative_path="app/db/dml/inserts/001_seed.sql"),
)


def apply_sql_assets(engine: Engine, base_dir: Path, assets: tuple[SqlAsset, ...]) -> None:
    sql_statements: list[str] = []
    for asset in assets:
        content = asset.read_text(base_dir=base_dir).strip()
        if content:
            sql_statements.append(content)

    if not sql_statements:
        return

    with engine.begin() as conn:
        for sql in sql_statements:
            conn.execute(text(sql))


def apply_ddl(engine: Engine, base_dir: Path) -> None:
    apply_sql_assets(engine=engine, base_dir=base_dir, assets=DDL_ASSETS)


def apply_inserts(engine: Engine, base_dir: Path) -> None:
    apply_sql_assets(engine=engine, base_dir=base_dir, assets=DML_INSERT_ASSETS)
