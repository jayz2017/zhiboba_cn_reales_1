from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    cols = db.execute(text("""
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'nba_players_name_data'
        ORDER BY ORDINAL_POSITION
    """)).scalars().all()
    print(cols)

    rows = db.execute(text("""
        SELECT *
        FROM nba_players_name_data
        WHERE zhiboba_player_id IN ('82513', '148570')
        LIMIT 2
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
