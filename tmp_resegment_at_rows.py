from pathlib import Path
from sqlalchemy import text
from app.core.database import SessionLocal
from app.modules.nba_live_text.nlp.tokenizer import Tokenizer
from app.modules.nba_live_text.zhiboba_livetext import (
    build_segmented_text,
    clean_live_text_for_tokenization,
    load_live_text_filter_rules,
    load_player_segmentation_config,
    normalize_player_tokens,
    split_filter_rules,
)

sid = '1780738'
out_file = Path('tmp_resegment_at_rows_result.txt')
db = SessionLocal()
try:
    rules = load_live_text_filter_rules(db)
    _, content_remove_rules = split_filter_rules(rules)
    player_cfg = load_player_segmentation_config(db=db, saishi_id=sid)
    rows = db.execute(text("""
        SELECT live_sid, live_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = :sid AND live_text LIKE '@%'
        ORDER BY live_sid ASC
    """), {'sid': sid}).mappings().all()

    tokenizer = Tokenizer()
    tokenizer.add_words(player_cfg.words)
    cleaned_texts = [clean_live_text_for_tokenization(row['live_text'], content_remove_rules) for row in rows]
    token_results = tokenizer.tokenize_batch(cleaned_texts)

    updated = 0
    samples = []
    for row, cleaned_text, token_result in zip(rows, cleaned_texts, token_results, strict=False):
        normalized_tokens = normalize_player_tokens(token_result.tokens, player_cfg.alias_to_full_name)
        segmented_text = build_segmented_text(normalized_tokens)
        db.execute(
            text("""
                UPDATE nba_zhiboba_live_text_event
                SET segmented_text = :segmented_text
                WHERE saishi_id = :sid AND live_sid = :live_sid
            """),
            {'sid': sid, 'live_sid': row['live_sid'], 'segmented_text': segmented_text},
        )
        updated += 1
        if len(samples) < 8:
            samples.append({
                'live_sid': row['live_sid'],
                'live_text': row['live_text'],
                'cleaned_text': cleaned_text,
                'segmented_text': segmented_text,
            })
    db.commit()

    remain = db.execute(text("""
        SELECT COUNT(*)
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = :sid AND segmented_text LIKE '%@%'
    """), {'sid': sid}).scalar() or 0

    out_file.write_text(str({'updated': updated, 'remain_at': int(remain), 'samples': samples}), encoding='utf-8')
    print(out_file.read_text(encoding='utf-8'))
finally:
    db.close()
