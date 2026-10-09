# Settings

Open `/console` and choose **Settings**, or run `bitcadence settings`.

```
$ bitcadence settings
Settings
  Pause everything: Off
  Tell me on my phone: On
Pause or resume with `bitcadence pause` / `bitcadence resume`.
For people who like details: bitcadence settings --show-advanced
```

Everyday things use plain labels: **Pause everything** (helpers stop taking new
work; jobs in progress finish) and **Tell me on my phone**. Memory lives under
Drumline in the menu.

## Show advanced

Addresses, ports and sign-in tokens appear only here. In the console, open
**Show advanced** (the connection, the raw gateway settings and connectors). In a
terminal:

```
bitcadence settings --show-advanced     # also: --all
```

adds where BitCadence listens and this computer's sign-in, always masked as
`mco_tok_...1a2b`, followed by every raw setting. Reading or changing one setting
by name still works exactly as before: `mco settings KEY` and `mco settings KEY
VALUE`.
