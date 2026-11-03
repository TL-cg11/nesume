variable "snapshot_identifier" {
  description = "RDS를 스냅샷에서 복원할 때만. 기본 null"
  type        = string
  default     = null
}
variable "alb_controller_chart_version" { type = string }
variable "external_secrets_chart_version" { type = string }
variable "team_user_names" {
  type    = list(string)
  default = ["kiseung", "sunjung", "seonyu"]
}
variable "embedding_node_enabled" {
  description = "D20 bge-m3 embedder 전용 노드그룹 생성 여부"
  type        = bool
  default     = true
}
variable "embedding_capacity_type" {
  description = "D20 임베딩 노드 ON_DEMAND|SPOT"
  type        = string
  default     = "ON_DEMAND"
}
variable "fluent_bit_chart_version" {
  description = "D14 helm search repo eks/aws-for-fluent-bit"
  type        = string
}
variable "alert_email" {
  description = "D14 알람 SNS 토픽 이메일 구독(비우면 구독 없음. 확인 메일의 링크를 눌러야 활성). Discord/Slack 웹훅 구독은 D16"
  type        = string
  default     = ""
}
variable "webhook_alerts_enabled" {
  description = "D16 SNS → Lambda → Discord/Slack 웹훅 구독. 앱 시크릿(nesume/dev/app) JSON 에 ALERTS_WEBHOOK_URL 을 넣은 뒤 true"
  type        = bool
  default     = false
}
