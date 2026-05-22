from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    total = db.execute(text('SELECT COUNT(*) FROM nba_zhiboba_live_text_event')).scalar() or 0
    per_game = db.execute(text("SELECT saishi_id, COUNT(*) AS c, MAX(updated_at) AS u FROM nba_zhiboba_live_text_event GROUP BY saishi_id ORDER BY u DESC LIMIT 10")).fetchall()
    print('total=', total)
    for row in per_game:
        print(row)
finally:
    db.close()
