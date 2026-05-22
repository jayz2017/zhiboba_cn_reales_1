from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    row = db.execute(text("""
        SELECT live_sid, live_text, segmented_text, updated_at
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780736' AND live_sid BETWEEN 34 AND 43
        ORDER BY live_sid ASC
    """)).mappings().all()
    for item in row:
        print(dict(item))
finally:
    db.close()
