"""snapshot/restore/set_text with a fake NSPasteboard.

Runs on every platform: the macOS module is imported and its clipboard
functions are exercised against an object that mimics the pyobjc interface
(`pasteboardItems`, `types`, `dataForType_`, `writeObjects_`, ...), so a real
Mac is not needed for the logic.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the darwin platform import guard does not apply on Windows",
)


def _import_macos():
    """Import the macos platform module with pystray on a dummy backend.

    On headless Linux CI pystray would reach for X11; on darwin it is already
    importable. The PYSTRAY_BACKEND env var is only set off-darwin.
    """
    import os

    if sys.platform == "darwin":
        from dictado.platform import macos

        return macos
    os.environ["PYSTRAY_BACKEND"] = "dummy"
    for name in [key for key in sys.modules if key.startswith("pystray")]:
        sys.modules.pop(name, None)
    from dictado.platform import macos

    return macos


class _FakeData:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __bytes__(self) -> bytes:
        return self.payload


class _FakeItem:
    def __init__(self, types: dict[str, bytes]) -> None:
        self._types = types

    def types(self):
        return list(self._types)

    def dataForType_(self, uti: str):
        return _FakeData(self._types[uti])


class _FakeItems(list):
    pass


class _FakePasteboard:
    def __init__(self) -> None:
        self.clear_count = 0
        self.written: list[dict] = []
        self._items: _FakeItems = _FakeItems()
        self.reject = False

    def pasteboardItems(self):
        return self._items

    def clearContents(self) -> int:
        self.clear_count += 1
        return 0 if self.reject else 1

    def writeObjects_(self, objects) -> bool:
        if self.reject:
            return False
        self.written.extend(objects)
        self._items = _FakeItems(
            _FakeItem({uti: bytearray(data.payload)}) for obj in objects for uti, data in obj.items()
        )
        return True

    def stringForType_(self, uti: str):
        for item in self._items:
            if uti in item._types:
                return bytes(item._types[uti]).decode("utf-8")
        return None


@pytest.fixture
def fake_board(monkeypatch):
    """Inject a stub Cocoa module plus a fake pasteboard.

    pyobjc only exists on macOS; the stub makes the module-level functions
    testable from any platform (CI linux included).
    """
    import types

    macos = _import_macos()

    class _StubData:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

    class _StubNSData:
        @staticmethod
        def dataWithBytes_length_(payload, length):
            return _StubData(bytes(payload))

    cocoa = types.ModuleType("Cocoa")
    cocoa.NSPasteboard = type("NSPasteboard", (), {"generalPasteboard": staticmethod(lambda: None)})
    cocoa.NSData = _StubNSData
    cocoa.NSMutableDictionary = type(
        "NSMutableDictionary",
        (),
        {"dictionary": staticmethod(dict)},
    )
    monkeypatch.setitem(sys.modules, "Cocoa", cocoa)

    board = _FakePasteboard()

    def items_of(payload):
        # writeObjects_ receives [{uti: _StubData}]
        out = []
        for obj in payload:
            out.append(_FakeItem({uti: bytes(data.payload) for uti, data in obj.items()}))
        return _FakeItems(out)

    def write(objects) -> bool:
        if board.reject:
            return False
        board.written.extend(objects)
        board._items = items_of(objects)
        return True

    monkeypatch.setattr(board, "writeObjects_", write, raising=False)
    monkeypatch.setattr(macos, "_pasteboard", lambda: board)
    return board


def _macos():
    return _import_macos()


def test_snapshot_keeps_every_type_of_every_item(fake_board) -> None:
    macos = _macos()
    fake_board._items = _FakeItems(
        [
            _FakeItem({"public.utf8-plain-text": b"hola", "public.tiff": b"\x89PNG"}),
            _FakeItem({"public.html": b"<b>x</b>"}),
        ]
    )
    saved = macos.snapshot()
    assert saved is not None
    types = [uti for item in saved.items for uti, _data in item]
    assert "public.utf8-plain-text" in types
    assert "public.tiff" in types
    assert "public.html" in types


def test_snapshot_of_an_empty_board_is_falsy(fake_board) -> None:
    macos = _macos()
    assert not macos.snapshot().items


def test_set_text_and_get_roundtrip(fake_board) -> None:
    macos = _macos()
    macos.set_text("texto áéíóú")
    assert macos.get_clipboard_text() == "texto áéíóú"


def test_restore_puts_every_item_back(fake_board) -> None:
    macos = _macos()
    fake_board._items = _FakeItems([_FakeItem({"public.utf8-plain-text": b"viejo"})])
    saved = macos.snapshot()
    macos.set_text("nuevo")
    assert macos.get_clipboard_text() == "nuevo"
    macos.restore(saved)
    assert macos.get_clipboard_text() == "viejo"
    assert fake_board.written, "writeObjects_ debe recibir el snapshot"


def test_restore_of_an_empty_snapshot_is_a_noop(fake_board) -> None:
    macos = _macos()
    fake_board._items = _FakeItems([_FakeItem({"public.utf8-plain-text": b"actual"})])
    macos.restore(macos.MacClipboardSnapshot([]))
    assert macos.get_clipboard_text() == "actual"


def test_restore_with_a_rejecting_board_does_not_crash(fake_board, caplog) -> None:
    macos = _macos()
    fake_board.reject = True
    saved = macos.MacClipboardSnapshot([[("public.utf8-plain-text", b"x")]])
    import logging

    caplog.set_level(logging.DEBUG)
    macos.restore(saved)  # swallow + log only


def test_paste_text_swaps_clipboard_and_restores(monkeypatch, fake_board) -> None:
    macos = _macos()
    events: list[str] = []

    monkeypatch.setattr(macos, "activate_pid", lambda pid: events.append(f"activate-{pid}") or True)
    monkeypatch.setattr(macos, "send_cmd_v", lambda: events.append("cmdv"))
    monkeypatch.setattr(macos.time, "sleep", lambda _s: events.append("sleep"))

    macos.paste_text("texto pegado", 450, 4242)
    # activate, 0.03 sleep, cmdv, restore_delay sleep
    assert events == ["activate-4242", "sleep", "cmdv", "sleep"]
    assert macos.get_clipboard_text() == "texto pegado"