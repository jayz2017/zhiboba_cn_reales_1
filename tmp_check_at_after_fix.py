from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    row = db.execute(text("""
        SELECT COUNT(*) AS cnt
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = '1780738' AND segmented_text LIKE '%@%'
    """)).mappings().one()
    print(dict(row))

    rows = db.execute(text("""
        SELECT live_sid, live_text, segmented_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = '1780738' AND live_text LIKE '@%'
        ORDER BY live_sid DESC
        LIMIT 12
    """)).mappings().all()
    for item in rows:
        print(dict(item))
finally:
    db.close()
