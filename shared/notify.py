"""텔레그램 발송 + 공용 httpx client. 봇들이 공유한다.

UA 가 브라우저 문자열인 이유: CNN dataviz 등 일부 endpoint 가 봇 UA 를 418 로 차단 —
브라우저로 위장해야 통과한다. telegram·alternative.me·CoinMetrics 는 UA 무관.

토큰·chat_id 는 env 로만 주입 (코드 하드코딩 금지). 현재 모든 봇이 같은 봇·같은 방으로
보내 env 이름을 모듈 상수로 고정 — 다른 방이 필요해지면 그때 파라미터화.
"""

from __future__ import annotations

import os

import httpx

TIMEOUT = 10.0
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

TOKEN_ENV = "TELEGRAMBOTTOKEN_SUHMPLUS"
CHAT_ID_ENV = "TELEGRAMCHATID_SUHMFUTURE"


def http_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": UA})


def send_telegram(text: str) -> None:
    """sendMessage 1회. 실패(4xx/5xx/네트워크)는 raise — 호출부가 GHA 실패로 드러냄."""
    token = os.environ[TOKEN_ENV]
    chat_id = os.environ[CHAT_ID_ENV]
    with http_client() as c:
        r = c.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )
        r.raise_for_status()
