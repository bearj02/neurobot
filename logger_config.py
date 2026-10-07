"""
logger_config.py — logging for the bot *and* for discord.py itself.

Why this file does more than it looks like it should:

discord.py configures its own logging inside `Client.run()`, not inside
`Client.connect()`/`Client.start()`. Verified directly against the v2.7.1
source: `run()` calls `utils.setup_logging(handler=..., formatter=...,
level=..., root=...)`, while `start()` is just `await self.login(token)`
followed by `await self.connect(reconnect=reconnect)` and takes no logging
arguments at all.

This bot starts with `await bot.start(TOKEN)` (see optimized_bot.safe_start,
which needs its own retry loop around the 429/Cloudflare case and therefore
can't use the blocking `run()`). The consequence was that **every log record
discord.py emitted went to a logger with no handler on it** — including the
one that matters most when a button "fails":

    discord.ui.view  ->  "Ignoring exception in view %r for item %r"

That record carries the full traceback of whatever a component callback
raised. Discord shows the clicker a bare "This interaction failed" and the
real reason was being dropped on the floor. Same for `discord.client`'s
event errors and `discord.app_commands.tree`'s command errors.

So: configure the `discord` logger tree explicitly here, rather than relying
on a `run()` call that never happens.

Everything is driven by environment variables so the verbosity can be turned
up on the panel without a code change and a redeploy:

    LOG_LEVEL          app logger level          (default INFO)
    DISCORD_LOG_LEVEL  discord.* level           (default INFO)
    HTTP_LOG_LEVEL     discord.http level        (default WARNING)
    GATEWAY_LOG_LEVEL  discord.gateway level     (default WARNING)
    LOG_TO_FILE        "0"/"false" disables the rotating file  (default on)
    LOG_FILE           path for it               (default logs/bot.log)

`discord.http` and `discord.gateway` get their own knobs because they are
the two that drown everything else: at DEBUG, `discord.http` logs every
single REST call and `discord.gateway` logs every heartbeat. They are
genuinely useful when chasing a rate limit or a reconnect loop, and
actively harmful the rest of the time, so they default quieter than the
rest of the library and can be raised on their own.
"""

import logging
import logging.handlers
import os
import sys

__all__ = ["global_logger", "setup_logger", "configure_logging", "current_levels"]

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

# The app's own logger name, kept as-is: every module in this project does
# `from logger_config import global_logger as logger`.
APP_LOGGER_NAME = "global_logger"

_configured = False
_last_applied: dict | None = None


def _env_level(var: str, default: int) -> int:
    """
    Read a level from the environment. Accepts a name ("DEBUG") or a number
    ("10"), case-insensitively. An unrecognised value falls back to the
    default rather than raising — a typo in a panel env var should not stop
    the bot from starting.
    """
    raw = os.getenv(var)
    if not raw:
        return default
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    resolved = logging.getLevelName(raw.upper())
    # getLevelName returns the string "Level X" for anything it doesn't know.
    return resolved if isinstance(resolved, int) else default


def _env_flag(var: str, default: bool) -> bool:
    raw = os.getenv(var)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _build_handlers() -> list[logging.Handler]:
    formatter = logging.Formatter(_DEFAULT_FORMAT, _DEFAULT_DATEFMT)

    # stdout, not stderr: the host panel's console tails stdout, and sending
    # ordinary INFO lines to stderr makes every one of them look like a fault
    # in logs that get split by stream.
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    handlers: list[logging.Handler] = [stream]

    if _env_flag("LOG_TO_FILE", True):
        path = os.getenv("LOG_FILE", os.path.join("logs", "bot.log"))
        try:
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            # Bounded on purpose: this host has limited disk and no shell to
            # clean up with. 5 x 2MB is enough to cover a few days of INFO
            # and still hold a full DEBUG session when one is turned on.
            file_handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            handlers.append(file_handler)
        except OSError as e:
            # A read-only or full disk must not stop the bot from starting —
            # console logging alone is still better than falling over.
            stream.handle(logging.LogRecord(
                APP_LOGGER_NAME, logging.ERROR, __file__, 0,
                "File logging disabled, could not open %s: %s", (path, e), None,
            ))

    return handlers


def configure_logging(force: bool = False) -> logging.Logger:
    """
    Attach handlers to the app logger and to discord.py's loggers.

    Idempotent: calling it twice does not double every line. `force=True`
    rebuilds the handlers, which is what a runtime log-level change would
    need.
    """
    global _configured
    if _configured and not force:
        return logging.getLogger(APP_LOGGER_NAME)

    handlers = _build_handlers()

    app_level = _env_level("LOG_LEVEL", logging.INFO)
    targets = {
        APP_LOGGER_NAME: app_level,
        "discord": _env_level("DISCORD_LOG_LEVEL", logging.INFO),
        "discord.http": _env_level("HTTP_LOG_LEVEL", logging.WARNING),
        "discord.gateway": _env_level("GATEWAY_LOG_LEVEL", logging.WARNING),
    }

    for name, level in targets.items():
        logger = logging.getLogger(name)
        for old in list(logger.handlers):
            logger.removeHandler(old)
        for handler in handlers:
            logger.addHandler(handler)
        logger.setLevel(level)
        # Stop at these loggers. Without this, anything that configures the
        # root logger later (a library, or a stray basicConfig) would print
        # every record a second time.
        logger.propagate = False

    global _last_applied
    _configured = True
    # Announce only when the resolved levels actually changed. This runs
    # twice on every startup by design — once at import, once after
    # load_dotenv() — and logging an identical line both times just reads as
    # something having gone wrong.
    if targets != _last_applied:
        logging.getLogger(APP_LOGGER_NAME).info(
            "Logging configured — app=%s discord=%s http=%s gateway=%s",
            logging.getLevelName(targets[APP_LOGGER_NAME]),
            logging.getLevelName(targets["discord"]),
            logging.getLevelName(targets["discord.http"]),
            logging.getLevelName(targets["discord.gateway"]),
        )
        _last_applied = dict(targets)
    return logging.getLogger(APP_LOGGER_NAME)


def current_levels() -> dict:
    """{logger name: level name} for the loggers this module manages — so a
    command can report what the bot is actually logging at right now."""
    return {
        name: logging.getLevelName(logging.getLogger(name).level)
        for name in (APP_LOGGER_NAME, "discord", "discord.http", "discord.gateway")
    }


def setup_logger() -> logging.Logger:
    """Backwards-compatible alias — this used to be the whole module."""
    return configure_logging()


global_logger = configure_logging()
