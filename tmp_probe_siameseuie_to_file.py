import json
from pathlib import Path
from app.core.database import SessionLocal
from app.modules.semantics.siamese_uie import extract_postgame_player_relations

out = Path('tmp_siameseuie_run_result.json')
db = SessionLocal()
try:
    result = extract_postgame_player_relations(db=db, saishi_id='1780736', max_rows=3, sample_limit=3)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print('WROTE_RESULT')
    print(out.resolve())
except Exception as exc:
    out.write_text(json.dumps({'error': repr(exc)}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('WROTE_ERROR')
    print(out.resolve())
finally:
    db.close()
