variable "name" { type = string } # nesume-dev
variable "account_id" { type = string }
variable "region" { type = string }

variable "trail_retention_days" {
  type        = number
  default     = 365
  description = "CloudTrail 로그 S3 보관 일수"
}
