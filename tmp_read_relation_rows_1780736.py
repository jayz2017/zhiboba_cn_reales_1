from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    summary = db.execute(text("""
        SELECT COUNT(*) AS total,
               COUNT(DISTINCT live_sid) AS live_sids,
               MAX(updated_at) AS last_updated_at
        FROM nba_zhiboba_player_relation
        WHERE saishi_id='1780736'
    """)).mappings().one()
    print({'summary': dict(summary)})
    rows = db.execute(text("""
        SELECT live_sid, relation_type, relation_side, subject_player_name, object_player_name, action_text, result_text, score_points, extractor_name, confidence
        FROM nba_zhiboba_player_relation
        WHERE saishi_id='1780736'
        ORDER BY updated_at DESC, id DESC
        LIMIT 15
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
