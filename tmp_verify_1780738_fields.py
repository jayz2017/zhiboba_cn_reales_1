from app.core.database import SessionLocal
from sqlalchemy import text

SQLS = {
    'summary': """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN score_diff IS NOT NULL THEN 1 ELSE 0 END) AS score_diff_filled,
            SUM(CASE WHEN score_points IS NOT NULL THEN 1 ELSE 0 END) AS score_points_filled,
            SUM(CASE WHEN score_team_side IS NOT NULL THEN 1 ELSE 0 END) AS score_team_side_filled,
            SUM(CASE WHEN current_player_name IS NOT NULL AND current_player_name <> '' THEN 1 ELSE 0 END) AS current_player_name_filled,
            SUM(CASE WHEN segmented_text IS NOT NULL AND segmented_text <> '' THEN 1 ELSE 0 END) AS segmented_text_filled,
            SUM(CASE WHEN home_score_change > 0 OR visit_score_change > 0 THEN 1 ELSE 0 END) AS score_change_rows
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = '1780738'
    """,
    'score_rows': """
        SELECT live_sid, live_text, home_score, visit_score,
               home_score_change, visit_score_change, score_team_side, score_points, score_diff,
               current_player_name, segmented_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = '1780738'
          AND (score_points IS NOT NULL OR home_score_change > 0 OR visit_score_change > 0)
        ORDER BY live_sid ASC
        LIMIT 12
    """,
    'player_rows': """
        SELECT live_sid, user_chn, current_player_name, live_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = '1780738'
          AND user_chn IS NOT NULL
        ORDER BY live_sid ASC
        LIMIT 12
    """,
}

db = SessionLocal()
try:
    summary = db.execute(text(SQLS['summary'])).mappings().one()
    print('SUMMARY', dict(summary))
    print('SCORE_ROWS')
    for row in db.execute(text(SQLS['score_rows'])).mappings().all():
        print(dict(row))
    print('PLAYER_ROWS')
    for row in db.execute(text(SQLS['player_rows'])).mappings().all():
        print(dict(row))
finally:
    db.close()
