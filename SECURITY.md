# Security Policy

Ontology Workbench is a self-hosted web application with authentication, so its
security matters even behind your own firewall. / Ontology Workbench 是带认证的自托管
Web 应用,即使在内网运行,安全同样重要。

## Supported versions / 支持版本

| Version | Supported |
| ------- | --------- |
| latest `v0.1.x` tag | ✅ |

## Reporting a vulnerability / 报告漏洞

**Please do not open a public issue for security problems.**
请勿用公开 issue 报告安全问题。

Use GitHub's **private vulnerability reporting**: *Security* tab →
**Report a vulnerability**. That reaches the maintainers privately and lets us
coordinate a fix and disclosure. If you cannot use it, open a regular issue
asking for a security contact and we will follow up.

Please include: affected version/tag, deployment mode (Docker / pip / source),
steps or proof of concept, and impact. We aim to acknowledge within 72 hours
and will credit reporters in the advisory unless you prefer to stay anonymous.

## Scope notes / 范围说明

Reports about the application itself (auth, upload handling, RDF parsing,
export paths, XSS in rendered ontology data) are in scope. Issues in a
deployer's own environment (exposed ports, missing TLS, shared `data/`
directories) are deployment matters — still happy to advise, but they are not
project vulnerabilities.

The server generates and persists its JWT secret under the data directory on
first start; if you report auth-related behavior, mention whether `OW_DATA_DIR`
was reused across installs.
