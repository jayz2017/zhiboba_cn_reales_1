from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class SemanticRelation:
    subject: str
    predicate: str
    object: str
    evidence_live_event_id: int | None
    confidence: float


_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?P<s>[\u4e00-\u9fa5A-Za-z·\.\s]{2,30})\s*助攻\s*(?P<o>[\u4e00-\u9fa5A-Za-z·\.\s]{2,30})"), "assists"),
    (re.compile(r"(?P<s>[\u4e00-\u9fa5A-Za-z·\.\s]{2,30})\s*命中\s*(?P<o>[\u4e00-\u9fa5A-Za-z0-9·\.\s]{1,30})"), "scores"),
)


def extract_relations_from_text(text_content: str, evidence_live_event_id: int | None) -> list[SemanticRelation]:
    content = (text_content or "").strip()
    if not content:
        return []

    relations: list[SemanticRelation] = []
    for pattern, predicate in _PATTERNS:
        match = pattern.search(content)
        if not match:
            continue

        s = (match.group("s") or "").strip()
        o = (match.group("o") or "").strip()
        if s and o:
            relations.append(
                SemanticRelation(
                    subject=s,
                    predicate=predicate,
                    object=o,
                    evidence_live_event_id=evidence_live_event_id,
                    confidence=0.6,
                )
            )

    return relations


def extract_and_persist_for_game(db: Session, game_id: int, source: str) -> int:
    rows = db.execute(
        text(
            """
            SELECT id, text
            FROM nba_live_text_event
            WHERE game_id = :game_id AND source = :source
            ORDER BY id ASC
            """
        ),
        {"game_id": game_id, "source": source},
    ).fetchall()

    inserted = 0
    for row in rows:
        relations = extract_relations_from_text(text_content=row.text, evidence_live_event_id=int(row.id))
        for rel in relations:
            db.execute(
                text(
                    """
                    INSERT INTO nba_semantic_relation
                      (game_id, subject, predicate, object, evidence_live_event_id, confidence)
                    VALUES
                      (:game_id, :subject, :predicate, :object, :evidence_live_event_id, :confidence)
                    """
                ),
                {
                    "game_id": game_id,
                    "subject": rel.subject,
                    "predicate": rel.predicate,
                    "object": rel.object,
                    "evidence_live_event_id": rel.evidence_live_event_id,
                    "confidence": rel.confidence,
                },
            )
            inserted += 1

    if inserted:
        db.commit()

    return inserted
