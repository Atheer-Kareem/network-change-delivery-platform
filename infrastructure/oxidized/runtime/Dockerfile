# syntax=docker/dockerfile:1.7
ARG RUBY_IMAGE=docker.io/library/ruby:3.3.9-slim-bookworm@sha256:b084aa6c608f29f4a3b54577884bb7e983abd0852c3650e7ab03f9b46f87151e

FROM ${RUBY_IMAGE} AS bundle
ARG BUNDLER_VERSION=2.5.22
ENV BUNDLE_DEPLOYMENT=true \
    BUNDLE_JOBS=4 \
    BUNDLE_PATH=/usr/local/bundle \
    BUNDLE_WITHOUT=development:test
WORKDIR /build
RUN apt-get update && \
    apt-get install --yes --no-install-recommends \
      build-essential \
      cmake \
      libgit2-dev \
      libicu-dev \
      libyaml-dev \
      pkg-config && \
    rm -rf /var/lib/apt/lists/*
COPY Gemfile Gemfile.lock ./
RUN gem install --no-document bundler --version "${BUNDLER_VERSION}" && \
    bundle _${BUNDLER_VERSION}_ install && \
    rm -rf /usr/local/bundle/cache /root/.bundle

FROM ${RUBY_IMAGE} AS runtime
ARG BUNDLER_VERSION=2.5.22
ENV BUNDLE_DEPLOYMENT=true \
    BUNDLE_PATH=/usr/local/bundle \
    BUNDLE_WITHOUT=development:test \
    HOME=/home/oxidized
RUN apt-get update && \
    apt-get install --yes --no-install-recommends \
      libgit2-1.5 \
      libicu72 \
      libyaml-0-2 && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 30000 --system oxidized && \
    useradd --uid 30000 --gid 30000 --system --create-home \
      --home-dir /home/oxidized oxidized && \
    install --directory --owner=oxidized --group=oxidized --mode=0700 \
      /home/oxidized/.config/oxidized
COPY --from=bundle /usr/local/bundle /usr/local/bundle
WORKDIR /opt/oxidized
COPY --chown=oxidized:oxidized Gemfile Gemfile.lock ./
USER 30000:30000
EXPOSE 8888/tcp
ENTRYPOINT ["bundle", "_2.5.22_", "exec", "oxidized"]
