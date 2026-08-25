variable "lab_id" {
  description = "Root-owned CML lab realization identifier."
  type        = string
  nullable    = false
}

variable "twin_lifecycle_state" {
  description = "Explicit desired CML lifecycle state."
  type        = string

  validation {
    condition     = contains(["DEFINED_ON_CORE", "STARTED", "STOPPED"], var.twin_lifecycle_state)
    error_message = "twin_lifecycle_state must be explicitly one of DEFINED_ON_CORE, STARTED, or STOPPED."
  }
}

variable "core_02_bootstrap_hostname" {
  type     = string
  nullable = false

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9.-]{0,62}$", var.core_02_bootstrap_hostname))
    error_message = "core_02_bootstrap_hostname must be a valid IOS hostname with no whitespace or control characters."
  }
}

variable "core_02_bootstrap_management_cidr" {
  type     = string
  nullable = false

  validation {
    condition = (
      can(cidrnetmask(var.core_02_bootstrap_management_cidr)) &&
      length(regexall(":", var.core_02_bootstrap_management_cidr)) == 0
    )
    error_message = "core_02_bootstrap_management_cidr must be a valid IPv4 CIDR."
  }
}

variable "core_02_bootstrap_username" {
  type      = string
  sensitive = true
  nullable  = false

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+$", var.core_02_bootstrap_username))
    error_message = "core_02_bootstrap_username contains characters unsafe for IOS Day-0 rendering."
  }
}

variable "core_02_bootstrap_password" {
  type      = string
  sensitive = true
  nullable  = false

  validation {
    condition = (
      length(var.core_02_bootstrap_password) > 0 &&
      length(regexall("[\\r\\n\\t ]", var.core_02_bootstrap_password)) == 0
    )
    error_message = "core_02_bootstrap_password must be non-empty and contain no whitespace or control characters."
  }
}

variable "edge_junos_01_bootstrap_hostname" {
  type     = string
  nullable = false

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9.-]{0,62}$", var.edge_junos_01_bootstrap_hostname))
    error_message = "edge_junos_01_bootstrap_hostname must be a valid Junos hostname with no whitespace or control characters."
  }
}

variable "edge_junos_01_bootstrap_management_cidr" {
  type     = string
  nullable = false

  validation {
    condition = (
      can(cidrnetmask(var.edge_junos_01_bootstrap_management_cidr)) &&
      length(regexall(":", var.edge_junos_01_bootstrap_management_cidr)) == 0
    )
    error_message = "edge_junos_01_bootstrap_management_cidr must be a valid IPv4 CIDR."
  }
}

variable "edge_junos_01_bootstrap_username" {
  type      = string
  sensitive = true
  nullable  = false

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9_-]{0,63}$", var.edge_junos_01_bootstrap_username))
    error_message = "edge_junos_01_bootstrap_username contains characters unsafe for Junos Day-0 rendering."
  }
}

variable "edge_junos_01_bootstrap_password_hash" {
  type      = string
  sensitive = true
  nullable  = false

  validation {
    condition = can(regex(
      "^\\$6\\$ncdpedgejunos01\\$[A-Za-z0-9./]{86}$",
      var.edge_junos_01_bootstrap_password_hash,
    ))
    error_message = "edge_junos_01_bootstrap_password_hash must be a SHA-512-crypt verifier using the fixed ncdpedgejunos01 salt."
  }
}
