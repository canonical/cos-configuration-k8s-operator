# COS Configuration Repository Operator for Kubernetes

[![COS configuration](https://charmhub.io/cos-configuration-k8s/badge.svg)](https://charmhub.io/cos-configuration-k8s)
[![Test Suite](https://github.com/canonical/alertmanager-k8s-operator/actions/workflows/release-edge.yaml/badge.svg)](https://github.com/canonical/alertmanager-k8s-operator/actions/workflows/release-edge.yaml)
![Discourse status](https://img.shields.io/discourse/status?server=https%3A%2F%2Fdiscourse.charmhub.io&style=flat)

This charmed operator for Kubernetes enables you to provide configurations to
various components of the
[Canonical Observability Stack (COS)](https://charmhub.io/topics/canonical-observability-stack) bundle.

## Supported configurations

The charm facilitates forwarding freestanding files from a git repository
to the following operators:

* [Prometheus K8s][Prometheus operator] charmed operator:
  Alert rules and recording rules
* [Loki K8s][Loki operator] charmed operator: Alert rules
* [Grafana K8s][Grafana operator] charmed operator: dashboards

Internally, the charm is using [`git-sync`][Git sync] to sync a remote repo with the local copy.
The repo syncs on `update-status` or when the user manually runs the `sync-now` action.

## Getting started

### Deployment

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

### Verification

After setting the `git_repo` (and optionally `git_branch`), the contents should be present in the workload container,

```
$ juju ssh --container git-sync cos-configuration-k8s/0 ls -l /git
total 4
drwxr-xr-x 6 root root 4096 Oct 24 08:59 7f0b1eac9317850aee320b4f47a7f1527aaff625
lrwxrwxrwx 1 root root   40 Oct 24 08:59 repo -> 7f0b1eac9317850aee320b4f47a7f1527aaff625
```

and accessible from the charm container

```
$ juju ssh cos-configuration-k8s/0 ls -l /var/lib/juju/storage/content-from-git/0
total 4
drwxr-xr-x 6 root root 4096 Oct 24 08:59 7f0b1eac9317850aee320b4f47a7f1527aaff625
lrwxrwxrwx 1 root root   40 Oct 24 08:59 repo -> 7f0b1eac9317850aee320b4f47a7f1527aaff625
```

After relating to e.g. prometheus, rules from the synced repo should appear in app data,

```
juju show-unit promethus-k8s/0 --format json | jq '."prometheus-k8s/0"."relation-info"' 
```

as well as in prometheus itself

```
juju ssh prometheus-k8s/0 curl localhost:9090/api/v1/rules
```

### Scale Out Usage
N/A

## Relations
Currently, supported relations are:
- `prometheus-config`, for interfacing with [prometheus][Prometheus operator].
- `loki-config`, for interfacing with [loki][Loki operator].
- `grafana-dashboards`, for interfacing with [grafana][Grafana operator].


### About Juju Topology

This charm forwards alert rules, recording rules and dashboards but does not add its own metadata to the topology.

The [Juju topology](https://charmhub.io/observability-libs/libraries/juju_topology) describes a node in the model, not the data flow. That's why this charm does not inject Juju topology.

Since a cos-configurator _app_ needs to be deployed per app, topology labels _could_ be used to give a since of origin (as in data flow). However, this would be semantically inconsistent with charms, where topology labels indicate a node in the model. This may unpredictably interfere with `group_by` directive.

On the other hand, the juju administrator may add annotations (or labels) to alert rules, recording rules and dashboards using different nomenclature that describes how it got into the model (like: `origin`, `giturl`, `branch`, `synctime`).


## OCI Images
This charm can be used with the following image:
- `k8s.gcr.io/git-sync/git-sync:v3.5.0`

### Resource revisions
Workload images are archived on charmhub by revision number.

| Resource       | Revision | Image                               |
|----------------|:--------:|-------------------------------------|
| git-sync-image |    r1    | k8s.gcr.io/git-sync/git-sync:v3.4.0 |
| git-sync-image |    r2    | k8s.gcr.io/git-sync/git-sync:v3.5.0 |

[Prometheus operator]: https://charmhub.io/prometheus-k8s
[Loki operator]: https://charmhub.io/loki-k8s
[Grafana operator]: https://charmhub.io/grafana-k8s
[Git sync]: https://github.com/kubernetes/git-sync
