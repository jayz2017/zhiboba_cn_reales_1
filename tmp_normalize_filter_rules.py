from app.core.database import SessionLocal
from sqlalchemy import text
from app.modules.nba_live_text.zhiboba_livetext import ensure_live_text_tables

db = SessionLocal()
try:
    ensure_live_text_tables(db)
    rows = db.execute(text("""
        SELECT id, rule_type, target_field, match_mode, filter_text, is_enabled, sort_order
        FROM nba_zhiboba_live_text_filter_rule
        WHERE rule_type='line_skip' AND target_field='live_text'
          AND filter_text IN ('@', '裁判', '现场', '熟人', '第1节', '第2节', '第3节', '第4节', '加时')
        ORDER BY sort_order, id
    """)).mappings().all()
    for row in rows:
        print(dict(row))
finally:
    db.close()
