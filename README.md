# J.A.R.V.I.S.

**Version 1.3.1** (shown at the bottom right of the HUD)

An Iron Man-style assistant for your Windows PC and phone: a holographic HUD, voice control, a trading
journal and coach for MetaTrader 5, PC control, reminders, a floating mini core over your games, and more.

Jarvis thinks using **Claude Code signed in with your own Claude account** (Pro or Max plan), so it runs on
your plan's usage with no API tokens to buy. Everything else stays on your PC.

## Setup (Windows, about 10 minutes)

1. **Install Python 3.12** from the Microsoft Store (search "Python 3.12"), or from python.org with
   "Add Python to PATH" ticked.
2. **Install Claude Code.** Open PowerShell and run:
   `irm https://claude.ai/install.ps1 | iex`
3. **Sign in:** close and reopen PowerShell, run `claude`, log in with your Claude account, then type `/exit`.
   If `claude` isn't recognised, run this once, then reopen PowerShell:
   `[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path","User") + ";$env:USERPROFILE\.local\bin", "User")`
4. **Unzip this folder** somewhere it can stay, e.g. `Documents\Jarvis`.
5. **Double-click `Jarvis.bat`.** The first run installs what it needs (voice control takes a few
   minutes). When Windows Firewall asks about Python, allow **Private networks**.
6. Jarvis asks your name, your city and what to call you, and you're in.
7. Optional: double-click `Create desktop shortcut.bat` for a desktop icon.

## Run it

1. Double-click `Create desktop shortcut.bat` once. A JARVIS icon appears on your desktop.
2. Open JARVIS from that icon. You can right-click it and choose "Pin to taskbar" or "Pin to Start".

After an update, double-click `Jarvis.bat` itself instead, so you can watch
the progress. Voice control is the big one and can take a few minutes the first time.
Close the main window and Jarvis shuts down fully.

If Jarvis won't open or misbehaves, check `jarvis.log` in this folder, or run
`python server.py --browser` to use it in your browser with a terminal showing messages.

## The mini core

Switch to another window and a small see-through Jarvis floats on top. Drag it to move it,
scroll over it to resize, click it to type, double-click it to bring back the full window.
League of Legends and other games need Borderless window mode for it to show on top.

## Personality and awareness

- **Boot sequence:** the rings power up one by one with a power-up sound, then he greets you.
- **3D core:** a rotating holographic core (rings in their own planes, orbiting particles, glowing heart)
  that pulses with his voice. It needs internet once per start to load its 3D library; offline you get
  the flat core.
- **HUD sounds:** quiet cues for panels, thinking, alerts and hold. Turn them off under Protocols.
- **Holographic panels:** ask "show me gold on the 15 minute" or "show me my week" and panels float out
  of the core with a live chart or the numbers. They fade after a minute; click x to close one. They
  show on your phone too.
- **Talk back:** after he answers you by voice, just reply within about 6 seconds, no "Hey Jarvis" needed.
- **Interrupt:** say "Hey Jarvis" while he's talking, press Esc, or click the core.
- **Hold on:** say "Hold on Jarvis" (or "hang on", "stop", "not now", "never mind"...). He stops talking,
  drops what he was doing and stops listening (no talk-back window) until you say "Hey Jarvis" or press
  Resume. Background jobs he's already started keep going. Typing "hold on" works too.
- **Reads the room:** he knows which app you're in, whether you're in a game and the time. In a game he
  keeps it short and holds anything that can wait until it ends (alerts and trade warnings still come
  through). After 10 minutes without keyboard or mouse he treats you as away, holds his messages and
  catches you up when you're back. Between 1 and 5 am he'll tell you to get some sleep, once.
- **Protocols:** say "goodnight Jarvis" (night protocol), "initiate focus protocol" or "house party
  protocol". They run instantly. Make your own: "make a movie protocol that opens Netflix and sets the
  volume to 40".
- **Learns about you:** while you're away he reads recent conversations and remembers lasting things you
  told him (e.g. which session you trade). Ask "what have you learned about me?"; say "forget that"
  to remove one. Conversations are kept in the `conversations` folder on this PC.

## Voice

Say **"Hey Jarvis"** or just **"Jarvis"**, wait for the chime, then talk. Or press **Mic** next to the chat box.
The Voice row in the left panel shows whether it's ready. Speech is understood on this PC, offline.
If plain "Jarvis" is missed or he wakes when he shouldn't, adjust `setx JARVIS_LOOSE_WAKE 0.08`
(catches more) or `0.2` (stricter); the default is 0.12. If it never hears you: Windows Settings > Privacy & security > Microphone, and turn on
"Let desktop apps access your microphone".

## Your phone

Click **Pair phone** in the left panel and scan the code with your phone's camera. The phone stays
paired; add the page to your home screen. Allow Python on **Private networks** when Windows Firewall asks.
For use away from home, install Tailscale (free) on the PC and phone, sign both into the same account,
and pair again with the "Anywhere" code. Delete `phone_key.txt` to unpair every phone.

## Jarvis speaks up on his own

- **Reminders and timers** when they're due.
- **Morning brief** the first time he's running each morning: weather, reminders, news, gold.
- **Price alerts** you've set ("tell me if gold hits 3,960"), while MT5 is open.
- **Trade guard**: when you open a trade at 2x your usual size, re-enter within 5 minutes of a loss, or
  trade after 3 losses in a day; once a day at 5% down or 3 losses in a row. Change the limits at the
  top of `trading.py`.
- **News warnings** 15 minutes before high-impact USD, GBP and JPY news.
- **End-of-day review** once you've traded and then stopped for 90 minutes. Saved in `reviews`.
- **Dev jobs** you gave him, when they finish.

## Clips, routines and projects

- **"Clip that"** presses Medal's clip key (F8). Medal has to be running already, since it can only clip
  what it recorded. If you changed Medal's key, run `setx JARVIS_CLIP_KEY "f9"` (or whatever it is).
- **Routines**: "gaming mode" closes MT5 and opens Medal, Discord and League; "trading mode" opens MT5.
  Ask him to change them or make new ones ("add Spotify to gaming mode").
- **Dev helper**: "add my project MyGame at C:\Users\me\Projects\MyGame", then "in MyGame, make the jump
  higher". It works in the background on that project's folder (it can read and edit files there, not run
  anything) and tells you when it's done.

## Anything else

Ask Jarvis for anything you'd ask Claude in chat: "install 7-Zip", "tidy my Downloads folder into
subfolders", "find out why my mic is so quiet", "write me a script that renames my clips by date".
He hands it to a full Claude Code run on your PC (shell, files and the web) that works in the background
and tells you when it's done. It runs in Claude Code's auto mode: a safety check reviews every action and
blocks risky ones, like deleting existing files, running downloaded code or sending your data anywhere.

**PC errors:** ask "any errors on my PC?" or "why did my PC crash?". Jarvis reads Windows' own error logs
(crashes, blue screens, driver resets, unexpected restarts), tells you what matters, and fixes it if you
say yes. Some repairs need Administrator rights; he'll say when, and what to run.

## A Hisense TV (optional)

If you have a Hisense TV running VIDAA, Jarvis can control it: "turn on the TV", "switch to HDMI 2", "channel 7", "TV volume 15",
"open Netflix on the TV", "turn the TV off". It needs a one-time pairing: in PowerShell, in this folder, run
`python tv_pair.py <TV IP>` (the TV's IP is under Settings > Network > Network Information) and type the
PIN the TV shows. The pairing is kept in `config.yaml` and `tokens.json` here; if the TV ever stops
answering, run it again. To turn the TV on from fully off, switch on "Wake on LAN" in the TV's network
settings; Jarvis learns the TV's address the first time he talks to it while it's on. TV steps work in protocols too ("make a movie protocol that turns on the TV and
opens Netflix").

## Your MT5 trades (optional)

Trading features need MetaTrader 5 on this PC. Whenever MT5 is open and logged in, Jarvis adds newly closed trades to your journal by himself.
You can still drop MT5 History reports (Toolbox > History > right-click > Report > HTML) into the
`mt5 reports` folder, for example for an account you don't keep logged in.

## Try saying

- "Market briefing" / "What's gold doing?" / "What have I got open?"
- "How did I go on gold last month?" / "What's my worst habit?"
- "Log a long on gold, plus 2R, London breakout, I chased the entry a bit"
- "Open MetaTrader" / "Open League" / "Open YouTube"
- "Pause the music" / "Next song" / "Set volume to 30" / "Find Drake on Spotify"
- "Remember my car's service is due at 60,000 km" / "Remind me at 6 to call Mum" / "Timer, 20 minutes"
- "Tell me if gold hits 3,960" / "Any big news today?" / "Review my day"
- "What's on my screen?" / "What does this error mean?"
- "Any errors on my PC?" / "Fix it" / "Install OBS" / "Clean up my Downloads folder"

## Good to know

- Jarvis uses your plan's usage limits, shared with your normal Claude chats.
- In a normal chat Jarvis only runs his own commands. Jobs you ask him to do on the PC go to a separate
  run under Claude Code's safety check (see "Anything else"). He never places trades.
- Your data lives in small files here: `settings.json`, `memory.json`, `reminders.json`, `alerts.json`,
  `routines.json`, `projects.json`, `conversations`. Don't share your folder once you've used it; share the
  original zip instead.
- Want faster replies later? Set an API key (`setx ANTHROPIC_API_KEY "sk-ant-..."`) and Jarvis
  switches to the API automatically. That is billed separately.
- `python server.py --test`, `python features.py`, `python trading.py`, `python devhelper.py` and
  `python voice.py` run the self-checks.

## Updating

When a new version is out, an **Update to vX** button appears at the bottom right of the HUD. Click it and
Jarvis downloads the update, installs it and restarts by himself. Your settings, memory, journal and TV
pairing are kept. (Updates come from github.com/Minno404/jarvis.)

## Version history

- **1.3.1** (5 Nov 2026): more time to think when talking. After "Hey Jarvis" he waits up to 8 seconds for you
  to start, and a pause of up to about 1.5 seconds no longer cuts you off mid-sentence.
- **1.3.0** (5 Nov 2026): spending plans with Spend Breakdown. Ask "how's my spending this month?",
  "make me a budget" or "set eating out to 300 a month", and "how am I tracking?". Jarvis warns you when a
  category reaches 80% and 100% of its limit.
- **1.2.0** (5 Nov 2026): one-click updates from inside the app; no more re-downloading the zip.
- **1.1.0** (5 Nov 2026): uses far less of your Claude plan. Everyday commands ("pause the music", "next song",
  "TV volume 15", "turn on the TV", "switch the TV to HDMI 2", "timer 20 minutes", "volume 30", "open Discord",
  "what time is it") are now done instantly on the PC without asking Claude at all. Everything else costs
  about half what it did: Jarvis now uses his own short instructions instead of Claude Code's long coding ones,
  and the learning pass runs on the small Haiku model.
- **1.0.0** (5 Nov 2026): first shareable release. Holographic HUD with 3D core and HUD sounds; voice
  ("Hey Jarvis" or just "Jarvis", talk back, interrupt, "hold on"); neural voice; floating see-through mini
  core; phone access with pairing; PC control, routines and protocols; MT5 journal, live prices, market
  briefing, price alerts, trade guard, news warnings, end-of-day reviews; memory and learning; reminders;
  weather; screen reading; PC jobs and error fixing; dev helper; Hisense TV control; Medal "clip that".
