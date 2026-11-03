terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
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