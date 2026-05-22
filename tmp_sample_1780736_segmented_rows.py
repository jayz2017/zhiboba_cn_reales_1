from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT live_sid, live_text, segmented_text, current_player_name, score_points, score_team_side
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780736'
          AND segmented_text IS NOT NULL
          AND TRIM(segmented_text) <> ''
        ORDER BY live_sid ASC
        LIMIT 30
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
