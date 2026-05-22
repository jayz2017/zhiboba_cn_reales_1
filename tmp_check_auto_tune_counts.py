from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    for sid in ['1780736', '1780738']:
        row = db.execute(text("""
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN segmented_text IS NOT NULL AND TRIM(segmented_text) <> '' THEN 1 ELSE 0 END) AS segmented_count,
              SUM(CASE WHEN live_text LIKE '@%' THEN 1 ELSE 0 END) AS raw_has_at,
              SUM(CASE WHEN live_text LIKE '%裁判%' THEN 1 ELSE 0 END) AS raw_has_referee
            FROM nba_zhiboba_live_text_event
            WHERE saishi_id=:sid
        """), {'sid': sid}).mappings().one()
        print(sid, dict(row))
finally:
    db.close()
