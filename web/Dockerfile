FROM node:22.23.3-alpine3.24 AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# 비루트 nginx(8080 포트) 사용
FROM nginxinc/nginx-unprivileged:1.30.6-alpine
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
# D7: 런타임 /config.json. 기동 스크립트가 /tmp/config.json 으로 치환해 쓴다(docker-entrypoint.d 는 이미지가 자동 실행).
COPY config.json.template /usr/share/nginx/config.json.template
# 스크립트는 반드시 LF 여야 한다(CRLF 면 shebang 이 깨져 기동 실패). web/.gitattributes 가 LF 를 강제한다.
COPY --chmod=755 docker-entrypoint.d/30-config-json.sh /docker-entrypoint.d/30-config-json.sh
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
