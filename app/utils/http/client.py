from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from app.core.config import settings
from app.core.http_resources import get_default_headers_for_url
from app.utils.crawler.retry import retryable


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    text: str


class HttpClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._proxies = self._build_proxies()

    def _merge_headers(self, url: str, headers: dict[str, str] | None) -> dict[str, str] | None:
        merged = get_default_headers_for_url(url)
        if headers:
            merged.update(headers)
        return merged or None

    def _build_proxies(self) -> dict[str, str] | None:
        proxies: dict[str, str] = {}
        if settings.CRAWLER_HTTP_PROXY:
            proxies["http"] = settings.CRAWLER_HTTP_PROXY
        if settings.CRAWLER_HTTPS_PROXY:
            proxies["https"] = settings.CRAWLER_HTTPS_PROXY
        return proxies or None

    @retryable()
    def get_text(
        self,
        url: str,
        *,
        timeout_seconds: float | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> str:
        response = self._session.get(
            url,
            timeout=timeout_seconds if timeout_seconds is not None else settings.REQUEST_TIMEOUT_SECONDS,
            headers=self._merge_headers(url, headers),
            params=params,
            proxies=self._proxies,
        )
        response.raise_for_status()
        return response.text

    @retryable()
    def get_json(
        self,
        url: str,
        *,
        timeout_seconds: float | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        response = self._session.get(
            url,
            timeout=timeout_seconds if timeout_seconds is not None else settings.REQUEST_TIMEOUT_SECONDS,
            headers=self._merge_headers(url, headers),
            params=params,
            proxies=self._proxies,
        )
        response.raise_for_status()
        return response.json()

    @retryable(exception_types=(requests.RequestException,))
    def get_text_with_status(
        self,
        url: str,
        *,
        timeout_seconds: float | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        allow_status_codes: set[int] | None = None,
    ) -> tuple[int, str]:
        response = self._session.get(
            url,
            timeout=timeout_seconds if timeout_seconds is not None else settings.REQUEST_TIMEOUT_SECONDS,
            headers=self._merge_headers(url, headers),
            params=params,
            proxies=self._proxies,
        )
        if allow_status_codes and response.status_code in allow_status_codes:
            return response.status_code, response.text
        response.raise_for_status()
        return response.status_code, response.text

    @retryable(exception_types=(requests.RequestException,))
    def get_json_with_status(
        self,
        url: str,
        *,
        timeout_seconds: float | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        allow_status_codes: set[int] | None = None,
    ) -> tuple[int, Any | None]:
        response = self._session.get(
            url,
            timeout=timeout_seconds if timeout_seconds is not None else settings.REQUEST_TIMEOUT_SECONDS,
            headers=self._merge_headers(url, headers),
            params=params,
            proxies=self._proxies,
        )
        if allow_status_codes and response.status_code in allow_status_codes:
            return response.status_code, None
        response.raise_for_status()
        return response.status_code, response.json()
