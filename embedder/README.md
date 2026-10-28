# embedder — bge-m3 임베딩 서비스 (D20)

C3 임베딩 파이프라인이 호출하는 내부 전용 HTTP 서비스. TEI(`text-embeddings-router`) + `BAAI/bge-m3`를 한 이미지에 담는다.
app 이미지에는 torch·모델이 들어가지 않는다(`app/app/retrieval/embedder.py` 원칙). 서빙 선택 근거는 D 문서 `embedding-serving-analysis-2026-10-28.md`.

| 항목 | 값 |
|---|---|
| 서비스 주소(클러스터 안) | `http://nesume-embedder:8080` → 환경변수 `EMBEDDING_URL` (ConfigMap, 차트가 채운다) |
| 임베딩 | `POST /embed` 본문 `{"inputs": ["텍스트", ...], "normalize": true, "truncate": true}` → `[[1024 floats], ...]` |
| 헬스 | `GET /health` 200 |
| 모델 | `EMBEDDING_MODEL=bge-m3`, 1024차원, 코사인(정규화 출력). **입력은 2048 토큰에서 잘린다**(`MAX_BATCH_TOKENS`). C 는 512~1024 토큰 청크로 보낸다 |
| 배치 | 요청 1개에 최대 32 텍스트(`MAX_CLIENT_BATCH_SIZE`). 백엔드(ORT)는 내부적으로 8개씩 처리 |
| 리소스 | fp32 ONNX(onnxruntime) CPU. 10-28 로컬 실측(arm64 8코어 VM): 기동 65s, RSS 4.4GB, 피크 4.45GB, 800토큰×32건 61s. 전용 노드그룹 `nesume-dev-embedding`(m7g.large, taint `nesume.io/workload=embedding`), requests 4.5Gi / limits 6Gi |
| 왜 ONNX | 같은 모델을 `pytorch_model.bin`(candle 백엔드)으로 돌리면 CPU 에서 3배 이상 느렸다(같은 배치 205s). 모델 최대 길이 8192 로 워밍업하면 어텐션 메모리가 7GB 를 넘어 OOM → 2048 로 제한 |

## 이미지 빌드·푸시

태그는 app·web 처럼 git sha 지만, **`embedder/` 를 바꾼 커밋에서만** 빌드한다(매 커밋 2.5GB 빌드는 낭비). 보통은 CI `embedder` 워크플로(`.github/workflows/embedder.yml`, main 푸시 시 `embedder/**` 변경 또는 수동 실행)가 올린다.

로컬에서 올릴 때(arm64 PC 기준. x86 이면 `--platform linux/arm64` 로 buildx):

```powershell
$Sha = git rev-parse --short HEAD
docker login --username AWS --password (aws ecr get-login-password --region ap-northeast-2) 852138520969.dkr.ecr.ap-northeast-2.amazonaws.com
docker build -f embedder/Dockerfile -t "852138520969.dkr.ecr.ap-northeast-2.amazonaws.com/nesume/embedder:$Sha" embedder
docker push "852138520969.dkr.ecr.ap-northeast-2.amazonaws.com/nesume/embedder:$Sha"
```

`infra/scripts/up.ps1`·`deploy.ps1` 은 ECR `nesume/embedder` 의 **가장 최근 태그**를 집어 `image.embedder.tag` 로 넘긴다. 저장소가 비어 있으면 `embedder.enabled=false` 로 배포한다(app 은 뜨고 임베딩만 없음).

## 로컬 확인

```powershell
# docker-compose (profile embed). 첫 기동 때 모델을 내려받아 볼륨에 둔다(~2.3GB).
docker compose --profile embed up -d embedder
curl -s -X POST http://127.0.0.1:8081/embed -H "content-type: application/json" -d '{"inputs":["자기소개서 테스트"]}' | python -c "import sys,json; v=json.load(sys.stdin); print(len(v), len(v[0]))"
# 기대: 1 1024
```

클러스터에서:

```powershell
kubectl -n dev get pods -l app.kubernetes.io/component=embedder
kubectl -n dev port-forward svc/nesume-embedder 8081:8080
# 위 curl 그대로
```

## C 에 전달할 인터페이스

`app/app/retrieval/embedder.py` 의 `Embedder` 프로토콜 구현 1개(`HttpEmbedder`)만 추가하면 된다: `EMBEDDING_URL` 읽기, 64개씩 나눠 `POST /embed`, 응답 `list[list[float]]` 그대로 반환, 타임아웃·재시도(서비스가 노드 교체 중이면 수 분 불가). `app/app/config.py` `Settings` 에 `EMBEDDING_URL: str = ""`, `EMBEDDING_MODEL: str = "bge-m3"` 필드 추가 요청.
