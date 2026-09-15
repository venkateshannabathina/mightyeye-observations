#!/usr/bin/env bash
set -euo pipefail
if [[ "$(uname -s)" != Linux ]]; then
  echo 'DeepStream acceptance requires the supported NVIDIA Linux/Jetson runtime.' >&2
  exit 2
fi
command -v deepstream-app >/dev/null
command -v gst-inspect-1.0 >/dev/null
if command -v nvidia-smi >/dev/null; then nvidia-smi; else echo 'No nvidia-smi: verify Jetson GPU with tegrastats.'; fi
deepstream-app --version-all
for plugin in nvurisrcbin nvstreammux nvinfer nvtracker nvdsanalytics; do
  gst-inspect-1.0 "$plugin" >/dev/null
  echo "Available: $plugin"
done
python3 -c 'import pyds; import gi; print("Python bindings available")'
echo 'Runtime checks passed. Next run the official sample, then local video and RTSP acceptance.'
