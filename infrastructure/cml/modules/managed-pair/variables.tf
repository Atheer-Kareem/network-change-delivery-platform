variable "lab_id" {
  description = "Root-owned disposable CML staging lab realization identifier."
  type        = string
  nullable    = false
}

variable "lifecycle_state" {
  description = "Explicit desired CML lifecycle state for the managed pair."
  type        = string

  validation {
    condition     = contains(["DEFINED_ON_CORE", "STARTED", "STOPPED"], var.lifecycle_state)
    error_message = "lifecycle_state must be explicitly one of DEFINED_ON_CORE, STARTED, or STOPPED."
  }
}

variable "cisco_bootstrap_hostname" {
  type     = string
  nullable = false

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9.-]{0,62}$", var.cisco_bootstrap_hostname))
    error_message = "cisco_bootstrap_hostname must be a valid IOS hostname with no whitespace or control characters."
  }
}

variable "cisco_bootstrap_management_cidr" {
  type     = string
  nullable = false

  validation {
    condition = (
      can(cidrnetmask(var.cisco_bootstrap_management_cidr)) &&
      length(regexall(":", var.cisco_bootstrap_management_cidr)) == 0
    )
    error_message = "cisco_bootstrap_management_cidr must be a valid IPv4 CIDR."
  }
}

variable "cisco_bootstrap_username" {
  type      = string
  sensitive = true
  nullable  = false

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+$", var.cisco_bootstrap_username))
    error_message = "cisco_bootstrap_username contains characters unsafe for IOS Day-0 rendering."
  }
}

variable "cisco_bootstrap_password" {
  type      = string
  sensitive = true
  nullable  = false

  validation {
    condition = (
      length(var.cisco_bootstrap_password) > 0 &&
      length(regexall("[\\r\\n\\t ]", var.cisco_bootstrap_password)) == 0
    )
    error_message = "cisco_bootstrap_password must be non-empty and contain no whitespace or control characters."
  }
}

variable "junos_bootstrap_hostname" {
  type     = string
  nullable = false

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9.-]{0,62}$", var.junos_bootstrap_hostname))
    error_message = "junos_bootstrap_hostname must be a valid Junos hostname with no whitespace or control characters."
  }
}

variable "junos_bootstrap_management_cidr" {
  type     = string
  nullable = false

  validation {
    condition = (
      can(cidrnetmask(var.junos_bootstrap_management_cidr)) &&
      length(regexall(":", var.junos_bootstrap_management_cidr)) == 0
    )
    error_message = "junos_bootstrap_management_cidr must be a valid IPv4 CIDR."
  }
}

variable "junos_bootstrap_username" {
  type      = string
  sensitive = true
  nullable  = false

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9_-]{0,63}$", var.junos_bootstrap_username))
    error_message = "junos_bootstrap_username contains characters unsafe for Junos Day-0 rendering."
  }
}

variable "junos_bootstrap_password_hash" {
  type      = string
  sensitive = true
  nullable  = false

  validation {
    condition = can(regex(
      "^\\$6\\$ncdpedgejunos01\\$[A-Za-z0-9./]{86}$",
      var.junos_bootstrap_password_hash,
    ))
    error_message = "junos_bootstrap_password_hash must be a SHA-512-crypt verifier using the fixed ncdpedgejunos01 salt."
  }
}
