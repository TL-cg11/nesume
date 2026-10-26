"""C7 — 레이트리밋 / 호출 예산 (앱단 per-user·session 상태 쿼터).

policy  : 한도·시간창·임계치(env 조정 가능).
rules   : 창 카운터 판정(순수).
store   : RateLimitStore 인터페이스 + 인메모리(개발/테스트)·Postgres(운영) 구현.
service : check / record / record_violation 오케스트레이션.

경계(docs/C7.md): C7=시간 누적 상태만. per-call 토큰상한=A8, per-query 분류=A3, IP=D WAF, 수집예산=C4.
"""
