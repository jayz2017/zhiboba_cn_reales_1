from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT saishi_id, COUNT(*) AS cnt
        FROM nba_zhiboba_live_text_event
        GROUP BY saishi_id
        ORDER BY cnt DESC
        LIMIT 10
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
