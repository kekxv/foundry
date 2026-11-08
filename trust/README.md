# Production trust configuration

No production key has been generated or committed. Before the first release:

1. Generate an Ed25519 seed offline using `foundry-release keygen`.
2. Keep the private seed outside this repository. Configure only its hex value as the `FOUNDRY_SIGNING_KEY` secret in the protected `release-signing` GitHub Environment.
3. Put the generated **public** root at `trust/root.json`, review it independently, and commit it. Set the environment variable `FOUNDRY_KEY_ID` to the root's key ID.
4. Require reviewers and default-branch-only deployments for `release-signing`. Protect main, workflows, signer source, Cargo configuration/lockfile and this trust directory. Configure required reviews via repository rules/CODEOWNERS with your real maintainer identities.
5. Distribute the root fingerprint through a trusted channel. Receiving a root and binary together over an untrusted channel does not authenticate either.

Do not use the hard-coded keys from tests for production. See `docs/security.md` and `docs/publishing.md` for rotation and recovery.
