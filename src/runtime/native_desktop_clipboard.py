# SPDX-License-Identifier: AGPL-3.0-or-later
"""STA-owned, materialized OLE clipboard preservation for messenger images."""
from contextlib import contextmanager
import io


class ClipboardChanged(RuntimeError):
    pass


class OleClipboardAPI:
    def __init__(self):
        import ctypes
        import pythoncom
        import win32clipboard
        from win32com.shell import shell
        self.com, self.clipboard = pythoncom, win32clipboard
        self.shell = shell
        self.ole32 = ctypes.OleDLL('ole32')
        self.ole32.OleUninitialize.argtypes = ()
        self.ole32.OleUninitialize.restype = None

    def initialize(self): self.com.OleInitialize()
    def uninitialize(self): self.ole32.OleUninitialize()

    def sequence(self): return self.clipboard.GetClipboardSequenceNumber()
    def object(self, entries):
        # Native IDataObject copies STGMEDIUMs, including GDI/metafile ownership.
        # SHCreateDataObject documents generic arbitrary-format SetData support.
        snapshot = self.shell.SHCreateDataObject([], [], None, self.com.IID_IDataObject)
        for fmt, medium in entries:
            snapshot.SetData(fmt, medium, False)
        return snapshot
    def png_object(self, png):
        from PIL import Image
        image = Image.open(io.BytesIO(png)).convert('RGB')
        output = io.BytesIO()
        image.save(output, format='BMP')
        png_id = self.clipboard.RegisterClipboardFormat('PNG')
        entries = []
        for format_id, data in ((8, output.getvalue()[14:]), (png_id, png)):
            medium = self.com.STGMEDIUM()
            medium.set(self.com.TYMED_HGLOBAL, data)
            entries.append(((format_id, None, self.com.DVASPECT_CONTENT, -1, medium.tymed), medium))
        return self.object(entries)


class PreservedClipboard:
    def __init__(self, api): self.api = api

    @contextmanager
    def preserve(self):
        api = self.api
        # OleInitialize fails on an MTA owner; no clipboard is overwritten then.
        api.initialize()
        original = None
        source = None
        overwritten = False
        entries = []
        try:
            sequence = api.sequence()
            source = api.com.OleGetClipboard()
            for fmt in source.EnumFormatEtc(api.com.DATADIR_GET) if source is not None else ():
                for tymed in (1, 2, 4, 8, 16, 32, 64):
                    if fmt[4] & tymed:
                        requested = (*fmt[:4], tymed)
                        entries.append((requested, source.GetData(requested)))
            # GetData materializes all formats before changing any global data.
            original = api.object(entries) if entries else None
            for fmt, _ in entries:
                # Verify replay/copy of each medium before overwriting any format.
                replay = original.GetData(fmt)
                replay = None
            source = None
            if api.sequence() != sequence:
                raise ClipboardChanged('Clipboard changed before desktop image input')
            owner = self
            def set_png(png):
                nonlocal sequence, overwritten
                if api.sequence() != sequence:
                    raise ClipboardChanged('Clipboard changed during desktop image input')
                image_object = api.png_object(png)
                api.com.OleSetClipboard(image_object)
                overwritten = True
                sequence = api.sequence()
                api.com.OleFlushClipboard()
                sequence = api.sequence()
            owner.set_png = set_png
            try:
                yield owner
            finally:
                if overwritten:
                    if api.sequence() != sequence:
                        raise ClipboardChanged('External clipboard change retained; original restoration skipped')
                    api.com.OleSetClipboard(original)
                    if original is not None: api.com.OleFlushClipboard()
        finally:
            # Complete flush before releasing interfaces and the STA apartment.
            original = None
            source = None
            entries.clear()
            api.uninitialize()
