# D20 임베딩 서비스: HuggingFace Text Embeddings Inference(TEI) + BAAI/bge-m3 (1024차원, 정규화).
# 모델을 이미지에 굽는다: 클러스터 컨테이너는 readOnlyRootFilesystem 이고 프라이빗 서브넷에서 HF 다운로드를 하지 않는다.
# 빌드(arm64, 노드와 같아야 한다): docker buildx build --platform linux/arm64 -f embedder/Dockerfile -t <ECR>/nesume/embedder:<sha> embedder --push
# 로컬 x86 테스트: --build-arg TEI_IMAGE=ghcr.io/huggingface/text-embeddings-inference:cpu-1.9
# API: POST /embed {"inputs": ["..."]} -> [[float x 1024], ...]   GET /health   (TEI 기본 스키마)

ARG TEI_IMAGE=ghcr.io/huggingface/text-embeddings-inference:cpu-arm64-1.9

# --- fetch: ONNX 가중치·토크나이저만 내려받는다(pytorch_model.bin·colbert·sparse 헤드·이미지 제외, ~2.3GB) ---
# ONNX 를 쓰는 이유: TEI CPU 이미지는 ORT(onnxruntime) 백엔드가 기본이고, candle(pytorch_model.bin) 폴백은 CPU 에서
# 10배 이상 느렸다(10-28 로컬 실측: 32건×800토큰 205s). ORT 는 /model/onnx/model.onnx(+ 외부 데이터) 를 읽는다.
FROM python:3.12.16-slim-bookworm AS fetch
ARG MODEL_ID=BAAI/bge-m3
ARG MODEL_REVISION=main
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 HF_HUB_DISABLE_TELEMETRY=1
RUN pip install "huggingface_hub==2.3.0"
# 파일명은 위치 인자로 준다. `--include a b c` 는 hf CLI 가 "파일명 직접 지정"으로 해석해 --include 를 무시하고
# config.json 을 빠뜨렸다(10-28 실측: TEI 기동 시 `config.json not found`). 끝의 test 가 빌드 단계에서 잡는다.
RUN hf download "${MODEL_ID}" \
      config.json tokenizer.json tokenizer_config.json special_tokens_map.json \
      sentencepiece.bpe.model modules.json sentence_bert_config.json \
      config_sentence_transformers.json 1_Pooling/config.json \
      onnx/model.onnx onnx/model.onnx_data onnx/Constant_7_attr__value \
      --revision "${MODEL_REVISION}" --local-dir /model \
 && rm -rf /model/.cache \
 && ls -la /model /model/1_Pooling /model/onnx \
 && test -f /model/config.json && test -f /model/tokenizer.json && test -f /model/onnx/model.onnx

# --- runtime: TEI 바이너리 + 모델. 비루트(10001)·읽기 전용 루트에서 동작 ---
FROM ${TEI_IMAGE} AS runtime
COPY --from=fetch --chown=10001:10001 /model /model
# TEI 는 MODEL_ID 가 로컬 경로면 다운로드 없이 그대로 읽는다. 풀링은 /model/1_Pooling/config.json(CLS) 에서 가져온다.
# MAX_BATCH_TOKENS=2048: bge-m3 최대 길이 8192 로 워밍업하면 어텐션(16헤드×8192²×4B≈4GB/레이어)이 CPU 메모리를 넘는다
# (10-28 실측: 7GB 에서도 OOM). 2048 이면 피크 ~4.4GB. 입력은 2048 토큰에서 잘린다(C 는 512~1024 토큰 청크로 보낸다).
ENV MODEL_ID=/model \
    HF_HUB_OFFLINE=1 \
    PORT=8080 \
    MAX_CLIENT_BATCH_SIZE=32 \
    MAX_BATCH_TOKENS=2048 \
    MAX_CONCURRENT_REQUESTS=64 \
    JSON_OUTPUT=true
USER 10001
EXPOSE 8080
# ENTRYPOINT 는 베이스 이미지의 text-embeddings-router. 인자는 전부 ENV 로 준다.
