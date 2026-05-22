from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    for sid in ['1780736', '1780738']:
        row = db.execute(text("""
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN segmented_text IS NOT NULL AND TRIM(segmented_text) <> '' THEN 1 ELSE 0 END) AS segmented_count,
              SUM(CASE WHEN segmented_text LIKE '%@%' THEN 1 ELSE 0 END) AS seg_has_at,
              SUM(CASE WHEN segmented_text LIKE '%裁判%' THEN 1 ELSE 0 END) AS seg_has_referee
            FROM nba_zhiboba_live_text_event
            WHERE saishi_id=:sid
        """), {'sid': sid}).mappings().one()
        print(sid, dict(row))
    rows = db.execute(text("""
        SELECT live_sid, live_text, segmented_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780736'
          AND segmented_text IS NOT NULL AND TRIM(segmented_text) <> ''
        ORDER BY live_sid ASC
        LIMIT 5
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
