# HTTPS: 도메인이 없어 CloudFront 기본 인증서(*.cloudfront.net)로 TLS 를 끝내고 ALB(HTTP 80)로 넘긴다(11-03).
# 뷰어 HTTP → HTTPS 리다이렉트, HSTS. 캐시는 해시 붙은 정적 파일(/assets/*)만 — /api·index.html·config.json 은 그대로 통과.
# ALB 직접 접근은 base 가 막는다: SG(CloudFront 대역만) + WAF origin-verify(아래 x-origin-verify 헤더).
# 도메인이 생기면 aliases + ACM(us-east-1) 인증서로 viewer_certificate 만 바꾼다.

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

# Host 를 뺀 뷰어 헤더·쿠키·쿼리 전부(Authorization 포함). Host 는 ALB DNS 로 간다 — Ingress 에 host 규칙이 없다.
data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

# WAF rate limit(base waf 모듈)이 IP 로 읽는 헤더. 클라이언트가 같은 이름을 보내도 여기서 덮어쓴다.
# X-Forwarded-For 는 맨 앞 값을 클라이언트가 정할 수 있어 쓰지 않는다.
resource "aws_cloudfront_function" "viewer_ip" {
  name    = "${var.name}-viewer-ip"
  runtime = "cloudfront-js-2.0"
  comment = "Set ${var.viewer_ip_header} to the viewer IP for WAF rate limiting"
  publish = true
  code    = <<-JS
    function handler(event) {
      event.request.headers['${var.viewer_ip_header}'] = { value: event.viewer.ip };
      return event.request;
    }
  JS
}

# nginx 가 nosniff·X-Frame-Options·Referrer-Policy·CSP 를 이미 붙인다. 여기서는 HTTPS 에서만 의미 있는 HSTS 만 더한다.
resource "aws_cloudfront_response_headers_policy" "hsts" {
  name    = "${var.name}-hsts"
  comment = "HSTS (other security headers come from nginx)"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = false # cloudfront.net 하위 도메인은 우리 것이 아니다
      preload                    = false
      override                   = true
    }
  }
}

# trivy 예외(dev): 0010 접근 로그 — WAF 로그(aws-waf-logs-nesume-dev)가 같은 요청을 남긴다.
#                 0011 CloudFront WAF — ALB 의 리전 Web ACL(D17)이 같은 요청을 본다(규칙·대시보드·알람을 그대로 쓰려고).
#                 0013 최소 TLS — 기본 인증서는 minimum_protocol_version 을 못 정한다(도메인 + ACM 이 생기면 TLSv1.2_2021).
#trivy:ignore:AVD-AWS-0010
#trivy:ignore:AVD-AWS-0011
#trivy:ignore:AVD-AWS-0013
resource "aws_cloudfront_distribution" "this" {
  enabled         = true
  comment         = var.name
  is_ipv6_enabled = true
  http_version    = "http2and3"
  price_class     = var.price_class

  origin {
    origin_id   = "alb"
    domain_name = var.origin_domain

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only" # ALB 는 인증서가 없어 80 만 연다(오리진 구간은 AWS 망 + 비밀 헤더)
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60 # 기본 30. LLM 응답 대기. ALB idle·nginx proxy_read_timeout 도 60 (할당량 없이 최대)
      origin_keepalive_timeout = 5
    }

    custom_header {
      name  = "x-origin-verify"
      value = var.origin_token
    }
  }

  default_cache_behavior {
    target_origin_id           = "alb"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.hsts.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.viewer_ip.arn
    }
  }

  # Vite 빌드 산출물(파일 이름에 해시). 배포마다 이름이 바뀌어 무효화가 필요 없다.
  ordered_cache_behavior {
    path_pattern               = "/assets/*"
    target_origin_id           = "alb"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.hsts.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.viewer_ip.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = { Name = var.name }
}
