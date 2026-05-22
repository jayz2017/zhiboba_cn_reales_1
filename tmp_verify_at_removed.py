from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    total = db.execute(text("""
        SELECT COUNT(*)
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780738' AND segmented_text LIKE '%@%'
    """)).scalar() or 0
    print({'remain_at': int(total)})
    rows = db.execute(text("""
        SELECT live_sid, live_text, segmented_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780738' AND live_sid IN (147, 148, 1248)
        ORDER BY live_sid ASC
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
