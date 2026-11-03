terraform {
  required_version = ">= 1.10"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" } # D17 WAF 평가 러너 비밀 헤더 값
  }
  backend "s3" {
    bucket       = "nesume-tfstate-852138520969"
    key          = "envs/dev/base.tfstate"
    region       = "ap-northeast-2"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = local.region
  default_tags {
    tags = { Project = "nesume", Env = "dev", ManagedBy = "terraform", Layer = "base" }
  }
}