variable "name" { type = string } # nesume-dev
variable "account_id" { type = string }
variable "region" { type = string }
variable "github_repo" {
  type    = string
  default = "TL-cg11/nesume"
}
variable "github_branch" {
  type    = string
  default = "main"
}
variable "docs_bucket_arn" { type = string }
variable "kms_key_arn" { type = string }
variable "app_secret_arn" { type = string }
variable "cognito_user_pool_arn" { type = string }
variable "bedrock_region" {
  description = "Bedrock 호출 리전(요청 엔드포인트). Haiku 5.5 global 프로파일을 서울로 호출 (§1-4)"
  type        = string
  default     = "ap-northeast-2"
}
variable "bedrock_model_prefixes" {
  description = "허용할 파운데이션 모델 id 접두사. Anthropic(목표) + Amazon Nova(Anthropic 승인 전 임시, §1-4)"
  type        = list(string)
  default     = ["anthropic.", "amazon."]
}
