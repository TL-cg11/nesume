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
}

resource "aws_eks_node_group" "default" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${var.name}-default"
  node_role_arn   = var.node_role_arn
  subnet_ids      = var.private_subnet_ids

  instance_types = ["t4g.medium"]
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
