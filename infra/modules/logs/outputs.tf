output "app_log_group" { value = aws_cloudwatch_log_group.app.name }
output "audit_log_group" { value = aws_cloudwatch_log_group.audit.name }
output "app_log_group_arn" { value = aws_cloudwatch_log_group.app.arn }
output "audit_log_group_arn" { value = aws_cloudwatch_log_group.audit.arn }
output "audit_kms_key_arn" { value = aws_kms_key.audit.arn }
