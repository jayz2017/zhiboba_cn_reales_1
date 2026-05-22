import os
from pathlib import Path
from sqlalchemy import text
from app.core.database import SessionLocal
from app.utils.http.client import HttpClient
from app.modules.nba_live_text.auto_tune import purge_live_text_for_saishi
from app.modules.nba_live_text.zhiboba_livetext import ensure_live_text_tables, sync_zhiboba_live_text

sid = '1780738'
out_file = Path('tmp_rerun_1780738_rule_fix_result.txt')
db = SessionLocal()
try:
    ensure_live_text_tables(db)
    purge_result = purge_live_text_for_saishi(db=db, saishi_id=sid)
    sync_result = sync_zhiboba_live_text(
        db=db,
        http_client=HttpClient(),
        saishi_id=sid,
        start_cursor=1,
        max_consecutive_404=300,
    )
    summary = db.execute(text("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN segmented_text LIKE '%裁判%' THEN 1 ELSE 0 END) AS seg_has_referee,
            SUM(CASE WHEN segmented_text LIKE '%@%' THEN 1 ELSE 0 END) AS seg_has_at,
            SUM(CASE WHEN live_text LIKE '%裁判%' THEN 1 ELSE 0 END) AS raw_has_referee,
            SUM(CASE WHEN live_text LIKE '@%' THEN 1 ELSE 0 END) AS raw_has_at
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = :sid
    """), {'sid': sid}).mappings().one()
    samples = db.execute(text("""
        SELECT live_sid, live_text, segmented_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = :sid
          AND (live_text LIKE '%裁判%' OR live_text LIKE '@%' OR segmented_text LIKE '%裁判%' OR segmented_text LIKE '%@%')
        ORDER BY live_sid ASC
        LIMIT 20
    """), {'sid': sid}).mappings().all()
    payload = {
        'purge_result': purge_result,
        'sync_result': sync_result,
        'summary': dict(summary),
        'samples': [dict(row) for row in samples],
    }
    out_file.write_text(str(payload), encoding='utf-8')
    print(out_file.read_text(encoding='utf-8'), flush=True)
finally:
    db.close()
os._exit(0)
