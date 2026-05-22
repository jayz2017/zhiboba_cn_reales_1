from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT live_sid, home_score, visit_score,
               home_score_change, visit_score_change, score_team_side, score_points, score_diff,
               current_player_name, updated_at
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = '1780738'
        ORDER BY updated_at DESC, live_sid DESC
        LIMIT 15
    """)).fetchall()
    for row in rows:
        print(row)
finally:
    db.close()
