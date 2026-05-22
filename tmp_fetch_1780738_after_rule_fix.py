from app.core.database import SessionLocal
from app.utils.http.client import HttpClient
from app.modules.nba_live_text.zhiboba_livetext import fetch_zhiboba_live_text_events, ensure_live_text_tables
from sqlalchemy import text

db = SessionLocal()
try:
    ensure_live_text_tables(db)
    result = fetch_zhiboba_live_text_events(
        db=db,
        http_client=HttpClient(),
        saishi_id='1780738',
        start_cursor=1,
        max_consecutive_404=300,
    )
    print(result)
    summary = db.execute(text("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN live_text LIKE '%裁判%' THEN 1 ELSE 0 END) AS raw_has_referee,
            SUM(CASE WHEN live_text LIKE '@%' THEN 1 ELSE 0 END) AS raw_has_at
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780738'
    """)).mappings().one()
    print(dict(summary))
finally:
    db.close()
