from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.utils.http.client import HttpClient


@dataclass(frozen=True)
class LiveTextEvent:
    quarter: int | None
    clock: str | None
    text: str


class LiveTextReader:
    def __init__(self, http_client: HttpClient) -> None:
        self._http = http_client

    def read_events_from_url(self, url: str) -> list[LiveTextEvent]:
        payload = self._http.get_json(url)
        return self._parse(payload)

    def _parse(self, payload: Any) -> list[LiveTextEvent]:
        if not isinstance(payload, dict):
            return []

        raw_events = payload.get("events")
        if not isinstance(raw_events, list):
            return []

        events: list[LiveTextEvent] = []
        for item in raw_events:
            if not isinstance(item, dict):
                continue

            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                continue

            quarter = item.get("quarter")
            quarter_value = int(quarter) if isinstance(quarter, int) else None
            clock = item.get("clock")
            clock_value = clock if isinstance(clock, str) and clock.strip() else None
            events.append(LiveTextEvent(quarter=quarter_value, clock=clock_value, text=text.strip()))

        return events
