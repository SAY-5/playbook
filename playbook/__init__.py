"""Playbook: expert SOP to deployed tool-calling agent with evals and a feedback loop."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("playbook")
except PackageNotFoundError:  # running from a checkout that was never installed
    __version__ = "0+unknown"
