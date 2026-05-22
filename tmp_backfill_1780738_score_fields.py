from app.core.database import SessionLocal
from sqlalchemy import text
from app.modules.nba_live_text.zhiboba_livetext import ZhibobaLiveTextEventRecord, enrich_records_with_game_state, load_player_segmentation_config

sid = '1780738'
db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT saishi_id, live_sid, live_pid, pid_text, live_text, segmented_text,
               home_score, visit_score, user_chn
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = :sid
        ORDER BY live_sid ASC
    """), {'sid': sid}).fetchall()

    cfg = load_player_segmentation_config(db, sid)
    records = [
        ZhibobaLiveTextEventRecord(
            saishi_id=row.saishi_id,
            live_sid=row.live_sid,
            live_pid=row.live_pid,
            pid_text=row.pid_text,
            live_text=row.live_text,
            segmented_text=row.segmented_text,
            home_score=row.home_score,
            visit_score=row.visit_score,
            user_chn=row.user_chn,
        )
        for row in rows
    ]
    enriched = enrich_records_with_game_state(db, records, alias_to_full_name=cfg.alias_to_full_name)

    for item in enriched:
        db.execute(text("""
            UPDATE nba_zhiboba_live_text_event
            SET current_player_name = :current_player_name,
                home_score_change = :home_score_change,
                visit_score_change = :visit_score_change,
                score_team_side = :score_team_side,
                score_points = :score_points,
                score_diff = :score_diff,
                updated_at = CURRENT_TIMESTAMP
            WHERE saishi_id = :saishi_id AND live_sid = :live_sid
        """), {
            'current_player_name': item.current_player_name,
            'home_score_change': item.home_score_change,
            'visit_score_change': item.visit_score_change,
            'score_team_side': item.score_team_side,
            'score_points': item.score_points,
            'score_diff': item.score_diff,
            'saishi_id': item.saishi_id,
            'live_sid': item.live_sid,
        })
    db.commit()

    total = db.execute(text("SELECT COUNT(*) FROM nba_zhiboba_live_text_event WHERE saishi_id = :sid"), {'sid': sid}).scalar() or 0
    non_null_diff = db.execute(text("SELECT COUNT(*) FROM nba_zhiboba_live_text_event WHERE saishi_id = :sid AND score_diff IS NOT NULL"), {'sid': sid}).scalar() or 0
    non_null_points = db.execute(text("SELECT COUNT(*) FROM nba_zhiboba_live_text_event WHERE saishi_id = :sid AND score_points IS NOT NULL"), {'sid': sid}).scalar() or 0
    non_null_team = db.execute(text("SELECT COUNT(*) FROM nba_zhiboba_live_text_event WHERE saishi_id = :sid AND score_team_side IS NOT NULL AND TRIM(score_team_side) <> ''"), {'sid': sid}).scalar() or 0
    non_null_player = db.execute(text("SELECT COUNT(*) FROM nba_zhiboba_live_text_event WHERE saishi_id = :sid AND current_player_name IS NOT NULL AND TRIM(current_player_name) <> ''"), {'sid': sid}).scalar() or 0
    print({
        'saishi_id': sid,
        'total': int(total),
        'score_diff_filled': int(non_null_diff),
        'score_points_filled': int(non_null_points),
        'score_team_side_filled': int(non_null_team),
        'current_player_name_filled': int(non_null_player),
    })
finally:
    db.close()
