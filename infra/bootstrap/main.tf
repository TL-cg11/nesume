# bootstrap: Terraform 원격 state 버킷·ECR 저장소.
# 이 디렉터리만 로컬 state를 쓴다. 나머지 레이어(envs/dev/{base,compute})는 여기서 만든 버킷을 backend로 쓴다.
# 잠금은 S3 네이티브 lockfile(use_lockfile, Terraform 1.10+). DynamoDB 테이블은 쓰지 않는다.
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = var.project, ManagedBy = "terraform", Layer = "bootstrap" }
  }
}

variable "region" {
  type    = string
  default = "ap-northeast-2"
}
variable "project" {
  type    = string
  default = "nesume"
}

data "aws_caller_identity" "me" {}

resource "aws_s3_bucket" "tfstate" {
  bucket = "${var.project}-tfstate-${data.aws_caller_identity.me.account_id}"
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration { status = "Enabled" }
}

# trivy 예외: tfstate 버킷은 AWS 관리 키(aws/s3)의 SSE-KMS면 충분하다. CMK를 만들면 bootstrap이 KMS에 의존하게 된다.
#trivy:ignore:AVD-AWS-0132
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
    rules = [
      {
        rulePriority = 1
        description  = "expire untagged images after 7 days"
        selection    = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 7 }
        action       = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "keep last 30 tagged images"
        selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 30 }
        action       = { type = "expire" }
      },
    ]
  })
}

output "tfstate_bucket" { value = aws_s3_bucket.tfstate.bucket }
output "ecr_urls" { value = { for k, r in aws_ecr_repository.repo : k => r.repository_url } }
