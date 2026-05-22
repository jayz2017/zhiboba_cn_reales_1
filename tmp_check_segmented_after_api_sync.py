from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    summary = db.execute(text("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN segmented_text IS NOT NULL AND TRIM(segmented_text) <> '' THEN 1 ELSE 0 END) AS segmented_count,
            SUM(CASE WHEN segmented_text LIKE '%裁判%' THEN 1 ELSE 0 END) AS seg_has_referee,
            SUM(CASE WHEN segmented_text LIKE '%@%' THEN 1 ELSE 0 END) AS seg_has_at
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780738'
    """)).mappings().one()
    print(dict(summary))
    rows = db.execute(text("""
        SELECT live_sid, live_text, segmented_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780738' AND segmented_text IS NOT NULL AND TRIM(segmented_text) <> ''
        ORDER BY live_sid ASC
        LIMIT 5
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
