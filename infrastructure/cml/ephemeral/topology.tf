resource "cml2_lab" "staging" {
  title       = "NCDP Staging ${var.staging_run_id}"
  description = "ADR 0023 ephemeral Terraform-owned Cisco/Junos staging pair."
  notes       = "Run ${var.staging_run_id}; disposable staging realization; stable identity remains NetBox-owned; not live/reference or a brownfield topology clone."
}

module "managed_pair" {
  source = "../modules/managed-pair"

  lab_id                          = cml2_lab.staging.id
  lifecycle_state                 = var.lifecycle_state
  cisco_bootstrap_hostname        = var.cisco_bootstrap_hostname
  cisco_bootstrap_management_cidr = var.cisco_bootstrap_management_cidr
  cisco_bootstrap_username        = var.cisco_bootstrap_username
  cisco_bootstrap_password        = var.cisco_bootstrap_password
  junos_bootstrap_hostname        = var.junos_bootstrap_hostname
  junos_bootstrap_management_cidr = var.junos_bootstrap_management_cidr
  junos_bootstrap_username        = var.junos_bootstrap_username
  junos_bootstrap_password_hash   = var.junos_bootstrap_password_hash
}
