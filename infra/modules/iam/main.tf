# 역할 전부 base. Pod Identity 신뢰 정책은 클러스터 id가 필요 없어 compute를 매일 새로 만들어도 ARN이 안 바뀐다.
locals {
  # D16: compute 레이어 observability 모듈이 만드는 토픽(aws_sns_topic.alerts) 이름과 같아야 한다
  alerts_topic_arn = "arn:aws:sns:${var.region}:${var.account_id}:${var.name}-alerts"
  pod_identity_trust = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
}

# ---------- GitHub Actions OIDC + CI 역할 ----------
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"] # AWS가 자체 검증하므로 형식만 맞으면 된다
}

resource "aws_iam_role" "ci" {
  name = "nesume-github-ci"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike = {
          # 이름형(기본)과 immutable subject(id 포함)형 둘 다 허용. 저장소 이름이 바뀌어도 id 형은 유지된다.
          "token.actions.githubusercontent.com:sub" = [
            "repo:${var.github_repo}:ref:refs/heads/${var.github_branch}",
            "repo:${split("/", var.github_repo)[0]}@${var.github_owner_id}/${split("/", var.github_repo)[1]}@${var.github_repo_id}:ref:refs/heads/${var.github_branch}",
          ]
        }
      }
    }]
  })
}

# 1차: PowerUserAccess + PassRole(nesume-dev-* 역할 한정). 축소는 D17.
# PassRole 대상에 Pod Identity 역할 4개도 들어가야 한다(CreatePodIdentityAssociation이 PassRole을 요구).
resource "aws_iam_role_policy_attachment" "ci_power" {
  role       = aws_iam_role.ci.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

resource "aws_iam_role_policy" "ci_extra" {
  name = "terraform-compute"
  role = aws_iam_role.ci.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = "arn:aws:iam::${var.account_id}:role/${var.name}-*"
      },
      {
        Effect   = "Allow"
        Action   = "iam:CreateServiceLinkedRole"
        Resource = "*"
      },
    ]
  })
}

# ---------- EKS 클러스터·노드 역할 ----------
resource "aws_iam_role" "eks_cluster" {
  name = "${var.name}-eks-cluster"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "eks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_cluster" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role" "eks_node" {
  name = "${var.name}-eks-node"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

# ECR pull은 AmazonEC2ContainerRegistryPullOnly 하나로 끝. imagePullSecrets 없음.
resource "aws_iam_role_policy_attachment" "eks_node" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPullOnly",
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
  ])
  role       = aws_iam_role.eks_node.name
  policy_arn = each.value
}

# ---------- Pod Identity 역할 6개 (app·batch·ALB·ESO + D14 fluent-bit·cloudwatch-agent) ----------
resource "aws_iam_role" "pod" {
  for_each           = toset(["app", "batch", "alb-controller", "external-secrets", "fluent-bit", "cloudwatch-agent"])
  name               = "${var.name}-${each.key}"
  assume_role_policy = local.pod_identity_trust
}

# app: S3 문서 버킷 RW + ListBucket(/ready의 head_bucket), KMS, Bedrock(서울), Cognito admin, 앱 시크릿 읽기
resource "aws_iam_role_policy" "app" {
  name = "app"
  role = aws_iam_role.pod["app"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "${var.docs_bucket_arn}/*" },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = var.docs_bucket_arn },
      { Effect = "Allow", Action = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey*", "kms:DescribeKey"], Resource = var.kms_key_arn },
      # Haiku 5.5 global 프로파일: 호출은 서울의 inference-profile ARN, 실행은 AWS가 고른 리전의 foundation-model ARN.
      # 둘 다 있어야 한다(둘 중 하나만 있으면 AccessDenied). 리전 와일드카드가 global 프로파일의 리전 없는 모델 ARN도 덮는다.
      {
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = flatten([for p in var.bedrock_model_prefixes : [
          "arn:aws:bedrock:${var.bedrock_region}:${var.account_id}:inference-profile/global.${p}*",
          "arn:aws:bedrock:${var.bedrock_region}:${var.account_id}:inference-profile/apac.${p}*",
          "arn:aws:bedrock:*::foundation-model/${p}*",
        ]])
      },
      # D19 출력 레일: 안전 분류 모델(기본 us.meta.llama3-1-8b, 버지니아 교차 리전 프로파일). 모델 ARN 단위로 제한
      {
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = flatten([for p in var.output_rail_model_prefixes : [
          "arn:aws:bedrock:${var.output_rail_region}:${var.account_id}:inference-profile/us.${p}*",
          "arn:aws:bedrock:*::foundation-model/${p}*",
        ]])
      },
      # D16 알림: SNS 토픽(compute observability 모듈 nesume-<env>-alerts)에 Publish. base 는 compute 를 읽지 않으므로 이름으로
      { Effect = "Allow", Action = ["sns:Publish"], Resource = local.alerts_topic_arn },
      # Admin*: 역할 변경·MFA 조회. ListUsers·ListUsersInGroup: 역할 관리 화면 검색·운영자/멘토 목록(GET /admin/users)
      {
        Effect   = "Allow"
        Action   = ["cognito-idp:Admin*", "cognito-idp:ListUsers", "cognito-idp:ListUsersInGroup"]
        Resource = var.cognito_user_pool_arn
      },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = var.app_secret_arn },
    ]
  })
}

resource "aws_iam_role_policy" "batch" {
  name = "batch"
  role = aws_iam_role.pod["batch"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = var.app_secret_arn },
      # D16: 수집 배치(C4)가 emit("collector_failed") 로 알림을 보낼 때
      { Effect = "Allow", Action = ["sns:Publish"], Resource = local.alerts_topic_arn },
    ]
  })
}

# AWS 공식 정책 JSON 그대로
resource "aws_iam_policy" "alb_controller" {
  name   = "${var.name}-alb-controller"
  policy = file("${path.module}/files/alb-controller-iam-policy.json")
}

resource "aws_iam_role_policy_attachment" "alb_controller" {
  role       = aws_iam_role.pod["alb-controller"].name
  policy_arn = aws_iam_policy.alb_controller.arn
}

# D14 Fluent Bit: base 의 로그 그룹 2개에만 쓴다. 그룹은 Terraform 이 만들므로 CreateLogGroup 은 주지 않는다.
resource "aws_iam_role_policy" "fluent_bit" {
  name = "fluent-bit"
  role = aws_iam_role.pod["fluent-bit"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
        Resource = [for arn in var.log_group_arns : "${arn}:*"]
      },
      { Effect = "Allow", Action = ["logs:DescribeLogGroups"], Resource = "*" },
      # 감사 로그 그룹 KMS 키(logs 서비스가 대신 쓰지만 PutLogEvents 호출자에게도 GenerateDataKey 가 필요할 수 있다)
      { Effect = "Allow", Action = ["kms:GenerateDataKey*", "kms:Encrypt", "kms:Describe*"], Resource = var.audit_kms_key_arn },
    ]
  })
}

# D14 Container Insights(amazon-cloudwatch-observability 애드온의 cloudwatch-agent). AWS 관리형 정책 그대로.
resource "aws_iam_role_policy_attachment" "cloudwatch_agent" {
  role       = aws_iam_role.pod["cloudwatch-agent"].name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_role_policy" "external_secrets" {
  name = "external-secrets"
  role = aws_iam_role.pod["external-secrets"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      Resource = "arn:aws:secretsmanager:${var.region}:${var.account_id}:secret:nesume/dev/*"
    }]
  })
}
