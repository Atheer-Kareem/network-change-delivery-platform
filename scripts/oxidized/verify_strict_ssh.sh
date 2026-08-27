#!/bin/sh
set -eu

image=${1:-ncdp-oxidized:10c2}
fixture=$(mktemp -d "${TMPDIR:-/tmp}/ncdp-oxidized-strict-ssh.XXXXXX")
cleanup() {
  rm -rf "${fixture}"
}
trap cleanup EXIT HUP INT TERM
chmod 0700 "${fixture}"

uv run python -c 'from network_change_delivery.oxidized_service import render_oxidized_config; print(render_oxidized_config(), end="")' > "${fixture}/config"
chmod 0600 "${fixture}/config"

docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --env HOME=/run/ncdp/home \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --tmpfs /run/ncdp/home/.config/oxidized:rw,noexec,nosuid,nodev,size=16m \
  --mount "type=bind,source=${fixture}/config,target=/run/ncdp/home/.config/oxidized/config,readonly" \
  --entrypoint /bin/sh \
  "${image}" -ec '
    bundle _2.5.22_ exec ruby -e '\''
      require "oxidized"
      require "oxidized/input/ssh"
      Oxidized::Config.load
      raise "input is not SSH-only" unless Oxidized.config.input.default == "ssh"
      raise "debug enabled" unless Oxidized.config.input.debug == false
      input = Oxidized::SSH.allocate
      model = Object.new
      node = Struct.new(:auth, :timeout, :model, :group, :vars).new(
        { username: "synthetic", password: "synthetic" }, 20, model, "managed", {}
      )
      input.instance_variable_set(:@node, node)
      secure = input.__send__(:must_secure?)
      raise "strict host verification disabled" unless secure == true
      options = input.__send__(:make_ssh_opts)
      raise "Net::SSH host verification is not strict" unless options[:verify_host_key] == :always
      puts "Oxidized strict SSH config verified: verify_host_key=:always"
    '\''
  '
