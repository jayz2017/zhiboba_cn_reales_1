from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT saishi_id, live_sid, live_text, segmented_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780738'
        ORDER BY live_sid ASC
        LIMIT 20
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
