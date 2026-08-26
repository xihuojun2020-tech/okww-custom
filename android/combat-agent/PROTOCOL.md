# Combat Agent protocol

Protocol version is `1`. Every frame has exactly these top-level fields:

`protocol_version`, `session_token`, `command_id`, `kind`, `payload`, `issued_at`,
`deadline`, `status`.

`kind` is one of `semantic_action`, `heartbeat`, `cancel`, `emergency_stop`, or
`release_all`. Requests use `status=accepted`. Responses use `accepted`, `started`, and
one terminal status: `completed`, `cancelled`, or `rejected`. A response always copies
the request's session token, command id, kind, issued time, and deadline.

`issued_at` and `deadline` are Unix seconds. Expired requests are rejected. Frames are
UTF-8 JSON Lines and may not exceed 64 KiB (excluding the newline). Unknown fields,
invalid JSON, old protocol versions, malformed payloads, and invalid lane/kind pairs are
rejected without terminating the agent.

The normal and emergency abstract sockets are independent. Disconnecting a normal lane
causes an immediate `releaseAll`; process shutdown does the same. The watchdog releases
all touch pointers when no heartbeat has arrived for two seconds. Every stop/cancel path
increments a generation so an older action cannot resume after a stop.

Semantic actions are currently rejected with `layout_not_configured`; no guessed or blind
coordinates are injected.
