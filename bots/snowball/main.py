"""snowball 수익 리포트 봇.

매일 09:30 KST, suhm-snowball 시트 portfolio 탭의 NASDAQ 종목 수익을 텔레그램으로 발송.
시트가 GOOGLEFINANCE 로 현재가·이익을 계산하므로 봇은 NASDAQ 종목을 읽어 합산·포맷만 한다.

[데이터 매핑] portfolio 탭 (행1 헤더):
- 종목=col 1(B), 마켓=col 2(C), 투입금=col 10(K), 이익금=col 12(M), 손익비=col 13(N)
- 마켓 == 'NASDAQ' 인 행만 (토스·예수금 등 현금성 제외)
- 종목별 수익률은 시트 손익비(N), 전체 수익률은 sum(이익금)/sum(투입금) 직접 계산

[silent failure 방지] 시트 읽기·발송 실패 시 텔레그램 에러통지(best-effort) + 예외 전파
(GHA 빨간 X). 봇1 과 동일 원칙.
"""

from __future__ import annotations

import json
import os
import sys

import gspread

from shared import notify

WORKSHEET = "portfolio"
COL_NAME = 1
COL_MARKET = 2
COL_INVESTED = 10
COL_PROFIT = 12
COL_RATE = 13


def _won(text: str) -> float:
    """'₩9,114,188' → 9114188.0. 빈 칸은 0."""
    return float(text.replace("₩", "").replace(",", "").strip() or 0)


def _fmt_won(v: float) -> str:
    """9114188.0 → '₩9.1M' (백만 단위, trailing zero 제거)."""
    return f"₩{round(v / 1e6, 1):g}M"


def fetch_nasdaq_items() -> list[dict]:
    sa = json.loads(os.environ["GOOGLESAJSON_SNOWBALLREADER"])
    gc = gspread.service_account_from_dict(sa)
    sh = gc.open_by_key(os.environ["SPREADSHEETID_SNOWBALL"])
    rows = sh.worksheet(WORKSHEET).get_all_values()
    items: list[dict] = []
    for r in rows[1:]:
        if len(r) <= COL_RATE or r[COL_MARKET] != "NASDAQ":
            continue
        items.append(
            {
                "name": r[COL_NAME],
                "invested": _won(r[COL_INVESTED]),
                "profit": _won(r[COL_PROFIT]),
                "rate": r[COL_RATE].strip(),  # '546.85%'
            }
        )
    return items


def build_message(items: list[dict]) -> str:
    total_profit = sum(i["profit"] for i in items)
    total_invested = sum(i["invested"] for i in items)
    total_rate = round(total_profit / total_invested * 100) if total_invested else 0

    lines = [f"Snowball 수익: {_fmt_won(total_profit)} ({total_rate:,}%)"]
    for i in items:
        rate = round(float(i["rate"].rstrip("%") or 0))  # 종목별은 시트 손익비 그대로
        lines.append(f"  {i['name']}: {_fmt_won(i['profit'])} ({rate:,}%)")
    return "\n".join(lines)


def main() -> int:
    try:
        items = fetch_nasdaq_items()
        if not items:
            notify.send_telegram("⚠️ snowball: NASDAQ 종목을 찾지 못함 (시트 구조 변경?)")
            return 1
        notify.send_telegram(build_message(items))
        return 0
    except Exception as e:
        # silent 방지 — 실패 사유를 텔레그램으로(best-effort) + 예외 전파로 Actions run 실패.
        try:
            notify.send_telegram(f"⚠️ snowball 리포트 실패: {type(e).__name__}: {e}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    sys.exit(main())
