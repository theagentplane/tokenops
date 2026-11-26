# 0010. Claude Code autopilot: opt-in, acts through hooks, keeps a saver only if it measures a saving

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-26 |
| Deciders | Tisha Chawla, Susheem Koul |

## Context

`/tokenops:doctor` (ADR 0009) shows where a Claude Code user's usage goes, but only reports. On our
own sessions the largest avoidable cost was the message sent after a break, once the prompt cache
had expired: it writes the whole conversation to the cache again, at up to 2x the input price.
Users also install token savers (RTK, caveman) without knowing whether they help their work; a
10-task pilot on SWE-bench found that stacking them cost more than any one alone.

## Options considered

### Option A: an opt-in autopilot made of three hook-based parts

1. **Resume guard** (`UserPromptSubmit`): hold the first message to a session whose cache has
   expired, once, with its cost and cheaper ways on; sending it again goes through.
2. **Smart RTK** (`PreToolUse` on Bash): ask the installed `rtk` how it would rewrite a command
   and apply it, except where full output matters (tests after a failure, files about to be edited).
3. **Saver A/B** (`SessionStart`): turn RTK and caveman on in a random half of sessions, compare
   usage per prompt between the halves, and keep a saver only when it is measurably cheaper.

- Good: each part is small and testable; nothing acts until the user runs `/tokenops:autopilot on`;
  RTK and caveman stay separate installs that TokenOps calls (RTK's engine is BSL 1.1, so it is
  never bundled).
- Bad: hooks cannot see task quality, so the A/B judges usage only, and says so.

### Option B: a proxy in front of the Anthropic API

- Good: could rewrite whole prompts and keep the cache aligned.
- Bad: users must reroute their traffic and trust a local proxy with every request; much more
  code and risk for a first version.

### Option C: report only (keep the doctor as it is)

- Good: nothing can go wrong in a session.
- Bad: advice alone is read once and forgotten; it fixes nothing.

## Decision

We will build Option A, in three pull requests (guard; smart RTK; saver A/B), off by default and
fail-open: a hook that errors does nothing.

## Consequences

- **Good:** the largest leak we measured is handled without new installs; saver advice becomes
  a measured result on the user's own sessions.
- **Bad or risky:** a held message must be sent again, a small friction we accept once per break;
  the A/B needs about ten sessions per arm before it decides; RTK and caveman changes can break
  their adapters.
- **Follow-ups:** a quality signal for the A/B (for example tests passing in the session).

## Impact on other repositories

None.

## Links

ADR 0009 · [Claude Code hooks](https://code.claude.com/docs/en/hooks)
