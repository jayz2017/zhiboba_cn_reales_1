from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    summary = db.execute(text("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN segmented_text LIKE '%裁判%' THEN 1 ELSE 0 END) AS seg_has_referee,
            SUM(CASE WHEN segmented_text LIKE '%@%' THEN 1 ELSE 0 END) AS seg_has_at,
            SUM(CASE WHEN live_text LIKE '%裁判%' THEN 1 ELSE 0 END) AS raw_has_referee,
            SUM(CASE WHEN live_text LIKE '@%' THEN 1 ELSE 0 END) AS raw_has_at
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780738'
    """)).mappings().one()
    print(dict(summary))
    rows = db.execute(text("""
        SELECT live_sid, live_text, segmented_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780738'
          AND (live_text LIKE '%裁判%' OR live_text LIKE '@%' OR segmented_text LIKE '%裁判%' OR segmented_text LIKE '%@%')
        ORDER BY live_sid ASC
        LIMIT 20
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
