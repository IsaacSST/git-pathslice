# git slice

Path-scoped branches derived from another branch.

A *slice* names a set of paths (say `docs/`) and a base branch (say `main`).
`git slice update docs` rebuilds the branch `slice/docs/<from>` as `main` plus
the commits on `<from>` that touch `docs/`, each restricted to those paths,
skipping whatever `main` already contains. The result can be pull-requested
into `main` on its own while the rest of `<from>` carries on.

Git has no per-path branches: a ref names a commit and a commit names a whole
tree. `git slice` does not change that. It is a path-filtered rebase with a
memory, built from `format-patch`, `am -3`, `patch-id` and a temporary
worktree.

## Install

Needs git 2.22 or newer and Python 3.

```bash
ln -s "$PWD/git-slice" ~/.local/bin/git-slice   # any directory on PATH
git slice -h        # `git slice --help` looks for a man page, as git does for any subcommand
```

## Quick start

```bash
# in the repository, once
git slice add docs docs/ --base main          # local definition (.git/config)
git slice add docs docs/ --base main --shared # or committed, in .gitslices

# on a feature branch that has accumulated docs changes
git slice log docs        # what an update would do, commit by commit
git slice update docs     # build slice/docs/<branch> from main
git slice update docs --push
git slice pr docs         # update, push, open or refresh a PR with gh
```

Your own checkout is never touched. The work happens in a temporary worktree
under `.git/slice/wt/`, which is removed when the update finishes.

## What an update does

1. Collects the commits on `<from>` that are not on `<base>` and touch the
   slice's paths. Merge commits are ignored.
2. Drops the ones `<base>` already has (see *Landing* below) and the ones the
   slice's selection rule excludes.
3. Rebuilds `slice/<name>/<from>` from `<base>` by replaying the rest with
   `git am -3`, each patch restricted to the slice's paths. A commit that also
   touched other files comes through with only its in-slice hunks. Messages
   and authorship are kept; a `Sliced-From: <sha>` trailer is added.
4. Records the source tip under `refs/slices/<name>/<from>/source`.

The derived branch is disposable. Do not commit on it; edit on `<from>` and run
`update` again.

Rebuilds are deterministic. The replayed commits take their committer identity
and date from the source commits, so a rebuild is a pure function of (base,
source, paths): running `update` twice with nothing changed produces the same
commit ids, and CI and a person produce the same ids as each other. `--push`
then has nothing to push and says so.

If base moves but the slice's own commits do not, the branch is left exactly
where it is rather than rebased, so an open pull request is not force-pushed
and its review comments do not go stale. `--force-rebuild` rebases it onto the
current base. If the branch has meanwhile stopped applying cleanly to base,
`update` says so and you can rebuild when it suits you.

## Landing

The difficulty in this workflow is the second update: after the slice branch
has been merged into base, dev's original commits are still not ancestors of
base, and replaying them again conflicts wherever a later commit touched the
same lines. `git slice` avoids that in four ways, checked in this order:

- **Recorded landed point.** `refs/slices/<name>/<from>/landed` marks the
  source commit up to which everything is known to be in base. Only commits
  after it are considered. It advances automatically when:
  - the previous slice branch is now an ancestor of base (merge commit or
    fast-forward), or
  - some commit on base since the last update has exactly the slice branch's
    content for the slice's paths (a squash merge).
- **Trailers.** A commit on base carrying `Sliced-From: <sha>` marks `<sha>`
  as landed. This survives rebase-merges and cherry-picks.
- **Patch ids.** A candidate whose path-restricted patch id matches one on
  base is landed, even if the message was rewritten.
- **`git slice landed <name> <rev>`** declares it by hand.

What this does not cover: a squash merge followed by further edits to the same
lines on base *before* the next update, when the tool has no record of the
previous slice branch (state was forgotten, or the branch was built elsewhere).
Then the usual rule applies: merge base back into `<from>`, or use `landed`.

Merging base back into `<from>` after a PR lands remains good practice; the
tool handles the state either way.

## Selection rules

Set with `--select` when adding a slice:

| rule     | replays                                                                     |
|----------|-----------------------------------------------------------------------------|
| `all`    | every commit touching the paths, restricted to them (default)               |
| `pure`   | only commits that touch nothing outside the paths                           |
| `marked` | only commits with a `Slice: <name>` trailer or a subject matching `--subject` |

`marked` is the answer to "docs for unreleased features must not land early":
mark a commit with `git commit --trailer 'Slice: docs'` when it may land on its
own. `--all` on `update` or `log` ignores the rule for one run.

## Conflicts

If a patch does not apply, the update stops and leaves the temporary worktree
in place:

```
conflict while replaying 3f2a1c9e0b docs: reword intro
  resolve it in:  /path/to/repo/.git/slice/wt/docs/dev
  then run:       git slice continue docs --from dev
  or:             git slice skip docs --from dev   /   git slice abort docs --from dev
```

Edit the files there, `git add` them, then `git slice continue`. `skip` drops
that one commit; `abort` removes the worktree and leaves the old branch as it
was.

## Commands

```
git slice add <name> <path>... [--base B] [--select all|pure|marked] [--subject RE] [--shared]
git slice rm <name> [--shared]
git slice list
git slice log <name> [--from B] [--onto B] [--all]        dry run, commit by commit
git slice status [<name>] [--from B]                        one summary per slice
git slice update <name> [--from B] [--onto B] [--all] [--branch NAME] [--push [REMOTE]]
                        [--force-rebuild] [-q]
git slice continue|skip|abort <name> [--from B]
git slice forget <name> [--from B] [--branch]               drop the sync refs (and branch)
git slice landed <name> <rev> [--from B]
git slice pr <name> [--remote R] [--title T] [--draft] [--no-update] [--force-rebuild]
```

`--from` defaults to the current branch. `--base` defaults to `origin/HEAD`,
then `main`, then `master`; use `origin/main` and fetch first if you want the
slice built on the remote's tip.

## Shared definitions

`--shared` writes to `.gitslices` at the repository root, in git config
syntax, so the definition travels with the repository:

```
[slice "docs"]
	path = docs/
	path = README.md
	base = main
	select = marked
	subject = ^docs(\\(.*\\))?:
```

Local definitions in `.git/config` use the same keys under `slice.<name>.*`
and add to the shared ones.

## GitHub

GitHub needs no support for any of this and is never told that a slice exists.
A slice branch is an ordinary branch and a slice pull request is an ordinary
pull request; the projection happens locally, in git. What follows is about the
places where the two-pull-request shape rubs against GitHub's defaults.

**Merge method.** All three work, by different routes:

| method       | how the next update knows it landed                                  |
|--------------|----------------------------------------------------------------------|
| merge commit | the branch becomes an ancestor of base; trailers land too             |
| rebase merge | commit bodies survive, so the `Sliced-From` trailers do               |
| squash merge | base ends up with the branch's content for the slice's paths          |

Squash is the weakest case, since GitHub may drop the commit bodies and with
them the trailers. It is covered by the content match and by the recorded
landed ref, both tested. To keep trailers under squash as well, set the
repository's squash commit message to *pull request title and commit details*.

**Required checks.** Give the slice's paths their own workflow so a docs pull
request does not wait on the code test matrix. The trap is that a required
check which is skipped by a `paths` filter never reports at all, and the pull
request stays blocked for ever. The usual answer is a companion job of the same
name on the inverse filter that does nothing and succeeds.

**Automation and the token.** A push made with the default `GITHUB_TOKEN` does
not trigger further workflows, so a slice branch pushed that way arrives with
no checks and the pull request cannot go green. Push with a PAT or a GitHub App
token instead:

```yaml
name: docs slice
on:
  push:
    branches: [dev]
permissions:
  contents: write
  pull-requests: write
jobs:
  slice:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0, token: "${{ secrets.SLICE_TOKEN }}"}
      - run: |
          git config user.name  'docs-slice[bot]'
          git config user.email 'docs-slice@users.noreply.github.com'
          git slice pr docs --from dev --onto origin/main --draft
        env:
          GH_TOKEN: ${{ secrets.SLICE_TOKEN }}
```

`--onto origin/main` is worth being explicit about in CI, where
`refs/remotes/origin/HEAD` is often unset. `git slice pr` refreshes an existing
open pull request rather than opening a second one, so this is safe to run on
every push.

**CODEOWNERS** works in your favour here: a docs-only pull request requests
only the docs reviewers.

**Merge queues** do not mix with a branch that can be rewritten. Because
`update` leaves an unchanged slice alone, this only bites when the slice's own
commits change while it is queued; avoid running `--force-rebuild` on a queued
branch.

**Forks.** The slice branch has to live somewhere you can push to, so a
contributor working from a fork uses `--push fork` and opens the pull request
from there.

What GitHub has no answer for, and nothing here changes: there is no way to
merge part of a pull request. The two-pull-request shape is the workaround, not
a limitation of the tool.

## Keeping the branch current automatically

A `post-commit` hook keeps a docs PR waiting for review at all times:

```sh
#!/bin/sh
branch=$(git symbolic-ref --short -q HEAD) || exit 0
[ "$branch" = main ] && exit 0
git slice update docs -q --push 2>/dev/null || true
```

Or run the same from CI on push. The update takes well under a second on a
small repository; the temporary worktree checks out only the slice's paths.

## Limitations

- Merge commits on `<from>` are not replayed. A conflict resolution that lives
  only in a merge commit is lost; it will show up as a conflict on update.
- The derived branch is rebuilt each time, so its commit ids change. Review
  comments on GitHub survive a force-push, but per-commit links do not.
- Paths are pathspecs relative to the repository root. Renames across the
  slice boundary appear as an add or a delete.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The suite builds throwaway repositories and covers mixed commits, deletions,
binary files, merge, squash and rebase-merge landings, merging base back into
the source branch, source-branch rebases, conflicts with continue, skip and
abort, deterministic and committer-independent rebuilds, leaving an unchanged
branch alone while base moves, the selection rules, shared definitions, and
pushing.
