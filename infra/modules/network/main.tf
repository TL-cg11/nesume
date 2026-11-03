# VPC·서브넷·IGW·라우팅·S3 게이트웨이 엔드포인트. NAT는 없다.
# 프라이빗 라우트 테이블은 기본 경로를 비워 둔다. 0.0.0.0/0 -> NAT 경로는 compute가 aws_route로 추가한다.
# trivy 예외(dev): VPC Flow Logs는 비용 대비 쓸 일이 없다. 필요해지면 D17에서 켠다.
#trivy:ignore:AVD-AWS-0178
resource "aws_vpc" "this" {
  cidr_block           = var.cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = var.name }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = var.name }
}

# trivy 예외: 퍼블릭 서브넷은 ALB·NAT 전용이고 노드는 프라이빗에 있다. 퍼블릭 IP 자동 할당은 의도된 것.
#trivy:ignore:AVD-AWS-0164
resource "aws_subnet" "public" {
  count                   = length(var.public_cidrs)
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.public_cidrs[count.index]
  availability_zone       = var.azs[count.index]
  map_public_ip_on_launch = true
  tags = {
    Name                     = "${var.name}-public-${var.azs[count.index]}"
    "kubernetes.io/role/elb" = "1" # ALB 컨트롤러가 인터넷용 ALB 서브넷을 찾는 태그
  }
}

resource "aws_subnet" "private" {
  count             = length(var.private_cidrs)
  vpc_id            = aws_vpc.this.id
  cidr_block        = var.private_cidrs[count.index]
  availability_zone = var.azs[count.index]
  tags = {
    Name                              = "${var.name}-private-${var.azs[count.index]}"
    "kubernetes.io/role/internal-elb" = "1"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name}-public" }
}

resource "aws_route" "public_igw" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# 기본 경로 없음. compute가 NAT 경로를 넣는다.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name}-private" }
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# S3 게이트웨이 엔드포인트(무료). ECR 레이어·tfstate·문서 버킷 트래픽이 NAT를 안 탄다.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.public.id, aws_route_table.private.id]
  tags              = { Name = "${var.name}-s3" }
}

# ALB 프런트엔드 SG. 80 은 CloudFront 오리진용 IP 대역(관리형 프리픽스 리스트)에서만 연다 — HTTPS 는 CloudFront 가 끝낸다
# (envs/dev/edge). Ingress 주석 alb.ingress.kubernetes.io/security-groups 가 이름(Name 태그)으로 찾아 붙이고,
# 노드 쪽 규칙은 컨트롤러의 공유 백엔드 SG(manage-backend-security-group-rules)가 맡는다. 남의 CloudFront 배포도
# 이 대역에서 오므로 이것만으로는 부족하다 — WAF origin-verify 규칙(비밀 헤더)이 나머지를 막는다.
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "alb" {
  name        = "${var.name}-alb"
  description = "ALB frontend - HTTP from CloudFront origin-facing only"
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${var.name}-alb" }
}

resource "aws_vpc_security_group_ingress_rule" "alb_cloudfront" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from CloudFront"
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_egress_rule" "alb_vpc" {
  security_group_id = aws_security_group.alb.id
  description       = "To targets (pod IPs) in the VPC"
  cidr_ipv4         = var.cidr
  ip_protocol       = "-1"
}
