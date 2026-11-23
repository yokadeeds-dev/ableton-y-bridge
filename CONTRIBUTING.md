# Contributing

Contributions are welcome. A few things first.

## Licence of your contribution

Ableton Y Bridge is **dual-licensed** (AGPL-3.0 and a commercial licence, see
[`LICENSING.md`](LICENSING.md)). So that the project owner can include contributions in
**both**, every contribution comes with this agreement:

> By submitting a pull request you agree that your contribution is published under
> **AGPL-3.0**, **and** you grant the project owner (Yoka) an irrevocable, worldwide,
> royalty-free right to also license your contribution under a **commercial licence**.

A contribution cannot be merged without this agreement. For larger contributions a
separately signed agreement may be needed.

## Workflow

- **Open an issue first** for bugs and ideas, so we can agree before you put in a lot of work.
- Branch from `main`, keep commits focused, describe the change in the pull request.
- Run the offline tests: `python -m unittest discover -s tests`.
- Changes that touch Live should be checked against a running Live with a throwaway Set
  (see "For developers" in the README).
- No secrets and no personal paths in commits; the repository is public.

---

*Not legal advice. The agreement above is a template; have it checked by a lawyer before
any money changes hands.*
