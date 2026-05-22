from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT saishi_id, live_sid, pid_text, live_text, segmented_text
        FROM nba_zhiboba_live_text_event
        WHERE segmented_text LIKE '%@%'
        ORDER BY updated_at DESC, live_sid DESC
        LIMIT 20
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
