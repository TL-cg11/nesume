# D16 알림·자동 대응 — SNS 토픽(main.tf 4번)의 구독과 추가 알람 (docs/ops/alerts.md).
#
#  1. Slack: SNS → Lambda(files/slack_notifier.py) → Incoming Webhook. 웹훅 URL 은 앱 시크릿(nesume/<env>/app) JSON 의
#     ALERTS_SLACK_WEBHOOK_URL 필드. var.slack_enabled 로 켠다(URL 을 시크릿에 넣은 뒤). 앱 알림과 CloudWatch 알람 모두 받는다.
#  2. 이메일: main.tf 의 var.alert_email 구독(그대로).
#  3. 수집 실패 알람: jobs-collector 파드 로그의 "FAILED" 를 하루 단위로 세어 3일 연속이면 알람(C4 "3회 연속 실패").
#     앱 쪽 emit("collector_failed") 는 C4 가 호출할 때 즉시 Slack 으로 간다(이 알람과 별개).
#  4. 앱이 토픽에 Publish 하는 권한은 base 의 iam 모듈(app·batch 역할 sns:Publish). 토픽 ARN 은 이름으로 만든다.

# ---------- 1. Slack Lambda ----------
data "archive_file" "slack_notifier" {
  count       = var.slack_enabled ? 1 : 0
  type        = "zip"
  source_file = "${path.module}/files/slack_notifier.py"
  output_path = "${path.module}/files/slack_notifier.zip"
}

resource "aws_iam_role" "slack_notifier" {
  count = var.slack_enabled ? 1 : 0
  name  = "${local.name}-slack-notifier"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "slack_notifier" {
  count = var.slack_enabled ? 1 : 0
  name  = "slack-notifier"
  role  = aws_iam_role.slack_notifier[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = var.app_secret_arn },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.region}:*:log-group:/aws/lambda/${local.name}-slack-notifier:*"
      },
    ]
  })
}

#trivy:ignore:AVD-AWS-0066 # X-Ray 추적 불필요(알림 1건 → 웹훅 1회)
resource "aws_lambda_function" "slack_notifier" {
  count            = var.slack_enabled ? 1 : 0
  function_name    = "${local.name}-slack-notifier"
  role             = aws_iam_role.slack_notifier[0].arn
  runtime          = "python3.12"
  handler          = "slack_notifier.handler"
  filename         = data.archive_file.slack_notifier[0].output_path
  source_code_hash = data.archive_file.slack_notifier[0].output_base64sha256
  timeout          = 10
  memory_size      = 128
  environment {
    variables = {
      SECRET_ARN         = var.app_secret_arn
      WEBHOOK_SECRET_KEY = var.slack_webhook_secret_key
      ENV                = var.env
    }
  }
}

resource "aws_lambda_permission" "sns_invoke" {
  count         = var.slack_enabled ? 1 : 0
  statement_id  = "AllowSnsInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.slack_notifier[0].function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.alerts.arn
}

resource "aws_sns_topic_subscription" "slack" {
  count     = var.slack_enabled ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.slack_notifier[0].arn
}

# ---------- 3. 수집 실패 알람 ----------
# Fluent Bit 가 보낸 줄은 {log: "...", kubernetes: {pod_name: ...}} 모양이다(배치는 JSON 로깅이 아니라 log 필드에 원문).
# jobs_collector._run_one 이 소스 실패마다 "<source>: FAILED" 를 남긴다(C4).
resource "aws_cloudwatch_log_metric_filter" "collector_failed" {
  name           = "${local.name}-collector-failed"
  log_group_name = var.app_log_group
  pattern        = "{ $.kubernetes.pod_name = \"*jobs-collector*\" && $.log = \"*FAILED*\" }"
  metric_transformation {
    name          = "CollectorFailedCount"
    namespace     = local.ns
    value         = "1"
    default_value = "0"
    unit          = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "collector_failed" {
  alarm_name          = "${local.name}-collector-failed"
  alarm_description   = "공고 수집 배치(jobs-collector)가 ${var.collector_failed_days}일 연속 실패. 대시보드 '배치 결과' 패널 → 파드 로그 FAILED 소스 확인(docs/ops/alerts.md)"
  namespace           = local.ns
  metric_name         = "CollectorFailedCount"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = var.collector_failed_days
  datapoints_to_alarm = var.collector_failed_days
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# 앱 알림(core/alerts.py)이 감사 로그 그룹에 남기는 "alert" 줄 → 종류별 메트릭(대시보드·추세용. 발송 자체는 SNS 가 한다)
resource "aws_cloudwatch_log_metric_filter" "app_alerts" {
  name           = "${local.name}-app-alerts"
  log_group_name = var.audit_log_group
  pattern        = "{ $.msg = \"alert\" && $.logger = \"nesume.audit.alerts\" }"
  metric_transformation {
    name          = "AppAlertCount"
    namespace     = local.ns
    value         = "1"
    default_value = "0"
    unit          = "Count"
  }
}
