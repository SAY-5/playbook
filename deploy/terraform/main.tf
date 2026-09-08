locals {
  name       = "${var.project}-${var.environment}"
  source_dir = coalesce(var.lambda_source_dir, "${path.module}/../lambda")
}

# Run artifacts: every trace, prompt version and report the runner produces.
resource "aws_s3_bucket" "artifacts" {
  bucket        = "${local.name}-artifacts"
  force_destroy = var.environment != "prod"
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Run queue: one message per scenario run, with a dead-letter queue for poison messages.
resource "aws_sqs_queue" "runs_dlq" {
  name                      = "${local.name}-runs-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "runs" {
  name                       = "${local.name}-runs"
  visibility_timeout_seconds = var.runner_timeout_seconds * 2
  message_retention_seconds  = 345600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.runs_dlq.arn
    maxReceiveCount     = 3
  })
}

# Run index: procedure -> version#scenario -> where the trace lives and how it ended.
resource "aws_dynamodb_table" "run_index" {
  name         = "${local.name}-run-index"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.environment == "prod"
  }
}

# API credentials. Values are set out of band (console or `aws secretsmanager put-secret-value`).
resource "aws_secretsmanager_secret" "api_keys" {
  name                    = "${local.name}/api-keys"
  description             = "ANTHROPIC_API_KEY, JIRA_BASE_URL, JIRA_TOKEN, SLACK_TOKEN for the runner"
  recovery_window_in_days = var.environment == "prod" ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "api_keys_placeholder" {
  secret_id = aws_secretsmanager_secret.api_keys.id
  secret_string = jsonencode({
    ANTHROPIC_API_KEY = ""
    JIRA_BASE_URL     = ""
    JIRA_TOKEN        = ""
    SLACK_TOKEN       = ""
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# Runner: a Lambda consuming the queue, running one scenario per message.
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "runner" {
  name               = "${local.name}-runner"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "runner" {
  statement {
    sid       = "Artifacts"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]
  }
  statement {
    sid       = "Index"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.run_index.arn]
  }
  statement {
    sid       = "Queue"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.runs.arn]
  }
  statement {
    sid       = "Secrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.api_keys.arn]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.runner.arn}:*"]
  }
}

resource "aws_iam_role_policy" "runner" {
  name   = "${local.name}-runner"
  role   = aws_iam_role.runner.id
  policy = data.aws_iam_policy_document.runner.json
}

resource "aws_cloudwatch_log_group" "runner" {
  name              = "/aws/lambda/${local.name}-runner"
  retention_in_days = var.log_retention_days
}

data "archive_file" "runner" {
  type        = "zip"
  source_dir  = local.source_dir
  output_path = "${path.module}/.build/runner.zip"
}

resource "aws_lambda_function" "runner" {
  function_name    = "${local.name}-runner"
  role             = aws_iam_role.runner.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.runner.output_path
  source_code_hash = data.archive_file.runner.output_base64sha256
  timeout          = var.runner_timeout_seconds
  memory_size      = 1024

  environment {
    variables = {
      PLAYBOOK_MODEL          = var.model
      PLAYBOOK_RUN_STORE      = "s3"
      PLAYBOOK_S3_BUCKET      = aws_s3_bucket.artifacts.bucket
      PLAYBOOK_DDB_TABLE      = aws_dynamodb_table.run_index.name
      PLAYBOOK_SECRET_ID      = aws_secretsmanager_secret.api_keys.name
      PLAYBOOK_PROCEDURES_DIR = "/var/task/procedures"
    }
  }

  depends_on = [aws_iam_role_policy.runner, aws_cloudwatch_log_group.runner]
}

resource "aws_lambda_event_source_mapping" "runs" {
  event_source_arn = aws_sqs_queue.runs.arn
  function_name    = aws_lambda_function.runner.arn
  batch_size       = 1
}
