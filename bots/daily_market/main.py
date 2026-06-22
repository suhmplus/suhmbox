"""일간 시장 리포트 봇 (daily_market).

매일 09:30 KST, 시장 심리·밸류에이션 지표 3종을 텔레그램으로 발송하고
suhm-snowball 시트의 market-log 탭에 시계열로 누적 기록한다.
- CNN Fear & Greed Index (production.dataviz.cnn.io — 봇 UA 는 418, 브라우저 UA 필요)
- Crypto Fear & Greed Index (alternative.me)
- BTC MVRV 비율 (CoinMetrics community)

[시트 기록] long 형식 (지표당 1행): 날짜·시각·항목·값·등급. snowball reader SA(편집자
권한)·SPREADSHEETID_SNOWBALL 을 재사용한다. 헤더는 시트에서 사람이 관리하고, 봇은
헤더 유무에 상관없이 데이터 행만 끝에 추가한다 (헤더 의존 없음).

[silent failure 방지]
- 지표별 독립 try — 부분 실패해도 나머지는 발송·기록, 실패는 메시지에 ⚠️ + exit(1).
- 시트 기록 실패도 메시지에 ⚠️ + exit(1) (텔레그램 발송 자체는 막지 않음).
- 텔레그램 발송 실패는 예외 전파 → Actions run 빨간 X (최후 가시성).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import gspread

from shared import notify

KST = timezone(timedelta(hours=9))

CNN_FGI_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
ALT_FNG_URL = "https://api.alternative.me/fng/"
CM_METRICS_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"

WORKSHEET = "market-log"


@dataclass
class Reading:
    """지표 1건. display 는 텔레그램 표시용, value·grade 는 시트 기록용."""

    display: str
    value: float
    grade: str = ""


def fetch_cnn_fgi() -> Reading:
    """CNN Fear & Greed — fear_and_greed.score (float) + .rating (str)."""
    with notify.http_client() as c:
        r = c.get(CNN_FGI_URL)
        r.raise_for_status()
        fg = r.json()["fear_and_greed"]
    score = float(fg["score"])
    grade = fg["rating"]
    return Reading(f"{score:.2f}({grade})", score, grade)


def fetch_crypto_fgi() -> Reading:
    """alternative.me FNG — data[0].value (0-100) + value_classification."""
    with notify.http_client() as c:
        r = c.get(ALT_FNG_URL, params={"limit": "1"})
        r.raise_for_status()
        row = r.json()["data"][0]
    value = int(row["value"])
    grade = row["value_classification"]
    return Reading(f"{value}({grade})", value, grade)


def fetch_btc_mvrv() -> Reading:
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
    mvrv = float(vals[-1])
    return Reading(f"{mvrv:.2f}", mvrv)


# 발송·기록 순서대로 (label, fetch_fn) — 메시지 라인·시트 행 순서와 1:1.
INDICATORS = [
    ("CNN FGI", fetch_cnn_fgi),
    ("Binance FGI", fetch_crypto_fgi),
    ("BTC MVRV 비율", fetch_btc_mvrv),
]


def append_to_sheet(date_str: str, time_str: str, readings: dict[str, Reading]) -> None:
    """수집 성공한 지표를 market-log 탭에 long 형식으로 append.

    헤더는 시트에서 사람이 관리하고, 봇은 데이터 행만 끝에 추가한다 (헤더 존재·내용에
    의존하지 않음). snowball reader SA(편집자 권한)·SPREADSHEETID_SNOWBALL 재사용.
    실패한 지표는 행을 만들지 않는다 (그날 결측).
    """
    sa = json.loads(os.environ["GOOGLESAJSON_SNOWBALLREADER"])
    gc = gspread.service_account_from_dict(sa)
    gc.set_timeout(10)  # Google API 무한 대기 방지 — notify.http_client 의 10초와 정합
    ws = gc.open_by_key(os.environ["SPREADSHEETID_SNOWBALL"]).worksheet(WORKSHEET)

    # 행 = [날짜, 시각, 항목, 값, 등급] — 시트 헤더(사람이 관리)와 같은 순서·1:1
    rows = [
        [date_str, time_str, label, readings[label].value, readings[label].grade]
        for label, _ in INDICATORS
        if label in readings
    ]
    ws.append_rows(rows, value_input_option="USER_ENTERED")


def main() -> int:
    now = datetime.now(KST)

    readings: dict[str, Reading] = {}
    errors: dict[str, str] = {}
    for label, fn in INDICATORS:
        try:
            readings[label] = fn()
        except Exception as e:  # noqa: BLE001 — 부분 실패 허용이 의도 (나머지는 발송·기록)
            errors[label] = f"{type(e).__name__}: {e}"

    # 시트 기록은 텔레그램 발송을 막지 않는다 — 실패해도 메시지에 ⚠️ 로 싣고 exit(1).
    sheet_error = ""
    if readings:
        try:
            append_to_sheet(now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), readings)
        except Exception as e:  # noqa: BLE001 — silent 방지: 사유를 메시지·exit code 로 표면화
            sheet_error = f"{type(e).__name__}: {e}"

    lines = [f"일간 리포트 [{now.strftime('%y%m%d')}]"]
    for label, _ in INDICATORS:
        disp = readings[label].display if label in readings else "⚠️ 조회 실패"
        lines.append(f"{label}: {disp}")
    if errors:
        lines.append("")
        lines.append("⚠️ 일부 지표 조회 실패:")
        lines += [f"  - {label}: {err}" for label, err in errors.items()]
    if sheet_error:
        lines.append("")
        lines.append(f"⚠️ 시트 기록 실패: {sheet_error}")

    notify.send_telegram("\n".join(lines))

    # 지표·시트 어느 실패든 Actions run 을 빨간 X 로 (silent 방지 이중 안전망).
    return 1 if errors or sheet_error else 0


if __name__ == "__main__":
    sys.exit(main())
