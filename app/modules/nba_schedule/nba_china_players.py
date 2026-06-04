from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.http_resources import NBA_CHINA_PLAYERS_LIST_URL, build_nba_china_pbp_headers
from app.modules.nba_live_text.nba_china_livetext import (
    NBA_CHINA_DEFAULT_APP_KEY,
    NBA_CHINA_DEFAULT_APP_VERSION,
    NBA_CHINA_DEFAULT_CHANNEL,
    NBA_CHINA_DEFAULT_DEVICE_ID,
    NBA_CHINA_DEFAULT_INSTALL_ID,
    NBA_CHINA_DEFAULT_SIGN2,
)
from app.modules.nba_schedule.zhiboba_team_players import ensure_players_table
from app.utils.http.client import HttpClient


logger = logging.getLogger(__name__)

NBA_CHINA_PLAYERS_DEFAULT_PAGE_SIZE = 50


@dataclass(frozen=True)
class NbaChinaPlayerRecord:
    player_id: str
    player_code: str
    nba_player_name: str | None
    en_player_name: str | None
    nba_jersey_number: str | None
    team_name: str | None
    raw_json: str


@dataclass(frozen=True)
class NbaChinaPagination:
    total: int | None
    page_no: int | None
    page_size: int | None


@dataclass(frozen=True)
class NbaChinaPlayersPageResult:
    records: list[NbaChinaPlayerRecord]
    pagination: NbaChinaPagination
    source_rows: int
    skipped_without_player_code: int


@dataclass(frozen=True)
class NbaChinaPlayersFetchResult:
    records: list[NbaChinaPlayerRecord]
    pages: int
    total_count: int | None
    source_rows: int
    skipped_without_player_code: int


def normalize_player_code(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().lower()
    cleaned = re.sub(r"^tmp_", "", cleaned)
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "", cleaned)
    return cleaned or None


def _strip_tmp_prefix(player_code: str | None) -> str | None:
    if not player_code:
        return None
    stripped = player_code.strip().lower()
    stripped = re.sub(r"^tmp_", "", stripped)
    stripped = re.sub(r"[^0-9a-zA-Z]+", "", stripped)
    return stripped or None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _pick_str(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _clean_str(data.get(key))
        if value:
            return value
    return None


def _build_player_name(item: dict[str, Any]) -> str | None:
    first_name = _pick_str(item, "firstName", "firstNameCn", "fn")
    last_name = _pick_str(item, "lastName", "lastNameCn", "ln")
    if first_name and last_name:
        return f"{first_name}{last_name}"
    if first_name or last_name:
        return first_name or last_name

    full_name = _pick_str(
        item,
        "name",
        "playerName",
        "displayName",
        "displayNameCn",
        "playerNameCn",
        "nameCn",
    )
    if full_name:
        return full_name
    return None


def _build_en_player_name(item: dict[str, Any]) -> str | None:
    last_name = _pick_str(item, "lastNameEn", "lastName", "ln")
    first_name = _pick_str(item, "firstNameEn", "firstName", "fn")
    if last_name and first_name:
        return f"{last_name} {first_name}"
    if last_name or first_name:
        return last_name or first_name
    return _pick_str(item, "displayName", "nameEn", "playerNameEn")


def build_nba_china_players_params(
    *,
    page_no: int,
    page_size: int = NBA_CHINA_PLAYERS_DEFAULT_PAGE_SIZE,
    timestamp: int | None = None,
    sign2: str = NBA_CHINA_DEFAULT_SIGN2,
) -> dict[str, str | list[str]]:
    return {
        "app_key": NBA_CHINA_DEFAULT_APP_KEY,
        "app_version": NBA_CHINA_DEFAULT_APP_VERSION,
        "channel": NBA_CHINA_DEFAULT_CHANNEL,
        "country": "",
        "device_id": NBA_CHINA_DEFAULT_DEVICE_ID,
        "firstName": "",
        "individual": "",
        "install_id": NBA_CHINA_DEFAULT_INSTALL_ID,
        "network": "N/A",
        "os_type": "3",
        "os_version": "1.0.0",
        "page_no": str(max(1, int(page_no))),
        "page_size": str(max(1, int(page_size))),
        "position": "",
        "retireStat": "A",
        "sign": "sign_v2",
        "sign2": sign2,
        "startYearRange": ["", ""],
        "t": str(int(timestamp if timestamp is not None else time.time())),
        "teamId": "",
    }


def _find_first_list(value: Any, keys: tuple[str, ...] = ("players", "list", "items", "records")) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        for key in keys:
            nested = value.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        for nested in value.values():
            found = _find_first_list(nested, keys)
            if found:
                return found
    elif isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _find_first_int(value: Any, keys: tuple[str, ...]) -> int | None:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            parsed = _to_int(candidate)
            if parsed is not None:
                return parsed
        for nested in value.values():
            found = _find_first_int(nested, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_first_int(item, keys)
            if found is not None:
                return found
    return None


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _extract_nba_china_pagination(payload: Any) -> NbaChinaPagination:
    if isinstance(payload, dict):
        pagination = payload.get("pagination")
        if isinstance(pagination, dict):
            return NbaChinaPagination(
                total=_to_int(pagination.get("total")),
                page_no=_to_int(pagination.get("page_no")),
                page_size=_to_int(pagination.get("page_size")),
            )
    return NbaChinaPagination(
        total=_find_first_int(payload, ("total", "totalCount", "total_count", "count", "recordCount")),
        page_no=_find_first_int(payload, ("page_no", "pageNo", "page")),
        page_size=_find_first_int(payload, ("page_size", "pageSize", "size")),
    )


def parse_nba_china_players_page_payload(payload: Any) -> NbaChinaPlayersPageResult:
    rows = _find_first_list(payload)
    pagination = _extract_nba_china_pagination(payload)

    records: list[NbaChinaPlayerRecord] = []
    skipped_without_player_code = 0
    for item in rows:
        player_id = _pick_str(item, "playerId", "player_id", "personId", "pid")
        player_code = _pick_str(item, "playerCode", "player_code", "code")
        if not player_id or not player_code:
            if player_id and not player_code:
                skipped_without_player_code += 1
            continue

        records.append(
            NbaChinaPlayerRecord(
                player_id=player_id,
                player_code=player_code,
                nba_player_name=_build_player_name(item),
                en_player_name=_build_en_player_name(item),
                nba_jersey_number=_pick_str(item, "jerseyNo", "jersey", "jerseyNumber", "shirtNo"),
                team_name=_pick_str(item, "teamName", "team_name", "teamNameCn"),
                raw_json=json.dumps(item, ensure_ascii=False),
            )
        )
    return NbaChinaPlayersPageResult(
        records=records,
        pagination=pagination,
        source_rows=len(rows),
        skipped_without_player_code=skipped_without_player_code,
    )


def parse_nba_china_players_payload(payload: Any) -> tuple[list[NbaChinaPlayerRecord], int | None]:
    page_result = parse_nba_china_players_page_payload(payload)
    return page_result.records, page_result.pagination.total


def fetch_nba_china_players_page(
    http_client: HttpClient,
    *,
    page_no: int,
    page_size: int = NBA_CHINA_PLAYERS_DEFAULT_PAGE_SIZE,
    sign2: str = NBA_CHINA_DEFAULT_SIGN2,
) -> NbaChinaPlayersPageResult:
    payload = http_client.get_json(
        NBA_CHINA_PLAYERS_LIST_URL,
        params=build_nba_china_players_params(page_no=page_no, page_size=page_size, sign2=sign2),
        headers=build_nba_china_pbp_headers(),
    )
    return parse_nba_china_players_page_payload(payload)


def fetch_nba_china_player_records(
    http_client: HttpClient,
    *,
    page_size: int = NBA_CHINA_PLAYERS_DEFAULT_PAGE_SIZE,
    max_pages: int = 200,
    sign2: str = NBA_CHINA_DEFAULT_SIGN2,
) -> NbaChinaPlayersFetchResult:
    page_no = 1
    request_page_size = max(1, int(page_size))
    requested_pages = 0
    all_records: list[NbaChinaPlayerRecord] = []
    total_count: int | None = None
    source_rows = 0
    skipped_without_player_code = 0
    while page_no <= max(1, int(max_pages)):
        page_result = fetch_nba_china_players_page(
            http_client=http_client,
            page_no=page_no,
            page_size=request_page_size,
            sign2=sign2,
        )
        requested_pages += 1
        source_rows += page_result.source_rows
        skipped_without_player_code += page_result.skipped_without_player_code
        if page_result.pagination.total is not None:
            total_count = page_result.pagination.total
        if page_result.source_rows == 0:
            break

        all_records.extend(page_result.records)
        response_page_no = page_result.pagination.page_no or page_no
        response_page_size = page_result.pagination.page_size or request_page_size
        if total_count is not None:
            total_pages = math.ceil(total_count / max(1, response_page_size))
            if response_page_no >= total_pages:
                break
        elif page_result.source_rows < request_page_size:
            break
        request_page_size = response_page_size
        page_no = response_page_no + 1

    return NbaChinaPlayersFetchResult(
        records=all_records,
        pages=requested_pages,
        total_count=total_count,
        source_rows=source_rows,
        skipped_without_player_code=skipped_without_player_code,
    )


def ensure_nba_china_player_columns(db: Session) -> None:
    ensure_players_table(db=db)
    required_columns = {
        "player_id": "ALTER TABLE nba_players_name_data ADD COLUMN player_id VARCHAR(50) NULL AFTER team_name",
        "nba_player_name": "ALTER TABLE nba_players_name_data ADD COLUMN nba_player_name VARCHAR(128) NULL AFTER en_player_name",
        "nba_jersey_number": "ALTER TABLE nba_players_name_data ADD COLUMN nba_jersey_number VARCHAR(16) NULL AFTER player_name_alias",
        "player_code": "ALTER TABLE nba_players_name_data ADD COLUMN player_code VARCHAR(50) NULL AFTER zhiboba_jersey_number",
        "team_name": "ALTER TABLE nba_players_name_data ADD COLUMN team_name VARCHAR(50) NULL AFTER team_id",
    }
    for column_name, alter_sql in required_columns.items():
        if not _column_exists(db, table_name="nba_players_name_data", column_name=column_name):
            db.execute(text(alter_sql))

    if not _index_exists(db, table_name="nba_players_name_data", index_name="idx_nba_player_code"):
        db.execute(text("ALTER TABLE nba_players_name_data ADD KEY idx_nba_player_code (player_code)"))
    db.commit()


def _column_exists(db: Session, *, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND COLUMN_NAME = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).fetchone()
    return row is not None


def _index_exists(db: Session, *, table_name: str, index_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND INDEX_NAME = :index_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "index_name": index_name},
    ).fetchone()
    return row is not None


def load_existing_player_code_map(db: Session) -> dict[str, int]:
    rows = db.execute(
        text(
            """
            SELECT id, player_code
            FROM nba_players_name_data
            WHERE player_code IS NOT NULL
              AND TRIM(player_code) <> ''
            """
        )
    ).fetchall()

    result: dict[str, int] = {}
    for row in rows:
        normalized_code = normalize_player_code(getattr(row, "player_code", None))
        row_id = getattr(row, "id", None)
        if normalized_code and isinstance(row_id, int):
            result.setdefault(normalized_code, row_id)
    return result


def _normalize_team_jersey_key(team_name: Any, jersey_number: Any) -> tuple[str, str] | None:
    team = _clean_str(team_name)
    jersey = _clean_str(jersey_number)
    if not team or not jersey:
        return None
    return team.lower(), jersey.lower()


def load_existing_team_jersey_map(db: Session) -> dict[tuple[str, str], int]:
    rows = db.execute(
        text(
            """
            SELECT id, team_name, nba_jersey_number, zhiboba_jersey_number
            FROM nba_players_name_data
            WHERE team_name IS NOT NULL
              AND TRIM(team_name) <> ''
              AND (
                (nba_jersey_number IS NOT NULL AND TRIM(nba_jersey_number) <> '')
                OR
                (zhiboba_jersey_number IS NOT NULL AND TRIM(zhiboba_jersey_number) <> '')
              )
            """
        )
    ).fetchall()

    result: dict[tuple[str, str], int] = {}
    for row in rows:
        row_id = getattr(row, "id", None)
        if not isinstance(row_id, int):
            continue
        for jersey_column in ("nba_jersey_number", "zhiboba_jersey_number"):
            key = _normalize_team_jersey_key(
                getattr(row, "team_name", None),
                getattr(row, jersey_column, None),
            )
            if key:
                result.setdefault(key, row_id)
    return result


def upsert_nba_china_player_records(db: Session, records: list[NbaChinaPlayerRecord]) -> dict[str, int]:
    if not records:
        return {
            "upserted": 0,
            "updated": 0,
            "inserted": 0,
            "matched_by_player_code": 0,
            "matched_by_team_jersey": 0,
        }

    existing_by_code = load_existing_player_code_map(db=db)
    existing_by_team_jersey = load_existing_team_jersey_map(db=db)
    updated = 0
    inserted = 0
    matched_by_player_code = 0
    matched_by_team_jersey_count = 0
    for record in records:
        normalized_code = normalize_player_code(record.player_code)
        existing_id = existing_by_code.get(normalized_code or "")
        used_team_jersey_match = False
        match_method = "player_code"
        if existing_id is not None:
            matched_by_player_code += 1
        else:
            cleaned_code = _strip_tmp_prefix(record.player_code)
            if cleaned_code and cleaned_code != normalized_code:
                existing_id = existing_by_code.get(cleaned_code)
                if existing_id is not None:
                    matched_by_player_code += 1
                    match_method = "player_code(tmp_stripped)"
                    logger.info(
                        "tmp_prefix_stripped player_code=%s -> normalized=%s matched_id=%s",
                        record.player_code, cleaned_code, existing_id,
                    )

        if existing_id is None:
            team_jersey_key = _normalize_team_jersey_key(record.team_name, record.nba_jersey_number)
            existing_id = existing_by_team_jersey.get(team_jersey_key) if team_jersey_key else None
            if existing_id is not None:
                used_team_jersey_match = True
                match_method = "team_jersey"
                logger.info(
                    "team_jersey_fallback player_code=%s team=%s jersey=%s matched_id=%s",
                    record.player_code, record.team_name, record.nba_jersey_number, existing_id,
                )

        if existing_id is not None:
            _update_existing_player(db=db, row_id=existing_id, record=record)
            updated += 1
            if used_team_jersey_match:
                matched_by_team_jersey_count += 1
            _remember_existing_record(
                existing_by_code=existing_by_code,
                existing_by_team_jersey=existing_by_team_jersey,
                record=record,
                row_id=existing_id,
            )
            continue

        _log_unmatched_player(record=record, normalized_code=normalized_code, db=db)
        _insert_new_player(db=db, record=record)
        inserted += 1
        new_id = db.execute(text("SELECT LAST_INSERT_ID() AS id")).fetchone()
        inserted_id = getattr(new_id, "id", None)
        if isinstance(inserted_id, int):
            _remember_existing_record(
                existing_by_code=existing_by_code,
                existing_by_team_jersey=existing_by_team_jersey,
                record=record,
                row_id=inserted_id,
            )

    db.commit()
    return {
        "upserted": updated + inserted,
        "updated": updated,
        "inserted": inserted,
        "matched_by_player_code": matched_by_player_code,
        "matched_by_team_jersey": matched_by_team_jersey_count,
    }


def _remember_existing_record(
    *,
    existing_by_code: dict[str, int],
    existing_by_team_jersey: dict[tuple[str, str], int],
    record: NbaChinaPlayerRecord,
    row_id: int,
) -> None:
    normalized_code = normalize_player_code(record.player_code)
    if normalized_code:
        existing_by_code.setdefault(normalized_code, row_id)
    team_jersey_key = _normalize_team_jersey_key(record.team_name, record.nba_jersey_number)
    if team_jersey_key:
        existing_by_team_jersey.setdefault(team_jersey_key, row_id)


def find_unmatched_nba_china_player_records(
    db: Session,
    records: list[NbaChinaPlayerRecord],
) -> tuple[int, list[NbaChinaPlayerRecord]]:
    existing_by_code = load_existing_player_code_map(db=db)
    existing_by_team_jersey = load_existing_team_jersey_map(db=db)
    matched = 0
    unmatched: list[NbaChinaPlayerRecord] = []
    for record in records:
        normalized_code = normalize_player_code(record.player_code)
        team_jersey_key = _normalize_team_jersey_key(record.team_name, record.nba_jersey_number)
        code_matched = existing_by_code.get(normalized_code or "") is not None
        if not code_matched:
            cleaned_code = _strip_tmp_prefix(record.player_code)
            if cleaned_code and cleaned_code != normalized_code:
                code_matched = existing_by_code.get(cleaned_code) is not None
        jersey_matched = team_jersey_key and existing_by_team_jersey.get(team_jersey_key) is not None
        if not code_matched and not jersey_matched:
            unmatched.append(record)
        else:
            matched += 1
    return matched, unmatched


def _log_unmatched_player(
    record: NbaChinaPlayerRecord,
    normalized_code: str | None,
    *,
    db: Session | None = None,
) -> None:
    reasons: list[str] = []
    if not normalized_code:
        reasons.append("normalized_code为空(player_code无法规范化)")
    elif db is not None:
        code_variants = _generate_code_variants(record.player_code)
        for variant in code_variants:
            normalized_variant = normalize_player_code(variant)
            if normalized_variant and normalized_variant != normalized_code:
                match_row = db.execute(
                    text(
                        "SELECT id, player_code FROM nba_players_name_data "
                        "WHERE LOWER(REPLACE(REPLACE(REPLACE(player_code, '.', ''), '-', ''), '_', '')) = :nc "
                        "LIMIT 1"
                    ),
                    {"nc": normalized_variant},
                ).fetchone()
                if match_row:
                    reasons.append(
                        f"变体'{variant}'匹配到id={getattr(match_row, 'id')}但主码'{normalized_code}'未匹配"
                    )
                    break

        if not reasons:
            name_like = f"%{record.nba_player_name}%" if record.nba_player_name else None
            if name_like:
                name_row = db.execute(
                    text(
                        "SELECT id, zhiboba_player_name, player_code FROM nba_players_name_data "
                        "WHERE zhiboba_player_name LIKE :name OR en_player_name LIKE :name "
                        "LIMIT 1"
                    ),
                    {"name": name_like},
                ).fetchone()
                if name_row:
                    reasons.append(
                        f"按名称'{record.nba_player_name}'找到id={getattr(name_row, 'id')}, "
                        f"但player_code='{getattr(name_row, 'player_code', None)}'不匹配"
                    )

        if not reasons:
            reasons.append(f"数据库中无player_code匹配(normalized_code='{normalized_code}')")
    else:
        reasons.append(f"数据库中无player_code匹配(normalized_code='{normalized_code}')")

    if not record.nba_player_name:
        reasons.append("nba_player_name为空(无法按名称回退匹配)")
    if not record.team_name:
        reasons.append("team_name为空(无法按球队缩小范围)")

    logger.warning(
        "nba_china_player_unmatched player_id=%s player_code=%s normalized_code=%s "
        "nba_player_name=%s team_name=%s jersey_no=%s reasons=[%s]",
        record.player_id,
        record.player_code,
        normalized_code,
        record.nba_player_name,
        record.team_name,
        record.nba_jersey_number,
        "; ".join(reasons),
    )


def _generate_code_variants(player_code: str) -> list[str]:
    """生成 player_code 的常见变体，用于模糊匹配诊断。

    例如 'lebron_james' -> ['lebron-james', 'lebron.james', 'LeBron_James', ...]
    """
    if not player_code:
        return []
    variants: list[str] = []
    variants.append(player_code.replace("_", "-"))
    variants.append(player_code.replace("_", "."))
    variants.append(player_code.replace("-", "_"))
    variants.append(player_code.replace("-", "."))
    variants.append(player_code.replace(".", "_"))
    variants.append(player_code.replace(".", "-"))
    parts = re.split(r"[_\-\.]", player_code)
    if len(parts) >= 2:
        capitalized = "".join(p.capitalize() for p in parts)
        variants.append(capitalized)
        variants.append(capitalized[0].lower() + capitalized[1:])
    return [v for v in variants if v != player_code]


def _serialize_player_record(record: NbaChinaPlayerRecord) -> dict[str, str | None]:
    return {
        "player_id": record.player_id,
        "player_code": record.player_code,
        "normalized_code": normalize_player_code(record.player_code),
        "nba_player_name": record.nba_player_name,
        "en_player_name": record.en_player_name,
        "team_name": record.team_name,
        "nba_jersey_number": record.nba_jersey_number,
    }


def _update_existing_player(db: Session, *, row_id: int, record: NbaChinaPlayerRecord) -> None:
    db.execute(
        text(
            """
            UPDATE nba_players_name_data
            SET player_id = :player_id,
                nba_player_name = :nba_player_name,
                en_player_name = :en_player_name,
                nba_jersey_number = :nba_jersey_number,
                team_name = :team_name,
                player_code = :player_code,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
            """
        ),
        _record_params(record) | {"id": row_id},
    )


def _insert_new_player(db: Session, *, record: NbaChinaPlayerRecord) -> None:
    db.execute(
        text(
            """
            INSERT INTO nba_players_name_data
              (
                team_id,
                team_name,
                player_id,
                zhiboba_player_id,
                nba_player_name,
                en_player_name,
                zhiboba_player_name,
                nba_jersey_number,
                player_code
              )
            VALUES
              (
                NULL,
                :team_name,
                :player_id,
                :zhiboba_player_id,
                :nba_player_name,
                :en_player_name,
                :nba_player_name,
                :nba_jersey_number,
                :player_code
              )
            ON DUPLICATE KEY UPDATE
              team_name = VALUES(team_name),
              nba_player_name = VALUES(nba_player_name),
              en_player_name = VALUES(en_player_name),
              zhiboba_player_name = VALUES(zhiboba_player_name),
              nba_jersey_number = VALUES(nba_jersey_number),
              player_code = VALUES(player_code),
              updated_at = CURRENT_TIMESTAMP
            """
        ),
        _record_params(record) | {"zhiboba_player_id": f"nba_cn_{record.player_id}"},
    )


def _record_params(record: NbaChinaPlayerRecord) -> dict[str, str | None]:
    return {
        "player_id": record.player_id,
        "player_code": record.player_code,
        "nba_player_name": record.nba_player_name,
        "en_player_name": record.en_player_name,
        "nba_jersey_number": record.nba_jersey_number,
        "team_name": record.team_name,
    }


def sync_nba_china_players(
    db: Session,
    http_client: HttpClient,
    *,
    page_size: int = NBA_CHINA_PLAYERS_DEFAULT_PAGE_SIZE,
    max_pages: int = 200,
    sign2: str = NBA_CHINA_DEFAULT_SIGN2,
) -> dict[str, Any]:
    ensure_nba_china_player_columns(db=db)

    fetched = fetch_nba_china_player_records(
        http_client=http_client,
        page_size=page_size,
        max_pages=max_pages,
        sign2=sign2,
    )
    result = upsert_nba_china_player_records(db=db, records=fetched.records)
    return {
        "pages": fetched.pages,
        "players": len(fetched.records),
        "total_count": fetched.total_count,
        "source_rows": fetched.source_rows,
        "skipped_without_player_code": fetched.skipped_without_player_code,
        **result,
    }


def diagnose_unmatched_nba_china_players(
    db: Session,
    http_client: HttpClient,
    *,
    page_size: int = NBA_CHINA_PLAYERS_DEFAULT_PAGE_SIZE,
    max_pages: int = 200,
    sign2: str = NBA_CHINA_DEFAULT_SIGN2,
    sample_limit: int = 20,
) -> dict[str, Any]:
    ensure_nba_china_player_columns(db=db)

    fetched = fetch_nba_china_player_records(
        http_client=http_client,
        page_size=page_size,
        max_pages=max_pages,
        sign2=sign2,
    )
    matched, unmatched = find_unmatched_nba_china_player_records(db=db, records=fetched.records)
    for record in unmatched:
        _log_unmatched_player(record=record, normalized_code=normalize_player_code(record.player_code), db=db)

    normalized_sample_limit = max(0, int(sample_limit))
    return {
        "pages": fetched.pages,
        "players": len(fetched.records),
        "total_count": fetched.total_count,
        "source_rows": fetched.source_rows,
        "skipped_without_player_code": fetched.skipped_without_player_code,
        "matched": matched,
        "unmatched": len(unmatched),
        "unmatched_sample": [
            _serialize_player_record(record)
            for record in unmatched[:normalized_sample_limit]
        ],
    }
