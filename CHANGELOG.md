# Changelog

## v0.5.2
- Route all skill REST operations through a credential-safe bundled client.
- Prevent agents from reading configs or placing credentials in commands and logs.
- Reject remote plaintext HTTP, unknown API routes, and inline installer tokens.
- Remove strict HTTP security settings
