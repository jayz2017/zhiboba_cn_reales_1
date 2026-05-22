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
db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT saishi_id, live_sid, live_pid, pid_text, live_text, home_score, visit_score, user_chn
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id=:sid AND live_sid BETWEEN 34 AND 60
        ORDER BY live_sid ASC
    """), {'sid': sid}).mappings().all()
    rules = load_live_text_filter_rules(db=db)
    _, content_remove_rules = split_filter_rules(rules)
    cfg = load_player_segmentation_config(db=db, saishi_id=sid)
    tokenizer = Tokenizer(batch_size=32)
    tokenizer.add_words(cfg.words)
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
    print('affected=', upsert_live_text_events(db=db, records=enriched))
    verify = db.execute(text("""
        SELECT live_sid, live_text, segmented_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id=:sid AND live_sid BETWEEN 34 AND 43
        ORDER BY live_sid ASC
    """), {'sid': sid}).mappings().all()
    for item in verify:
        print(dict(item))
finally:
    db.close()
