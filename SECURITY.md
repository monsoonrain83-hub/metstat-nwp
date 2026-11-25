# Security policy

## Reporting
Report security vulnerabilities privately using GitHub's **Security → Report a vulnerability** if private vulnerability reporting is enabled. If unavailable, request a private maintainer contact through a public issue without including details, credentials, exploit payloads or sensitive data. Do not publish secrets, private datasets or production access details in issues, logs, or pull requests. No response-time guarantee is made.

## Supported scope
The current maintained default branch is the development reference; installed production versions can differ. Older archives are not assumed supported. Report affected commit/version and safe reproduction steps using synthetic data.

## Operational safeguards
- Use least privilege, read-only default workflow tokens and separate deployment credentials for each component. Never run untrusted PR code with production secrets.
- Keep station databases and keys outside the document root, expose only narrowly scoped, validated query APIs; use rate limits and monitoring. Public map outputs remain subject to provider terms.
- Never disable TLS certificate validation. Rotate exposed secrets immediately; deleting a file does not erase Git history, forks, caches or clones.
- Verify dependencies, actions and artifacts before release; use checksums, restricted release environments, explicit deployment approval and rollback. These controls are policy targets, not a claim that repository settings already enforce them.
