resource "cml2_lab" "twin" {
  title       = "NCDP Terraform Twin"
  description = "Terraform-owned personal CML digital twin; no production configuration."
  notes       = "Personal-lab Day-0 manageability only; stable identity remains NetBox-owned and NCDP-managed intent remains outside Terraform."
}

module "twin" {
  source = "./modules/twin"

  lab_id                                  = cml2_lab.twin.id
  twin_lifecycle_state                    = var.twin_lifecycle_state
  core_02_bootstrap_hostname              = var.core_02_bootstrap_hostname
  core_02_bootstrap_management_cidr       = var.core_02_bootstrap_management_cidr
  core_02_bootstrap_username              = var.core_02_bootstrap_username
  core_02_bootstrap_password              = var.core_02_bootstrap_password
  edge_junos_01_bootstrap_hostname        = var.edge_junos_01_bootstrap_hostname
  edge_junos_01_bootstrap_management_cidr = var.edge_junos_01_bootstrap_management_cidr
  edge_junos_01_bootstrap_username        = var.edge_junos_01_bootstrap_username
  edge_junos_01_bootstrap_password_hash   = var.edge_junos_01_bootstrap_password_hash
}
