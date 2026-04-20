"""InferGrid -- tenant-fair LLM inference orchestration on a single GPU."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("infergrid")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
