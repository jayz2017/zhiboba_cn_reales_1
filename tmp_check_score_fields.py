from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT saishi_id, live_sid, live_text, home_score, visit_score,
               home_score_change, visit_score_change, score_team_side, score_points, score_diff,
               updated_at
        FROM nba_zhiboba_live_text_event
        ORDER BY updated_at DESC, live_sid DESC
        LIMIT 10
    """)).fetchall()
    for row in rows:
        print(row)
finally:
    db.close()
