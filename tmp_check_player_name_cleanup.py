import json
import re

from sqlalchemy import text

from app.core.database import SessionLocal


db = SessionLocal()
try:
    rows = db.execute(
        text(
            """
            SELECT zhiboba_player_id, zhiboba_player_name, team_name
            FROM nba_players_name_data
            ORDER BY id DESC
            """
        )
    ).mappings().all()

    invalid_rows = [
        dict(row)
        for row in rows
        if re.search(r"[.\s·]", str(row["zhiboba_player_name"] or ""))
    ]

    total = db.execute(text("SELECT COUNT(*) AS total FROM nba_players_name_data")).scalar_one()

    print(
        json.dumps(
            {
                "total": int(total or 0),
                "checked_rows": len(rows),
                "invalid_name_count": len(invalid_rows),
                "invalid_samples": invalid_rows[:20],
                "latest_rows": [dict(row) for row in rows[:15]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
finally:
    db.close()
