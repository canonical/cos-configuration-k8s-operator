# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Name of the deployed application."
  value       = juju_application.cos-configuration-k8s.name
}

# Required integration endpoints

output "loki_config_endpoint" {
  description = "Name of the endpoint used send alerting rules to Loki."
  value       = "loki-config"
}

# Provided integration endpoints

output "prometheus_config_endpoint" {
  description = "Name of the endpoint used send alerting and recording rules to Prometheus."
  value       = "prometheus-config"
}

output "grafana_dashboards_endpoint" {
  description = "Name of the endpoint used to send dashboards configs to Grafana."
  value       = "grafana-dashboards"
}
