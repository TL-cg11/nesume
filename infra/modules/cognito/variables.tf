variable "project" {
  description = "프로젝트 이름. 리소스 이름 접두사"
  type        = string
  default     = "nesume"
}

variable "env" {
  description = "환경 이름(dev | staging | prod)"
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.env)
    error_message = "env must be one of dev, staging, prod."
  }
}

variable "region" {
  description = "AWS 리전. issuer / jwks_url 출력에 쓴다"
  type        = string
  default     = "ap-northeast-2"
}
