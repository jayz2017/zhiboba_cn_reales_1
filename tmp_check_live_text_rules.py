from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT id, rule_type, target_field, match_mode, filter_text, is_enabled, sort_order
        FROM nba_zhiboba_live_text_filter_rule
        WHERE target_field='live_text'
        ORDER BY sort_order, id
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
