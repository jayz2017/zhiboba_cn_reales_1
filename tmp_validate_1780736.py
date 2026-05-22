from app.core.database import SessionLocal
from app.modules.nba_live_text.auto_tune import validate_live_text_segmentation_spec

db = SessionLocal()
try:
    result = validate_live_text_segmentation_spec(db=db, saishi_id='1780736', sample_limit=10)
    print({'passed': result['passed'], 'violation_rule_count': result['violation_rule_count']})
    print(result)
finally:
    db.close()
