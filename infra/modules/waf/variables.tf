variable "name" { type = string } # nesume-dev
variable "project" { type = string }
variable "env" { type = string }
variable "account_id" { type = string }
variable "region" { type = string }

variable "mode" {
  type        = string
  default     = "count"
  description = "count = 기록만(관찰), block = 차단. 관찰 절차는 docs/D17.md 7절"
  validation {
    condition     = contains(["count", "block"], var.mode)
    error_message = "mode 는 count 또는 block."
  }
}

variable "rate_limit" {
  type        = number
  default     = 1000
  description = "IP당 5분 요청 수 한도(결정2)"
}

variable "log_retention_days" {
  type    = number
  default = 14
}
