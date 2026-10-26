#!/bin/sh
# D7: 런타임 설정 /config.json 생성. nginx 공식 이미지가 /docker-entrypoint.d/*.sh 를 기동 시 순서대로 실행한다.
# 빌드 시점이 아니라 기동 시점에 Cognito 설정을 넣어 같은 이미지를 dev→staging→prod 로 승격한다(D4).
# readOnlyRootFilesystem(D5)이라 /usr/share/nginx/html 에는 못 쓴다. /tmp 에 쓰고 nginx 가 alias 로 서빙한다.
set -eu

: "${COGNITO_USER_POOL_ID:=}"
: "${COGNITO_WEB_CLIENT_ID:=}"
: "${COGNITO_ENDPOINT:=}"
: "${AUTH_FLOW:=USER_SRP_AUTH}"
export COGNITO_USER_POOL_ID COGNITO_WEB_CLIENT_ID COGNITO_ENDPOINT AUTH_FLOW

# 치환 대상 변수를 명시해 템플릿의 다른 '$' 가 바뀌지 않게 한다.
envsubst '${COGNITO_USER_POOL_ID} ${COGNITO_WEB_CLIENT_ID} ${COGNITO_ENDPOINT} ${AUTH_FLOW}' \
  < /usr/share/nginx/config.json.template > /tmp/config.json

echo "30-config-json.sh: wrote /tmp/config.json (authFlow=${AUTH_FLOW})"
