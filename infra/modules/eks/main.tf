# trivy 예외(dev). 퍼블릭 엔드포인트는 팀원·GitHub Actions 러너(IP 가변)가 kubectl을 쓰려면 필요하다. IP 제한은 D17.
# 시크릿 암호화는 EKS 1.28+에서 AWS 소유 키로 기본 적용된다(encryption_config는 한 번 켜면 못 끈다). 컨트롤 플레인 로그는 매일 재생성하는 dev에서 비용만 든다.
#trivy:ignore:AVD-AWS-0040
#trivy:ignore:AVD-AWS-0041
#trivy:ignore:AVD-AWS-0039
#trivy:ignore:AVD-AWS-0038
resource "aws_eks_cluster" "this" {
  name     = var.name
  version  = var.cluster_version
  role_arn = var.cluster_role_arn

  vpc_config {
    subnet_ids              = concat(var.public_subnet_ids, var.private_subnet_ids)
    endpoint_public_access  = true # IP 제한은 D17
    endpoint_private_access = true
  }

  access_config {
    authentication_mode                         = "API_AND_CONFIG_MAP"
    bootstrap_cluster_creator_admin_permissions = true # OrganizationAccountAccessRole = admin
  }

  # 표준 지원이 끝나면 자동 업그레이드. 연장 지원(6배 요금)으로 넘어가지 않게 한다.
  upgrade_policy {
    support_type = "STANDARD"
  }

  enabled_cluster_log_types = ["api", "audit", "authenticator"] # D14
}

# 노드 전에 있어야 하는 애드온. 버전을 비우면 클러스터 버전의 기본값을 쓴다.
resource "aws_eks_addon" "pre_node" {
  for_each                    = toset(["vpc-cni", "kube-proxy", "eks-pod-identity-agent"])
  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = each.key
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  # D17: vpc-cni 가 NetworkPolicy 를 집행하게 한다(없으면 정책이 무시된다). 모드는 기본(standard) — 정책이 없는 파드는 그대로 통신
  configuration_values = each.key == "vpc-cni" ? jsonencode({ enableNetworkPolicy = "true" }) : null
}

resource "aws_eks_node_group" "default" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${var.name}-default"
  node_role_arn   = var.node_role_arn
  subnet_ids      = var.private_subnet_ids

  # 스팟은 타입 하나면 못 띄운다(10-27 실측: t4g.medium 단독 배치 점수 1/10, 아래 6개면 9/10).
  # 전부 arm64, 2 vCPU. *.medium 중 m6g/m7g는 ENI 한도로 노드당 파드 8개뿐이라 제외(시스템 파드만 15개).
  # t4g.medium 17, t4g.large 35, 나머지 large 29. ASG가 가용한 것을 고른다(capacity-optimized).
  instance_types = ["t4g.medium", "t4g.large", "m6g.large", "m7g.large", "c6g.large", "c7g.large"]
  ami_type       = "AL2023_ARM_64_STANDARD"
  capacity_type  = "SPOT"
  disk_size      = 20

  scaling_config {
    desired_size = 2
    min_size     = 2
    max_size     = 2
  }

  update_config {
    max_unavailable = 1
  }

  depends_on = [aws_eks_addon.pre_node]
}

# D20 임베딩(bge-m3) 전용 노드. embedder 파드 1개가 메모리 ~3GB 라 default(t4g.medium 스팟, 4GB)에는 안 들어간다.
# 온디맨드 1대: 스팟 회수 때 모델 재로드(1분+) 동안 임베딩이 전면 중단되는 것을 피한다.
# taint 로 embedder 파드만 올라온다. 관리형 애드온 DaemonSet(vpc-cni·kube-proxy·pod-identity-agent)은 기본 toleration 이 있다.
# 끄기: -var embedding_node_enabled=false (compute 비용 절약). 차트 쪽은 embedder.enabled=false.
resource "aws_eks_node_group" "embedding" {
  count           = var.embedding_node_enabled ? 1 : 0
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${var.name}-embedding"
  node_role_arn   = var.node_role_arn
  subnet_ids      = var.private_subnet_ids

  instance_types = var.embedding_instance_types
  ami_type       = "AL2023_ARM_64_STANDARD"
  capacity_type  = var.embedding_capacity_type
  disk_size      = 30 # embedder 이미지(모델 내장) ~2.5GB + app·web 이미지

  scaling_config {
    desired_size = 1
    min_size     = 1
    max_size     = 1
  }

  update_config {
    max_unavailable = 1
  }

  labels = { "nesume.io/workload" = "embedding" }

  taint {
    key    = "nesume.io/workload"
    value  = "embedding"
    effect = "NO_SCHEDULE"
  }

  depends_on = [aws_eks_addon.pre_node]
}

# 노드가 있어야 Running이 되는 애드온. 노드 전에 만들면 타임아웃.
resource "aws_eks_addon" "post_node" {
  for_each                    = toset(["coredns", "metrics-server"])
  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = each.key
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"
  depends_on                  = [aws_eks_node_group.default]
}

# ---------- 액세스 엔트리 (CLI로 만들면 다음날 사라진다. 반드시 여기에) ----------
resource "aws_eks_access_entry" "ci" {
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = var.ci_role_arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "ci_admin" {
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = aws_eks_access_entry.ci.principal_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
}

resource "aws_eks_access_entry" "team" {
  for_each      = toset(var.team_user_arns)
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "team_view" {
  for_each      = aws_eks_access_entry.team
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value.principal_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"
  access_scope { type = "cluster" }
}

resource "aws_eks_access_policy_association" "team_edit_dev" {
  for_each      = aws_eks_access_entry.team
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value.principal_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"
  access_scope {
    type       = "namespace"
    namespaces = ["dev"]
  }
}

# ---------- Pod Identity 연결 ----------
resource "aws_eks_pod_identity_association" "this" {
  for_each        = var.pod_identities
  cluster_name    = aws_eks_cluster.this.name
  namespace       = each.value.namespace
  service_account = each.value.service_account
  role_arn        = each.value.role_arn
  depends_on      = [aws_eks_addon.pre_node]
}
