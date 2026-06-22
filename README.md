# suhmbox

GitHub Actions cron 으로 도는 작은 알림봇 모음. 봇 하나 = `bots/<name>/` + `.github/workflows/<name>.yml`.

## 봇

| 봇 | 주기 | 내용 | 시크릿/변수 |
|---|---|---|---|
| `daily_market` | 매일 09:30 KST | CNN FGI · Crypto FGI · BTC MVRV 를 텔레그램 발송 + `market-log` 시트에 누적 기록 | `TELEGRAMBOTTOKEN_SUHMPLUS`(secret), `TELEGRAMCHATID_SUHMFUTURE`(var), `GOOGLESAJSON_SNOWBALLREADER`(secret), `SPREADSHEETID_SNOWBALL`(var) |

## 시크릿·변수

코드/yaml 에 토큰·키를 평문으로 박지 않는다. **Settings → Secrets and variables → Actions** 에 등록:

- **Secret** (민감): 봇 토큰, service account JSON 등
- **Variable** (비밀 아님): chat_id, spreadsheet id 등

yaml 에서 `${{ secrets.X }}` / `${{ vars.X }}` 로 주입 → Python `os.environ` 로 읽음.

## 실패 가시성

각 봇은 silent failure 를 피하도록 설계:
- 지표별 독립 try — 부분 실패해도 나머지는 발송, 실패 항목은 메시지에 ⚠️ 명시
- 하나라도 실패하면 `exit(1)` → Actions run 이 빨간 X (GitHub 알림)

## 로컬 실행

```bash
pip install -r requirements.txt
TELEGRAMBOTTOKEN_SUHMPLUS=... TELEGRAMCHATID_SUHMFUTURE=... python bots/daily_market/main.py
```
