from pathlib import Path
from app.core.database import SessionLocal
from sqlalchemy import text
from app.utils.http.client import HttpClient
from app.modules.nba_live_text.zhiboba_livetext import sync_zhiboba_live_text

out_file = Path('tmp_sync_1780738_internal_result.txt')
db = SessionLocal()
try:
    result = sync_zhiboba_live_text(
        db=db,
        http_client=HttpClient(),
        saishi_id='1780738',
        start_cursor=1,
        max_consecutive_404=300,
    )
    rows = db.execute(text("""
        SELECT live_sid, live_text, segmented_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = '1780738' AND live_text LIKE '@%'
        ORDER BY live_sid DESC
        LIMIT 5
    """)).mappings().all()
    out_file.write_text(str({'result': result, 'rows': [dict(r) for r in rows]}), encoding='utf-8')
    print(out_file.read_text(encoding='utf-8'))
finally:
    db.close()
