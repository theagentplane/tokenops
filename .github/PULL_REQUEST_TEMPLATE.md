## Summary

<!-- What changes and why? One thing per pull request. -->

## Related issue

<!-- e.g. Closes #123 -->

## Compatibility

- [ ] Compatible (additive only)
- [ ] Breaking (migration noted below and in CHANGELOG.md)

<!-- If the public API, a policy's behaviour or the control-plane contract changed: who is
     affected (SDK users, the control plane, Chronicle) and what must each do to migrate? -->

## Checklist

- [ ] Change is under about 400 lines, or the description links the split plan or says why it is one change
- [ ] Tests added or updated
- [ ] CHANGELOG entry added and classified as compatible or breaking
- [ ] `ruff check`, `ruff format --check`, `mypy` and `pytest` pass locally
- [ ] Fail-safe behaviour when the control plane is unreachable is unchanged, or documented and tested
- [ ] No retry can double count spend (ledger events are not deduplicated)
- [ ] Primitives models are imported, not copied
- [ ] Commits are signed off for the [DCO](https://developercertificate.org/) (`git commit -s`)
