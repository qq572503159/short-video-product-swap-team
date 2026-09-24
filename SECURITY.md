# Security Policy

## Credentials and private media

Never commit API keys, OAuth tokens, cookies, signed media URLs, private videos, product photos, generated media, raw provider responses, or local runtime configuration. Use process environment variables or a user-local secrets file. Redact task URLs before sharing because signed download URLs may grant temporary access.

If a credential is exposed, revoke and rotate it with its provider immediately. Removing the file in a later commit does not remove it from Git history.

## Reporting

For a suspected vulnerability in this private project, contact the repository owner through GitHub privately. Do not open a public issue containing credentials or personal media.
