variable "name" { type = string } # nesume-dev
variable "account_id" { type = string }
variable "region" { type = string }

variable "trail_retention_days" {
  type        = number
  default     = 365
  description = "CloudTrail 로그 S3 보관 일수"
}

variable "config_enabled" {
  type        = bool
  default     = true
  description = "AWS Config 기록(Security Hub 점검의 근거). 발표 뒤 비용을 끊으려면 false(docs/D17.md 결정10)"
}
