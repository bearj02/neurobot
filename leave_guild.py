"""
leave_guild.py — take the bot out of a server, and keep it out.

    python leave_guild.py                          # list every server, change nothing
    python leave_guild.py 1414050080515690559      # leave that one, once
    python leave_guild.py --blacklist 1414...      # leave it, and auto-leave if re-added
    python leave_guild.py --unblacklist 1414...    # stop auto-leaving it
    python leave_guild.py --blacklisted            # show the blacklist (no login)

Written after `on_ready`'s startup line (see optimized_bot._format_guilds)
turned up a server nobody recognised. There is no in-Discord way to do this
that doesn't depend on already being in the server with the right
permissions, and `Guild.leave()` is the only API for it.

**Leaving is not enough on its own.** Anyone with the invite link can add the
bot straight back, which happened. A bot cannot refuse an invite, so the
blacklist works by leaving the moment it arrives: the running bot reads
`guild_blacklist.json` (via `load_blacklist`, below) in `on_guild_join` and
again at startup, for servers it was added to while offline. The real fix is
upstream — Developer Portal -> the application -> Bot -> turn off "Public
Bot", so only the owner can add it at all. The blacklist is for the servers
that already have a link.

`guild_blacklist.json` is server-only data, `.gitignore`d like the database:
tracked, it would be rewritten from the repo by the GitHub sync on every
restart, silently dropping anything added on the server. The bot re-reads it
on every join, so an entry added here takes effect without a restart.

Run it from the panel's shell, next to the running bot — two connections on
one token is fine for a script this short.

Deliberately standalone: it imports `discord` and the standard library and
nothing else from this project. Importing `optimized_bot` would run db
migrations, take a backup and re-sync the whole command tree as a side effect
of wanting to leave one server, and `db.load_league_names_sync()` runs at
import in three more modules besides. The dependency runs the other way:
optimized_bot imports `load_blacklist` from here, so there is one reader.

Safe by default: with no arguments it only lists. It never resolves a server
by name — names are not unique and get renamed, and the whole point of this
script is acting on one specific server.

Exit codes: 0 did what was asked, 1 did not (no token, bad id, not in that
server, an unreadable blacklist, or the API refused).
"""

import asyncio
import datetime
import json
import os
import sys

import discord

# Long enough for a cold connect on a slow host, short enough that a wedged
# login shows up as a failure rather than a container sitting there forever.
_READY_TIMEOUT = 60.0

BLACKLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "guild_blacklist.json")

_USAGE = (
    "usage:\n"
    "  python leave_guild.py                      list servers\n"
    "  python leave_guild.py <id>                 leave once\n"
    "  python leave_guild.py --blacklist <id>     leave and keep out\n"
    "  python leave_guild.py --unblacklist <id>   allow back in\n"
    "  python leave_guild.py --blacklisted        show the blacklist")


# --- the blacklist file ------------------------------------------------------

def load_blacklist(path: str = BLACKLIST_PATH) -> dict[int, dict]:
    """
    {guild_id: {"name": ..., "added": ...}}. A missing file is an empty
    blacklist — that is the normal state before the first entry.

    An unreadable one raises ValueError rather than reading as empty: an empty
    blacklist means "let everyone in", which is the wrong thing to fall back to
    silently, and treating it as empty here would let the next save overwrite
    the entries it couldn't read.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {int(k): dict(v) for k, v in data["guilds"].items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"{path} is unreadable ({type(e).__name__}: {e}). "
                         "Fix or delete it by hand — it was left untouched.") from e


def save_blacklist(entries: dict[int, dict], path: str = BLACKLIST_PATH) -> None:
    """Write via a temp file and rename, so a crash mid-write can't leave the
    bot reading half a file."""
    data = {"guilds": {str(k): v for k, v in sorted(entries.items())}}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def add_to_blacklist(guild_id: int, name: str | None = None,
                     path: str = BLACKLIST_PATH) -> bool:
    """Returns False if it was already there (name refreshed if now known)."""
    entries = load_blacklist(path)
    existed = guild_id in entries
    entry = entries.get(guild_id, {"added": datetime.date.today().isoformat()})
    if name:
        entry["name"] = name
    entry.setdefault("name", None)
    entries[guild_id] = entry
    save_blacklist(entries, path)
    return not existed


def remove_from_blacklist(guild_id: int, path: str = BLACKLIST_PATH) -> bool:
    """Returns False if it wasn't there."""
    entries = load_blacklist(path)
    if guild_id not in entries:
        return False
    del entries[guild_id]
    save_blacklist(entries, path)
    return True


# --- arguments ---------------------------------------------------------------

def _parse_id(raw: str) -> int:
    raw = raw.strip()
    if not raw.isdigit():
        raise ValueError(
            f"{raw!r} is not a guild id. Ids are all digits — in Discord, turn on "
            "Developer Mode, then right-click the server and Copy Server ID.")
    return int(raw)


def parse_args(argv: list[str]) -> tuple[str, int | None]:
    """
    argv[1:] -> (action, guild id). Actions: "list", "leave", "blacklist",
    "unblacklist", "show". Only "list" and "show" have no id.

    Raises ValueError with a message meant to be read in the console.
    """
    args = [a.strip() for a in argv[1:] if a.strip()]
    if not args:
        return "list", None
    flags = {"--blacklist": "blacklist", "--unblacklist": "unblacklist",
             "--blacklisted": "show"}
    action = "leave"
    if args[0].startswith("--"):
        if args[0] not in flags:
            raise ValueError(f"Unknown option {args[0]!r}.\n{_USAGE}")
        action = flags[args.pop(0)]
        if action == "show":
            if args:
                raise ValueError(f"--blacklisted takes no id.\n{_USAGE}")
            return "show", None
    if not args:
        raise ValueError(f"Expected a guild id.\n{_USAGE}")
    if len(args) > 1:
        raise ValueError(
            f"Expected one guild id, got {len(args)}: {' '.join(args)}\n"
            "Leave one server at a time — this is not an operation to batch.")
    return action, _parse_id(args[0])


# --- display -----------------------------------------------------------------

def format_guild(guild, blacklisted: bool = False) -> str:
    """One line per server, with everything needed to recognise it."""
    owner = getattr(guild, "owner", None)
    owner_txt = f"owner {owner}" if owner else f"owner id {getattr(guild, 'owner_id', '?')}"
    members = getattr(guild, "member_count", None)
    members_txt = f"{members} members" if members is not None else "member count unknown"
    flag = "  [BLACKLISTED]" if blacklisted else ""
    return f"  {guild.name}  (id {guild.id}, {members_txt}, {owner_txt}){flag}"


def format_blacklist(entries: dict[int, dict]) -> str:
    if not entries:
        return "The blacklist is empty."
    lines = [f"{len(entries)} blacklisted server(s):"]
    for gid, e in sorted(entries.items()):
        lines.append(f"  {e.get('name') or '(name unknown)'}  "
                     f"(id {gid}, added {e.get('added', '?')})")
    return "\n".join(lines)


def find_guild(guilds, guild_id: int):
    """The guild with that id, or None. Plain lookup over the cached list —
    `Client.get_guild` would do, but passing the list in keeps this testable
    without a client."""
    for g in guilds:
        if g.id == guild_id:
            return g
    return None


# --- connecting --------------------------------------------------------------

async def run(token: str, action: str, guild_id: int | None) -> int:
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
            blacklist = load_blacklist()
            guilds = sorted(client.guilds, key=lambda g: g.name.lower())
            print(f"Signed in as {client.user} — in {len(guilds)} server(s):")
            for g in guilds:
                print(format_guild(g, g.id in blacklist))

            if action == "list":
                print("\nNo guild id given, so nothing was changed.")
                print("Re-run with one of the ids above to leave that server.")
                result["code"] = 0
                return

            target = find_guild(guilds, guild_id)
            if action == "blacklist" and target is not None:
                # Refresh the entry's name now that it's known; main() has
                # already written the id, so the block is in force either way.
                add_to_blacklist(guild_id, target.name)

            if target is None:
                # The listing above is the useful part of this failure, so it
                # is printed before this check rather than after it.
                print(f"\nNot in any server with id {guild_id} — nothing to leave.")
                if action == "blacklist":
                    print("It is blacklisted, so the bot will leave it if it is ever added.")
                    result["code"] = 0
                else:
                    print("Either it already left, or that id belongs to somewhere else.")
                    result["code"] = 1
                return

            print(f"\nLeaving {target.name} (id {target.id})...")
            await target.leave()
            if action == "blacklist":
                print("Left, and blacklisted: if anyone adds the bot back, it "
                      "leaves again straight away.")
            else:
                print("Left. Anyone with an invite link can add it back — use "
                      "--blacklist to keep it out.")
            result["code"] = 0
        except discord.HTTPException as e:
            print(f"\nDiscord refused: {e}", file=sys.stderr)
            result["code"] = 1
        except Exception as e:
            print(f"\nFailed: {type(e).__name__}: {e}", file=sys.stderr)
            result["code"] = 1
        finally:
            # Always close, including on the failure paths — otherwise the
            # process hangs on an open gateway connection and never exits.
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
        # A clean line beats a traceback in the console, but keep the type so
        # an unexpected failure is still diagnosable.
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
        action, guild_id = parse_args(argv)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    # The file-only actions need no login, and run before the token check so
    # they work wherever the file is.
    try:
        if action == "show":
            print(format_blacklist(load_blacklist()))
            return 0
        if action == "unblacklist":
            if remove_from_blacklist(guild_id):
                print(f"Removed {guild_id} from the blacklist. The bot can be "
                      "added there again (it does not rejoin by itself).")
            else:
                print(f"{guild_id} was not blacklisted — nothing changed.")
            return 0
        if action == "blacklist":
            # Written before connecting, so the block holds even if the login
            # below fails or the bot isn't in that server right now.
            new = add_to_blacklist(guild_id)
            print(f"{guild_id} {'added to' if new else 'already on'} the blacklist.")
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("DISCORD_TOKEN is not set.", file=sys.stderr)
        print("It lives on the panel's environment tab, not in a file on disk "
              "(this host has no .env — see CLAUDE.md).", file=sys.stderr)
        return 1

    return asyncio.run(run(token, action, guild_id))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
