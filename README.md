# COS Configuration Repository Operator for Kubernetes

This charmed operator for Kubernetes enables you to provide configurations to
various components of the
[Canonical Observability Stack (COS)](https://juju.is/docs/lma2) bundle.

The charm facilitates forwarding free-standing rules from a git repository
to [prometheus][Prometheus operator], [loki][Loki operator] or
[grafana][Grafana operator] operators.


## Supported configurations

* [Prometheus K8s][Prometheus operator] charmed operator:
  Alert rules and recording rules
* [Loki K8s][Loki operator] charmed operator: Alert rules
* [Grafana K8s][Grafana operator] charmed operator: dashboards

## Usage

```shell
juju deploy cos-configuration-k8s \
  --config git_repo=https://path.to/repo \
  --config git_branch=main \
  --config git_depth=1 \
  --config prometheus_alert_rules_path=rules/prod/prometheus/

juju relate cos-configuration-k8s prometheus-k8s
```

Paths to rules files etc. can also be set after deployment:

```shell
juju config cos-configuration-k8s loki_alert_rules_path=rules/prod/loki/
juju relate cos-configuration-k8s loki-k8s

juju config cos-configuration-k8s grafana_dashboards_path=dashboards/prod/grafana/
juju relate cos-configuration-k8s grafana-k8s
```

### Scale Out Usage
N/A

## Relations
Currently, supported relations are:
- `prometheus-config`, for interfacing with [prometheus][Prometheus operator].
- `loki-config`, for interfacing with [loki][Loki operator].
- `grafana-dashboards`, for interfacing with [grafana][Grafana operator].

## OCI Images
This charm can be used with the following image:
- `k8s.gcr.io/git-sync/git-sync:v3.5.0`


[Prometheus operator]: https://charmhub.io/prometheus-k8s
[Loki operator]: https://charmhub.io/loki-k8s
[Grafana operator]: https://charmhub.io/grafana-k8s
