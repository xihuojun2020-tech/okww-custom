# Desktop QQ / WeChat notification candidate

The isolated candidate consists of `native_desktop_notifications.py`,
`native_desktop_clipboard.py` and `TestNativeDesktopNotifications.py`. No
production file was changed by this implementation. All modules remain AGPL
package code; they do not import the legacy notification manager or GUI singleton.

## Final integration API

```python
from src.runtime.native_desktop_notifications import create_owner_desktop_notifications

desktop = create_owner_desktop_notifications(context, ocr_engine, notification_config)
futures = desktop.submit(title, message, png_images=())
```

The factory returns `OwnerDesktopNotifications`. It binds the existing live
`context.assert_input_owner` and thread identity, creates a queue and retains the
OCR engine reference without calling it. No Windows backend, clipboard or OLE
apartment is initialized until an enabled route reaches `drain_one()`. The
concrete lazy sender is `MessengerSender(WindowsMessengerBackend(), ocr_engine,
stop=context.stop, pause=context.pause,
clipboard=PreservedClipboard(OleClipboardAPI()))`.

The native Windows device must advertise the implemented generic capability
`desktop-handoff`. Replay, MuMu and ADB do not advertise it. On those devices,
selected routes produce `unavailable/windows-desktop-device-required` without
enumerating windows or initializing Windows/OLE/OCR. Preferences remain intact.

`submit(title, message, png_images=())` returns a tuple of standard Futures, one
per currently enabled desktop route. Exact False produces no route. Disabling a
route while it is queued yields `skipped/route-disabled` at dispatch time. The
notification hub should attach delivery callbacks to each returned Future;
queued work is not a delivered message. Future results contain one sanitized
route dict, which the hub can wrap in a list for `notification-delivery`.

`pending` reports queued work. `checkpoint()` only raises the existing
`SessionPreempted`, allowing background combat to unwind. `drain_one()` performs
at most one queued route on the bound live owner thread. It releases game input,
executes the desktop sender, releases again and restores the previous trusted
foreground window only if it remains valid and the messenger still owns focus.
An external new foreground window is retained. Cleanup also applies to explicit
pause/stop during a sender without changing either Event or any service enable
preference. Held game keys are released, never replayed.

`close()` rejects new submissions and cancels queued Futures. The sender checks
pause/stop at UI observation and send boundaries. Clipboard preservation is
transactional cleanup, not another helper input thread.

## Root wiring points

- Create the factory inside the Runtime-owned package session/run, after the
  input lease is acquired. Configuration children do not instantiate it.
- At the existing `run_session` background checkpoint, invoke
  `desktop.checkpoint()` alongside pending user-command preemption.
- After `SessionPreempted` unwinds and the existing host `finally` sets
  `executor.session_checkpoint=None` and releases input, call `drain_one()`
  at the next owner loop boundary. Pause keeps notifications queued; stop
  calls close. Do not call drain while the combat stack is active.
- Foreground one-shot tasks keep their input until completion. Drain pending
  notifications after their lifecycle and input release, before returning.
- A standalone service must use the same checkpoint/yield/boundary pattern.
  The helper HTTP worker may enqueue but cannot invoke sender methods.
- Preserve existing `_enabled`, pause state, current task and the Runtime input
  lease. No additional worker or thread sends desktop messages.

## Real sender behavior and verification

The backend uses documented Win32 process/window identity, foreground,
PrintWindow, targeted synchronous messages and Chromium child-surface APIs.
QQ.exe and WeChat.exe/Weixin.exe are supported executable selectors. Each actual
input boundary verifies the selected HWND still belongs to its PID/create-time.
Physical DPI coordinates use the existing GameFrame physical-coordinate scope.
Thread and active lease assertions occur at the owner dispatch boundary.

The sender OCR-verifies an exact contact in the main list or the Contacts/Features
section of a same-process search popup, then verifies the conversation header and
Send button. It refuses detected unsent composer text rather than deleting a
user draft. Before each remote send it rechecks the conversation. Text is reported
delivered only when the outgoing chat region contains an additional matching
message. Images are pasted via the verified Paste context menu and reported
delivered only when a new matching thumbnail is observed in the outgoing chat
region. UI waits are bounded observation of asynchronous client rendering;
failed sends are not resent. Failed confirmation includes `submitted_messages`,
so an already dispatched action is not described as unsent or safe to retry.

The existing Not Reliable desktop label remains accurate: UI layout and OCR can
reject a real client or fail confirmation after a send. No recipient-read status
is claimed. There are no contact/message logs or automatic messenger screenshots.

## Full-format clipboard / STA contract

The Windows API adapter uses `pythoncom.OleInitialize`, OleGetClipboard,
OleSetClipboard, OleFlushClipboard and native OleUninitialize on the same owner
thread. Incompatible apartment initialization fails before changing clipboard.
It enumerates every FORMATETC and advertised medium, materializes GetData before
overwrite, and stores it in a native Shell IDataObject created with
`shell.SHCreateDataObject([], [], None, IID_IDataObject)`. SetData(..., False)
requires the native object to copy the medium without taking the source's
ownership. GetData is preflighted for every saved representation before image
input. Thus failure to retain any format aborts before overwrite.

This avoids a custom Python IDataObject gateway: pywin32 PySTGMEDIUM.CopyTo
directly transfers GDI handles, which cannot safely be returned repeatedly from a
Python cache. The native Shell IDataObject provides documented arbitrary-format
SetData support and native medium ownership. Registered HTML/PNG, Unicode text,
file-drop, bitmaps/metafiles and stream/storage representations are retained;
no Unicode-only restoration is used. PNG input exposes both PNG and CF_DIB.

After image use, OleSetClipboard(original) and OleFlushClipboard complete before
the interfaces and STA are released. Sequence-number checks detect external
clipboard changes; such new data is retained and restoration is explicitly
reported as failed rather than silently overwritten. All copying/restoration
must succeed for the delivery result to remain successful.

Public interface evidence inspected (read-only GET, no messages):

- Microsoft [SHCreateDataObject](https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shcreatedataobject)
  explicitly documents generic arbitrary clipboard formats through SetData.
- Microsoft [OleGetClipboard](https://learn.microsoft.com/en-us/windows/win32/api/ole2/nf-ole2-olegetclipboard)
  distinguishes original OLE objects from default objects wrapping native data.
- Installed pywin32 `win32com/test/testClipboard.py` demonstrates OleInitialize,
  IDataObject GetData/SetClipboard/Flush and STGMEDIUM contracts.
- Upstream pywin32 `PyIDataObject.cpp`, `PySTGMEDIUM.cpp` and shell.cpp confirm
  SetData ownership, GDI CopyTo semantics and the SHCreateDataObject signature.
- Static installed DLL string inspection confirms OleInitialize and
  SHCreateDataObject. Pythoncom has no OleUninitialize export; native ole32 is
  used for that required STA teardown.

Verification is entirely offline: genuine Runtime + Replay live-owner,
cross-thread and ended-owner assertions; helper enqueue/preemption; pause,
stop, enable preference, identity reuse, Chromium coordinates, Unicode; text and
image UI outcomes; all-format clipboard materialization/copy/restoration,
external clipboard change, incompatible apartment and snapshot failure. Real
Windows clipboard/OLE round trips, client UI delivery and hardware OCR were not
run. Root integration must retain that acceptance limit rather than claiming
actual messenger delivery from fixture success.
