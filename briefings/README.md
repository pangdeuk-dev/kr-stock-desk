# briefings

평일 11시 채팅 에이전트가 여기에 `YYYY-MM-DD.json` 을 씁니다.
계좌 잔고·보유 수량은 넣지 않습니다. 로컬 앱이 예수금으로 주 수를 계산합니다.

```json
{
  "day": "2026-08-19",
  "headline": "한 줄 지시",
  "regime_note": "시장 해석",
  "news": [{"title": "제목", "source": "매체", "url": "https://..."}],
  "calls": [
    {
      "ticker": "005930",
      "name": "삼성전자",
      "action": "BUY",
      "limit_price": 251000,
      "reason": "이유"
    }
  ]
}
```

`action`은 `BUY` / `SELL` / `HOLD` / `AVG` 만 사용합니다.
