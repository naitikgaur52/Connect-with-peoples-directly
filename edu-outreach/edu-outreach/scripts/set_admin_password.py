"""
Generates a password hash to put in your .env file as ADMIN_PASSWORD_HASH.

Usage:
    python scripts/set_admin_password.py
    (then paste the printed line into your .env file)

The plaintext password is never stored anywhere -- only the hash.
"""

import getpass
from werkzeug.security import generate_password_hash

if __name__ == "__main__":
    pw = getpass.getpass("New admin password: ")
    confirm = getpass.getpass("Confirm password: ")
    if pw != confirm:
        print("Passwords do not match. Try again.")
        raise SystemExit(1)
    print("\nAdd this line to your .env file:\n")
    print(f"ADMIN_PASSWORD_HASH={generate_password_hash(pw)}")
