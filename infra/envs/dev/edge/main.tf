# dev edge: HTTPS 앞단 CloudFront(11-03). compute 와 따로 둔다 — down 해도 배포(주소)는 남고, up 이 ALB 를 새로 만들면
# 이 레이어만 다시 apply 해 오리진을 바꾼다(up.ps1·infra.yml 이 helm 다음에 한다). ALB 가 없으면(down 상태) plan 이 실패한다.
locals {
  name   = "nesume-dev"
  region = "ap-northeast-2"
  base   = data.terraform_remote_state.base.outputs
}

data "terraform_remote_state" "base" {
  backend = "s3"
  config = {
    bucket = "nesume-tfstate-852138520969"
    key    = "envs/dev/base.tfstate"
    region = local.region
  }
}

# Ingress(dev/nesume)가 만든 ALB. 컨트롤러가 붙이는 태그로 찾는다(이름·DNS 는 만들 때마다 바뀐다).
data "aws_lb" "ingress" {
  tags = {
    "elbv2.k8s.aws/cluster" = local.name
    "ingress.k8s.aws/stack" = "dev/nesume"
  }
}

module "edge" {
  source           = "../../../modules/edge"
  name             = local.name
  origin_domain    = data.aws_lb.ingress.dns_name
  origin_token     = local.base.origin_verify_token
  viewer_ip_header = local.base.viewer_ip_header
}
