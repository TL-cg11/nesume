"""C10 — 학습 갭 정리 (A11 매칭 결과 위의 얇은 계층).

gap: A11 대조 결과(covered/in_experience_only/missing)에서 **배워야 할 missing만** 골라
중요도순으로 C14 학습 로드맵 입력(`LearningGap`)으로 정리. 갭 계산은 A11이 하고, C10은 그 위.
`from_coverage` 어댑터가 A11 `coverage.Match`→순수 입력(`_Match`)으로 매핑(유일 통합 seam).
"""
