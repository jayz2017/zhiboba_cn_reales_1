from app.core.database import SessionLocal
from sqlalchemy import text
from app.modules.nba_live_text.nlp.tokenizer import Tokenizer
from app.modules.nba_live_text.zhiboba_livetext import (
    ZhibobaLiveTextEventRecord,
    build_segmented_text,
    clean_live_text_for_tokenization,
    enrich_records_with_game_state,
    load_live_text_filter_rules,
    load_player_segmentation_config,
    normalize_player_tokens,
    split_filter_rules,
    upsert_live_text_events,
)
from app.modules.nba_live_text.auto_tune import validate_live_text_segmentation_spec

sid = '1780736'
chunk_rows = 300
batch_size = 100

db = SessionLocal()
try:
    rules = load_live_text_filter_rules(db=db)
    _, content_remove_rules = split_filter_rules(rules)
    cfg = load_player_segmentation_config(db=db, saishi_id=sid)
    tokenizer = Tokenizer(batch_size=batch_size)
    tokenizer.add_words(cfg.words)

    for round_no in range(1, 6):
        rows = db.execute(text("""
            SELECT saishi_id, live_sid, live_pid, pid_text, live_text, home_score, visit_score, user_chn
            FROM nba_zhiboba_live_text_event
            WHERE saishi_id=:sid
              AND (segmented_text IS NULL OR TRIM(segmented_text) = '')
            ORDER BY live_sid ASC
            LIMIT :limit_rows
        """), {'sid': sid, 'limit_rows': chunk_rows}).mappings().all()
        print({'round': round_no, 'pending_rows': len(rows)}, flush=True)
        if not rows:
            break

        texts = [clean_live_text_for_tokenization(row['live_text'], content_remove_rules) for row in rows]
        token_results = tokenizer.tokenize_batch(texts)
        records = []
        for row, token_result in zip(rows, token_results, strict=False):
            tokens = normalize_player_tokens(token_result.tokens, cfg.alias_to_full_name)
            records.append(ZhibobaLiveTextEventRecord(
                saishi_id=row['saishi_id'],
                live_sid=row['live_sid'],
                live_pid=row['live_pid'],
                pid_text=row['pid_text'],
                live_text=row['live_text'],
                segmented_text=build_segmented_text(tokens),
                home_score=row['home_score'],
                visit_score=row['visit_score'],
                user_chn=row['user_chn'],
            ))
        enriched = enrich_records_with_game_state(db=db, records=records, alias_to_full_name=cfg.alias_to_full_name)
        affected = upsert_live_text_events(db=db, records=enriched)
        summary = db.execute(text("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN segmented_text IS NOT NULL AND TRIM(segmented_text) <> '' THEN 1 ELSE 0 END) AS segmented_count
            FROM nba_zhiboba_live_text_event
            WHERE saishi_id=:sid
        """), {'sid': sid}).mappings().one()
        print({'round': round_no, 'affected': affected, 'segmented_count': int(summary['segmented_count'] or 0)}, flush=True)

    validation = validate_live_text_segmentation_spec(db=db, saishi_id=sid, sample_limit=10)
    print({'validation_passed': validation['passed'], 'violation_rule_count': validation['violation_rule_count']}, flush=True)
    print(validation, flush=True)
finally:
    db.close()
