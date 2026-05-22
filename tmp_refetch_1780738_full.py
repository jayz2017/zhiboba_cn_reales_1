from app.core.database import SessionLocal
from app.utils.http.client import HttpClient
from app.modules.nba_live_text.zhiboba_livetext import fetch_zhiboba_live_text_events

db = SessionLocal()
try:
    result = fetch_zhiboba_live_text_events(db=db, http_client=HttpClient(), saishi_id='1780738', start_cursor=1, max_consecutive_404=300)
    print(result)
finally:
    db.close()
