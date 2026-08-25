output "controller_version" {
  description = "CML controller software version observed through the provider."
  value       = module.twin.controller_version
}

output "system_bridge_device_name" {
  description = "Actual Linux device name for the uniquely resolved System Bridge connector."
  value       = module.twin.system_bridge_device_name
}

output "cat8000v_image_id" {
  description = "Accepted CAT8000V image definition ID available on the controller."
  value       = module.twin.cat8000v_image_id
}

output "vjunos_router_image_id" {
  description = "Accepted vJunos Router image definition ID available on the controller."
  value       = module.twin.vjunos_router_image_id
}

output "twin_lab_id" {
  description = "CML realization identifier for the Terraform-owned twin lab."
  value       = cml2_lab.twin.id
}

output "twin_lab_state" {
  description = "Observed lifecycle state of the Terraform-owned twin lab."
  value       = module.twin.lifecycle_state
}

output "twin_node_ids" {
  description = "CML node realization identifiers keyed by stable topology role."
  value       = module.twin.node_ids
}

output "twin_link_ids" {
  description = "CML link realization identifiers keyed by topology purpose."
  value       = module.twin.link_ids
}
