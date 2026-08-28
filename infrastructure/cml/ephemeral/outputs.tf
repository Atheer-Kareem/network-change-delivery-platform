output "staging_run_id" {
  description = "Non-secret identity supplied for this staging run."
  value       = var.staging_run_id
}

output "lab_title" {
  description = "Attributable title of the ephemeral staging lab."
  value       = cml2_lab.staging.title
}

output "lab_id" {
  description = "Disposable CML lab realization identifier."
  value       = cml2_lab.staging.id
}

output "node_ids" {
  description = "Disposable CML node identifiers keyed by stable topology role."
  value       = module.managed_pair.node_ids
}

output "link_ids" {
  description = "Disposable CML link identifiers keyed by topology purpose."
  value       = module.managed_pair.link_ids
}

output "lifecycle_state" {
  description = "Observed CML lifecycle state for the ephemeral managed pair."
  value       = module.managed_pair.lifecycle_state
}
