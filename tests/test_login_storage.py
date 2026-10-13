"""Credential protection works before writing secrets, including native Windows ACLs."""

import json
import os

import pytest

from scripts import chatgpt_login as helper


def test_private_file_replace_and_permissions(tmp_path):
    path = tmp_path / "account.json"
    helper.atomic_private_write(path, {"token": "test-value"})
    helper.atomic_private_write(path, {"token": "replacement"})
    assert json.loads(path.read_text()) == {"token": "replacement"}
    if os.name == "nt":
        import win32security

        security = win32security.GetNamedSecurityInfo(
            str(path), win32security.SE_FILE_OBJECT, win32security.DACL_SECURITY_INFORMATION
        )
        assert security.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED
        assert security.GetSecurityDescriptorDacl().GetAceCount() == 1
    else:
        assert path.stat().st_mode & 0o777 == 0o600


def test_permission_failure_never_replaces_credentials(tmp_path, monkeypatch):
    path = tmp_path / "account.json"
    helper.atomic_private_write(path, {"token": "original"})

    def fail(*args):
        raise OSError("cannot protect")

    if os.name == "nt":
        monkeypatch.setattr(helper, "_protect_windows_file", fail)
    else:
        monkeypatch.setattr(helper.os, "fchmod", fail)
    with pytest.raises(OSError):
        helper.atomic_private_write(path, {"token": "never-write-this"})
    assert json.loads(path.read_text()) == {"token": "original"}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["account.json"]
