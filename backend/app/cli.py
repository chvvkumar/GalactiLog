import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.user import User
from app.services.auth import hash_password


async def create_user(username: str, role: str) -> None:
    password = getpass.getpass("Password (min 12 chars): ")
    if len(password) < 12:
        print("Error: Password must be at least 12 characters.")
        sys.exit(1)
    if len(password) > 128:
        print("Error: Password must be at most 128 characters.")
        sys.exit(1)
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Error: Passwords do not match.")
        sys.exit(1)

    async with async_session() as session:
        existing = await session.execute(
            select(User).where(User.username == username)
        )
        if existing.scalar_one_or_none():
            print(f"Error: User '{username}' already exists.")
            sys.exit(1)
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
        )
        session.add(user)
        await session.commit()
        print(f"User '{username}' created with role '{role}'.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli", description="GalactiLog CLI")
    sub = parser.add_subparsers(dest="command")
    create_cmd = sub.add_parser("create-user", help="Create a new user account")
    create_cmd.add_argument("--username", required=True)
    create_cmd.add_argument("--role", required=True, choices=["admin", "viewer"])
    args = parser.parse_args()
    if args.command == "create-user":
        asyncio.run(create_user(args.username, args.role))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
