from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    row = db.execute(text("SELECT COUNT(*) FROM nba_zhiboba_live_text_event WHERE saishi_id='1780738'" )).scalar() or 0
    print('1780738_count=', row)
finally:
    db.close()
