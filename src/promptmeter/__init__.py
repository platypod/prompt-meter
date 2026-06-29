"""prompt-meter — provider-agnostic AI coding-assistant usage telemetry shipper.

See the README for the architecture and the provider contract.
"""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("prompt-meter")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0+unknown"
