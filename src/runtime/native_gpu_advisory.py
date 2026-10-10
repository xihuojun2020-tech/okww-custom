# SPDX-License-Identifier: AGPL-3.0-or-later
"""One read-only GPU advisory for the worker's existing trusted Windows target."""

from dataclasses import asdict

from src.runtime.native_logging import Logger


logger = Logger.get_logger(__name__)


class NativeGpuAdvisory:
    def __init__(self, *, detector=None, process_factory=None):
        self.detector, self.process_factory = detector, process_factory
        self._checked = False

    def check(self, device, emit, translate=str):
        """Report uncertainty instead of aborting tasks or inferring disabled.

        The package owns this object for the worker lifetime. It never creates
        another device or requests capture, input, driver writes or HDR changes.
        """
        if self._checked:
            return None
        self._checked = True
        event = {'event': 'task-log', 'advisory': 'gpu-driver', 'level': 'info',
                 'notify': False, 'title': translate('GPU Driver Warning'),
                 'features': [], 'checks': []}
        if 'desktop-handoff' not in device.capabilities:
            event.update(status='skipped', message=translate('GPU driver check skipped for this device.'))
        else:
            try:
                device._check_target_identity()
                window = device.window
                hwnd, pid, created = window.hwnd, window._pid, window._process_created
                if self.process_factory is None:
                    import psutil
                    self.process_factory = psutil.Process
                process = self.process_factory(pid)
                if process.create_time() != created:
                    raise RuntimeError('Selected process identity changed before GPU advisory')
                executable = process.exe()
                # exe() is an external process query. Do not use its result for a
                # reused HWND/PID observed while the query was in progress.
                device._check_target_identity()
                if self.detector is None:
                    from src.runtime.vendor.gpu_driver_settings import get_gpu_driver_post_processing_report
                    self.detector = get_gpu_driver_post_processing_report
                report = self.detector(executable, hwnd)
                event['features'] = [asdict(feature) for feature in report['enabled']]
                event['checks'] = [asdict(check) for check in report['checks']]
                unknown = any(check.enabled is None for check in report['checks'])
                if report['enabled']:
                    event.update(status='warning', level='warning', notify=True,
                        message='\n'.join(translate('{vendor} {feature} is enabled and may cause malfunctions!').format(
                            vendor=feature.vendor, feature=translate(feature.feature)) for feature in report['enabled']))
                elif unknown:
                    event.update(status='unknown',
                        message=translate('GPU driver check incomplete; unavailable results remain unknown.'))
                else:
                    event.update(status='checked',
                        message=translate('GPU driver checks completed; no enabled effects were detected.'))
            except Exception as error:
                logger.error('GPU startup advisory failed; continuing with unknown state', error)
                event.update(status='unknown', level='warning', failure=type(error).__name__,
                    message=translate('GPU driver check failed; state remains unknown ({error}).').format(
                        error=type(error).__name__))
        try:
            emit(event)
        except Exception as error:
            logger.error('Unable to deliver GPU startup advisory; continuing task startup', error)
        return event
