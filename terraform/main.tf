# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "cos-configuration-k8s" {
  name = var.app_name
  model = var.model_name

  charm {
    name = "cos-configuration-k8s"
    channel = var.channel
  }
  config = {
    "git_repo" = var.git_repo
    "git_branch" = var.git_branch
    "git_rev" = var.git_rev
    "git_depth" = var.git_depth
    "git_ssh_key" = var.git_ssh_key
    "prometheus_alert_rules_path" = var.prometheus_alert_rules_path
    "loki_alert_rules_path" = var.loki_alert_rules_path
    "grafana_dashboards_path" = var.grafana_dashboards_path
  }

  units = 1
  trust = true
}
