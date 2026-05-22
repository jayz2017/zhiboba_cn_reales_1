from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT live_sid, live_text, segmented_text, current_player_name,
               home_score_change, visit_score_change, score_team_side, score_points, score_diff
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = '1780738' AND segmented_text IS NOT NULL AND segmented_text <> ''
        ORDER BY live_sid ASC
        LIMIT 8
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
