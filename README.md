# Avalanche Operator (k8s)

## Description

[Avalanche][Avalanche source] is an [OpenMetrics][OpenMetrics source] endpoint
load tester.

## Usage

To use Avalanche, you need to be able to relate to a charm that supports the
`prometheus_scrape` relation interface.

For more information see [INTEGRATING](INTEGRATING.md).

You also need to have a working Kubernetes environment, and have bootstrapped a
Juju controller of version 2.9+, with a model ready to use with the Kubernetes
cloud.

Example deployment:

```shell
juju deploy avalanche-k8s
```

Then you could relate to [prometheus][Prometheus operator]:
```shell
juju deploy prometheus-k8s
juju relate prometheus-k8s avalanche-k8s
```

### Scale Out Usage
To add additional Avalanche units for high availability,

```shell
juju add-unit avalanche-k8s
```

## Relations
Currently, supported relations are:
- `metrics-endpoint`, for interfacing with [prometheus][Prometheus operator].

## OCI Images
This charm can be used with the following image:
- `quay.io/freshtracks.io/avalanche`


[Avalanche source]: https://github.com/open-fresh/avalanche
[OpenMetrics source]: https://github.com/OpenObservability/OpenMetrics
[Prometheus operator]: https://charmhub.io/prometheus-k8s
