{{/*
Chart name
*/}}
{{- define "nesume.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified release name. release "nesume" + chart "nesume" -> "nesume"
*/}}
{{- define "nesume.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "nesume.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels (no component). Use with a component label added by the caller.
*/}}
{{- define "nesume.labels" -}}
helm.sh/chart: {{ include "nesume.chart" . }}
app.kubernetes.io/name: {{ include "nesume.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels for a component. Usage: {{ include "nesume.selectorLabels" (dict "root" . "component" "app") }}
*/}}
{{- define "nesume.selectorLabels" -}}
app.kubernetes.io/name: {{ include "nesume.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Image references
*/}}
{{- define "nesume.image" -}}
{{- $reg := .root.Values.image.registry -}}
{{- $img := .image -}}
{{- $tag := required (printf "image.%s.tag is required (set to git sha, or 'local' for kind)" .name) $img.tag -}}
{{- if $reg }}{{ printf "%s/%s:%s" $reg $img.repository $tag }}{{ else }}{{ printf "%s:%s" $img.repository $tag }}{{ end }}
{{- end }}

{{- define "nesume.appImage" -}}
{{ include "nesume.image" (dict "root" . "image" .Values.image.app "name" "app") }}
{{- end }}

{{- define "nesume.webImage" -}}
{{ include "nesume.image" (dict "root" . "image" .Values.image.web "name" "web") }}
{{- end }}

{{- define "nesume.embedderImage" -}}
{{ include "nesume.image" (dict "root" . "image" .Values.image.embedder "name" "embedder") }}
{{- end }}

{{/*
Resource names shared across templates
*/}}
{{- define "nesume.configMapName" -}}
{{ include "nesume.fullname" . }}-config
{{- end }}

{{- define "nesume.secretName" -}}
{{ include "nesume.fullname" . }}-secret
{{- end }}

{{- define "nesume.appServiceName" -}}
{{ include "nesume.fullname" . }}-app
{{- end }}

{{- define "nesume.webServiceName" -}}
{{ include "nesume.fullname" . }}-web
{{- end }}

{{- define "nesume.postgresServiceName" -}}
{{ include "nesume.fullname" . }}-postgres
{{- end }}

{{- define "nesume.embedderServiceName" -}}
{{ include "nesume.fullname" . }}-embedder
{{- end }}

{{/*
D20: app·batch 가 쓰는 임베딩 서비스 URL. config.EMBEDDING_URL 이 비어 있으면 차트 안의 embedder Service 를 가리킨다.
embedder 를 끄고 외부 서빙을 쓰려면 config.EMBEDDING_URL 을 직접 준다.
*/}}
{{- define "nesume.embeddingUrl" -}}
{{- if .Values.config.EMBEDDING_URL }}{{ .Values.config.EMBEDDING_URL }}
{{- else if .Values.embedder.enabled }}{{ printf "http://%s:%d" (include "nesume.embedderServiceName" .) (int .Values.embedder.service.port) }}
{{- end }}
{{- end }}

{{- define "nesume.appServiceAccountName" -}}
{{ include "nesume.fullname" . }}-app
{{- end }}

{{- define "nesume.batchServiceAccountName" -}}
{{ include "nesume.fullname" . }}-batch
{{- end }}

{{/*
Pod-level security context (app uid 10001)
*/}}
{{- define "nesume.appPodSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{/*
Container-level security context (shared by app/migrate/batch/web)
*/}}
{{- define "nesume.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end }}

{{/*
envFrom: ConfigMap + Secret. Secret is created by secret.yaml (kind) or ExternalSecret (AWS); the name is the same.
*/}}
{{- define "nesume.envFrom" -}}
- configMapRef:
    name: {{ include "nesume.configMapName" . }}
- secretRef:
    name: {{ include "nesume.secretName" . }}
{{- end }}

{{/*
initContainer that waits for the in-chart Postgres (kind only)
*/}}
{{- define "nesume.waitForDb" -}}
{{- if .Values.postgres.enabled }}
- name: wait-for-db
  image: {{ .Values.postgres.waitImage }}
  imagePullPolicy: IfNotPresent
  command:
    - sh
    - -c
    - |
      until nc -z "$DB_HOST" "$DB_PORT"; do echo "waiting for $DB_HOST:$DB_PORT"; sleep 2; done
  env:
    - name: DB_HOST
      valueFrom:
        configMapKeyRef:
          name: {{ include "nesume.configMapName" . }}
          key: DB_HOST
    - name: DB_PORT
      valueFrom:
        configMapKeyRef:
          name: {{ include "nesume.configMapName" . }}
          key: DB_PORT
  securityContext:
    {{- include "nesume.containerSecurityContext" . | nindent 4 }}
    runAsNonRoot: true
    runAsUser: 10001
  resources:
    requests: { cpu: 10m, memory: 16Mi }
    limits: { cpu: 50m, memory: 32Mi }
{{- end }}
{{- end }}

{{/*
D17 NetworkPolicy 이그레스 조각 (templates/networkpolicy.yaml). 들여쓰기는 호출하는 쪽 nindent.
*/}}
{{- define "nesume.np.dbEgress" -}}
# DB(RDS, 프라이빗 서브넷). 파드도 같은 서브넷 IP 를 쓰지만 5432 로 듣는 파드는 없다
- to:
    {{- range .Values.networkPolicy.dbCidrs }}
    - ipBlock: { cidr: {{ . | quote }} }
    {{- end }}
  ports:
    - { protocol: TCP, port: {{ .Values.networkPolicy.dbPort }} }
{{- end }}

{{- define "nesume.np.embedderEgress" -}}
- to:
    - podSelector:
        matchLabels:
          {{- include "nesume.selectorLabels" (dict "root" . "component" "embedder") | nindent 10 }}
  ports:
    - { protocol: TCP, port: {{ .Values.embedder.containerPort }} }
{{- end }}

{{- define "nesume.np.awsEgress" -}}
# 밖으로 HTTPS(Bedrock·Cognito JWKS·S3·STS·Secrets Manager). VPC 안 443 은 막는다(VPC 엔드포인트가 생기면 그 CIDR 로 좁힌다)
- to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except: [{{ .Values.networkPolicy.vpcCidr | quote }}]
  ports:
    - { protocol: TCP, port: 443 }
# EKS Pod Identity 에이전트(노드 링크 로컬). IMDS(169.254.169.254)는 열지 않는다
- to:
    - ipBlock: { cidr: 169.254.170.23/32 }
  ports:
    - { protocol: TCP, port: 80 }
{{- end }}
