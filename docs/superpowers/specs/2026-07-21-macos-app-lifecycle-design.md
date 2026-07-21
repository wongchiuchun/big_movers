# Big Movers macOS App Lifecycle Design

**Date:** 2026-07-21  
**Status:** Approved for specification by the user; pending implementation planning

## Problem

`Big Movers.app` is currently a fire-and-forget AppleScript launcher. It starts
`Big_movers_server.py` with `nohup`, opens the browser, and then exits. The Flask
server continues as an independent Python process, so the user cannot stop the
software through the normal macOS Quit command. Force-quitting Python can make
macOS treat the termination as a crash and offer to submit an error report.

The app bundle contains only a compiled `main.scpt`; its AppleScript source and
rebuild procedure are not tracked.

## Goal

Make Big Movers behave like a normal macOS application:

- Opening the app starts the local Flask server and opens the browser.
- The app remains running in the Dock for as long as the server is running.
- Reopening or clicking the running app opens the browser without starting a
  duplicate server.
- Quit, Cmd-Q, or Quit from the Dock cleanly stops the owned server and then
  exits the app.
- A normal start/quit cycle does not produce a macOS crash-report prompt.

## Non-goals

- Replacing Flask or the browser-based frontend with a native UI.
- Closing the user's browser window or tab when Big Movers quits.
- Installing a launch agent, login item, or system-wide service.
- Managing arbitrary programs that happen to use port 5051.
- Changing `Big_Movers_Start.command` in this fix.

## Chosen Approach

Retain the current AppleScript applet, but rebuild it as a stay-open applet using
`osacompile -s`. Track the AppleScript source and a reproducible build script in
the repository. This preserves the current one-click app, bundle icon, and local
Flask architecture without introducing a Swift/Xcode project.

## Components

### Stay-open AppleScript controller

The controller owns these constants and runtime state:

- Absolute project directory and Python 3.13 path already used by the launcher.
- Port `5051` and URL `http://localhost:5051/`.
- A Big Movers-specific PID file under `/tmp`.
- The server PID adopted or created by the current app session.

The applet implements `run`, `reopen`, `idle`, and `quit` handlers.

### Tracked source and build script

The repository will contain readable AppleScript source plus a build script that
compiles the stay-open app, preserves the existing custom icon/bundle identity,
and refreshes the app's ad-hoc signature. The checked-in `Big Movers.app` remains
the double-clickable artifact.

### Lifecycle smoke test

An automated macOS integration test will exercise the real compiled app and port
5051. It is intentionally separate from the JavaScript simulation tests.

## Lifecycle

### Launch

1. Validate that the project directory and configured Python executable exist.
2. Inspect the PID file, if present.
3. If the PID is alive and its command identifies this project's
   `Big_movers_server.py`, adopt it instead of starting a duplicate.
4. If the PID file is stale, remove it.
5. If port 5051 is occupied without a valid owned Big Movers PID, show a clear
   error and do not kill or replace that process.
6. Otherwise start `Big_movers_server.py`, capture its exact PID, and write the
   PID file.
7. Poll for port readiness with a bounded timeout instead of sleeping for a
   fixed two seconds. Readiness requires the exact ownership-verified server PID
   to own the listening socket on port 5051; separate "PID alive" and "port
   open" checks are insufficient because they could refer to different processes.
8. When ready, open the local URL. If readiness fails or times out for either a
   newly started server or a previously adopted server, show the log location,
   terminate that ownership-verified server, remove its PID file, and quit the
   controller. An unowned port occupant remains untouched.

### Reopen

When macOS sends a reopen event to the already-running app, open the local URL.
Do not restart the server or alter its PID.

### Runtime monitoring

The stay-open app's `idle` handler periodically checks whether its owned server
PID is still alive. If the server exits independently, remove the PID file and
allow the app to quit normally. Do not automatically restart the server.

### Quit

1. Send `SIGTERM` only to the server PID owned or validly adopted by this app.
2. Poll briefly for the process and port to disappear.
3. If the server exits within the bounded wait, remove the PID file and continue
   the AppleScript quit event so the app exits normally.
4. If the server remains alive, cancel the Quit event, keep the controller app
   running, retain the PID file, and show a message with the PID and log path so
   the user can retry after investigating.

The normal path will not use Force Quit or `SIGKILL`. If the server does not
terminate within the bounded wait, the app will report that shutdown did not
complete instead of silently killing an unrelated or unverified process.

## Process Ownership and Safety

A PID is considered owned only when both conditions hold:

- It came from the Big Movers PID file or the process just launched by the app.
- The live process command identifies the configured Python executable and this
  project's `Big_movers_server.py`.

PID validation is repeated immediately before termination to protect against a
stale PID being reused by another process. Port ownership alone is never enough
authorization to terminate a process.

## Error Handling

- Missing project or Python: show a concise configuration error and quit.
- Port occupied by an unowned process: identify port 5051 as unavailable and
  leave that process untouched.
- Server startup failure: point the user to `/tmp/big_movers.log`, clean up the
  failed ownership-verified process/PID file whether it was newly started or
  adopted, and quit.
- Server exits during use: clean up the PID file and close the controller app;
  do not generate a crash dialog or restart loop.
- Shutdown timeout: cancel Quit, keep the controller and verified server
  running, retain the PID file, and show a clear message with the PID and log
  path. Never silently orphan the server or fall back to `SIGKILL`.

## Testing

Development follows a failing-test-first lifecycle:

1. Add the integration test and run it against the current bundle. It must fail
   because the current app exits while the server stays alive.
2. Implement and rebuild the stay-open app.
3. Verify the app remains running after the server becomes reachable.
4. Send the app a normal Quit Apple event.
5. Verify both the app and the listener on port 5051 exit within the timeout.
6. Verify reopening a running app does not create a second server process.
7. Verify an unrelated port occupant is not terminated.
8. Verify a controlled server that ignores `SIGTERM` causes Quit to be canceled
   while the controller and PID file remain available for a retry.
9. Run the existing JavaScript quiz and simulation suites to catch unrelated
   regressions.

## Acceptance Criteria

- A Finder or Dock launch starts one Big Movers server and opens the browser.
- Big Movers remains present and normally quitable while the server is active.
- Cmd-Q/Dock Quit stops the server and exits the app without Force Quit.
- No crash-report prompt appears after the normal tested quit path.
- Reopening does not duplicate the server.
- Stale PID files are recovered safely.
- Processes not verified as this project's server are never killed.
- The launcher source, build procedure, and lifecycle test are tracked.
