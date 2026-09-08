output "lab_id" {
  value = cml2_lab.profiled_staging.id
}

output "lab_title" {
  value = cml2_lab.profiled_staging.title
}

output "node_ids" {
  value = merge(
    { system_bridge = cml2_node.system_bridge.id, management_switch = cml2_node.management_switch.id },
    { for name, node in cml2_node.device : name => node.id },
  )
}

output "link_ids" {
  value = merge(
    { system_bridge_management = cml2_link.system_bridge_management.id },
    { for name, link in cml2_link.management : "management_${name}" => link.id },
    { for name, link in cml2_link.data : name => link.id },
  )
}
