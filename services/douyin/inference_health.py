"""Classify recoverable inference failures without retrying publication."""
import ctypes
import os


def inference_failure_kind(error):
    text = str(error).lower()
    if any(value in text for value in ('out-of-memory', 'out of memory', 'bad_alloc',
                                       'failed to allocate', 'cuda_host buffer')):
        return 'memory'
    if 'cuda error' in text or 'ggml_assert' in text:
        return 'gpu'
    if any(value in text for value in ('runner has unexpectedly stopped',
                                       'connection was forcibly closed', 'wsarecv',
                                       'connection refused', 'winerror 10061')):
        return 'runner'
    if '视频理解模型' in text and any(value in text for value in (
            'timed out', 'http 503', 'http 502', 'connection reset', 'remote end closed',
            'connection closed', '连接失败')):
        return 'transport'
    return ''


def memory_snapshot():
    if os.name != 'nt':
        return {}
    class Memory(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in ('physical', 'available_physical',
                'commit_limit', 'available_commit', 'virtual', 'available_virtual', 'extended')]
    value = Memory()
    value.length = ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        return {}
    return {name: getattr(value, name) for name in
            ('physical', 'available_physical', 'commit_limit', 'available_commit')}
