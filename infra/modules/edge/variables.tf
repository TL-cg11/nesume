variable "name" { type = string } # nesume-dev

variable "origin_domain" {
  type        = string
  description = "ALB DNS 이름(Ingress 가 만든 것). ALB 가 다시 만들어지면 바뀐다 → edge apply"
}

variable "origin_token" {
  type        = string
  sensitive   = true
  description = "x-origin-verify 값(base waf 모듈). WAF origin-verify 규칙이 대조한다"
}

variable "viewer_ip_header" {
  type        = string
  description = "WAF rate limit 이 IP 로 읽는 헤더(base waf 모듈)"
}

variable "price_class" {
  type        = string
  default     = "PriceClass_200" # 한국 엣지 포함. PriceClass_100 은 북미·유럽뿐
  description = "CloudFront 가격 등급"
}
