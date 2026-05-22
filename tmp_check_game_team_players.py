from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT team_id, COUNT(*) AS cnt
        FROM nba_players_name_data
        WHERE team_id IN (
            SELECT home_id FROM nba_zhiboba_yj_gamelist WHERE saishi_id='1780738'
            UNION ALL
            SELECT guest_id FROM nba_zhiboba_yj_gamelist WHERE saishi_id='1780738'
        )
        GROUP BY team_id
        ORDER BY team_id
    """)).mappings().all()
    for item in rows:
        print(dict(item))
finally:
    db.close()
