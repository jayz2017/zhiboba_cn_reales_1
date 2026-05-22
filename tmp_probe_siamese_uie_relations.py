import json
from app.core.database import SessionLocal
from app.modules.semantics.siamese_uie import extract_postgame_player_relations

db = SessionLocal()
try:
    result = extract_postgame_player_relations(db=db, saishi_id='1780736', max_rows=10, sample_limit=5)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
finally:
    db.close()
