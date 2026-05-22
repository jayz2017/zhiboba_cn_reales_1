import json

from sqlalchemy import text

from app.core.database import SessionLocal
from app.modules.nba_schedule.zhiboba_team_players import ensure_players_table, sync_all_zhiboba_team_players
from app.utils.http.client import HttpClient


db = SessionLocal()
http_client = HttpClient()

try:
    ensure_players_table(db=db)
    before_count = db.execute(text("SELECT COUNT(*) AS total FROM nba_players_name_data")).scalar_one()
    db.execute(text("DELETE FROM nba_players_name_data"))
    db.commit()
    after_delete_count = db.execute(text("SELECT COUNT(*) AS total FROM nba_players_name_data")).scalar_one()

    sync_result = sync_all_zhiboba_team_players(db=db, http_client=http_client)
    after_sync_count = db.execute(text("SELECT COUNT(*) AS total FROM nba_players_name_data")).scalar_one()

    print(
        json.dumps(
            {
                "before_count": int(before_count or 0),
                "after_delete_count": int(after_delete_count or 0),
                "after_sync_count": int(after_sync_count or 0),
                "sync_result": sync_result,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
finally:
    db.close()
