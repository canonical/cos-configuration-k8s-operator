# Contributing to cos-configuration-k8s-operator
![GitHub](https://img.shields.io/github/license/canonical/cos-configuration-k8s-operator)
![GitHub commit activity](https://img.shields.io/github/commit-activity/y/canonical/cos-configuration-k8s-operator)
![GitHub](https://img.shields.io/tokei/lines/github/canonical/cos-configuration-k8s-operator)
![GitHub](https://img.shields.io/github/issues/canonical/cos-configuration-k8s-operator)
![GitHub](https://img.shields.io/github/issues-pr/canonical/cos-configuration-k8s-operator) ![GitHub](https://img.shields.io/github/contributors/canonical/cos-configuration-k8s-operator) ![GitHub](https://img.shields.io/github/watchers/canonical/cos-configuration-k8s-operator?style=social)


## Design choices
- You need to deploy a `cos-config` app per repo.
- Internally, the charm is using `git-sync` to sync a remote repo with the local copy.
  `git-sync` is always called with the `--one-time` argument, which means it exits after the first sync. The repo syncs
  on `update-status` or when the user manually runs the `sync-now` action.

[Git sync]: https://github.com/kubernetes/git-sync
