provider "cml2" {
  skip_verify    = false
  token_cache    = false
  dynamic_config = false
  named_configs  = false
}

data "cml2_system" "controller" {
  ready         = true
  timeout       = "30s"
  ignore_errors = false
}

data "cml2_connector" "system_bridge" {
  label = "System Bridge"
}

locals {
  system_bridge_matches = [
    for connector in data.cml2_connector.system_bridge.connectors : connector
    if connector.label == "System Bridge"
  ]
}
