variable "project" { type = string } # nesume
variable "env" { type = string }     # dev
variable "region" { type = string }
variable "cluster_name" { type = string }
variable "app_log_group" { type = string }   # base logs 모듈 출력 /nesume/dev/app
variable "audit_log_group" { type = string } # /nesume/dev/audit
variable "fluent_bit_role_arn" { type = string }
variable "cloudwatch_agent_role_arn" { type = string }
variable "fluent_bit_chart_version" { type = string } # helm search repo eks/aws-for-fluent-bit
variable "rds_identifier" { type = string }
variable "alert_email" {
  description = "SNS 이메일 구독. 비우면 없음"
  type        = string
  default     = ""
}
variable "fluent_bit_namespace" {
  type    = string
  default = "logging"
}
variable "error_rate_threshold_percent" {
  description = "5xx 비율 알람 기준(5분)"
  type        = number
  default     = 2
}
variable "p95_threshold_ms" {
  description = "p95 지연 알람 기준(5분)"
  type        = number
  default     = 3000
}
variable "rds_connections_threshold" {
  description = "db.t4g.micro 의 max_connections 는 대략 80. 그 전에 알린다"
  type        = number
  default     = 60
}
variable "rds_free_storage_bytes" {
  description = "RDS 여유 스토리지 알람 기준(기본 2GB)"
  type        = number
  default     = 2147483648
}
variable "pod_restart_threshold" {
  description = "5분 동안 클러스터 전체 컨테이너 재시작 횟수 기준"
  type        = number
  default     = 5
}
# ---- D16 (alerts.tf) ----
variable "webhook_enabled" {
  description = "SNS → Lambda → Discord/Slack 웹훅 구독을 만든다. 먼저 앱 시크릿 JSON 에 ALERTS_WEBHOOK_URL 을 넣는다"
  type        = bool
  default     = false
}
variable "app_secret_arn" {
  description = "웹훅 URL 이 든 앱 시크릿(nesume/<env>/app) ARN. Lambda 가 읽는다"
  type        = string
}
variable "webhook_secret_key" {
  description = "앱 시크릿 JSON 안의 웹훅 URL 필드 이름"
  type        = string
  default     = "ALERTS_WEBHOOK_URL"
}
variable "collector_failed_days" {
  description = "수집 배치 연속 실패 알람 기준(일). tasks.md C4 '3회 연속 실패'"
  type        = number
  default     = 3
}
