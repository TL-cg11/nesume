terraform {
  required_version = ">= 1.10"
  required_providers {
    aws  = { source = "hashicorp/aws", version = "~> 6.0" }
    helm = { source = "hashicorp/helm", version = "~> 3.0" }
    # D16 웹훅 Lambda 소스 zip
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
  }
}
