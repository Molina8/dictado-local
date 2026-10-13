import sys
import winreg

from dictado.autostart import RUN_VALUE, apply_autostart, current_command


class _Key:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_frozen_command_quotes_the_executable(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Users\jesus\AppData\Local\Programs\dictado-local\DictadoLocal.exe")
    assert current_command() == r'"C:\Users\jesus\AppData\Local\Programs\dictado-local\DictadoLocal.exe"'


def test_apply_autostart_writes_the_run_value(monkeypatch) -> None:
    written: dict[str, str] = {}

    def create_key(_root, _path):
        return _Key()

    def set_value(_key, name, _reserved, _kind, value):
        written[name] = value

    monkeypatch.setattr(winreg, "CreateKey", create_key)
    monkeypatch.setattr(winreg, "SetValueEx", set_value)
    apply_autostart(True, r'"C:\App\DictadoLocal.exe"')
    assert written[RUN_VALUE] == r'"C:\App\DictadoLocal.exe"'


def test_apply_autostart_removes_the_run_value(monkeypatch) -> None:
    removed: list[str] = []

    monkeypatch.setattr(winreg, "OpenKey", lambda *_args, **_kwargs: _Key())
    monkeypatch.setattr(winreg, "DeleteValue", lambda _key, name: removed.append(name))
    apply_autostart(False, r'"C:\App\DictadoLocal.exe"')
    assert removed == [RUN_VALUE]


def test_missing_run_value_is_not_an_error(monkeypatch) -> None:
    def delete(_key, _name):
        raise FileNotFoundError

    monkeypatch.setattr(winreg, "OpenKey", lambda *_args, **_kwargs: _Key())
    monkeypatch.setattr(winreg, "DeleteValue", delete)
    apply_autostart(False)
