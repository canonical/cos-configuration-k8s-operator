# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

variable "model_name" {
  description = "Name of Juju model to deploy application to."
  type        = string
  default     = ""
}

variable "app_name" {
  description = "Name of the application in the Juju model"
  type        = string
  default     = "cos-configuration"
}

variable "channel" {
  description = "The channel to use when deploying a charm."
  type        = string
  default     = "stable"
}

# Application config

variable "git_repo" {
  description = "URL to repo to clone and sync against."
  type        = string
  default     = ""
}

variable "git_branch" {
  description = "The git branch to check out."
  type        = string
  default     = "master"
}

variable "git_rev" {
  description = "The git revision (tag or hash) to check out."
  type        = string
  default     = "HEAD"
}

variable "git_depth" {
  description = "Cloning depth, to truncate commit history to the specified number of commits. Zero means no truncating."
  type        = number
  default     = 1
}

variable "git_ssh_key" {
  description = "An optional SSH private key to use when cloning the repository."
  type        = string
  default     = ""
}

variable "prometheus_alert_rules_path" {
  description = "Relative path in repo to prometheus rules."
  type        = string
  default     = "prometheus_alert_rules"
}

variable "loki_alert_rules_path" {
  description = "Relative path in repo to loki rules."
  type        = string
  default     = "loki_alert_rules"
}

variable "grafana_dashboards_path" {
  description = "Relative path in repo to grafana dashboards."
  type        = string
  default     = "grafana_dashboards"
}
