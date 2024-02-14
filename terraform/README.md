# COS Configuration Operator for Kubernetes Terraform module

This folder contains a base [Terraform][Terraform] module for the cos-configuration-k8s charm. 

The module uses the [Terraform Juju provider][Terraform Juju provider] to model the charm
deployment onto any Kubernetes environment managed by [Juju][Juju].

The base module is not intended to be deployed in separation (it is possible though), but should 
rather serve as a building block for higher level modules.

## Module structure

- **main.tf** - Defines the Juju application to be deployed. 
- **variables.tf** - Allows customization of the deployment. Except for exposing the deployment 
    options (Juju model name, channel or application name) also models the charm configuration.
- **output.tf** - Responsible for integrating the module with other Terraform modules, primarily
    by defining potential integration endpoints (charm integrations), but also by exposing 
    the application name.
- **terraform.tf** - Defines the Terraform provider.

## Using cos-configuration-k8s base module in higher level modules

If you want to use `cos-configuration-k8s` base module as part of your Terraform module, import it
like shown below:

```text
module "cos-configuration-k8s" {
  source = "git::https://github.com/canonical/cos-configuration-k8s-operator/terraform"
  
  model_name = "juju_model_name"

  (Customize configuration variables here if needed)
}
```

Create integrations, for instance:

```text
resource "juju_integration" "cos-configuration-grafana" {
  model = var.model_name

  application {
    name     = module.cos-configuration.app_name
    endpoint = module.cos-configuration.grafana_dashboards_endpoint
  }

  application {
    name     = module.grafana.app_name
    endpoint = module.grafana.grafana_dashboard_endpoint
  }
}
```

[Terraform]: https://www.terraform.io/
[Terraform Juju provider]: https://registry.terraform.io/providers/juju/juju/latest
[Juju]: https://juju.is
