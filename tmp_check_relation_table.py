from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    total = db.execute(text("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'nba_zhiboba_player_relation' ")).scalar()
    print({'table_exists': int(total or 0)})
    if total:
        rows = db.execute(text("""
            SELECT saishi_id, live_sid, relation_type, relation_side, subject_player_name, object_player_name, action_text, result_text, score_points
            FROM nba_zhiboba_player_relation
            WHERE saishi_id='1780736'
            ORDER BY id DESC
            LIMIT 10
        """)).mappings().all()
        for row in rows:
            print(dict(row))
finally:
    db.close()
