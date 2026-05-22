from app.core.database import SessionLocal
from sqlalchemy import text
from app.modules.nba_live_text.auto_tune import validate_live_text_segmentation_spec

db = SessionLocal()
try:
    row = db.execute(text("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN segmented_text IS NOT NULL AND TRIM(segmented_text) <> '' THEN 1 ELSE 0 END) AS segmented_count,
               MAX(CASE WHEN segmented_text IS NOT NULL AND TRIM(segmented_text) <> '' THEN live_sid END) AS max_segmented_sid
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id='1780736'
    """)).mappings().one()
    print({'progress': dict(row)})
    validation = validate_live_text_segmentation_spec(db=db, saishi_id='1780736', sample_limit=10)
    print({'validation_passed': validation['passed'], 'violation_rule_count': validation['violation_rule_count']})
    print(validation)
finally:
    db.close()
