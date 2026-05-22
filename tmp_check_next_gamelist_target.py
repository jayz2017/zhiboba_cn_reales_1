from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    row = db.execute(text("""
        SELECT
          game.id AS saishi_id,
          game.home_team,
          game.visit_team,
          game.sdate,
          game.`start` AS start_time,
          COALESCE(event_stats.event_count, 0) AS event_count
        FROM game_list AS game
        LEFT JOIN (
          SELECT saishi_id, COUNT(*) AS event_count
          FROM nba_zhiboba_live_text_event
          GROUP BY saishi_id
        ) AS event_stats
          ON event_stats.saishi_id = game.id
        WHERE UPPER(TRIM(COALESCE(game.type, 'NBA'))) = 'NBA'
        ORDER BY
          CASE WHEN COALESCE(event_stats.event_count, 0) = 0 THEN 0 ELSE 1 END ASC,
          game.sdate ASC,
          game.`start` ASC,
          game.id ASC
        LIMIT 5
    """)).mappings().all()
    for item in row:
        print(dict(item))
finally:
    db.close()
