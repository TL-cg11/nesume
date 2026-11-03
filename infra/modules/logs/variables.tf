variable "project" { type = string }
variable "env" { type = string }
variable "region" { type = string }
variable "account_id" { type = string }
variable "app_retention_in_days" {
  description = "앱(접근·오류) 로그 보존 일수"
  type        = number
  default     = 30
}
variable "audit_retention_in_days" {
  description = "감사 로그 보존 일수(spec 10.2: 90일)"
  type        = number
  default     = 90
}
