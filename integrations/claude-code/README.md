# TokenOps for Claude Code

**Why am I hitting my limit?** One command shows where your Claude Code usage goes and what to
change, read from your own session logs on your machine.

```
/tokenops:doctor

Why am I hitting my limit?   (last 30 days, 79 sessions, $5,041 at API list prices)

Where your usage goes
   46%  Re-reading context every turn
   35%  Re-buying context after breaks
   10%  Claude's output
    8%  Caching new context

What to change
  1. Breaks cost you 35%: 672 times you came back to an expired cache ...
  2. Re-reading is 46%: use /clear when you switch to an unrelated task.
  3. Output is 10% of your usage, so caveman can save at most that ...
  4. 3% of the tool output came from shell commands RTK can compact ...
```

## Install

In Claude Code:

```
/plugin marketplace add theagentplane/tokenops
/plugin install tokenops@tokenops
```

Then run `/tokenops:doctor` (or `/tokenops:doctor 7` for the last 7 days). Needs Python 3.9+
on your PATH; nothing to `pip install`.

## How it reads your usage

Claude Code writes every model response to `~/.claude/projects/*/*.jsonl`, often on several
lines with the same message id. The doctor keeps the last line per response, includes subagent
transcripts, and prices each response at Anthropic's list rates: input, output, cache reads,
and cache writes (1.25x input for the 5-minute cache, 2x for the 1-hour cache). Prices come from
TokenOps' price book (`src/tokenops/framework/pricing.py`).

- **Re-buying context after breaks:** a cache write of 20,000+ tokens more than an hour after the
  previous response. The cache had expired, so the whole conversation was written again.
- **Re-reading context:** cache reads. Every turn reads the conversation again.
- **Caveman and RTK advice** is a ceiling from your own usage mix (what share is output, what
  share of tool output came from shell commands RTK compacts), not a measured A/B.

On a Claude plan the dollar figures are API-equivalent: they show your share of usage, not a
bill. Nothing leaves your machine.

## Development

```
python scripts/sync-claude-prices.py   # after changing DEFAULT_RATES
python -m pytest tests/claude_code
```
