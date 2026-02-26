"""CLI module for nanobot."""

from nanobot.cli.app import app

__all__ = ["app"]

from nanobot.cli import onboard
from nanobot.cli import gateway
from nanobot.cli import agent
from nanobot.cli import channels
from nanobot.cli import cron
from nanobot.cli import status