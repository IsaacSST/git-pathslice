# git pathslice

Publish the changes a branch makes to selected paths as a separate pull request
(PR). The source branch and checkout remain unchanged.

Git computes each export with `git merge-tree`, without a worktree. Python
manages configuration and the export branch. The GitHub CLI (`gh`) manages
pull requests.

## Installation

Requires Git 2.40 or later and Python 3.12 or later. PR commands also require
the GitHub CLI, authenticated with `gh auth login`.

```sh
git clone https://github.com/IsaacSST/git-pathslice.git
cd git-pathslice
mkdir -p ~/.local/bin
ln -s "$PWD/git-pathslice" ~/.local/bin/git-pathslice
export PATH="$HOME/.local/bin:$PATH"
git pathslice -h
```

Keep `~/.local/bin` on your shell's `PATH`. Use `-h` for help; Git's `--help`
option expects a manual page.

## Configuration

A slice is a named selection of paths to export. Define a slice and commit its
shared configuration:

```sh
git pathslice add docs docs/ --base origin/main --upstream origin/dev --shared
git add .gitpathslices
git commit -m "Define the documentation slice"
```

| Setting | Meaning |
| --- | --- |
| `path` | Paths to export, in Git pathspec syntax, relative to the repository root. `add` also accepts paths relative to the current directory. |
| `base` | The branch PRs target. |
| `upstream` | The branch the source is developed against, if it is not the base. Its changes are not exported. |

`.gitpathslices` uses Git configuration syntax and permits multiple `path`
entries. It is read from the source branch's latest commit, or from the
working tree if that commit lacks it. Local definitions in `.git/config` can
add paths or override other settings.

## Use

Publish the documentation slice from the current branch:

```sh
git pathslice publish docs
```

`publish` fetches the remote, adds the source's latest changes to the export
branch, pushes it, then creates a PR or reuses an open one. `pr` is an alias
for `publish`. Only committed changes are exported.

The export branch is named `pathslice/<slice>/<source>` unless `--branch NAME`
chooses another. The chosen name is recorded in `branch.<name>.pathsliceSlice`
and `branch.<name>.pathsliceSource`, which `git branch -m` carries with a
rename, so later commands find the branch without `--branch`.

| Command | Behaviour |
| --- | --- |
| `log docs` | List the source commits and files the export contains. |
| `status` | Summarise each slice: whether the export branch is up to date, changes made on it that the source lacks, and conflicts. |
| `update docs` | Update the export branch locally, without fetching. |
| `update docs --push` | Update and push the export branch, without fetching or opening a PR. |

Use `--from BRANCH` to select another source and `--onto REF` to override the
base. `publish --no-update` publishes the export branch as it is.

## What the export contains

The export holds the source's net change to the selected paths. The change is
measured from the commits the source last merged from its base and from its
upstream: for each branch, the most recent commit on its first-parent history
that the source contains. Where merging those two commits conflicts in a file,
the upstream's version is used. The change is then applied to the base with a
three-way merge.

A source commit changing `src/parser.rs` and `docs/parser.md` therefore
contributes only the documentation change. Conflict resolutions in the
source's merges are part of the net change and are exported. Changes the
source merged from its upstream or base are not. A change the base already
contains produces no difference, whichever route it took, so no records of
merged changes are kept.

Without an upstream, changes the source merged from another branch are
exported as its own. `status` reports when the source shares commits with
other branches or merges commits that are not on the base.

The upstream is expected to receive the source through a merge commit, a squash
merge or a rebase merge, as GitHub performs them. If the upstream is
fast-forwarded to the source, the source's changes are measured as already
merged and the export appears empty.

## Updating an open pull request

While the PR is open, commit to the source branch and run `publish` again.
Each update adds one commit to the export branch. Earlier commits are not
rewritten, so pushes are fast-forwards. The commit lists the source commits it
covers, and the trailers `Pathslice-Slice` and `Pathslice-Source` identify the
slice and the source commit. Identities and dates are taken from the source
commit and the parents, so identical inputs produce identical commits.

Commits added to the export branch, such as review suggestions applied on
GitHub, are kept. `update` and `status` list the files in which the export
branch differs from the source; make those changes in the source as well so
that both PRs agree. If such a change conflicts with a later source change,
the update stops. Make the change in the source, or run with `--rebuild` to
discard it.

Changes to the base alone leave the export branch unchanged. If the source
merges a newer base than the export branch holds, the next update commit also
merges the base, so the PR still shows only the source's changes.

After the PR is merged, by merge commit or squash, `update` reports that there
is nothing to export. When the source has new changes, the next update starts
again from the base.

`--rebuild` starts the export branch again from the base, discarding its
commits. The push uses a lease, as described below.

## Conflicts

If the source's changes conflict with the base, `update` and `publish` stop and
name the files. Merge the base into the source, resolve the conflicts there,
then run the command again. The resolution then belongs to the source and
reaches the export with the rest of its changes.

## Working with Git

Pathslice installs no hooks. It refuses to update a branch that is checked out
or used by a rebase or bisect, including in other worktrees. Neither the source
nor the base can be the export branch. An existing branch is updated only if it
holds a pathslice commit for the slice, holds commits made by version 0.2, or
is recorded for the slice and source.

`publish` fetches first. If the local export branch and the remote branch have
diverged, local commits made by pathslice are replaced by the remote history,
since they are recomputed; any other local commit stops the command. `update`
does not fetch, builds on the local branch and reports a divergence. Pushes use
Git's `--force-with-lease` option with the last fetched value, so a remote
branch that changed since the last fetch is not overwritten.

## Upgrading from version 0.2

An export branch made by version 0.2 continues: its first update adds one
commit that brings it into line with the source's net change. The branch that
version 0.2 recorded for a slice and source is found without `--branch`.

The commands `continue`, `skip`, `abort`, `adopt`, `release`, `landed` and
`forget` have been removed, and the `select` and `subject` settings are
ignored. Records under `refs/pathslices/` are no longer written. After the first
update of each export branch, remove them with:

```sh
git for-each-ref --format='delete %(refname)' refs/pathslices/ | git update-ref --stdin
```

A `.git/pathslice/` directory left by an interrupted version 0.2 update can be
deleted.

## Limits and tests

Renames crossing a slice boundary become additions or deletions. Path
selection does not check dependencies between documentation and code.

Development uses Python 3.14. Compatibility checks cover Python 3.12 and 3.14. Tests require Git 2.40 or later.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m mypy
.venv/bin/python -m ruff check git-pathslice tests
.venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary Git repositories and local remotes. GitHub PR calls are
simulated.
