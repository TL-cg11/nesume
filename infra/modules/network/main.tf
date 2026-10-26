# VPC·서브넷·IGW·라우팅·S3 게이트웨이 엔드포인트. NAT는 없다.
# 프라이빗 라우트 테이블은 기본 경로를 비워 둔다. 0.0.0.0/0 -> NAT 경로는 compute가 aws_route로 추가한다.
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
