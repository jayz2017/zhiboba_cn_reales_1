from app.core.database import SessionLocal
from app.modules.nba_live_text.auto_tune import select_next_game_list_target

db = SessionLocal()
try:
    target = select_next_game_list_target(db)
    print(None if target is None else {
        'saishi_id': target.saishi_id,
        'home_team': target.home_team,
        'visit_team': target.visit_team,
        'sdate': target.sdate.isoformat() if target.sdate else None,
        'start_time': target.start_time.isoformat() if target.start_time else None,
    })
finally:
    db.close()
