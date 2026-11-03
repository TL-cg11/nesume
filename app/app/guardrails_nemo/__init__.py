"""C16 NeMo Guardrails 2차 보강 (spec 12.2, docs/C16.md).

A3 규칙 분류기 **뒤**에서 예시 문장 임베딩 유사도로 의도를 고른다. LLM 을 쓰지 않는다.
판정은 올리기만 한다(allow → flag·block). A3 가 막은 것을 풀지 않는다.

`nemoguardrails` 는 앱 이미지에 없다(약 276MB) — 평가·시험에서만 설치해 쓴다(`requirements-nemo.txt`).
실행 경로 연결(Guardrail 레일 포트)은 발표 뒤 A·D 협의 후.
"""
