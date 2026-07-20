# Changelog

## v0.5.1

- Route all skill REST operations through a credential-safe bundled client.
- Prevent agents from reading configs or placing credentials in commands and logs.
- Reject remote plaintext HTTP, unknown API routes, and inline installer tokens.

## v0.5.0

- Replace instance-wide Basic Auth with user-bound Bearer API keys.
- Add users, principals, scoped credentials, and identity audit records.
- Isolate every user's memory in an owner-bound SQLite database.
- Replace the REST surface with the incompatible `/v2` API.

## v0.4.2

- Add pam version check
