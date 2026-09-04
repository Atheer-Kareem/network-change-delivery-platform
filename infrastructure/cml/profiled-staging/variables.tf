variable "staging_run_id" {
  type     = string
  nullable = false

  validation {
    condition     = can(regex("^[a-z0-9]+(?:[._-][a-z0-9]+)*$", var.staging_run_id))
    error_message = "staging_run_id must be a bounded lowercase run identity."
  }
}

variable "lifecycle_state" {
  type     = string
  nullable = false

  validation {
    condition     = contains(["DEFINED_ON_CORE", "STARTED", "STOPPED"], var.lifecycle_state)
    error_message = "lifecycle_state must be explicit."
  }
}

variable "devices" {
  description = "Sensitive profiled Day-0 values derived at runtime from exact inventory, OpenBao, and the realization catalog."
  sensitive   = true
  nullable    = false
  type = map(object({
    hostname          = string
    management_cidr   = string
    username          = string
    password_verifier = string
    node_definition   = string
    image_definition  = string
    cpu_cores         = number
    ram_mb            = number
    management_port   = number
    bootstrap_profile = string
  }))

  validation {
    condition     = toset(keys(var.devices)) == toset(["core_02", "edge_junos_01", "transit_ios_01", "access_sw_01"])
    error_message = "devices must be the exact profiled exact-four population."
  }
}
