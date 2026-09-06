# Local DNS/TLS and kernel egress rehearsal

Status: **pass**. 12 cases, 1.370 seconds inside the isolated container.

The actual shared HTTPS client resolved DNS over loopback UDP and connected to a real local TLS server. The tests covered hostname validation, manual redirects, mixed DNS answers, rebinding, private IP rejection, body/header limits and total deadline cancellation. The container had only loopback, no capabilities, a read-only root, a non-root user, bounded heap/memory, and no route for a TEST-NET egress attempt.

Only the test constructor permits exactly 127.0.0.1 for a positive local TLS fixture. The production address policy was separately exercised and rejected that DNS result before HTTP. No runtime flag disables this policy.

Production acceptance remains false. Live Telegram/CDN responses and the approved production egress proxy/firewall deployment remain external gates. The rehearsal does not change production network configuration.
