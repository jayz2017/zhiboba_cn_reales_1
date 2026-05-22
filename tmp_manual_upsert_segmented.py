from app.core.database import SessionLocal
from sqlalchemy import text
from app.modules.nba_live_text.zhiboba_livetext import ZhibobaLiveTextEventRecord, upsert_live_text_events

db = SessionLocal()
try:
    row = db.execute(text("""
        SELECT saishi_id, live_sid, live_pid, pid_text, live_text, home_score, visit_score, user_chn,
               current_player_name, home_score_change, visit_score_change, score_team_side, score_points, score_diff
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780736' AND live_sid=34
        LIMIT 1
    """)).mappings().one()
    record = ZhibobaLiveTextEventRecord(
        saishi_id=row['saishi_id'],
        live_sid=row['live_sid'],
        live_pid=row['live_pid'],
        pid_text=row['pid_text'],
        live_text=row['live_text'],
        segmented_text='手工\\验证\\分词',
        home_score=row['home_score'],
        visit_score=row['visit_score'],
        user_chn=row['user_chn'],
        current_player_name=row['current_player_name'],
        home_score_change=row['home_score_change'],
        visit_score_change=row['visit_score_change'],
        score_team_side=row['score_team_side'],
        score_points=row['score_points'],
        score_diff=row['score_diff'],
    )
    print('affected=', upsert_live_text_events(db, [record]))
    verify = db.execute(text("""
        SELECT saishi_id, live_sid, segmented_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780736' AND live_sid=34
    """)).mappings().one()
    print(dict(verify))
finally:
    db.close()
