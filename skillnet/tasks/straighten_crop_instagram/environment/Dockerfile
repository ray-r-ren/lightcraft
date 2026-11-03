FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git xz-utils unzip file procps xvfb xauth ffmpeg libgl1 libglib2.0-0 fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://nodejs.org/dist/v22.11.0/node-v22.11.0-linux-x64.tar.xz | tar xJ -C /usr/local --strip-components=1
RUN pip install --no-cache-dir pydantic==2.10.3 pytest==8.3.4 pyyaml==6.0.2 requests==2.32.3 pypdf==5.1.0
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DISPLAY=:99 MPLBACKEND=Agg
RUN mkdir -p /workspace/inputs /workspace/outputs /skill
RUN apt-get update && apt-get install -y --no-install-recommends imagemagick && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends libimage-exiftool-perl && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends build-essential pkg-config git ca-certificates fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir numpy==2.1.3
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain 1.95.0 && git clone https://github.com/ray-r-ren/lightcraft /opt/lightcraft-src && cd /opt/lightcraft-src && git checkout 32d569ad5d19a6b55cf8d5c077127faa0f44a83b && CARGO_BUILD_JOBS=4 CARGO_PROFILE_RELEASE_DEBUG=0 /root/.cargo/bin/cargo build --release --locked -p lightcraft-cli && install -m755 target/release/lightcraft-cli /usr/local/bin/lightcraft-cli && mkdir -p /usr/share/doc/lightcraft /usr/share/lightcraft && cp LICENSE-APACHE LICENSE-MIT NOTICE README.md /usr/share/doc/lightcraft/ && cp -r assets /usr/share/lightcraft/assets && cd / && rm -rf /opt/lightcraft-src /root/.cargo /root/.rustup
RUN sed -i '/\.cargo\/env/d' /root/.bashrc /root/.profile 2>/dev/null || true
COPY files/ /task/
COPY inputs/ /task/inputs/
RUN rm -f /task/.keep /task/inputs/.keep && mkdir -p /task/outputs && useradd -m -u 1000 agent && chown -R agent /task
WORKDIR /task
