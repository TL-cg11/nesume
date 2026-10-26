# helm/kubernetes provider 설정은 루트(envs/dev/compute)에 있다.
# IRSA annotation은 없다. Pod Identity 연결이 네임스페이스/SA 이름으로 역할을 붙인다.
resource "helm_release" "alb_controller" {
  name       = "aws-load-balancer-controller"
  namespace  = "kube-system"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = var.alb_controller_chart_version
  timeout    = 600

  values = [yamlencode({
    clusterName = var.cluster_name
    region      = var.region
    vpcId       = var.vpc_id
    serviceAccount = {
      create = true
      name   = "aws-load-balancer-controller" # Pod Identity 연결 kube-system/aws-load-balancer-controller 와 일치
    }
  })]
}

resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  namespace        = "external-secrets"
  create_namespace = true
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  version          = var.external_secrets_chart_version
  timeout          = 600

  values = [yamlencode({
    installCRDs = true
    serviceAccount = {
      name = "external-secrets" # Pod Identity 연결 external-secrets/external-secrets 와 일치
    }
  })]
}

resource "kubernetes_namespace" "dev" {
  metadata {
    name = "dev"
    labels = {
      "pod-security.kubernetes.io/warn" = "restricted" # enforce는 D17
    }
  }
}
