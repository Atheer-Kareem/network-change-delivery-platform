variable "twin_lifecycle_state" {
  description = "Explicit desired CML lifecycle state. Required; no implicit lifecycle action is allowed."
  type        = string

  validation {
    condition = contains(
      ["DEFINED_ON_CORE", "STARTED", "STOPPED"],
      var.twin_lifecycle_state,
    )
    error_message = "twin_lifecycle_state must be explicitly one of DEFINED_ON_CORE, STARTED, or STOPPED."
  }
}
