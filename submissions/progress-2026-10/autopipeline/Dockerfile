# syntax=docker/dockerfile:1
# UNTESTED: `docker build` has not been run on this file. Its AppImage step was run as a bash script on Ubuntu 24.04
# (x86_64) on 2026-10-12: the sha256 check passed and `kit vc3d which` found the tools.
# AutoPipeline on villa's published VC3D image, headless.
#   docker build -t autopipeline .
#   docker run --rm autopipeline                       # tool check, VC3D self-test, synthetic demo
#   docker run --rm -v "$PWD/work:/opt/autopipeline/work" autopipeline \
#     python -m kit autopipeline plan PHerc0841 --settings '{"purpose": "benchmark", "segment": "0841-w00"}'
# Base: tags main and edge resolve to this index (read 2026-10-12): Ubuntu 24.04, villa 1e3f4c0 of 2026-05-13,
# amd64 and arm64. Its tools lack --flip-normals, vc_tifxyz_selfcross and vc_gen_umbilicus, so on amd64 the
# current release AppImage is laid over it below. villa publishes no arm64 AppImage: on arm64 (Docker on Apple
# Silicon builds arm64 by default), or with VC3D_APPIMAGE= empty, the tool check reports those two tools missing
# (the umbilicus and qa stages); the default command still goes on to the self-test and the demo.
ARG VILLA_IMAGE=ghcr.io/scrollprize/villa/volume-cartographer@sha256:bad516f66001abca759454cc43e4fd11e5b19aa55d36bdc2043817291c8083c4
FROM ${VILLA_IMAGE}
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

# villa's release AppImage (x86_64), unpacked; it carries its own glibc loader, so every tool starts through
# AppRun via a link named after the tool. 4eecd08 passed `kit vc3d selftest` on Ubuntu 24.04 on 2026-10-12.
# The `latest` release is replaced on each villa build: update both arguments together, or pass VC3D_APPIMAGE=.
ARG VC3D_APPIMAGE=https://github.com/ScrollPrize/villa/releases/download/latest/VC3D-4eecd08-2026-10-12-linux-x86_64.AppImage
ARG VC3D_APPIMAGE_SHA256=59af3ea88cd2bb16610efb087dc45cf12c07668269951932f38ef8cc32b08ce4
RUN if [ -n "$VC3D_APPIMAGE" ] && [ "$(uname -m)" = x86_64 ]; then \
      mkdir -p /opt/vc3d/bin && cd /opt/vc3d && curl -fsSL -o vc3d.AppImage "$VC3D_APPIMAGE" && \
      echo "$VC3D_APPIMAGE_SHA256  vc3d.AppImage" | sha256sum -c - && chmod +x vc3d.AppImage && \
      ./vc3d.AppImage --appimage-extract >/dev/null && rm vc3d.AppImage && \
      for t in squashfs-root/usr/bin/*; do ln -s /opt/vc3d/squashfs-root/AppRun "bin/${t##*/}"; done; \
    fi

# kit needs Python 3.11 or newer (zarr 3); the image's own Python is 3.10, so use Ubuntu's 3.12 in a venv.
RUN apt-get update && apt-get install -y --no-install-recommends python3-venv && rm -rf /var/lib/apt/lists/* && \
    /usr/bin/python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_WAIT_POLICY=PASSIVE

WORKDIR /opt/autopipeline
COPY . /opt/autopipeline
# Editable: kit finds scripts/vc3d/, docs/ and work/ next to its package, so they must stay in this folder.
RUN python -m pip install --no-cache-dir -e . && python -m kit autopipeline defaults >/dev/null

COPY --chmod=0755 <<'EOF' /usr/local/bin/autopipeline-entry
#!/bin/sh
# The AppImage tools when present (VC_BIN is searched before PATH), else the image's /usr/local/bin.
if [ -z "${VC_BIN:-}" ] && [ -x /opt/vc3d/bin/vc_render_tifxyz ]; then export VC_BIN=/opt/vc3d/bin; fi
exec "$@"
EOF
ENTRYPOINT ["/usr/local/bin/autopipeline-entry"]
# `which` exits 1 when a pipeline tool is missing (always on arm64), so it does not gate the self-test and the demo.
CMD ["sh", "-c", "python -m kit vc3d which; python -m kit vc3d selftest && python scripts/demo_synthetic.py"]
