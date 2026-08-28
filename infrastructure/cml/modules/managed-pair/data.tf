data "cml2_system" "controller" {
  ready         = true
  timeout       = "30s"
  ignore_errors = false
}

data "cml2_connector" "system_bridge" {
  label = "System Bridge"
}

data "cml2_images" "cat8000v" {
  nodedefinition = "cat8000v"
}

data "cml2_images" "vjunos_router" {
  nodedefinition = "vjunos-router"
}

locals {
  system_bridge_matches = [
    for connector in data.cml2_connector.system_bridge.connectors : connector
    if connector.label == "System Bridge"
  ]
  accepted_cat8000v_images = [
    for image in data.cml2_images.cat8000v.image_list : image
    if image.id == "cat8000v-17-18-02"
  ]
  accepted_vjunos_images = [
    for image in data.cml2_images.vjunos_router.image_list : image
    if image.id == "vjunos-router-23-2r1-15"
  ]
}
