# With `localstack = true` every AWS API call is pointed at a local LocalStack container so the
# whole stack can be applied and inspected without an AWS account.
provider "aws" {
  region = var.region

  access_key                  = var.localstack ? "test" : null
  secret_key                  = var.localstack ? "test" : null
  skip_credentials_validation = var.localstack
  skip_metadata_api_check     = var.localstack
  skip_requesting_account_id  = var.localstack
  s3_use_path_style           = var.localstack

  dynamic "endpoints" {
    for_each = var.localstack ? [1] : []
    content {
      s3             = var.localstack_endpoint
      sqs            = var.localstack_endpoint
      dynamodb       = var.localstack_endpoint
      secretsmanager = var.localstack_endpoint
      lambda         = var.localstack_endpoint
      iam            = var.localstack_endpoint
      logs           = var.localstack_endpoint
      sts            = var.localstack_endpoint
    }
  }

  default_tags {
    tags = {
      project     = var.project
      environment = var.environment
      managed_by  = "terraform"
    }
  }
}
