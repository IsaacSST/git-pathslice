# git pathslice

Derive branches containing selected paths from a source branch. Each selected
source commit becomes a separate commit on the destination branch, retaining
its message, author and author date. Mixed commits contribute only the selected
paths. The source checkout and branch remain unchanged.

The implementation uses Git for patch generation, equivalence checks and
three-way application. Python manages slice definitions, export records and
the temporary worktree. GitHub operations use `gh`.

## Installation

Requires Git 2.22 or later and Python 3. PR commands also require GitHub CLI.
From this directory:

```sh
ln -s "$PWD/git-pathslice" ~/.local/bin/git-pathslice
git pathslice -h
```

Git's `--help` option looks for a manual page; use `-h` for the command help.

## Repository setup

Define a slice once and commit its configuration:

```sh
git pathslice add specs specs/ --base origin/main --shared
git add .gitpathslices
git commit -m "Define the specifications slice"
```

The shared file uses Git configuration syntax:

```ini
[pathslice "specs"]
    path = specs/
    base = origin/main
```

Multiple `path` entries are permitted. Local definitions in `.git/config` can
add paths or override other settings. Paths are Git pathspecs relative to the
repository root; `add` also accepts paths relative to the current directory.

## Daily use

On the implementation branch:

```sh
git pathslice log specs       # inspect the proposed selection
git pathslice update specs    # build locally
git pathslice pr specs        # fetch, build, push and create or update the PR
```

The default derived branch is `pathslice/specs/<source-branch>`. Make subsequent
edits on the source branch and run the same command again. Derived branches
are generated outputs; do not edit them directly.

`update` uses the currently available refs. `pr` fetches its remote first.
Use `--from BRANCH` to select another source and `--onto REF` to override the
destination. No update is performed on the source checkout.

Unchanged exports retain their commit IDs. Movement on the destination alone
does not rebuild an open PR; `--force-rebuild` requests that rebase. The tool
reports conflicts with the current destination when Git supports this check.
Each replay uses the source committer's identity and date, so rebuilding with
the same inputs also gives the same commit IDs.

## Selection

`add --select RULE` sets one of these rules:

| Rule | Commits exported |
| --- | --- |
| `all` | Every commit touching the paths, restricted to those paths. |
| `pure` | Commits touching only the selected paths. |
| `marked` | Commits with `Slice: NAME`, or a subject matching `--subject REGEX`. |

`--all` on an update overrides the rule. Excluded or manually skipped commits
remain eligible for a later export, including after an earlier export lands.

## Landing and checkpoints

Export commits include `Sliced-From: SHA` for readability and a `Pathslice:`
trailer identifying the source revision and the scope of the export. The
scope includes the slice name, paths and destination ref. A trailer for one
scope cannot mark another scope's changes as landed.

Local export records under `refs/pathslices/` retain the exported revisions
and the revisions known to have landed. They are updated atomically with the
derived branch. Normal merges are recognised through ancestry. Squash merges
can be recognised when a later destination revision matches the exported
content in the selected paths. In either case, only the recorded exported
commits are marked as landed. Git's path-restricted patch equivalence also
recognises independently applied commits without matching trailers.

The old unscoped `source` and `landed` refs are not imported: they may describe
skipped changes incorrectly. Unscoped `Sliced-From:` trailers remain readable
but do not independently establish that a change landed.

When starting from existing history or recovering a squash merge without its
local export record, an explicit checkpoint may be needed:

```sh
git pathslice landed specs SOURCE_REVISION
```

This declares that all changes through that source revision are already
accounted for, within the current scope. Verify the revision first. Declarations
accumulate, so imports from separate side branches can have separate checkpoints.
Use `forget` before replacing a mistaken declaration. A checkpoint excludes
its ancestors; older commits on branches merged later may still need review.
Expanding the paths or changing the destination starts a separate scope and
does not inherit these declarations.

## Conflicts and publication

On conflict, the command reports a temporary worktree under `.git/pathslice/`.
Resolve and stage the files there, then run from the source checkout:

```sh
git pathslice continue specs
# Alternatively:
git pathslice skip specs
git pathslice abort specs
```

`continue` retains the source author and committer metadata. `abort` removes
the temporary worktree and leaves the previous derived branch intact.

Pushes use an explicit lease against the last successfully published revision.
A newer remote export is refused even if a background fetch has updated the
remote-tracking ref. A first publication from another checkout can use its
remote-tracking ref after checking that the remote export belongs to the same
scope and source history. A failed push leaves the local export available for
retry; it does not require replaying the commits again.

## Other commands

`list`, `status`, `rm` and `forget` inspect or remove configuration and local
export records. `forget` leaves publication leases intact. `update --push`
publishes without creating a PR. `pr --no-update` publishes an existing derived
branch. Use `git pathslice COMMAND -h` for the remaining options.

## Limits and tests

Merge commits on the source branch are not replayed. Changes made only in a
merge resolution can therefore be absent without a conflict being reported.
Review the final PR against the intended changes, especially when importing
an existing branch. Renames crossing a slice boundary appear as additions or
deletions.

Without a local record or scoped trailers, squash merges that combine several
changes may require an explicit checkpoint. Private export records and
publication leases do not travel with an ordinary clone.

Run the scenario tests with:

```sh
python3 -m unittest discover -s tests -v
```

The tests use temporary repositories and local remotes. They cover repeated
exports, supported landing methods, selection changes, conflict recovery and
publication races, as well as preservation of messages and authorship.
