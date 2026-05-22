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

sid = '1780736'
batch_size = 20

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT saishi_id, live_sid, live_pid, pid_text, live_text, home_score, visit_score, user_chn
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id=:sid
        ORDER BY live_sid ASC
    """), {'sid': sid}).mappings().all()
    print(f'total_rows={len(rows)}', flush=True)

    rules = load_live_text_filter_rules(db=db)
    _, content_remove_rules = split_filter_rules(rules)
    cfg = load_player_segmentation_config(db=db, saishi_id=sid)
    print(f'dict_words={len(cfg.words)} alias_map={len(cfg.alias_to_full_name)}', flush=True)

    tokenizer = Tokenizer(batch_size=batch_size)
    tokenizer.add_words(cfg.words)
    print('tokenizer_ready', flush=True)

    affected_total = 0
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset: offset + batch_size]
        texts = [clean_live_text_for_tokenization(row['live_text'], content_remove_rules) for row in batch]
        token_results = tokenizer.tokenize_batch(texts)
        records = []
        for row, token_result in zip(batch, token_results, strict=False):
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
        affected_total += upsert_live_text_events(db=db, records=enriched)
        print(f'batch_done offset={offset} affected_total={affected_total}', flush=True)

    summary = db.execute(text("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN segmented_text IS NOT NULL AND TRIM(segmented_text) <> '' THEN 1 ELSE 0 END) AS segmented_count,
               SUM(CASE WHEN segmented_text LIKE '%@%' THEN 1 ELSE 0 END) AS seg_has_at,
               SUM(CASE WHEN segmented_text LIKE '%裁判%' THEN 1 ELSE 0 END) AS seg_has_referee
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id=:sid
    """), {'sid': sid}).mappings().one()
    print(dict(summary), flush=True)
finally:
    db.close()
