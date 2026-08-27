#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'
require 'oxidized'
require 'oxidized/output/git'
require 'rugged'

using Refinements

repository = ARGV.fetch(0)
File.umask(0o077)
Oxidized.asetus = Asetus.new
Oxidized.config.output.git.user = 'NCDP Oxidized'
Oxidized.config.output.git.email = 'oxidized@ncdp.local'
Oxidized.config.output.git.repo = repository
Oxidized.config.output.git.single_repo = true
Oxidized.config.output.git.type_as_directory = false

writer = Oxidized::Output::Git.new

def outputs_for(content)
  outputs = Oxidized::Model::Outputs.new
  output = String.new(content)
  output.type = nil
  outputs << output
  outputs
end

def path_versions(repo, head, path)
  walker = Rugged::Walker.new(repo)
  walker.push(head)
  walker.count do |commit|
    commit.diff.each_delta.any? do |delta|
      (delta.added? || delta.modified?) && delta.new_file.fetch(:path) == path
    end
  end
end

def store(writer, repository, node, content)
  before = if File.directory?(repository)
             Rugged::Repository.new(repository).head.target_id
           end
  writer.store(
    node,
    outputs_for(content),
    group: 'managed',
    msg: "Synthetic observation for #{node}"
  )
  repo = Rugged::Repository.new(repository)
  head = repo.head.target_id
  path = "managed/#{node}"
  blob = repo.blob_at(head, path).oid
  count = Rugged::Walker.new(repo).tap { |walk| walk.push(head) }.count
  created_commit = writer.commitref ? repo.lookup(writer.commitref) : nil
  {
    node: node,
    commit_created: !writer.commitref.nil?,
    commitref: writer.commitref,
    head: head,
    head_changed: before != head,
    blob: blob,
    commit_count: count,
    path_revision_count: path_versions(repo, head, path),
    author_name: created_commit&.author&.fetch(:name),
    author_email: created_commit&.author&.fetch(:email)
  }
end

node1_a = "! NCDP synthetic chronology\nnode netbox-device-1\nversion A\n"
node1_b = "! NCDP synthetic chronology\nnode netbox-device-1\nversion B\n"
node1_c = "! NCDP synthetic chronology\nnode netbox-device-1\nversion C\n"
node2_a = "! NCDP synthetic chronology\nnode netbox-device-2\nversion A\n"

results = []
results << store(writer, repository, 'netbox-device-1', node1_a)
results << store(writer, repository, 'netbox-device-1', node1_a)
results << store(writer, repository, 'netbox-device-1', node1_b)
results << store(writer, repository, 'netbox-device-2', node2_a)
results << store(writer, repository, 'netbox-device-1', node1_b)
results << store(writer, repository, 'netbox-device-1', node1_c)

repo = Rugged::Repository.new(repository)
node_ref = Struct.new(:repo, :name)
Oxidized::Output::Git.clear_cache
node1_versions = writer.version(node_ref.new(repository, 'netbox-device-1'), 'managed')
Oxidized::Output::Git.clear_cache
node2_versions = writer.version(node_ref.new(repository, 'netbox-device-2'), 'managed')
puts JSON.generate(
  results: results,
  bare: repo.bare?,
  remotes: repo.remotes.each_name.to_a,
  index_present: File.file?(File.join(repository, 'index')),
  hook_entries: Dir.glob(File.join(repository, 'hooks', '*')).map do |path|
    File.basename(path)
  end,
  executable_hooks: Dir.glob(File.join(repository, 'hooks', '*')).select do |path|
    File.executable?(path)
  end,
  object_format: results.first.fetch(:head).length == 40 ? 'sha1' : 'sha256',
  public_versions: {
    node1_count: node1_versions.length,
    node1_latest: node1_versions.first.fetch(:oid),
    node2_count: node2_versions.length,
    node2_latest: node2_versions.first.fetch(:oid),
    metadata_keys: node1_versions.first.keys.map(&:to_s).sort
  }
)
