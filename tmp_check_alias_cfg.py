from app.core.database import SessionLocal
from app.modules.nba_live_text.zhiboba_livetext import load_player_segmentation_config

db = SessionLocal()
try:
    cfg = load_player_segmentation_config(db=db, saishi_id='1780738')
    for key in ['希尔德', '巴迪-希尔德', '巴迪希尔德', '文森特', '盖布-文森特', '盖布文森特']:
        print(key, '=>', cfg.alias_to_full_name.get(key))
    print('has 希尔德 word =', '希尔德' in cfg.words)
    print('has 文森特 word =', '文森特' in cfg.words)
    print('sample words =', [w for w in cfg.words if '希尔德' in w or '文森特' in w][:20])
finally:
    db.close()
