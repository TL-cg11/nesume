# bootstrap: Terraform 원격 state 버킷·잠금 테이블·ECR 저장소.
# 이 디렉터리만 로컬 state를 쓴다. 나머지 환경(D8)은 여기서 만든 버킷을 backend로 쓴다.
# apply는 AWS 크레딧 도착 후. 그 전에는 init -backend=false / validate / fmt -check까지만 확인한다.
terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

provider "aws" {
  region = var.region
}

variable "region" { default = "ap-northeast-2" }
variable "project" { default = "nesume" }

data "aws_caller_identity" "me" {}

resource "aws_s3_bucket" "tfstate" {
  bucket = "${var.project}-tfstate-${data.aws_caller_identity.me.account_id}"
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "tflock" {
  name         = "${var.project}-tflock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
}

# IMMUTABLE: 같은 sha 태그를 덮어쓰지 못하게 ECR 차원에서 강제한다(README 태그 규칙).
resource "aws_ecr_repository" "repo" {
  for_each             = toset(["app", "web"])
  name                 = "${var.project}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "KMS" }
}

resource "aws_ecr_lifecycle_policy" "repo" {
  for_each   = aws_ecr_repository.repo
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "expire untagged images after 7 days"
      selection    = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 7 }
      action       = { type = "expire" }
    }]
  })
}

output "tfstate_bucket" { value = aws_s3_bucket.tfstate.bucket }
output "ecr_urls" { value = { for k, r in aws_ecr_repository.repo : k => r.repository_url } }
