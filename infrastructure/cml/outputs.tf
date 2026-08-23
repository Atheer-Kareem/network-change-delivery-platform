output "controller_version" {
  description = "CML controller software version observed through the provider."
  value       = data.cml2_system.controller.version
}

output "system_bridge_device_name" {
  description = "Actual Linux device name for the uniquely resolved System Bridge connector."
  value       = try(one(local.system_bridge_matches).device_name, null)

  precondition {
    condition     = length(local.system_bridge_matches) == 1
    error_message = "Exactly one CML connector labelled System Bridge is required."
  }
}

output "cat8000v_image_id" {
  description = "Accepted CAT8000V image definition ID available on the controller."
  value       = try(one(local.accepted_cat8000v_images).id, null)

  precondition {
    condition     = length(local.accepted_cat8000v_images) == 1
    error_message = "Exactly one CAT8000V image with ID cat8000v-17-18-02 is required."
  }
}

output "vjunos_router_image_id" {
  description = "Accepted vJunos Router image definition ID available on the controller."
  value       = try(one(local.accepted_vjunos_images).id, null)

  precondition {
    condition     = length(local.accepted_vjunos_images) == 1
    error_message = "Exactly one vJunos Router image with ID vjunos-router-23-2r1-15 is required."
  }
}

output "twin_lab_id" {
  description = "CML realization identifier for the Terraform-owned twin lab."
  value       = cml2_lab.twin.id
}

output "twin_lab_state" {
  description = "Observed lifecycle state of the Terraform-owned twin lab."
  value       = cml2_lifecycle.twin.state
}
