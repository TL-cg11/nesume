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
    # Service 뮤테이팅 웹훅은 끈다. 10-27 실측: ESO와 동시에 설치되면 ESO의 webhook Service 생성이
    # 이 웹훅(아직 엔드포인트 없음)에 막혀 release가 failed로 남는다. Service type=LoadBalancer는 안 쓴다(ALB는 Ingress).
    enableServiceMutatorWebhook = false
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
      # D17: restricted 를 강제한다. 차트 파드는 _helpers.tpl securityContext 로 충족(docs/D17.md 2.4).
      "pod-security.kubernetes.io/enforce"         = "restricted"
      "pod-security.kubernetes.io/enforce-version" = "latest"
      "pod-security.kubernetes.io/audit"           = "restricted"
      "pod-security.kubernetes.io/warn"            = "restricted"
    }
  }
}
