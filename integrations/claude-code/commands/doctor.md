---
description: Why am I hitting my limit? Where your Claude Code usage goes and what to change
argument-hint: "[days]"
allowed-tools: Bash(tokenops:*)
---

!`tokenops doctor --days ${ARGUMENTS:-30}`

Show the TokenOps output above to the user exactly as printed, inside a code block. Do not recompute numbers or promise savings it does not show. Then say in one sentence which change to make first.
