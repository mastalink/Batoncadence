# Ask for something

Open `/console` and choose **Ask for something**, or run `bitcadence ask` in a
terminal. Both use the same planner: say what you want in plain words, check the
drawn plan, and approve once.

## In the console

1. Type what should happen, for example: *Research open PRs, run tests, if green
   draft release notes and ask me to publish.* Two example buttons fill the box
   for you.
2. **Draft a plan** draws the steps in order. "If everything passes" appears
   between steps that only run after a check. A dashed step marked "you decide"
   is a point where it stops and asks you.
3. Make only light tweaks:
   - **Remove a step** shows a Remove button on each step. A plan always keeps at
     least one step.
   - **Always ask me at the end** adds a final "Ask you before finishing" step.
   - **Make it repeat** offers every day, every weekday or every Friday at 9 AM.
     The plan then also shows up under Schedules.
4. **Approve and start** creates the work. Your Approve click is the OK, so only
   the plan's own "ask you" steps wait for you again. **Change my request** goes
   back to the text box; to change the plan itself, edit the request and draft
   again.

Nothing is created until you approve. If you are not connected yet (demo mode),
the page asks you to connect first.

## In a terminal

```
bitcadence ask "tidy the install docs"
bitcadence ask "Research open PRs, run tests, if green draft release notes and ask me to publish."
bitcadence ask "tidy the install docs" --remove 2 --ask-me --repeat "every Friday at 9 AM"
```

The plan prints as a numbered list and asks `Start this? [Y/n]`. `--remove N`
leaves out step N (repeat it for more), `--ask-me` always asks at the end,
`--repeat` makes it repeat, and `--yes` skips the question. From a terminal the
first step also waits for `bitcadence approve`.

## Workflow files

The drag-and-drop workflow builders are gone from the console. Workflow YAML
files still work and run exactly as before:

```
bitcadence ask --file plan.yaml
mco workflow plan.yaml
```

A repeat saves the plan as `~/.mco/workflows/ask-<name>.yaml` and adds a
schedule to `~/.mco/schedules.yaml` (the old file is kept as
`schedules.yaml.bak`). The older `mco gui --flow` option still works and opens
the console.

## How the plan is drawn

Commas, "then" and "ask me ..." split the request into steps, one per clause.
"If green" or "if it passes" becomes a condition on the next step. This is a
simple, predictable reading of your sentence, not a guess about what you meant:
if the drawn plan is wrong, reword the request and draft again.
