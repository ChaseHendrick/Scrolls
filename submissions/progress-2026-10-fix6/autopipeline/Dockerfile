# syntax=docker/dockerfile:1
# Built and run on 2026-10-15 (x86_64, Docker 29.8) with villa's VC3D-5432721-2026-10-14 AppImage: the default
# command found all five of AutoPipeline's VC3D tools, passed the self-test and printed DEMO PASS. That machine was
# behind a proxy, so a test-only layer under this file added the proxy's certificate and https apt sources, and its
# build fetched the AppImage through scripts/get_vc3d.py from a saved copy of GitHub's release listing. The script's
# lookup against GitHub itself found the same file, with a matching sha256, on another machine the same day.
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
# AppRun via a link named after the tool. villa replaces its `latest` release on every build, so a pinned file name
# stops downloading within days: by default scripts/get_vc3d.py asks GitHub which AppImage `latest` holds now and
# checks it against the sha256 GitHub publishes (a file with no sha256 to check is refused), and
# /opt/vc3d/appimage.json records its name, URL and sha256. Docker caches this step, so `docker build --no-cache`
# fetches the newest again. To pin one file instead, pass --build-arg VC3D_APPIMAGE=URL --build-arg
# VC3D_APPIMAGE_SHA256=HEX; VC3D_APPIMAGE=stable takes villa's older stable release (no vc_tifxyz_selfcross or
# vc_gen_umbilicus), and VC3D_APPIMAGE= empty skips the AppImage. If GitHub's limit of 60 anonymous API requests an
# hour stops the build (shared addresses such as CI runners), pass a token as a secret, which stays out of the image:
#   GITHUB_TOKEN=... docker build --secret id=github_token,env=GITHUB_TOKEN -t autopipeline .
ARG VC3D_APPIMAGE=latest
ARG VC3D_APPIMAGE_SHA256=
COPY scripts/get_vc3d.py /opt/vc3d/get_vc3d.py
RUN --mount=type=secret,id=github_token,env=GITHUB_TOKEN \
    if [ -n "$VC3D_APPIMAGE" ] && [ "$(uname -m)" = x86_64 ]; then \
      cd /opt/vc3d && mkdir -p bin && \
      img="$(/usr/bin/python3 get_vc3d.py "$VC3D_APPIMAGE" --sha256 "$VC3D_APPIMAGE_SHA256" --require-sha256 \
             --record appimage.json)" && \
      "$img" --appimage-extract >/dev/null && rm "$img" && \
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
