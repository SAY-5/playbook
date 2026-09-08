variable "project" {
  description = "Name prefix for every resource."
  type        = string
  default     = "playbook"
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "dev"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "localstack" {
  description = "Point the AWS provider at LocalStack instead of AWS."
  type        = bool
  default     = false
}

variable "localstack_endpoint" {
  type    = string
  default = "http://localhost:4566"
}

variable "model" {
  description = "Model id the runner calls through the Anthropic API."
  type        = string
  default     = "claude-sonnet-5"
}

variable "lambda_source_dir" {
  description = "Directory zipped into the runner Lambda. `make lambda-zip` builds one with dependencies."
  type        = string
  default     = null
}

variable "runner_timeout_seconds" {
  type    = number
  default = 300
}

variable "log_retention_days" {
  type    = number
  default = 30
}
