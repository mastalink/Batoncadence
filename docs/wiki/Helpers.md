# Helpers

Open `/console` and choose **Helpers**, or run `bitcadence helpers` in a
terminal. Both show the same thing: each helper's friendly name, a health light
with a word, and what it is doing in plain words.

## The light and the word

| Light | Word | Meaning |
|---|---|---|
| ● green | Working | It has a job right now. |
| ● green | Ready | It is connected and waiting for a job. |
| ▲ red | Stuck | Something needs fixing (see Fix it). |
| ○ grey | Not connected | No sign of life. |
| ○ grey | Paused | Turned off on purpose. |

Colour is never the only signal: every light has a shape and its word. A name
like `claude-worker_3` is shown as "Claude worker 3". Each card also says when
the helper was last heard from. Tokens and credentials are never on this page.

## Add a helper

**+ Add a helper** asks which AI should power it (Claude, ChatGPT / Codex,
Gemini / Antigravity) and a name. It uses the same code as
`bitcadence helpers add`: the helper is registered and its sign-in is saved on
this computer. The page confirms "Penny is added" and never shows the sign-in; the
terminal shows it only masked, as `mco_tok_...1a2b`. An existing helper's name is
refused instead of silently replacing its sign-in.

```
bitcadence helpers add --name penny --role codex
```

## Fix it

Two problems look fine from outside, so BitCadence checks for them:

- **A locked notes file.** Another BitCadence process has the helper's
  `<name>.log` open, so it cannot save its notes. The light turns red even
  though the helper looks online.
- **Two copies running.** More than one `wake` process is watching the same
  helper. The oldest copy stays; the extras are stopped.

**Fix it** looks first and changes nothing: it lists what it found and what it
would do. Only after you answer **Yes, fix it** (in a terminal, `Y`) does it stop
the extra copy. Without an answer, nothing is stopped. A program that is not
BitCadence is never stopped; you are told to close it yourself.

```
bitcadence helpers fix
bitcadence fix
```

`--yes` skips the question for scripts. In the gateway API, `POST
/api/helpers/fix` is a dry run unless the body has `"confirm": true`.

Checking for these problems reads the list of running programs on this computer
only. It does not change anything, and a program it is not allowed to inspect is
skipped.
