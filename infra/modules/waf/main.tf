# D17 WAF: ALB 앞단 Web ACL (spec 277행). base 레이어 — ALB 는 매일 새로 만들어져도 ACL 은 그대로 두고
# Ingress 주석(alb.ingress.kubernetes.io/wafv2-acl-arn)으로 붙인다(ALB 컨트롤러 IAM 에 wafv2:AssociateWebACL 있음).
# 결정(docs/D17.md): Rate Limit IP당 5분 1,000건(결정2) · 평가 러너 비밀 헤더는 Rate Limit 에서만 제외(결정1)
#                  · Count 로 관찰 뒤 Block(결정6) · 본문 크기 규칙은 자소서 본문을 막을 수 있어 Count 고정.

locals {
  block = var.mode == "block"

  # 순서대로 평가. Count 모드에서는 끝내지 않으므로 순서는 Block 때의 의미다.
  managed_rule_groups = [
    { name = "AWSManagedRulesAmazonIpReputationList", priority = 10 },
    { name = "AWSManagedRulesKnownBadInputsRuleSet", priority = 20 },
    { name = "AWSManagedRulesCommonRuleSet", priority = 30 },
  ]

  # Block 모드에서도 Count 로만 두는 규칙(오탐이 확인된 것만 여기에 더한다)
  count_only_rules = {
    AWSManagedRulesCommonRuleSet = [
      "SizeRestrictions_BODY", # 8KB 넘는 자소서 본문 저장·다듬기
      "GenericLFI_BODY",       # 보안 직무 문장(`../../etc/passwd`) — 글 입력 경로 밖은 아래 lfi-body-outside-text 가 막는다
    ]
  }

  # GenericLFI_BODY 를 풀어 주는 글 입력 경로(관찰 7건이 난 곳, 결정11). 앱은 이 본문을 파일 경로로 쓰지 않는다.
  lfi_text_paths = ["/api/writing/", "/api/resumes/", "/api/experiences"]
}

# ---------------------------------------------------------------- 평가 러너 비밀 헤더

# 값은 Terraform 이 만든다 — 변수로 받으면 다른 사람이 값 없이 apply 할 때 예외가 사라진다.
# 값은 state(S3, 암호화)·Web ACL 정의(wafv2:GetWebACL 권한자)에 평문으로 남는다. 새도 Rate Limit 만 피한다.
resource "random_password" "eval_token" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "eval_token" {
  name                    = "${var.project}/${var.env}/eval-waf-token"
  description             = "X-Eval-Token value for the eval runner (WAF rate limit exception only)"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "eval_token" {
  secret_id     = aws_secretsmanager_secret.eval_token.id
  secret_string = random_password.eval_token.result
}

# ---------------------------------------------------------------- Web ACL

resource "aws_wafv2_web_acl" "this" {
  name        = "${var.name}-alb"
  description = "nesume ALB - D17"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # IP 단위 폭주·스크래핑 차단. 앱 C7(사용자·세션 단위, LLM 경로)과 층이 다르다 — 인증 전·모든 경로.
  rule {
    name     = "rate-limit-ip"
    priority = 0

    action {
      dynamic "block" {
        for_each = local.block ? [1] : []
        content {}
      }
      dynamic "count" {
        for_each = local.block ? [] : [1]
        content {}
      }
    }

    statement {
      rate_based_statement {
        limit                 = var.rate_limit
        evaluation_window_sec = 300
        aggregate_key_type    = "IP"

        # 비밀 헤더가 정확히 맞는 요청은 세지 않는다(결정1). 관리형 규칙은 예외 없이 적용.
        scope_down_statement {
          not_statement {
            statement {
              byte_match_statement {
                search_string         = random_password.eval_token.result
                positional_constraint = "EXACTLY"
                field_to_match {
                  single_header { name = "x-eval-token" }
                }
                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name}-rate-limit-ip"
      sampled_requests_enabled   = true
    }
  }

  dynamic "rule" {
    for_each = local.managed_rule_groups
    content {
      name     = rule.value.name
      priority = rule.value.priority

      override_action {
        dynamic "none" {
          for_each = local.block ? [1] : []
          content {}
        }
        dynamic "count" {
          for_each = local.block ? [] : [1]
          content {}
        }
      }

      statement {
        managed_rule_group_statement {
          vendor_name = "AWS"
          name        = rule.value.name

          dynamic "rule_action_override" {
            for_each = lookup(local.count_only_rules, rule.value.name, [])
            content {
              name = rule_action_override.value
              action_to_use {
                count {}
              }
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name}-${rule.value.name}"
        sampled_requests_enabled   = true
      }
    }
  }

  # 결정11: GenericLFI_BODY 는 Count 로 라벨만 남기고, 글 입력 경로 밖에서만 막는다.
  # 라벨은 앞 규칙(CommonRuleSet, 30)이 붙이므로 그 뒤(40)에 둔다.
  rule {
    name     = "lfi-body-outside-text"
    priority = 40

    action {
      dynamic "block" {
        for_each = local.block ? [1] : []
        content {}
      }
      dynamic "count" {
        for_each = local.block ? [] : [1]
        content {}
      }
    }

    statement {
      and_statement {
        statement {
          label_match_statement {
            scope = "LABEL"
            key   = "awswaf:managed:aws:core-rule-set:GenericLFI_Body"
          }
        }
        statement {
          not_statement {
            statement {
              or_statement {
                dynamic "statement" {
                  for_each = local.lfi_text_paths
                  content {
                    byte_match_statement {
                      search_string         = statement.value
                      positional_constraint = "STARTS_WITH"
                      field_to_match {
                        uri_path {}
                      }
                      text_transformation {
                        priority = 0
                        type     = "NONE"
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name}-lfi-body-outside-text"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.name}-alb"
    sampled_requests_enabled   = true
  }
}

# ---------------------------------------------------------------- 로그

# 이름은 aws-waf-logs- 로 시작해야 한다. 본문은 WAF 로그에 안 남고, 인증·쿠키·비밀 헤더는 아래에서 가린다
# → PII·비밀이 없어 CMK 없이 둔다(logs 모듈 앱 로그 그룹과 같은 기준).
#trivy:ignore:AVD-AWS-0017
resource "aws_cloudwatch_log_group" "waf" {
  name              = "aws-waf-logs-${var.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_resource_policy" "waf" {
  policy_name = "${var.name}-waf-logs"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "delivery.logs.amazonaws.com" }
      Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource  = "${aws_cloudwatch_log_group.waf.arn}:*"
      Condition = {
        ArnLike      = { "aws:SourceArn" = "arn:aws:logs:${var.region}:${var.account_id}:*" }
        StringEquals = { "aws:SourceAccount" = var.account_id }
      }
    }]
  })
}

resource "aws_wafv2_web_acl_logging_configuration" "this" {
  resource_arn            = aws_wafv2_web_acl.this.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]

  redacted_fields {
    single_header { name = "authorization" }
  }
  redacted_fields {
    single_header { name = "cookie" }
  }
  redacted_fields {
    single_header { name = "x-eval-token" }
  }

  depends_on = [aws_cloudwatch_log_resource_policy.waf]
}
