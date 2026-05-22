from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT live_sid, relation_type, relation_side, subject_player_name, object_player_name, action_text, result_text, score_points, confidence
        FROM nba_zhiboba_player_relation
        WHERE saishi_id='1780736'
        ORDER BY updated_at DESC, id DESC
        LIMIT 10
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
