from app.core.database import SessionLocal
from app.utils.http.client import HttpClient
from app.modules.nba_live_text.zhiboba_livetext import sync_zhiboba_live_text

db = SessionLocal()
try:
    result = sync_zhiboba_live_text(db=db, http_client=HttpClient(), saishi_id='1780736', start_cursor=1, max_consecutive_404=50)
    print(result)
finally:
    db.close()
