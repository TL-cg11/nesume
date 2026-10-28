# C 기능 로컬 E2E 데모 스크립트

C 담당 기능(공고 추천·학습 로드맵·지원 현황)을 **로컬에서 처음부터 끝까지(E2E)** 돌려보기 위한 데모용 수집·시드 스크립트입니다. 제품 코드(`app/`)가 아니라 로컬 데모 도구입니다.

## 스크립트

| 파일 | 역할 |
|---|---|
| `seed_e2e.py` | 데모용 시드: job_postings + JobPostingEmbedding(합성 벡터) + UserProfileEmbedding + LearningContent |
| `collect_kmooc.py` | 실제 K-MOOC(`apis.data.go.kr`) 강좌 수집 → `LearningContent(source=kmooc, mode=online)`, 실제 강좌 링크 |
| `collect_work24.py` | 실제 WORK24 국민내일배움카드 훈련과정 수집 → `LearningContent(source=work24, mode=offline)`, 실제 과정 링크 |

## 실행 (Docker 스택 기동 후)

컨테이너 내부에서 실행합니다. 외부 API 키는 환경변수로 주입(커밋 금지):

```bash
docker compose exec -T app python - < tools/c-e2e-demo/seed_e2e.py
docker compose exec -T -e KMOOC_API_KEY=... app python - < tools/c-e2e-demo/collect_kmooc.py
docker compose exec -T -e WORK24_TRAINING_API_KEY=... app python - < tools/c-e2e-demo/collect_work24.py
```

## 주의

- **API 키는 `.env`(gitignore)로만** 주입하고 커밋하지 않습니다.
- 합성 벡터·시드 데이터는 데모 전용이며 제품 데이터가 아닙니다.
- `collect_work24.py`는 데모 품질입니다. 정식 제품 기능으로 승격 시 별도 Plan + PR이 필요합니다.
