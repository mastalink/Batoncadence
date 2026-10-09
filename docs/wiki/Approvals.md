# Approvals

Open `/console` and choose **Approvals** ("Needs your OK"), or run `bitcadence
approve`. Nothing sensitive happens until you say so.

## When you can't approve yet

A missing approver right used to show up as `403 Forbidden: missing scope
jobs:approve`. It no longer does. In a terminal:

```
$ bitcadence approve
You can't approve yet because your account isn't an approver.
Fix it? [Y/n] y
Done. You can approve now.
Approved: Publish release notes.
```

Enter or `Y` makes the account on this computer an approver and then approves.
`N` changes nothing and points to `bitcadence fix`. `bitcadence fix` finds the same
problem on its own and offers the same repair. With no terminal and no `--yes`,
the right is never granted.

The repair edits this computer's own account, from a terminal you are sitting at.
It works only on the built-in local database; if your account is managed
somewhere else you are told to ask the person who runs BitCadence. There is
deliberately no web or API button for it, because an account that cannot approve
must not be able to promote itself over the network.

In the console, a refused Approve/Reject shows a card in words ("You can't approve
this yet. Your account isn't set up as an approver", with the command to run)
instead of an HTTP error.

## Approved, but nobody is free

If no helper is online for the job, you are told so and pointed to `bitcadence
helpers add`. See [Helpers](Helpers.md).
