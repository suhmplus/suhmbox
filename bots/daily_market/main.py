"""일간 시장 리포트 봇 (daily_market).

매일 09:30 KST, 시장 심리·밸류에이션 지표 3종을 텔레그램으로 발송.
- CNN Fear & Greed Index (production.dataviz.cnn.io — 봇 UA 는 418, 브라우저 UA 필요)
- Crypto Fear & Greed Index (alternative.me)
- BTC MVRV 비율 (CoinMetrics community)

[silent failure 방지]
- 지표별 독립 try — 부분 실패해도 나머지는 발송, 실패는 메시지에 ⚠️ + exit(1).
- 텔레그램 발송 실패는 예외 전파 → Actions run 빨간 X (최후 가시성).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta, timezone

from shared import notify

KST = timezone(timedelta(hours=9))

CNN_FGI_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
ALT_FNG_URL = "https://api.alternative.me/fng/"
CM_METRICS_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"


def fetch_cnn_fgi() -> str:
    """CNN Fear & Greed — fear_and_greed.score (float) + .rating (str)."""
    with notify.http_client() as c:
        r = c.get(CNN_FGI_URL)
        r.raise_for_status()
        fg = r.json()["fear_and_greed"]
    return f"{float(fg['score']):.2f}({fg['rating']})"


def fetch_crypto_fgi() -> str:
    """alternative.me FNG — data[0].value (0-100) + value_classification."""
    with notify.http_client() as c:
        r = c.get(ALT_FNG_URL, params={"limit": "1"})
        r.raise_for_status()
        row = r.json()["data"][0]
    return f"{int(row['value'])}({row['value_classification']})"


def fetch_btc_mvrv() -> str:
    """CoinMetrics community CapMVRVCur — 최근 7일 중 가장 최신 가용값.

    CoinMetrics v4 는 기본 시간 오름차순이라 page_size=1 은 가장 오래된 값을 줄 위험이
    있다. 최근 구간을 fetch 한 뒤 CapMVRVCur 가 있는 마지막 row 를 최신값으로 쓴다.
    """
    start = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    with notify.http_client() as c:
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

    notify.send_telegram("\n".join(lines))

    # 부분 실패라도 Actions run 을 실패로 — 빨간 X 로 사용자가 인지 (silent 방지 이중 안전망).
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
