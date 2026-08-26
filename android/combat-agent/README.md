# OKWW MuMu Combat Agent

This directory contains the small Android-side agent used by the host's ADB-forwarded
combat channel. It listens on two independent abstract local sockets:

* `okww-combat-normal` accepts `semantic_action` and `heartbeat`.
* `okww-combat-emergency` accepts `heartbeat`, `cancel`, `emergency_stop`, and `release_all`.

Each frame is one UTF-8 JSON object followed by `\n`, and is limited to 64 KiB. The
first valid `session_token` binds the process; other tokens are rejected. Safety commands
use a separate lane and never wait on an in-flight normal action.

The current build deliberately rejects every semantic action with
`reason=layout_not_configured`. UI anchors must be calibrated and supplied through a
future `LayoutMap` before any game coordinate can be used. Heartbeats and all release /
cancel paths are implemented now.

## Build

Run `build.ps1` with explicit tool paths, for example:

```powershell
.\build.ps1 -JavaHome 'C:\Program Files\Java\jdk-17' `
  -AndroidSdkRoot 'C:\Android\Sdk' `
  -AndroidJar 'C:\Android\Sdk\platforms\android-35\android.jar' `
  -D8 'C:\Android\Sdk\build-tools\35.0.0\d8.bat'
```

The script compiles with Java 8 compatibility and creates `build/okww-combat-agent.jar`
containing `classes.dex`, suitable for loading with `app_process`. It fails closed when
any tool or input path is missing. `JAVA_HOME` and `ANDROID_SDK_ROOT` may be used when
the corresponding parameters are omitted.

Agent startup, both heartbeat lanes, emergency cleanup, and forward removal have been
validated on an Android 15 x86_64 MuMu instance. Actual touch injection has not yet been validated;
multi-pointer behavior still requires a separate calibrated test.
