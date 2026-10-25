# Wayland recording feasibility

MintCapture currently uses FFmpeg's `x11grab` input for recording. That input
cannot capture a Wayland compositor's private desktop buffers, so the app
continues to refuse recording in Wayland sessions. Screenshot capture is
separate: it asks the desktop's `org.freedesktop.portal.Screenshot` service
for a local image.

## ScreenCast portal flow

A portal-based recorder needs to use the `org.freedesktop.portal.ScreenCast`
interface. The typical sequence is:

1. Call `CreateSession` and wait for its `Request::Response`.
2. Call `SelectSources` for the desired monitor/window sources and wait for its
   response.
3. Call `Start`, usually presenting the portal's source-selection UI, then
   read the returned PipeWire stream node IDs.
4. Call `OpenPipeWireRemote` for the session. The returned Unix file descriptor
   is a PipeWire remote connection; it is not a video stream that can be
   written directly to a file.

The file descriptor must be passed to a PipeWire consumer. GStreamer provides
the `pipewiresrc` source; a schematic command is:

```text
gst-launch-1.0 pipewiresrc fd=<portal-fd> path=<stream-node-id> ! videoconvert ! ...
```

The exact options and ownership/lifetime rules for the descriptor and node
come from the portal response and installed GStreamer plugin. A production
recorder must keep the descriptor open while the pipeline is running and
release it when stopping or cancelling the session.

## FFmpeg availability

FFmpeg's supported inputs depend on its build configuration. The Ubuntu 24.04
FFmpeg 6.1.1 package inspected during this implementation does not list a
PipeWire input in `ffmpeg -devices`; the local `gst-inspect-1.0 pipewiresrc`
does report that GStreamer's PipeWire source is installed. Linux Mint 22
systems should check their exact package build rather than assume that
`x11grab` or a `pipewire` FFmpeg input is available:

```sh
ffmpeg -version
ffmpeg -hide_banner -devices | grep -i pipewire
gst-inspect-1.0 pipewiresrc
```

MintCapture does not currently use GStreamer for video capture. The existence
of the PipeWire plugin alone does not make a portal stream usable by the
current FFmpeg recorder.

## Proposed implementation

A later Wayland recorder should isolate the portal session/callback lifecycle
from the UI, request screen sources asynchronously, and then connect the
returned remote descriptor and node IDs to a maintained PipeWire consumer.
The capture pipeline should encode video/audio to a temporary local file,
report progress and errors to the UI, and close the pipeline, descriptor, and
portal session on stop, cancellation, or application shutdown. It should not
fall back to `x11grab` under Wayland. Any implementation should be validated
against Cinnamon/Muffin and other target compositors, since portal policy and
available audio streams vary by desktop.
