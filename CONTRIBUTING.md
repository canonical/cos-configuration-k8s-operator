# Contributing to cos-configuration-k8s-operator
TODO


# Design choices
Charm code attempts to manipulate the workload into a one of the three
well-defined state:

| State         | Config options   | Pebble service | Repo folder   | Stored hash     |
|---------------|------------------|----------------|---------------|-----------------|
| Uninitialized | `git_repo` unset | None           | Doesn't exist | None (NoneType) |
| Idle          | `git_repo` unset | Stopped        | Doesn't exist | Placeholder     |
| Configured    | `git_repo` set   | Running        | *             | *               |


# Charmhub resource revisions
## git-sync-image
- Revision 1: `k8s.gcr.io/git-sync/git-sync:v3.4.0`
- Revision 2: `k8s.gcr.io/git-sync/git-sync:v3.5.0`

