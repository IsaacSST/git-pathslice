# git pathslice

Publish the changes that one branch makes to selected paths as a separate pull
request (PR). The branch you work on stays as it is.

## Terms

- **Slice**: a named set of paths, such as `docs/`, with the branch its PRs
  target.
- **Source branch**: the branch you commit to. Its commits may change files
  inside and outside the slice.
- **Base**: the branch the PR targets, such as `main`.
- **Upstream**: the branch the source branch is developed against, if it is not
  the base, such as `dev`. Its changes are not exported.
- **Export branch**: the branch pathslice writes. It holds only the source
  branch's changes to the slice, and the PR is opened from it.

For example, a team might merge documentation into `main` and code into `dev`.
A feature branch made from `dev` changes both. Its documentation slice has the
base `main` and the upstream `dev`, so the export branch proposes to `main` only
the feature's own documentation changes.

Git computes each export with `git merge-tree`, without a worktree. Python
manages configuration and the export branch. The GitHub CLI (`gh`) manages
pull requests.

## Installation

Requires Git 2.40 or later and Python 3.9 or later. PR commands also require
the GitHub CLI, authenticated with `gh auth login`.

```sh
git clone https://github.com/IsaacSST/git-pathslice.git
cd git-pathslice
mkdir -p ~/.local/bin
ln -s "$PWD/git-pathslice" ~/.local/bin/git-pathslice
export PATH="$HOME/.local/bin:$PATH"
git pathslice -h
```

Keep `~/.local/bin` on your shell's `PATH`. The script runs with the first
`python3` on the `PATH`. Use `-h` for help; Git's `--help` option expects a
manual page.

## Configuration

Define a slice and commit its definition, so that it travels with the
repository:

```sh
git pathslice add docs docs/ --base origin/main --upstream origin/dev --shared
git add .gitpathslices
git commit -m "Define the documentation slice"
```

| Setting | Meaning |
| --- | --- |
| `path` | Paths to export, in Git pathspec syntax, relative to the repository root. Repeat it for several paths. |
| `base` | The branch PRs target. The default is the remote's default branch (`origin/HEAD`), otherwise `main` or `master`. |
| `upstream` | The branch the source branch is developed against, if it is not the base. |

`add` also accepts paths relative to the current directory. Pathspecs with
magic, such as `:!drafts`, are stored as given and read from the repository
root, so give those from the root.

`.gitpathslices` uses Git configuration syntax. Commands that export read it
from the source branch's latest commit, or from the working tree if that commit
lacks it; `list`, `add` and `rm` use the copy in the working tree. Definitions
in Git's own configuration, such as `.git/config`, can add paths or override
other settings.

## Use

Publish the documentation slice from the current branch:

```sh
git pathslice publish docs
```

`publish` fetches the remote, adds the source branch's latest changes to the
export branch, pushes it, then creates a PR or reuses an open one. `pr` is an
alias for `publish`. Only committed changes are exported.

The export branch is named `pathslice/<slice>/<source branch>` unless
`--branch NAME` chooses another. The slice, source branch and base are
recorded in the branch's Git configuration (`branch.<name>.pathsliceSlice`,
`pathsliceSource` and `pathsliceBase`), which `git branch -m` carries with a
rename, so later commands find the branch without `--branch`.

| Command | Behaviour |
| --- | --- |
| `log docs` | List the source commits and the files the export contains. |
| `status` | Summarise each slice: whether the export branch is up to date, changes made on it that the source branch lacks, files left out, and conflicts. |
| `update docs` | Update the export branch locally, without fetching. |
| `update docs --push` | Update and push the export branch, without fetching or opening a PR. |
| `list`, `add`, `rm` | Show, define and remove slices. |

Use `--from BRANCH` to export from a branch other than the current one, and
`--onto BRANCH` to override the base. `publish --no-update` publishes the
export branch as it is. `git pathslice COMMAND -h` lists a command's options.

## What the export contains

The export holds the source branch's net change to the slice. The change is
measured against the latest commits of the base and of the upstream that the
source branch has merged: for each, the most recent commit on that branch's
first-parent history that the source branch contains. Where those two commits
conflict in a file, the upstream's version is used. The change is then applied
to the base with a three-way merge.

A source commit that changes `src/parser.c` and `docs/parser.md` therefore
contributes only the documentation change. Conflict resolutions in the source
branch's merges are part of the net change and are exported. Changes that the
source branch merged from its upstream or base are not. A change the base
already contains produces no difference, however it arrived, so pathslice keeps
no records of merged changes.

Without an upstream, changes the source branch merged from another branch are
exported as its own. `status` reports when the source branch shares commits
with other branches, or merges commits that are not on the base.

The upstream can merge the source branch, and the source branch can then merge
the upstream again. The changes the upstream received from the source branch
are taken out of the measure, so they stay in the export. If the upstream is
fast-forwarded to the source branch instead, the source branch's changes are
measured as the upstream's, and the export appears empty.

## Updating an open pull request

While the PR is open, commit to the source branch and run `publish` again.
Each update adds one commit to the export branch; earlier commits are not
rewritten, so pushes are fast-forwards. The commit lists the source commits it
covers. Its trailers record the slice (`Pathslice-Slice`), the source commit
(`Pathslice-Source`) and the definition used (`Pathslice-Base`,
`Pathslice-Upstream` and `Pathslice-Path`). Identities and dates are taken from
the source commit and the parents, so identical inputs produce identical
commits.

A change to the slice's paths or upstream takes effect at the next update,
which compares the new export with the one made under the recorded definition.
An export branch serves one base. For another base, choose another `--branch`
once; later commands pick the branch recorded for the base in use.

An update stops if the source branch is behind the commit that the export
branch was last made from, as in a checkout that has not pulled. It also stops
if that commit is missing, for example after the source branch was rewritten
and the old commits were pruned; `--rebuild` then starts the export branch
again.

Commits added to the export branch, such as review suggestions applied on
GitHub, are kept. `update` and `status` list the files in which the export
branch differs from the source branch; make those changes in the source branch
as well, so that the two agree. If such a change conflicts with a later change
to the source branch, the update stops. Make the change in the source branch,
or run with `--rebuild` to discard it.

Changes to the base alone leave the export branch unchanged; `update` and
`status` report when it no longer merges cleanly into the base. If the source
branch merges a newer base than the export branch holds, the next update commit
also merges the base, so the PR still shows only the source branch's changes.

If the source branch withdraws all its changes while the PR is open, the next
update leaves the export branch with none, and `publish` pushes it so that the
PR shows none.

After the PR is merged, whether by merge commit, squash or rebase, `update`
reports that there is nothing to export, and the changes the PR brought to the
base count as merged even if the base edits them later. When the source branch has new
changes, the next update starts the export branch again from the base.

`--rebuild` starts the export branch again from the base, discarding its
commits; with nothing to export, it resets the export branch to the base.

## Conflicts

If the source branch's changes conflict with changes the base made after the
source branch last merged it, `update` and `publish` stop and name the files.
Merge the base into the source branch, resolve the conflicts there, and run
the command again. The resolution then belongs to the source branch and
reaches the export with the rest of its changes.

A conflict in a file that the base has not changed since then comes from
upstream changes that the base lacks, which merging the base cannot resolve.
Such files keep the base's version, and `update` and `status` list them. They
are exported once the upstream changes they build on reach the base.

## Working with Git

Pathslice installs no hooks. It refuses to update a branch that is checked out,
or in use by a rebase or bisect, in any worktree. Neither the source branch nor
the base can be the export branch.

An existing branch is updated only if it is recorded as the export for the
slice and source branch, or if pathslice made one of its commits for the slice:
its last commit, or one that the base lacks. For an export made by version
0.2, that commit must name the same paths and base.

If the local export branch and the remote one have diverged, `publish` keeps
the remote history. It discards local commits that pathslice made, since the
update makes them again, and recognises them by the committer and date it gave
them. Any other local commit, including an amended one, stops the command.
`update` builds on the local branch and reports the divergence.

Before pushing, pathslice reads the remote branch with `git ls-remote` and
passes that value to Git's `--force-with-lease` option. A push that is not a
fast-forward replaces only commits that were fetched and built on, or whose
changes the base already holds.

## Upgrading from version 0.2

An export branch made by version 0.2 continues: its first update adds one
commit that brings it into line with the source branch's net change. The
branch that version 0.2 recorded for a slice and source branch is found without
`--branch`.

The commands `continue`, `skip`, `abort`, `adopt`, `release`, `landed` and
`forget` have been removed, and the `select` and `subject` settings are
ignored. Version 0.2's records under `refs/pathslices/` are no longer written.
After the first update of each export branch, remove them with:

```sh
git for-each-ref --format='delete %(refname)' refs/pathslices/ | git update-ref --stdin
```

A `.git/pathslice/` directory left by an interrupted version 0.2 update can be
deleted.

## Limits and tests

Renames across the boundary of a slice become additions or deletions.
Pathslice does not check whether the exported files depend on files outside
the slice.

Development uses Python 3.14, and the tests also run on Python 3.9, the oldest
supported version. Tests require Git 2.40 or later.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m mypy
.venv/bin/python -m ruff check git-pathslice tests
.venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary Git repositories and local remotes. GitHub PR calls are
simulated.
