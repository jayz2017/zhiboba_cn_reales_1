from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    row = db.execute(text("""
        SELECT saishi_id, COUNT(*) AS total,
               SUM(CASE WHEN segmented_text IS NOT NULL AND TRIM(segmented_text) <> '' THEN 1 ELSE 0 END) AS segmented_count
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id IN ('1780736','1780738')
        GROUP BY saishi_id
        ORDER BY saishi_id ASC
    """)).mappings().all()
    for item in row:
        print(dict(item))
finally:
    db.close()
