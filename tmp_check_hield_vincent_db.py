from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    row = db.execute(text("SELECT saishi_id, home_id, guest_id FROM nba_zhiboba_yj_gamelist WHERE saishi_id='1780738' LIMIT 1")).mappings().first()
    print('game=', dict(row) if row else None)

    rows = db.execute(text("""
        SELECT team_id, player_id, zhiboba_player_id, nba_player_name, zhiboba_player_name, player_name_alias
        FROM nba_players_name_data
        WHERE nba_player_name LIKE '%希尔德%'
           OR zhiboba_player_name LIKE '%希尔德%'
           OR player_name_alias LIKE '%希尔德%'
           OR nba_player_name LIKE '%文森特%'
           OR zhiboba_player_name LIKE '%文森特%'
           OR player_name_alias LIKE '%文森特%'
        ORDER BY team_id, nba_player_name, zhiboba_player_name
    """)).mappings().all()
    print('players:')
    for item in rows:
        print(dict(item))

    rows2 = db.execute(text("""
        SELECT player_id, alias_name, type
        FROM player_alias_name_info
        WHERE alias_name LIKE '%希尔德%'
           OR alias_name LIKE '%文森特%'
        ORDER BY player_id, alias_name
    """)).mappings().all()
    print('aliases:')
    for item in rows2:
        print(dict(item))
finally:
    db.close()
