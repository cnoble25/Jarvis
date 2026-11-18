"""
Make NVIDIA's CUDA math libraries visible to CTranslate2 without touching the system.

The pip wheels nvidia-cublas-cu12 / nvidia-cudnn-cu12 install the shared libraries inside
site-packages, where the dynamic loader doesn't look. CTranslate2 dlopen()s them by soname
(libcublas.so.12, libcudnn*.so.9), and LD_LIBRARY_PATH can't be changed after start-up,
so we preload them with RTLD_GLOBAL; the later dlopen() then finds the already-loaded copy.
"""

import ctypes
import glob
import os
import site
from typing import Optional

_cuda_ready: Optional[bool] = None

_PATTERNS = [
    "nvidia/cuda_nvrtc/lib/libnvrtc.so.*",
    "nvidia/cublas/lib/libcublasLt.so.*",
    "nvidia/cublas/lib/libcublas.so.*",
    "nvidia/cudnn/lib/libcudnn*.so.*",
]


def _site_dirs():
    dirs = list(site.getsitepackages())
    try:
        dirs.append(site.getusersitepackages())
    except Exception:
        pass
    return [d for d in dirs if os.path.isdir(d)]


def cuda_available() -> bool:
    """True when a CUDA GPU is present and CTranslate2 can use it (libraries preloaded once)."""
    global _cuda_ready
    if _cuda_ready is not None:
        return _cuda_ready
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() == 0:
            _cuda_ready = False
            return False
    except Exception:
        _cuda_ready = False
        return False

    files = []
    for root in _site_dirs():
        for pattern in _PATTERNS:
            files.extend(sorted(glob.glob(os.path.join(root, pattern))))
    # cuDNN's sub-libraries depend on each other; a second pass picks up the ones that failed first.
    pending = files
    for _ in range(2):
        failed = []
        for path in pending:
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                failed.append(path)
        pending = failed
    _cuda_ready = True
    return True
