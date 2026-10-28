# C 기능 로컬 E2E 데모 도구

운영 기능이 아직 없는 부분을 **로컬에서만** 메우는 임시 도구입니다. 제품 코드(`app/`)가 아니며,
아래 "없어지는 조건"이 충족되면 해당 파일을 삭제합니다.

| 파일 | 역할 | 없어지는 조건 |
|---|---|---|
| `demo_vectors.py` | 사용자 프로필 + 실제 공고(활성)에 **합성 벡터** 부착 → 추천 화면이 뜨게 함(순서 무의미) | D 임베더(bge-m3 서빙) 연결 → C3 실임베딩 경로가 대신 |
| `collect_kmooc.py` | K-MOOC 수집 + 제목으로 역량 키(`competency_keys`) 태깅 → 로드맵 매칭 | K-MOOC 역량 키 색인이 제품 코드에 들어올 때 |

실제 공고·훈련과정 수집은 제품 배치를 씁니다: `python -m app.batch.jobs_collector --source work24_open|work24|kmooc|seoul`.

## 실행 (Docker 스택 기동 후)

```bash
set -a; . ./.env; set +a
# 1) 실제 공채속보 공고 수집(제품 배치)
docker compose exec -T -e WORK24_JOB_API_KEY -e WORK24_API_BASE_URL app python -m app.batch.jobs_collector --source work24_open
# 2) 합성 벡터(사용자 sub 지정)
docker compose exec -T app python - <사용자 sub> < tools/c-e2e-demo/demo_vectors.py
# 3) K-MOOC 강좌 + 역량 키(로드맵용)
docker compose exec -T -e KMOOC_API_KEY app python - < tools/c-e2e-demo/collect_kmooc.py
```

## 주의

- API 키는 `.env`(gitignore)로만 주입하고 커밋하지 않습니다.
- 합성 벡터는 데모 전용이며 `[DEMO]`로 표시됩니다(재실행 시 이것만 지우고 다시 만듦).
