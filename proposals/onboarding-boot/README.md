# Next sprint: onboarding-boot
// Turn a working project identity into a verified, recoverable shared workspace.

Status: proposal captured after the v0.1 baseline. No onboarding automation is activated by this document.

## Product goal
// Let a human start with an Apple device, working iCloud access and a dedicated project mailbox.

The dedicated mailbox is the root of the bot-facing identity domain. Project accounts, credentials, vault replicas and delegated resources belong inside that domain; everyday human accounts remain outside. Apple/iCloud carries selected project records without delegating the human's Apple identity.

Success means a guided, resumable ceremony produces a usable synced vault, verified required service access, a recovery path and a readiness receipt before project work starts.

## A — Minimal human input
// Keep the entry experience small without making every task a root administrator.

User supplies the dedicated project email and bootstrapping access through an approved credential surface. An Apple Passwords project group is the credential catalog; literal sharing is optional. If a group requires another participant, use prefixed personal entries until sharing is desired.

Record names/references, owners, permissions, consumers and revocation locations. The root mailbox password is a bootstrap capability, not a default input to every runtime. Provider-issued credentials are independent secrets, not derivatives of that password.

Legal name and payment details are supplied only when a provider's human-controlled billing step requires them. Do not put them into the synced vault, source control, environment template, task logs or general runtime variables. Do not assume a Passwords shared group can act as a shared payment-card store. Select an appropriate payment-entry workflow during implementation.

## B — Guided boot skill
// Coordinate service setup with explicit human checkpoints and durable progress.

Suggested sequence:

1. Confirm dedicated-mailbox access and independent recovery; record actual login-provider dependencies.
2. Establish GitHub and ChatGPT/OpenAI project identities and required subscriptions.
3. Create a private vault from the reusable template; configure Obsidian Sync and E2EE; preserve the separate vault password outside the vault.
4. Verify an ordinary device-to-device note round trip before adding cloud complexity.
5. Configure Tailscale enrollment and grants, and optionally a Runpod development host with persistent storage and human-authorized billing.
6. Guide Rootshell profile, known-host and per-key iCloud setup on Apple devices. Use a named host-side tmux session for floating terminals.
7. Prepare Codex Cloud tooling separately from task-specific vault enrollment. Provision selected personal inputs; use unique replica identities and one Sync writer per replica.
8. Test replacement enrollment and an independent backup restore; produce the readiness receipt.

Browser-only registration, MFA, email verification, consent and payment approval pause for the human. Resume from completed checkpoints instead of duplicating accounts, vaults, pods or charges. Apple Passwords does not automatically provision Linux credentials; define explicit human-mediated delivery to Codex Personal vault.

The existing parameterized recovery script lives in the companion dotbox-hello repository. Reuse or deliberately migrate that interface; do not invent a second incompatible bootstrap.

## C — Optional inference credentials
// Verify selected providers before building a feature that depends on them.

Optional adapters: Anthropic, OpenAI, Google Gemini and xAI/Grok. Missing optional providers do not block core vault readiness.

For each configured provider:

- Validate the configured endpoint and supported credential mechanism.
- Use a documented minimal identity or capability request when available.
- Distinguish valid identity, required permissions, model availability, quota and a successful inference request.
- Ask explicitly before a paid inference check; never imply all verification is free.
- Record provider, capability, non-secret credential reference, check time and outcome.
- Keep secrets and raw provider responses out of receipts; recheck access when needed rather than treating initial success as permanent.

API capability is separate from a consumer-chat subscription.

## Credential and execution contract
// Delegate only the capabilities required for the stage being executed.

Use direct variables for values the program must read, including local E2EE derivation. Use destination-bound HTTPS network secrets only with compatible clients. Tailscale enrollment belongs in supported VPN configuration; inventory API access is a separate capability.

Ordinary inputs include owner email, vault ID/path and per-replica identity. Secret inputs may include an Obsidian session token, separate vault encryption password and stage-specific API credentials. Do not default to injecting human Apple/mail recovery credentials.

Host, SSH, browser and filesystem permissions must preserve the separation from everyday accounts; dedicated email naming alone cannot do that.

## Acceptance criteria
// Demonstrate the ceremony works and fails safely before calling it turnkey.

- A new human can follow the guide from the stated prerequisites; paid prerequisites and human steps are clear.
- A partial run resumes without duplicate service resources or unapproved charges.
- Required credentials are usable before dependent steps; absent optional providers are reported separately.
- Logs, receipts, examples and published setup files contain no secret values, payment details or legal identity data.
- Two fresh cloud tasks get independent identities; resumes retain their existing identities.
- An existing Sync writer is preserved; wrong-vault bindings and missing decryption credentials stop clearly.
- Floating-session tests distinguish reconnecting to one host from recovering after host loss.
- A readiness receipt reports actual evidence, skipped checks and remaining human actions without guessing review or verification status.
- Tests cover fake-provider success/failure, revocation, network errors, missing inputs, interrupted human steps and retry idempotency without paid live calls.

## Implementation order
// Start with an honest guide and state machine before automating account creation.

1. Define a generic input catalog and redacted progress/receipt format.
2. Implement guided stage orchestration with stop/resume behavior and fake-service tests.
3. Integrate the existing vault bootstrap and supported credential delivery.
4. Add provider-specific verification adapters, starting with one optional inference provider.
5. Perform one human-assisted end-to-end onboarding and one replacement recovery.
6. Only then consider broader registration or billing automation.

Open implementation choices: supported Apple credential-entry surface; payment-entry workflow; provider registration restrictions; recovery ownership; exact verification endpoints and costs. Resolve against current vendor documentation before writing adapters.

## Scope boundary
// Capture the next sprint without altering the released baseline.

This branch is documentation-only. No accounts, cards, credentials, pods, schedulers or inference calls are provisioned. The v0.1 tags remain unchanged.
