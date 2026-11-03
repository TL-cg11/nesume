# dev compute: 올리고 내리는 단위(상시 가동, 필요할 때만 내린다). base 출력은 remote_state로 읽는다. base가 compute를 읽는 일은 없다.
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

# RDS 마스터 비밀번호. base 시크릿에서 읽는다(값은 Terraform 밖에서 1회 put-secret-value).
data "aws_secretsmanager_secret_version" "app" {
  secret_id = local.base.app_secret_arn
}

# ---------- NAT (가장 비싼 상시 비용. compute에 있어야 밤에 꺼진다) ----------
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${local.name}-nat" }
}

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = local.base.public_subnet_ids[0]
  tags          = { Name = local.name }
}

# 프라이빗 서브넷 기본 경로. 이게 없으면 노드가 EKS API·ECR에 못 나가 NotReady.
resource "aws_route" "private_nat" {
  route_table_id         = local.base.private_route_table_id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this.id
}

# ---------- EKS ----------
module "eks" {
  source             = "../../../modules/eks"
  name               = local.name
  cluster_role_arn   = local.base.eks_cluster_role_arn
  node_role_arn      = local.base.eks_node_role_arn
  public_subnet_ids  = local.base.public_subnet_ids
  private_subnet_ids = local.base.private_subnet_ids
  ci_role_arn        = local.base.ci_role_arn
  team_user_arns     = [for u in var.team_user_names : "arn:aws:iam::${local.base.account_id}:user/${u}"]

  # D20 임베딩 노드(bge-m3 embedder 전용, 온디맨드 1대). 비용만 쓸 때는 -var embedding_node_enabled=false
  embedding_node_enabled  = var.embedding_node_enabled
  embedding_capacity_type = var.embedding_capacity_type

  # SA 이름은 D5 차트 helpers(nesume.appServiceAccountName = <fullname>-app)와 글자 하나까지 같아야 한다.
  # release 이름이 nesume 이므로 fullname = nesume.
  pod_identities = {
    app   = { namespace = "dev", service_account = "nesume-app", role_arn = local.base.app_role_arn }
    batch = { namespace = "dev", service_account = "nesume-batch", role_arn = local.base.batch_role_arn }
    alb   = { namespace = "kube-system", service_account = "aws-load-balancer-controller", role_arn = local.base.alb_controller_role_arn }
    eso   = { namespace = "external-secrets", service_account = "external-secrets", role_arn = local.base.external_secrets_role_arn }
  }

  depends_on = [aws_route.private_nat] # 노드가 조인하려면 NAT 경로가 먼저
}

# ---------- RDS ----------
module "rds" {
  source                    = "../../../modules/rds"
  name                      = local.name
  vpc_id                    = local.base.vpc_id
  private_subnet_ids        = local.base.private_subnet_ids
  cluster_security_group_id = module.eks.cluster_security_group_id
  password                  = jsondecode(data.aws_secretsmanager_secret_version.app.secret_string)["DB_PASSWORD"]
  snapshot_identifier       = var.snapshot_identifier
}

# ---------- Helm 애드온 + dev 네임스페이스 ----------
module "addons" {
  source                         = "../../../modules/addons"
  cluster_name                   = module.eks.cluster_name
  region                         = local.region
  vpc_id                         = local.base.vpc_id
  alb_controller_chart_version   = var.alb_controller_chart_version
  external_secrets_chart_version = var.external_secrets_chart_version

  depends_on = [module.eks] # 노드그룹·애드온·Pod Identity 연결이 전부 끝난 뒤
}

# ---------- D14 로그·모니터링: Fluent Bit → CloudWatch Logs(app/audit 분리), Container Insights, 알람·SNS, 대시보드 ----------
# base 출력 fluent_bit_role_arn·cloudwatch_agent_role_arn 이 필요하다(base 를 먼저 apply).
module "observability" {
  source                    = "../../../modules/observability"
  project                   = "nesume"
  env                       = "dev"
  region                    = local.region
  cluster_name              = module.eks.cluster_name
  app_log_group             = local.base.app_log_group
  audit_log_group           = local.base.audit_log_group
  fluent_bit_role_arn       = local.base.fluent_bit_role_arn
  cloudwatch_agent_role_arn = local.base.cloudwatch_agent_role_arn
  fluent_bit_chart_version  = var.fluent_bit_chart_version
  rds_identifier            = local.name
  alert_email               = var.alert_email
  # D16: Discord/Slack 웹훅 구독(Lambda). 앱 시크릿에 ALERTS_WEBHOOK_URL 을 넣은 뒤 -var webhook_alerts_enabled=true
  app_secret_arn  = local.base.app_secret_arn
  webhook_enabled = var.webhook_alerts_enabled

  depends_on = [module.eks]
}
