"""
leave_guild.py — take the bot out of a server, from the command line.

    python leave_guild.py                     # list every server, change nothing
    python leave_guild.py 1414050080515690559 # leave that one

Written after `on_ready`'s startup line (see optimized_bot._format_guilds)
turned up a server nobody recognised. There is no in-Discord way to do this
that doesn't depend on already being in the server with the right
permissions, and `Guild.leave()` is the only API for it.

**This host has no shell**, so "the command line" is the panel's startup
command, not a terminal — the panel's own "terminal" was tested directly and
just echoes input back (see CLAUDE.md). The working sequence is:

    1. Panel -> Startup -> change the file/args from `optimized_bot.py` to
       `leave_guild.py <guild id>`.
    2. Restart. The console shows what it did; the process then exits.
    3. Change the startup back to `optimized_bot.py` and restart again.

Step 3 is not optional — leave it pointing here and the bot never comes
back up.

Deliberately standalone: it imports `discord` and nothing else from this
project. Importing `optimized_bot` would run db migrations, take a backup
and re-sync the whole command tree as a side effect of wanting to leave one
server, and `db.load_league_names_sync()` runs at import in three more
modules besides. None of that has any business running here.

Safe by default: with no guild id it only lists. It never resolves a server
by name — names are not unique and get renamed, and the whole point of this
script is acting on one specific server.

Exit codes: 0 did what was asked, 1 did not (no token, bad id, not in that
server, or the API refused).
"""

import asyncio
import os
import sys

import discord

# Long enough for a cold connect on a slow host, short enough that a wedged
# login shows up as a failure rather than a container sitting there forever.
_READY_TIMEOUT = 60.0


def parse_args(argv: list[str]) -> int | None:
    """
    argv[1:] -> the guild id to leave, or None meaning "just list".

    Raises ValueError with a message meant to be read in the panel console,
    since that is the only place anyone will see it.
    """
    args = [a for a in argv[1:] if a.strip()]
    if not args:
        return None
    if len(args) > 1:
        raise ValueError(
            f"Expected one guild id, got {len(args)}: {' '.join(args)}\n"
            "Leave one server at a time — this is not an operation to batch.")
    raw = args[0].strip()
    if not raw.isdigit():
        raise ValueError(
            f"{raw!r} is not a guild id. Ids are all digits — in Discord, turn on "
            "Developer Mode, then right-click the server and Copy Server ID.")
    return int(raw)


def format_guild(guild) -> str:
    """One line per server, with everything needed to recognise it."""
    owner = getattr(guild, "owner", None)
    owner_txt = f"owner {owner}" if owner else f"owner id {getattr(guild, 'owner_id', '?')}"
    members = getattr(guild, "member_count", None)
    members_txt = f"{members} members" if members is not None else "member count unknown"
    return f"  {guild.name}  (id {guild.id}, {members_txt}, {owner_txt})"


def find_guild(guilds, guild_id: int):
    """The guild with that id, or None. Plain lookup over the cached list —
    `Client.get_guild` would do, but passing the list in keeps this testable
    without a client."""
    for g in guilds:
        if g.id == guild_id:
            return g
    return None


async def run(token: str, guild_id: int | None) -> int:
    """Connect, do the one thing, disconnect. Returns the process exit code."""
    intents = discord.Intents.default()
    # Explicitly *not* message_content: it's privileged, and nothing here
    # reads a message. The default intents already include guilds, which is
    # what populates the cache this reads.
    client = discord.Client(intents=intents)
    result = {"code": 1}

    @client.event
    async def on_ready():
        try:
            guilds = sorted(client.guilds, key=lambda g: g.name.lower())
            print(f"Signed in as {client.user} — in {len(guilds)} server(s):")
            for g in guilds:
                print(format_guild(g))

            if guild_id is None:
                print("\nNo guild id given, so nothing was changed.")
                print("Re-run with one of the ids above to leave that server.")
                result["code"] = 0
                return

            target = find_guild(guilds, guild_id)
            if target is None:
                # The listing above is the useful part of this failure, so it
                # is printed before this check rather than after it.
                print(f"\nNot in any server with id {guild_id} — nothing to leave.")
                print("Either it already left, or that id belongs to somewhere else.")
                result["code"] = 1
                return

            print(f"\nLeaving {target.name} (id {target.id})...")
            await target.leave()
            print("Left. Re-joining needs a fresh invite from someone with "
                  "Manage Server there — this is not undoable from here.")
            result["code"] = 0
        except discord.HTTPException as e:
            print(f"\nDiscord refused: {e}", file=sys.stderr)
            result["code"] = 1
        except Exception as e:
            print(f"\nFailed: {type(e).__name__}: {e}", file=sys.stderr)
            result["code"] = 1
        finally:
            # Always close, including on the failure paths — otherwise the
            # process hangs on an open gateway connection and the panel shows
            # a container that never exits.
            await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=_READY_TIMEOUT)
    except asyncio.TimeoutError:
        print(f"Gave up after {_READY_TIMEOUT:.0f}s waiting to connect.", file=sys.stderr)
        return 1
    except discord.LoginFailure as e:
        print(f"Could not log in: {e}", file=sys.stderr)
        print("Check DISCORD_TOKEN on the panel's environment tab.", file=sys.stderr)
        return 1
    except Exception as e:
        # A clean line beats a traceback in the panel console, but keep the
        # type so an unexpected failure is still diagnosable.
        print(f"Could not connect: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        # on_ready closes the client on every path it reaches. This covers
        # the ways of getting here without it having run at all — otherwise
        # aiohttp prints "Unclosed connector" and a repr of its connection
        # deque into the console at exactly the moment someone is trying to
        # read an error out of it. Confirmed against a bad token.
        if not client.is_closed():
            await client.close()
    return result["code"]


def main(argv: list[str]) -> int:
    try:
        guild_id = parse_args(argv)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("DISCORD_TOKEN is not set.", file=sys.stderr)
        print("It lives on the panel's environment tab, not in a file on disk "
              "(this host has no .env — see CLAUDE.md).", file=sys.stderr)
        return 1

    return asyncio.run(run(token, guild_id))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
