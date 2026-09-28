"""Atomic no-replace raw files with anchored directories on Windows and POSIX."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import stat
from uuid import uuid4

from risk_intelligence.domain.evidence import RawEvidence
from .objects import EvidenceIntegrityError, validate_object_path, verify_checksum

_FILE_READ_ATTRIBUTES = 0x80
_GENERIC_READ = 0x80000000
_SHARE_READ = 1
_SHARE_READ_WRITE = 3
_OPEN_EXISTING = 3
_OPEN_REPARSE_POINT = 0x00200000
_BACKUP_SEMANTICS = 0x02000000
_ATTRIBUTE_REPARSE_POINT = 0x400
_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_TAG_INFO = 9


@contextmanager
def _windows_handle(path: Path, *, directory: bool) -> Iterator[int]:
    """Hold a non-reparse handle that denies rename/deletion for its lifetime."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                   wintypes.LPVOID, wintypes.DWORD]
    # OPEN_REPARSE_POINT prevents following the final component. BACKUP_SEMANTICS
    # permits directory handles. No FILE_SHARE_DELETE means ancestors cannot move.
    handle = kernel.CreateFileW(
        str(path), _FILE_READ_ATTRIBUTES if directory else _GENERIC_READ,
        _SHARE_READ_WRITE if directory else _SHARE_READ, None, _OPEN_EXISTING,
        _OPEN_REPARSE_POINT | _BACKUP_SEMANTICS, None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        attributes = (wintypes.DWORD * 2)()
        if not kernel.GetFileInformationByHandleEx(handle, _FILE_ATTRIBUTE_TAG_INFO, attributes, ctypes.sizeof(attributes)):
            raise ctypes.WinError(ctypes.get_last_error())
        if attributes[0] & _ATTRIBUTE_REPARSE_POINT or bool(attributes[0] & _ATTRIBUTE_DIRECTORY) != directory:
            raise ValueError("Storage paths must not contain reparse points or wrong file types")
        yield handle
    finally:
        kernel.CloseHandle(handle)


def _windows_read(path: Path) -> bytes:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    with _windows_handle(path, directory=False) as handle:
        chunks: list[bytes] = []
        buffer = ctypes.create_string_buffer(65536)
        read = wintypes.DWORD()
        while True:
            if not kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(read), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not read.value:
                return b"".join(chunks)
            chunks.append(buffer.raw[:read.value])


class LocalStorage:
    """Preserve exact immutable bytes beneath a configured development root.

    Directory handles prevent symlink/rename escapes. Final publication uses a
    same-filesystem hard link, which fails rather than replacing an existing key.
    A filesystem without hard-link support fails explicitly; no unsafe fallback.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.abspath(root))

    @contextmanager
    def _parent(self, parts: tuple[str, ...], *, create: bool) -> Iterator[tuple[Path, int | None]]:
        path = Path(self.root.anchor)
        components = self.root.parts[1:] + parts[:-1]
        with ExitStack() as stack:
            if os.name == "nt":
                stack.enter_context(_windows_handle(path, directory=True))
                for component in components:
                    path = path / component
                    if create:
                        path.mkdir(exist_ok=True)
                    stack.enter_context(_windows_handle(path, directory=True))
                yield path, None
            else:
                descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                stack.callback(os.close, descriptor)
                for component in components:
                    if create:
                        try:
                            os.mkdir(component, dir_fd=descriptor)
                        except FileExistsError:
                            pass  # The no-follow directory open below validates the existing entry.
                    descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                         dir_fd=descriptor)
                    stack.callback(os.close, descriptor)
                    path = path / component
                yield path, descriptor

    def _read_at(self, parent: Path, descriptor: int | None, name: str) -> bytes:
        if descriptor is None:
            return _windows_read(parent / name)
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(handle, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Raw object must be a regular file")
            return stream.read()

    def read(self, object_path: str) -> bytes:
        """Read exact bytes through anchored handles; absent keys raise FileNotFoundError."""
        parts = validate_object_path(object_path)
        with self._parent(parts, create=False) as (parent, descriptor):
            return self._read_at(parent, descriptor, parts[-1])

    def put(self, evidence: RawEvidence, content: bytes) -> None:
        """Publish verified complete bytes once; identical retries are harmless."""
        evidence = RawEvidence.model_validate(evidence)
        verify_checksum(content, evidence.checksum)
        parts = validate_object_path(evidence.object_path)
        with self._parent(parts, create=True) as (parent, descriptor):
            temporary = ".pending-" + uuid4().hex
            target = parent / temporary if descriptor is None else temporary
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            handle = os.open(target, flags, 0o600, dir_fd=descriptor)
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                verify_checksum(self._read_at(parent, descriptor, temporary), evidence.checksum)
                try:
                    if descriptor is None:
                        os.link(parent / temporary, parent / parts[-1])
                    else:
                        os.link(temporary, parts[-1], src_dir_fd=descriptor, dst_dir_fd=descriptor,
                                follow_symlinks=False)
                except FileExistsError:
                    existing = self._read_at(parent, descriptor, parts[-1])
                    if existing != content:
                        raise EvidenceIntegrityError("Immutable local object already contains different bytes") from None
                verify_checksum(self._read_at(parent, descriptor, parts[-1]), evidence.checksum)
                if descriptor is not None:
                    os.fsync(descriptor)
            finally:
                os.unlink(target, dir_fd=descriptor)
