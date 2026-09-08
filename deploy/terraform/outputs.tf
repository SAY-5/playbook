output "artifact_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "run_queue_url" {
  value = aws_sqs_queue.runs.url
}

output "run_index_table" {
  value = aws_dynamodb_table.run_index.name
}

output "secret_name" {
  value = aws_secretsmanager_secret.api_keys.name
}

output "runner_function" {
  value = aws_lambda_function.runner.function_name
}
