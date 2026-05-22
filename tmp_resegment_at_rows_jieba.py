from sqlalchemy import text
import jieba
from app.core.database import SessionLocal
from app.modules.nba_live_text.zhiboba_livetext import (
    build_segmented_text,
    clean_live_text_for_tokenization,
    load_live_text_filter_rules,
    load_player_segmentation_config,
    normalize_player_tokens,
    split_filter_rules,
)

sid = '1780738'
db = SessionLocal()
try:
    rules = load_live_text_filter_rules(db)
    _, content_remove_rules = split_filter_rules(rules)
    player_cfg = load_player_segmentation_config(db=db, saishi_id=sid)
    for word in player_cfg.words:
        jieba.add_word(word, freq=100000)

    rows = db.execute(text("""
        SELECT live_sid, live_text
        FROM nba_zhiboba_live_text_event
        WHERE saishi_id = :sid AND live_text LIKE '@%'
        ORDER BY live_sid ASC
    """), {'sid': sid}).mappings().all()

    samples = []
    for row in rows:
        cleaned_text = clean_live_text_for_tokenization(row['live_text'], content_remove_rules)
        tokens = [token.strip() for token in jieba.lcut(cleaned_text) if isinstance(token, str) and token.strip()]
        normalized_tokens = normalize_player_tokens(tokens, player_cfg.alias_to_full_name)
        segmented_text = build_segmented_text(normalized_tokens)
        db.execute(
            text("""
                UPDATE nba_zhiboba_live_text_event
                SET segmented_text = :segmented_text
                WHERE saishi_id = :sid AND live_sid = :live_sid
            """),
            {'sid': sid, 'live_sid': row['live_sid'], 'segmented_text': segmented_text},
        )
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
    print({'updated': len(rows), 'remain_at': int(remain), 'samples': samples})
finally:
    db.close()
