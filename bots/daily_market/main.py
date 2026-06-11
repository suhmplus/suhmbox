"""일간 시장 리포트 봇 (daily_market).

매일 오전 9:30 KST, 시장 심리·밸류에이션 지표 3종을 "Suhm 의 미래" 채팅방으로 발송.
- CNN Fear & Greed Index (주식 시장 심리)
- Crypto Fear & Greed Index (alternative.me)
- BTC MVRV 비율 (CoinMetrics community)

GitHub Actions cron 으로 실행. 의존성은 httpx 하나뿐 (인증 없는 GET 3개).

[silent failure 방지]
- 각 지표 fetch 를 독립 try 로 감싸 부분 실패 시에도 나머지는 발송한다.
- 하나라도 실패하면 메시지 끝에 ⚠️ 상세를 붙이고 exit(1) 로 Actions run 도 실패 처리한다.
- 텔레그램 발송 자체가 실패하면 예외가 전파되어 Actions run 이 빨갛게 뜬다 (최후 가시성).
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta, timezone

import httpx

KST = timezone(timedelta(hours=9))
TIMEOUT = 10.0
# CNN dataviz endpoint 는 봇 UA 를 418 로 차단 — 브라우저 UA 로 위장해야 통과한다.
# (alternative.me·CoinMetrics 는 UA 무관하나 공용 client 라 한 값으로 통일)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

CNN_FGI_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
ALT_FNG_URL = "https://api.alternative.me/fng/"
CM_METRICS_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"


def _client() -> httpx.Client:
    # CNN endpoint 는 User-Agent 없으면 403/418 — 모든 호출에 동일 UA 부착.
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": UA})


def fetch_cnn_fgi() -> str:
    """CNN Fear & Greed — fear_and_greed.score (float) + .rating (str)."""
    with _client() as c:
        r = c.get(CNN_FGI_URL)
        r.raise_for_status()
        fg = r.json()["fear_and_greed"]
    return f"{float(fg['score']):.2f}({fg['rating']})"


def fetch_crypto_fgi() -> str:
    """alternative.me FNG — data[0].value (0-100) + value_classification."""
    with _client() as c:
        r = c.get(ALT_FNG_URL, params={"limit": "1"})
        r.raise_for_status()
        row = r.json()["data"][0]
    return f"{int(row['value'])}({row['value_classification']})"


def fetch_btc_mvrv() -> str:
    """CoinMetrics community CapMVRVCur — 최근 7일 중 가장 최신 가용값.

    CoinMetrics v4 는 기본 시간 오름차순(오래된→최신) 정렬이라 page_size=1 은
    가장 오래된 값을 줄 위험이 있다. 최근 구간을 fetch 한 뒤 CapMVRVCur 가 있는
    마지막 row 를 최신값으로 사용한다 (당일 미집계 방어).
    """
    start = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    with _client() as c:
        r = c.get(
            CM_METRICS_URL,
            params={
                "assets": "btc",
                "metrics": "CapMVRVCur",
                "frequency": "1d",
                "start_time": start,
                "page_size": "100",
            },
        )
        r.raise_for_status()
        rows = r.json()["data"]
    vals = [row["CapMVRVCur"] for row in rows if row.get("CapMVRVCur") not in (None, "")]
    if not vals:
        raise ValueError("CapMVRVCur 값이 응답에 없음")
    return f"{float(vals[-1]):.2f}"


# 발송 순서대로 (label, fetch_fn) — 메시지 라인 순서와 1:1.
INDICATORS = [
    ("CNN FGI", fetch_cnn_fgi),
    ("Binance FGI", fetch_crypto_fgi),
    ("BTC MVRV 비율", fetch_btc_mvrv),
]


def send_telegram(text: str) -> None:
    """sendMessage 1회. 토큰·chat_id 는 env 로만 주입 (코드 하드코딩 금지).

    실패(4xx/5xx/네트워크)는 raise 로 전파 — 호출부 main 이 잡지 않으면 Actions run 실패.
    """
    token = os.environ["TELEGRAMBOTTOKEN_SUHMPLUS"]
    chat_id = os.environ["TELEGRAMCHATID_SUHMFUTURE"]
    with _client() as c:
        r = c.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )
        r.raise_for_status()


def main() -> int:
    today = datetime.now(KST).strftime("%y%m%d")

    results: dict[str, str] = {}
    errors: dict[str, str] = {}
    for label, fn in INDICATORS:
        try:
            results[label] = fn()
        except Exception as e:  # noqa: BLE001 — 부분 실패 허용이 의도 (나머지는 발송)
            results[label] = "⚠️ 조회 실패"
            errors[label] = f"{type(e).__name__}: {e}"

    lines = [f"일간 리포트 [{today}]"]
    lines += [f"{label}: {results[label]}" for label, _ in INDICATORS]
    if errors:
        lines.append("")
        lines.append("⚠️ 일부 지표 조회 실패:")
        lines += [f"  - {label}: {err}" for label, err in errors.items()]

    send_telegram("\n".join(lines))

    # 부분 실패라도 Actions run 을 실패로 — 빨간 X 로 사용자가 인지 (silent 방지 이중 안전망).
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
