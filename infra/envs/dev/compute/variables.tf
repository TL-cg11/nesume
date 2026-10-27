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
