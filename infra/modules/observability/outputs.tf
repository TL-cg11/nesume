output "alerts_topic_arn" { value = aws_sns_topic.alerts.arn }
output "dashboard_name" { value = aws_cloudwatch_dashboard.main.dashboard_name }
output "metric_namespace" { value = local.ns }
output "webhook_notifier_function" { value = var.webhook_enabled ? aws_lambda_function.webhook_notifier[0].function_name : "" } # D16
