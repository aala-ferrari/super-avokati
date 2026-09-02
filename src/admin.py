"""Admin CLI for user management — no web-based signup exists by design.

Usage:
    ./venv/bin/python -m src.admin adduser <username> [--admin]
    ./venv/bin/python -m src.admin listusers
    ./venv/bin/python -m src.admin deluser <username>
    ./venv/bin/python -m src.admin passwd <username>

Password is read from stdin (silent). The first user created is
automatically marked admin so the owner always has a way in.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from . import storage
from .auth import hash_password
from .logging_utils import get_logger

log = get_logger(__name__)


def _read_password(prompt: str = "Password: ") -> str:
    pw = getpass.getpass(prompt)
    pw2 = getpass.getpass("Confirm: ")
    if pw != pw2:
        print("Passwords do not match.", file=sys.stderr)
        sys.exit(2)
    if len(pw) < 6:
        print("Password must be at least 6 characters.", file=sys.stderr)
        sys.exit(2)
    return pw


def cmd_adduser(username: str, admin_flag: bool) -> None:
    storage.init_db()
    if storage.get_user_by_username(username):
        print(f"User {username!r} already exists.", file=sys.stderr)
        sys.exit(1)
    is_first = storage.count_users() == 0
    pw = _read_password()
    user = storage.create_user(
        username=username,
        password_hash=hash_password(pw),
        is_admin=admin_flag or is_first,
    )
    badge = " (admin)" if user.is_admin else ""
    print(f"✅ Created user {user.username!r}{badge} (id={user.id}).")


def cmd_listusers() -> None:
    storage.init_db()
    users = storage.list_users()
    if not users:
        print("(no users yet)")
        return
    print(f"{'id':>3}  {'username':<20}  admin  created")
    print("-" * 60)
    for u in users:
        print(f"{u.id:>3}  {u.username:<20}  {'yes' if u.is_admin else ' no':<5}  {u.created_at}")


def cmd_deluser(username: str) -> None:
    storage.init_db()
    if not storage.get_user_by_username(username):
        print(f"No such user: {username!r}", file=sys.stderr)
        sys.exit(1)
    confirm = input(f"Really delete user {username!r} and all their cases? [y/N] ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return
    ok, motivo = storage.delete_user(username)
    if not ok:
        # prima stampava «Deleted» qualunque cosa fosse successa
        print(f"❌ {motivo or 'errore eliminazione'}", file=sys.stderr)
        sys.exit(1)
    print(f"🗑  Deleted user {username!r}.")


def cmd_passwd(username: str) -> None:
    storage.init_db()
    if not storage.get_user_by_username(username):
        print(f"No such user: {username!r}", file=sys.stderr)
        sys.exit(1)
    pw = _read_password(f"New password for {username}: ")
    storage.set_password_hash(username, hash_password(pw))
    print(f"🔑 Password updated for {username!r}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Super Avvocato admin CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("adduser", help="create a new user")
    p_add.add_argument("username")
    p_add.add_argument("--admin", action="store_true", help="grant admin privileges")

    sub.add_parser("listusers", help="list all users")

    p_del = sub.add_parser("deluser", help="delete a user and all their cases")
    p_del.add_argument("username")

    p_pw = sub.add_parser("passwd", help="change a user's password")
    p_pw.add_argument("username")

    args = parser.parse_args()
    if args.cmd == "adduser":
        cmd_adduser(args.username, args.admin)
    elif args.cmd == "listusers":
        cmd_listusers()
    elif args.cmd == "deluser":
        cmd_deluser(args.username)
    elif args.cmd == "passwd":
        cmd_passwd(args.username)


if __name__ == "__main__":
    main()
