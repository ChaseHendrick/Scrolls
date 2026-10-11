# Security policy

## Supported code

Security fixes target the latest `main` branch. Historical experiment branches
and archived snapshots do not have a separate security maintenance commitment.
Use the current code when reproducing an issue, and record the commit hash.

## Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/ChaseHendrick/Scrolls/security/advisories/new).
If that channel is unavailable, email [chase@hendrickresearch.com](mailto:chase@hendrickresearch.com)
with the subject `Scrolls security report`.

Include the affected commit and file, impact, prerequisites, and a minimal
reproducer using synthetic or already-public inputs. Redact credentials,
account identifiers, private paths and restricted research material.
Do not open a public issue or pull request with exploit details, secrets,
unpublished scroll candidates, or private experiment outputs.

The maintainer will assess the report and coordinate a fix and disclosure with
the reporter. This is a volunteer project with no guaranteed response time or
paid bug bounty. Test only systems and data you are authorized to access.

## Scope and safe use

Downloader path handling, untrusted inputs, credentials, and command execution
are examples of security concerns in this workbench. For a vulnerability in a
separate dependency, use that upstream project's reporting policy and privately
note the effect on Scrolls if relevant. Scientific disagreements and ordinary
bugs belong in the public issue templates when they can be explained without
restricted information.

Review scripts before running them. Model checkpoints and third-party tools can
execute code; load only trusted sources. Never commit tokens, private data,
model weights, maps, renders, meshes, masks or labels. See
[contributing](CONTRIBUTING.md) for the public research boundary.
