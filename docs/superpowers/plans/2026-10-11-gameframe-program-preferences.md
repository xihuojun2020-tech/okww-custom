# GameFrame program preferences implementation plan

> **For agentic workers:** Execute task by task after v72 integration. Delegation follows the parent’s explicit assignments. This document does not authorize real notification sends, device input or system changes during planning.

**Goal:** Restore real program preferences, startup services, account context and language behavior without publishing controls that have no native implementation.

**Architecture:** Generic launcher behavior remains independently written MIT core code. Wuthering Waves settings, catalogs, notification-provider reuse and production account semantics stay in the AGPL game pack (`src/`, pack payload), connected through existing subprocess messages. Keep one device/input owner and explicit saved service intent.

**Audit:** Static source reads on 2026-10-11; no imports of device backends, network messages, NAS, system scheduling or additional test run. Runtime checks below are implementation acceptance plans, not completed verification. `src/gui/GeneralSettingsTab.py`, `custom_ok/ok/gui/settings/SettingTab.py` and installed framework source were inspected for consumers, not merely field definitions.

## Verified legacy consumers

Paths beginning `.venv/Lib/site-packages/ok/` below refer to the inspected dependency, **not an acceptable release dependency on this workstation’s .venv**. Extract only necessary source into the AGPL payload with provenance/license notices; do not import the legacy OK application to obtain a setting.

| Field | Actual legacy consumer | Native migration decision |
| --- | --- | --- |
| Auto Start Game When App Starts | Full Python search in `custom_ok`, `src`, installed `ok` found definition only | Do not show an inert switch. Pack config currently `windows.start_exe=False`; automatic service startup is a different behavior. If game auto-launch is requested, use the already explicit native launch command and implement its trigger. |
| Minimize Window to System Tray when Closing | `custom_ok/ok/gui/MainWindow.py:closeEvent` | Independently implement core tray hide/show/explicit quit. Tray hide keeps worker alive; explicit quit performs current owner cleanup. |
| Mute Game while in Background | `ok/device/capture_methods/hwnd_window.py` config listener and window monitor; `ok.util.audio.mute_process` | Existing behavior is real. A generic native Windows PID-bound mute action may be independently implemented; package preference enables it. Preserve/restore per-process audio state on explicit stop. Do not call old singleton window monitor. |
| Auto Resize Game Window | `hwnd_window.py:try_resize_to`, `ok/gui/StartController.py` startup validation | Real implementation chooses a supported fitting resolution and adjusts window bounds. Add only to current trusted Windows target, honoring configured ratio/minimum sizes. Native task geometry must refresh after resize. |
| Exit App when Game Exits | `hwnd_window.py` monitor, executor pause and quit signal | Real behavior on selected game disappearance. Route a pack/session terminal event to core close; distinguish genuine target exit from transient capture failure or replacement HWND. |
| Use DirectML | `ok/__init__.py:set_use_dml`, GPU-memory Auto decision, OS-build gate | Real framework flag, but native plugin currently constructs `ONNXPaddleOcr(use_angle_cls=False,use_npu=False,use_openvino=True)` and has no corresponding DirectML setting consumer. Inspect actual native OCR/model constructor provider API before adding a control. Do not map DirectML Yes to OpenVINO True. |
| Trigger Interval | `custom_ok/ok/task/TaskExecutor.py:trigger_sleep`, ms/1000 | Real legacy loop delay. Native scheduling has its own service timing; port only a clear inter-service delay at the host scheduling boundary, preserving per-task trigger interval/recovery delays. |
| Start/Stop | GeneralSettings hotkey preference; framework control path | Already listed in final-surfaces plan. Route application pause/resume, preserving enabled services. |
| Kill Launcher After Start | `custom_ok/ok/gui/MainWindow.py:showEvent` calls `pyappify.kill_pyappify()` | Refers to external PyAppify, not GameFrame or game launcher. Expose only when running with that supported external launcher and ownership/API available; no arbitrary process termination. |
| Launch with DX11 | `ok/gui/StartController.py:start_device` appends `-dx11 -d3d11 -force-d3d11` | Consumer exists but reads `get_config('Launch with DX11')`; default field is in Basic Options. This mismatch means field presence does not establish functioning behavior. Native explicit launch argv can support chosen flags; do not claim old toggle worked unchanged. |
| Enable Blur / Blur Algorithm / Blur Interval | optional framework blur config registration | Native saved screenshots already use pack UID redaction; do not equate that with a live OLED overlay. Expose overlay blur only with an actual renderer; preserve screenshot privacy independently. |

App Launcher is **conditional**, not universally supported: `ok/util/GlobalConfig.py:create_app_launcher_options` requires PyAppify `get_app_json_path/get_app_config/update_app_config`, valid `app.json`, then `AppLauncherConfig` writes `auto_start` and update_method; optional `show_pyappify` opens launcher. Labels map Manual Update / Automatic Update(Release Only) / Automatic Update(Pre-release) to MANUAL_UPDATE/AUTO_UPDATE/AUTO_UPDATE_PRE_RELEASE. This controls PyAppify Windows sign-in startup and its updates, not the game pack’s current update pipeline. Current native gamepack updates should keep their own verified package API. Do not copy these fields into launcher.json and imply they update PyAppify.

## Notification implementation and license boundary

The inspected `ok/notification/manager.py` selects all routes; `pipeline.py` provides FIFO thread/5s spacing; `providers.py` holds four HTTP providers. These modules have **real transports**, but provider exceptions are logged and return False; manager ignores route return values. A native route must surface per-provider failure instead of reporting enqueue as successful delivery. No speculative automatic retry is needed.

| Channel | Actual source/API | Minimal supported native behavior |
| --- | --- | --- |
| Windows system | `custom_ok/ok/gui/MainWindow.py:show_notification` uses Qt/tray facilities; manager.system_enabled controls preference | Launcher receives selected notification events, pack-configured route invokes a generic core tray display command. Display inside app remains available. |
| Discord | `providers.py:DiscordProvider.send`; webhook multipart content/images, optional username/avatar, HTTP timeout30 | Reuse adapted provider in AGPL payload, explicit enabled+webhook. HTTP errors return sanitized failure to UI, not webhook-containing exceptions. |
| Telegram | `TelegramBotProvider.send`; Bot API sendMessage/sendPhoto, HTTP and JSON ok checks | token/chat_id; preserve actual text/image support. Never log full token-bearing request URL. |
| Enterprise WeChat / WeCom | `WeComWebhookProvider.send`; markdown and base64 PNG+MD5; errcode check | webhook, explicit error outcome. This is a group bot, not desktop WeChat. |
| QQ Bot | `QQBotProvider.send`; `api.sgroup.qq.com/channels/{id}/messages`, Authorization Bot app_id.token | Current implementation is guild/channel bot and text only; images are merely a text attachment-count note. Do not promise QQ friend/group messaging or actual image upload. Preserve available route with accurate label; external API success still requires real acceptance. |
| QQ desktop | `manager.py` config creates `windows_messenger.MessengerAutomation` targeting QQ.exe; `ppocr.py`, `messenger_images.py` support OCR/clipboard images | Actual desktop automation, marked Not Reliable. Needs window/UI input and clipboard ownership; cannot run concurrently from a notification helper thread while game owns input. Keep visible as unavailable until routed through a safe exclusive desktop-input handoff. Do not silently send using current legacy thread. |
| WeChat desktop | Same classes; WeChat.exe/Weixin.exe, search/contact OCR and clipboard actions | Same ownership requirement; distinct from WeCom. Full migration must record this pending behavior rather than pretend notification schema completes it. |

Observed license conflict: installed `ok_script-1.0.190.dist-info/METADATA` classifier says MIT, but its `licenses/LICENSE.txt` contains AGPLv3. Repository `LICENSE.txt` is AGPLv3, `gameframe/LICENSE` is MIT, and GameFrame README explicitly keeps compatibility/production runtime AGPL. Do not resolve this conflict in favor of the classifier. Source taken from framework/modified repository remains in the AGPL pack with attribution/source availability; do not copy providers, MainWindow, catalogs or production selectors into MIT core. Process separation alone does not remove licensing obligations. New core tray/controller/message plumbing can remain independently written generic code.

The notification modules inspected are dependency-installed files, not tracked repository payload sources. Before reuse, establish exact source provenance/version (including local modifications) and include the selected modules in the gamepack file/license manifest. Missing provenance blocks redistributing those particular files, not implementing documented public HTTP APIs independently in the pack.

## Task 1 — pack preference schema and delivery boundary

**Files:** `src/runtime/native_metadata.py`, native pack defaults/configuration, new focused `src/runtime/native_program_preferences.py` and notification service module only as needed; existing NativeConfigurationTab rendering. Generic core gets only documented message consumption and independently written tray handling.

- [ ] Add only settings whose consumers will ship in the same change. Import legacy corresponding JSON values once without overriding explicitly disabled values; keep secrets inside package data configuration, masked in forms and redacted from logs/diagnostic exports.
- [ ] Route existing `combat-notification` and notified `task-log` once to a pack-owned notification service. Avoid duplicates and never treat all screenshot/evidence events as permission to send images remotely. Feature-code bridge responses stay private and excluded.
- [ ] Begin with local UI/tray and four HTTP provider contracts. Adapt queue ownership/shutdown using standard library; report queued vs delivered vs failure honestly. Do not import legacy NotificationManager, which assumes executor/global_config/OCR/window automation.
- [ ] Preserve legacy desktop channel preferences without enabling unsafe execution. Implement a separate exclusive handoff if desktop notification parity is required; document its pending state until it exists.
- [ ] Fixture-check selected route, transport payload/HTTP/JSON error, disabled route, secret redaction and shutdown. No real messages during automated validation.

## Task 2 — languages in package workers and management

**Actual resources:** tracked repository `i18n/{zh_CN,zh_TW,es_ES,ja_JP,ko_KR}/LC_MESSAGES/ok.po` and compiled `ok.mo`. There is no tracked English ok catalog in the static inventory; English source strings are the default. No tracked `ocr.po`/`ocr.mo` was found. Framework references an `ocr` domain but reference is not proof that its catalog exists in this payload.

Framework Qt resources are `.venv/Lib/site-packages/ok/gui/i18n/{zh_CN,zh_TW,en_US,es_ES,ja_JP,ko_KR}.ts/.qm`; `ok/gui/qt.qrc` embeds five non-English catalogs into `ok/gui/resources.py`, addressed `:/i18n/<locale>.qm`. `ok/gui/util/app.py:init_app_config` installs FluentTranslator and QTranslator. `ok/gui/i18n/GettextTranslator.py` reads the executable-relative i18n directory. Old UI selection is stored in `configs/ui_config.json`, MainWindow.Language, Auto or locale string, and is restart-required.

**Files:** package-only language utility, plugin creation/prepare/execute, `src/runtime/native_configuration.py` startup, `src/management.py`/`run_management_window`, overview startup, pack build manifest and language settings form. Do not import `ok.gui.util.app`, which creates another QApplication and framework singleton/resources.

- [ ] Persist chosen package UI locale with existing ui_config value migration; resolve Auto to the actual system locale at process startup. Use explicit pack-root resource paths, not cwd or executable-relative legacy helpers.
- [ ] Worker/configuration child load `gettext.translation('ok', pack_i18n, languages=[resolved_locale])`, use English NullTranslations for English or supported missing entries, and pass `.gettext` to NativeCombatHost. Keep text-fix/OCR locale separate; do not install a nonexistent OCR domain or globally overwrite `_` with OCR mappings.
- [ ] Management/overview construct QApplication once, install retained package QTranslator/catalog before business widgets, and use gettext for production task metadata. Existing framework context names such as @default/MainWindow do not automatically cover Native* widgets or fixed QLabel strings; explicitly map existing translations and add required strings to pack catalogs. Preserve QTranslator objects for app lifetime.
- [ ] Ship only catalog resources with verified provenance in AGPL pack. Generic MIT launcher has its own independently maintained translations; do not embed copied old Qt resource module there. Language selection may signal restart-required rather than building live widget reconstruction.
- [ ] Check metadata translation in actual configuration child and representative management labels, Auto resolution and English behavior using fixtures. Do not claim six-language completion until new native text has coverage.

## Task 3 — restore saved services when application opens

**Evidence:** `custom_ok/ok/gui/MainWindow.py` post-show startup calls executor.start after integrity review; `AssistantHubTab` describes app-start services with saved switches. Native host restores preferences only after a session exists.

- [ ] Add an explicit session-start operation that starts no foreground one-shot and changes no service switch. Current starting a selected task is unsuitable: choosing auto-combat as a shortcut may enable a saved-disabled service.
- [ ] Launcher saves selected package/device context and schedules automatic session creation after UI is shown and configuration/integrity is ready. Reuse owner/controller leases and startup failures. Missing device configuration shows a clear setup state; no guessed HWND or hardware fallback.
- [ ] Keep user-disabled combat disabled, respect global pause, and avoid a second worker if an owned session already exists. Test saved enabled/disabled mix and opening application without configuration via Replay/Qt fixture.

## Task 4 — account context and activity navigation

**Files:** pack metadata/context protocol, pack management/account UI, generic launcher rendering only; `src/gui/navigation_sections.py`, activity_catalog and production MultiAccountDailyTask remain AGPL.

- [ ] Expose current sequence/account choices and labels from the existing production owner/config selection, rather than creating another account store. Preserve unregistered/no-sequence mode and its meaning. Show verified running account; freeze changes while a foreground account run is active.
- [ ] Reuse pack category/order metadata for tasks and services. Core renders groups without importing Wuthering Waves classes or AGPL navigation functions.
- [ ] Resolve existing visibility mismatch: legacy navigation hides PianoTeachingTask/SecondSolTask/EchoesRemainTask while native manifest exposes them. Default to current product’s intended legacy visibility unless user explicitly restores those tools; keep 29 registered regardless of navigation visibility. Hidden internal material tasks stay callable by production plans.
- [ ] Verify selection persistence, live read-only account context, no-sequence semantics and exact product task list with metadata/Qt fixtures.

## Task 5 — manual Windows-user data mapping and remaining window preferences

- [ ] Display current interactive Windows user, explicit package data root and A/B account-sequence context. A/B game slots do not identify Windows users. Let each manually logged-in OS user choose its own local data root through the launcher’s existing root selection contract; do not store a password, switch OS users, revive KRLauncher or enumerate other users’ profile data.
- [ ] Persist only per-user mappings for the explicitly selected root; scheduled task binding already includes current user/package/data. Avoid silently sharing one mutable root across users. Full data-root movement follows the separate storage migration plan, not an unverified folder change.
- [ ] Implement tray behavior first because it is independent and clearly evidenced. Add trusted-target resize/mute/exit-on-game-exit only with their actual backend consumer and focused fake-window/audio fixtures. Preserve auto-combat intent on capture loss and ordinary errors; these are not game-exit evidence.
- [ ] Expose PyAppify-only options only through verified adapter availability. Native package auto-updates remain a separate product setting with current verified-update behavior; do not repurpose old PyAppify preference labels.

## Release and verification limits

Each implementation unit should have a focused fixture test and review of added protective branches against actual settings/protocol/input contracts. No extra retry layer or compatibility facade is needed. Parent owns code version/release-note synchronization and publishing. This read-only plan changes no product version. v72 integration must precede implementation to avoid conflicts with its live bridge/device UI work. Hardware, real external delivery, OS sign-in startup and cross-user operation require explicit later acceptance; none occurred during this audit.
