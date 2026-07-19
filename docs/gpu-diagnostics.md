# GPU stream-server diagnostics

The bridge reads the optional endpoint:

```text
GET /casting/diagnostics
```

For the GPU/Cast stream-server, direct Cast encoding is ready when PowerShell returns:

```powershell
Invoke-RestMethod http://127.0.0.1:11470/casting/diagnostics |
    ConvertTo-Json -Depth 5
```

Expected fields:

```json
{
  "selected_encoder": "h264_nvenc",
  "nvenc_usable": true
}
```

Home Assistant exposes these values on the bridge connectivity sensor as
`cast_selected_encoder`, `cast_nvenc_usable`, and `cast_hardware_ready`.

The diagnostics endpoint confirms the direct-Cast encoder. Actual HLS hardware
selection must still be confirmed in the stream-server log. The expected marker is:

```text
HLS transcoder selected ... encoder="h264_nvenc" hardware=true
```
