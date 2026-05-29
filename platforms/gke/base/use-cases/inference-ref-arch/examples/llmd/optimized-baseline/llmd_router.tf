# Copyright 2024 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

locals {
  kubeconfig_directory               = "${path.module}/../../../../../kubernetes/kubeconfig"
  kubeconfig_file                    = "${local.kubeconfig_directory}/${local.kubeconfig_file_name}"
  manifests_directory                = "${local.namespace_directory}/${local.ira_online_gpu_kubernetes_namespace_name}"
  manifests_directory_root           = "${path.module}/../../../../kubernetes/manifests"
  namespace_directory                = "${local.manifests_directory_root}/namespace"
  workload_identity_principal_prefix = "principal://iam.googleapis.com/projects/${data.google_project.cluster.number}/locations/global/workloadIdentityPools/${data.google_project.cluster.project_id}.svc.id.goog/subject"
}

data "local_file" "kubeconfig" {
  filename = local.kubeconfig_file
}


data "http" "router_base_values" {
  url = "${var.git_url_prefix}/${var.llmd_git_org}/${var.llmd_git_repo}/${var.llmd_git_branch}/guides/recipes/router/base.values.yaml"
}

data "http" "router_guide_values" {
  url = "${var.git_url_prefix}/${var.llmd_git_org}/${var.llmd_git_repo}/${var.llmd_git_branch}/guides/${var.llmd_guide_name}/router/${var.llmd_guide_name}.values.yaml"
}

data "helm_template" "llmd_router" {
  name         = var.llmd_guide_name
  namespace    = local.ira_online_gpu_kubernetes_namespace_name
  kube_version = var.kubernetes_version_router_templates

  repository = var.llmd_router_chart_repo
  chart      = var.llmd_router_chart
  version    = var.llmd_router_chart_version

  values = [
    data.http.router_base_values.response_body,
    data.http.router_guide_values.response_body,
    yamlencode({
      provider = {
        name = var.gateway_provider_name
      }
      httpRoute = {
        create               = true
        inferenceGatewayName = "llm-d-inference-gateway"
      }
    })
  ]
  skip_tests = var.skip_router_render_tests
  validate   = var.validate_router_manifests
}

resource "local_file" "llmd_router_manifests" {
  filename = "${local.namespace_directory}/${local.ira_online_gpu_kubernetes_namespace_name}/router/router.yaml"
  content  = data.helm_template.llmd_router.manifest
}

module "kubectl_apply_llmd_router_manifests" {
  source                      = "../../../../../modules/kubectl_apply"
  apply_server_side           = true
  kubeconfig_file             = data.local_file.kubeconfig.filename
  manifest                    = local_file.llmd_router_manifests.filename
  manifest_includes_namespace = false
  namespace                   = local.ira_online_gpu_kubernetes_namespace_name
}
