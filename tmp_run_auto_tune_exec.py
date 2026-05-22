import json
from pathlib import Path
from app.core.database import SessionLocal
from app.utils.http.client import HttpClient
from app.modules.nba_live_text.auto_tune import auto_tune_next_game_live_text, select_next_game_list_target

out_path = Path('tmp_auto_tune_exec_result.json')
db = SessionLocal()
try:
    target = select_next_game_list_target(db)
    payload = {
        'selected_target': None if target is None else {
            'saishi_id': target.saishi_id,
            'home_team': target.home_team,
            'visit_team': target.visit_team,
            'sdate': target.sdate.isoformat() if target.sdate else None,
            'start_time': target.start_time.isoformat() if target.start_time else None,
        },
        'result': auto_tune_next_game_live_text(
            db=db,
            http_client=HttpClient(),
            sample_limit=10,
            max_attempts=3,
        ),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(out_path.read_text(encoding='utf-8'))
finally:
    db.close()
