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
