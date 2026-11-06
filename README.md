# J.A.R.V.I.S.

**Version 1.33.1** (shown at the bottom right of the HUD)

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

## ChatGPT as a backup brain (optional)

If your Claude plan's limit runs out, Jarvis can carry on using ChatGPT, with the same memory, journals,
settings and recent conversation. It uses your ChatGPT plan (Plus or higher), not paid API credits.

1. Install Node.js (LTS) from https://nodejs.org if you don't have it.
2. Open a Command Prompt and run: `npm install -g @openai/codex`
3. Then run: `codex login` and choose **Sign in with ChatGPT**.
4. Restart Jarvis. The Systems panel shows which brain he's using.

He switches by himself when the Claude limit is hit, and tries Claude again an hour later. You can also say
"switch to ChatGPT", "use Claude" or "auto mode". Background jobs (coding and PC jobs) use whichever brain he's
on, and switch to ChatGPT if Claude runs out mid-job. If you only have ChatGPT (no Claude Code), Jarvis uses
ChatGPT for everything. (The background learning pass still needs Claude.)

## Your own additions (kept through updates)

Ask Jarvis to build something into himself ("create an expanded systems panel", "add a battery panel") and he
builds it in the `custom/` folder. Updates never touch that folder, so your additions carry over to every
version. Close a custom panel with its x and say "show the <panel name>" to bring it back. To build your own by
hand, see CUSTOM.md.

## Updating

When a new version is out, an **Update to vX** button appears at the bottom right of the HUD. Click it and
Jarvis downloads the update, installs it and restarts by himself. Your settings, memory, journal and TV
pairing are kept. (Updates come from github.com/Minno404/jarvis.)

## Waking the PC when you're out

Wake-up packets can't cross the internet, so a device left on at home does it. `wake_helper.py` runs on an
always-on Android tablet (in Termux) with Tailscale: open its page on your phone, press Wake, and Jarvis opens once
the PC is up. Setup is at the top of the file.

## Version history

- **1.33.1** (7 Nov 2026): local AI fixes: RAM mode no longer fails with "pull model manifest: file does not exist",
  and Codex jobs find Node.js when it was installed while Jarvis was running.
- **1.33.0** (7 Nov 2026): a much faster local AI. Chat now goes straight to Ollama (no Codex in between, so far
  less to read per message), thinking is switched off, and the model stays loaded for 30 minutes. Coding and PC
  jobs still go through Codex.
- **1.32.7** (7 Nov 2026): Settings > Brain > "Local AI runs on": the graphics card (fast) or RAM and the processor
  (slower, but leaves the graphics card free for games).
- **1.32.6** (7 Nov 2026): instant brain swaps: "online mode", "offline mode" and "swap brain" (flips between the
  local AI and the online ones) are done on the spot, without asking an AI.
- **1.32.5** (7 Nov 2026): the local AI answers again (newer Codex refused with "this chat uses ollama, but your
  current provider is openai").
- **1.32.4** (7 Nov 2026): local AI fixes. Codex is told to use Ollama (newer versions need it), the message is
  handed over without any chance of a deadlock, and if the AI goes silent for 5 minutes Jarvis stops it and says so
  instead of hanging.
- **1.32.3** (7 Nov 2026): faster again. Replies no longer wait ~2 s checking on the local AI, and the quick
  "did he say Jarvis?" check uses the small fast speech model, so the mic keeps up.
- **1.32.2** (7 Nov 2026): no more robotic voice: symbols, emoji and local models' "thinking" are never read out,
  and if the online voice fails Jarvis tries Ryan, then Kokoro, before the Windows voice. Settings > Brain > Local
  AI voice gives the local AI its own voice (any Kokoro or online voice).
- **1.32.1** (7 Nov 2026): ChatGPT (and the local AI) no longer say they're "restricted": PC jobs (clearing temp
  files, installing, fixing) go to cleanup or pc_task, coding to dev_task, and Codex jobs are told they have full
  access. Temporary files and caches count as fine to clear in PC jobs.
- **1.32.0** (7 Nov 2026): a third brain, a free local AI that runs on your PC (Ollama + Codex's local mode): no
  account, no tokens. First launch offers to install it (it picks a model for your graphics card); or Settings >
  Brain > Install. Brain choice: automatic (Claude, then ChatGPT, then local), Claude, ChatGPT or local; "switch
  to local" by voice. Coding and PC jobs work with it too. Plus free web search and page reading for every brain.
- **1.31.0** (7 Nov 2026): better voice recognition: a more accurate speech model by default (Settings > Voice
  recognition: fast / accurate / best), a wider search, and a vocabulary that includes your name. When he isn't
  sure he heard you right he checks first ("did you say ...?") and acts on yes; spoken requests that could mean
  something else get a quick question before anything changes.
- **1.30.1** (7 Nov 2026): the spending report hides every other panel (moved ones and add-ons too), and "close the
  report", "go back" or "Jarvis close spending report" bring the normal HUD straight back.
- **1.30.0** (7 Nov 2026): Spend Breakdown is built into Jarvis. "Jarvis, pull up my spending report" turns the
  whole HUD into it (his core moves to a corner): add CSV/PDF statements or use the Documents\Statements folder,
  filter by account and month, spent/earned/net, the category donut, open a category to see its shops, drag a
  shop to another category (or use "Move to"), new and deleted categories, re-categorise a transaction, your
  pay, remove an account, insights (plus "Ask Jarvis for more") and your spending plan. Same data as the app.
- **1.29.0** (7 Nov 2026): first-launch setup asks what Jarvis should keep an eye on: day trading and markets,
  spending, TV. Anything left off still works when asked, but he won't bring it up himself (no market news,
  trade warnings, trading review or gold in the morning brief, and the trading panels stay closed). Change it
  any time in Settings > Features. Existing installs keep everything on.
- **1.28.6** (5 Nov 2026): Jarvis never opens MetaTrader 5 by himself (MetaTrader's connector used to start it
  whenever anything asked for live data); he uses MT5 only when it's already open, or opens it when asked.
- **1.28.5** (5 Nov 2026): iPhone, normal view: Jarvis's sound starts from your first tap (like holo mode's "tap
  to wake"), so Silent mode no longer mutes him.
- **1.28.4** (5 Nov 2026): Jarvis's voice on iPhone in Silent mode, for real: a silent media clip makes iOS treat
  him like a music app.
- **1.28.3** (5 Nov 2026): on a phone, drag the bar under any panel (or the chat) to make it taller or shorter
  (double-tap the bar to reset), and Settings can be opened from the phone too.
- **1.28.2** (5 Nov 2026): iPhones play Jarvis's voice even with Silent mode on (his voice counts as media playback).
- **1.28.1** (5 Nov 2026): phones on your Tailscale network can use Jarvis with no pairing (only your own devices
  can reach that address), and Phone link shows one Tailscale link that works at home and away.
- **1.28.0** (5 Nov 2026): "Put the PC to sleep" / "goodnight Jarvis" closes what blocks real sleep (SteelSeries
  GG by default), sleeps, and reopens it on waking. Quiet wake: when your phone wakes the PC (Wake-on-LAN) the
  screens stay off and Jarvis works from the phone behind the lock screen, stays silent on the PC, and puts it
  back to sleep 10 minutes after the phone goes quiet.
- **1.27.1** (5 Nov 2026): "Start with Windows" now uses a log-on scheduled task (no startup delay, higher
  priority) and skips the component checks, so Jarvis is up first. The old Startup-folder shortcut moves over
  by itself.
- **1.27.0** (5 Nov 2026): game coach. "Coach me" and Jarvis watches your gameplay (a screenshot every ~20 s, kept
  on this PC), gives a short live tip when he spots a clear mistake, and reviews the session when the game ends
  ("how did I play?"). "What am I doing wrong?" checks the last minute; "coach every game" makes it automatic.
- **1.26.1** (5 Nov 2026): both brains (Claude and ChatGPT) may read Jarvis's own files (README, CUSTOM.md, code)
  to answer questions, and changes to Jarvis go to the coder (dev_task), which builds them in custom/.
- **1.26.0** (5 Nov 2026): Settings > Startup & closing: start Jarvis with Windows (he waits in the tray), and
  close to the system tray instead of quitting (Quit from the tray icon). Checkboxes in Settings show properly.
- **1.25.0** (5 Nov 2026): "What can you do?" / "show all commands" / "help" opens a searchable panel of every
  command by topic (instant ones starred; click one to try it). Add-ons in custom/ can add their own phrases.
- **1.24.0** (5 Nov 2026): Iron Man boot-up (a cinematic systems check and "welcome home" when you're back after
  3+ hours, or say "boot up"); ambient light (the HUD's edges glow with the time of day and weather, pulse to
  music and turn red as a timer runs out; Settings); holo mode for your phone (Systems > Holo mode: a desk
  hologram that speaks Jarvis's announcements); and Jarvis as Dungeon Master, with real dice on the HUD.
- **1.23.0** (5 Nov 2026): instant calculator and converter (sums, tips, bill splits, units, currency; no tokens);
  voice notes ("note: ..."); a workout coach that runs timed workouts on the HUD and calls each exercise out;
  "what's this error?" / "explain my screen" (Jarvis looks at your screen first); a translator that speaks in a
  native voice; and price watch (tells you when something drops to your price).
- **1.22.0** (5 Nov 2026): meal ideas now come with a shopping list priced at Woolworths and Coles (cheapest store
  per item, totals, specials), kept between sessions: "add milk to my list", "what's on my list", "got the
  milk". Jarvis.exe works with the Microsoft Store Python (it keeps its own copy in pyruntime/), and if it
  can't run, the reason goes in jarvis_exe.log.
- **1.21.0** (5 Nov 2026): everyday helpers (life.py). Meal ideas with a recipe panel that stays up while you cook;
  bills and renewals with warnings a week and a day before; a habit tracker with streaks; "clean up my PC"
  (scans first, cleans only what you OK, old downloads go to the Recycle Bin); game mode (closes the apps you
  pick when a game starts and reopens them after); and "find my file" across your own folders.
- **1.20.1** (5 Nov 2026): say "Jarvis split" to split (and "Jarvis merge", or "merge with ChatGPT/Claude", to
  merge back). Jarvis no longer mentions which brain answered or did a job.
- **1.20.0** (5 Nov 2026): Split mode voices in Settings: pick each avatar's voice (any Kokoro voice or an online one).
  ChatGPT defaults to Kokoro's Emma, Claude to Jarvis's own voice. If an online voice stops working, Jarvis's
  Ryan stands in instead of the basic Windows voice.
- **1.19.1** (5 Nov 2026): Jarvis.exe now runs Python inside itself, so his window really belongs to "Jarvis":
  his name in Task Manager and his logo on the taskbar. It's checked before use; if it can't run on a PC,
  Jarvis starts with pythonw as before.
- **1.19.0** (5 Nov 2026): split mode. Triple-click the core and Jarvis splits in two: Claude (orange) argues the
  pros of whatever you ask, ChatGPT (green) the cons, each in its own voice. Triple-click either to merge back,
  with that one as the brain. The Update button now always shows above panels.
- **1.18.1** (5 Nov 2026): fixes the tray icon and taskbar logo (the icon file was looked for in the wrong folder).
  Jarvis.exe is now a small launcher built with Windows' own C# compiler, so it works with the Microsoft Store
  Python too.
- **1.18.0** (5 Nov 2026): Jarvis shows as "Jarvis" with his own icon in Task Manager and on the taskbar (Jarvis.exe,
  a renamed pythonw made on first launch), and lives in the system tray by the clock: click to open, right-click
  for mini core, quiet mode, restart and quit. Windows 11 tucks new tray icons behind the ^ arrow: drag it out next
  to the clock, or turn it on in Settings → Personalisation → Taskbar → Other system tray icons.
- **1.17.3** (5 Nov 2026): Text size slider in Settings → Panels (70–130%), remembered across restarts.
- **1.17.2** (5 Nov 2026): moved panels keep their place relative to the window, so the same layout mirrors onto
  a bigger or smaller window, and they're always kept fully on screen (dragging too).
- **1.17.1** (5 Nov 2026): launching Jarvis while he's already running now brings his window to the front, or, if
  he was left running in the background without a window, replaces him, instead of silently doing nothing.
- **1.17.0** (5 Nov 2026):
  - No Windows title bar: minimise, maximise and close are small buttons in the HUD's top-right corner. Drag the
    window by the strip along the top (double-click it to maximise) and resize it from the bottom-right corner.
  - Slim scrollbars in the HUD colour.
  - Fixed the Systems panel's Brain row showing blank, and closing Jarvis now always closes him fully.
- **1.16.0** (5 Nov 2026): pinned panels are see-through, following Settings → Panels → See-through (lower =
  more see-through), so they sit over a game without getting in the way. They're drawn like the mini core now:
  drag them anywhere, resize from the corner, and click the x to unpin.
- **1.15.1** (5 Nov 2026): fixed the app window showing an old copy of the HUD after an update.
- **1.15.0** (5 Nov 2026):
  - Clearer, more see-through panels, with a See-through slider in Settings → Panels.
  - Pin up to 3 panels with the + beside a panel's x. While Jarvis is in the background (another window in
    front, or minimised), each pinned panel floats on top of other windows as its own little window, like the
    mini core: drag it by its title, resize it from the corner, and it stays where you put it. The x on a
    pinned panel (or the − in the HUD) unpins it.
- **1.14.0** (5 Nov 2026): quality of life.
  - Panel positions and which panels are open or closed are now kept when Jarvis restarts.
  - Backgrounds: "make the background stars" (also nebula, grid, hex, falling code, plain dark), "set the
    background to a picture of a city at night", or "set the background to my last photo"; or Settings →
    Background, with a darken slider for pictures. Undo works on it too.
  - A quieter message bar: no Send button (press Enter), a + at the end of the box for photos, and the
    suggestion buttons fade back until you hover over them.
- **1.13.0** (5 Nov 2026):
  - "Undo that": reverses the last thing Jarvis changed (a logged trade, memory, reminder, alert, routine,
    budget, rules, colour, personality, panel, an app he opened, the TV). Say it again to go further back.
  - Quiet mode ("quiet mode" / "quiet mode off", or the switch in the Activity panel): routine announcements wait
    until you turn it off, like they already do during a game. Reminders, price alerts and trade warnings still
    come through.
  - Activity panel: coding and PC jobs, things downloading or converting, upcoming reminders and held messages.
  - Session debrief ("debrief my session"): every entry checked against your own trading rules, what breaking them
    cost, the mistakes that keep recurring across your last 10 sessions, and one thing to watch tomorrow. It's
    also part of the end-of-day review and the morning brief. Change your rules by voice ("stop me after 2
    losses", "no trading after 11pm", "wait 15 minutes after a loss").
- **1.12.2** (5 Nov 2026): core models can also be a .zip (a .blend with its texture images), unpacked and
  converted with Blender, which also finds textures the .blend lost track of.
- **1.12.1** (5 Nov 2026): the core model can be a Blender file (.blend) as well as .glb. Jarvis converts it with
  Blender automatically (Blender needs to be installed; it's free from blender.org).
- **1.12.0** (5 Nov 2026): a more human voice. Settings → Voice → Kokoro installs a natural-sounding voice that
  runs on your PC (free, no limits, about 350 MB once), with British and American voices to pick from and a
  speed slider. Both voices now say things the way a person would ("gold", "minus 41 dollars", "plus 2 R"),
  and after his first sentence Jarvis speaks in longer, smoother stretches.
- **1.11.0** (5 Nov 2026): settings (Protocols → Settings → Open).
  - Listening: "Hey Jarvis", push-to-talk only, or both. Push-to-talk works anywhere, even in games: hold the
    key (or a mouse side/middle button) and talk, let go to send.
  - Core model: swap the arc reactor for any 3D model (.glb), shown as a hologram in the HUD colour or in its own
    colours; it turns, breathes and pulses with his voice, and plays the model's idle animation if it has one.
    Models live in custom/models, so updates keep them.
  - "Restart yourself" and "power down": Jarvis restarts or closes himself (not the PC).
- **1.10.0** (5 Nov 2026): trading coach and personalities.
  - Trade replay: "replay my last loss" shows the trade on a chart (entry, exit, stop, target) and what price did.
  - Pre-trade checklist: "should I take this long?" checks news, losses today, daily loss, tilt and your record
    at this hour, then says go, caution or no-go.
  - Tilt detector: watches for losing streaks, revenge re-entries, sizing up or flipping after losses and
    overtrading, warns as it builds, and "am I tilting?" shows a tilt meter.
  - Personalities: "switch to FRIDAY" (Irish, cheeky), "EDITH mode" (crisp, tactical), "casual mode" (Jarvo, an
    Aussie mate) and "back to Jarvis". Each has its own voice.
- **1.9.0** (5 Nov 2026): coding and PC jobs work with ChatGPT too. They follow whichever brain Jarvis is on,
  switch to ChatGPT if Claude's limit is hit mid-job, and a PC with only ChatGPT set up uses it for everything.
- **1.8.1** (5 Nov 2026): select and copy text from the chat, or use the Copy button on any message.
- **1.8.0** (5 Nov 2026): your own additions survive updates. Anything Jarvis builds into himself now goes in
  the `custom/` folder (panels, stats, tools, styles), which updates never touch. Fixes updates being skipped
  after Jarvis had edited his own files.
- **1.7.1** (5 Nov 2026): the HUD scales with the window. Make the window bigger (or full screen) and the side
  panels move out to the edges while the core, text, panels and charts grow, with Jarvis kept in the centre.
- **1.7.0** (5 Nov 2026): send Jarvis photos. Press Photo (opens the camera on a phone), paste one, or drag it
  onto the window, then ask about it by typing or by voice ("Hey Jarvis, what's this?"). Works with both brains.
- **1.6.1** (5 Nov 2026): the ChatGPT brain can now use Jarvis's tools (MT5, TV, PC...). Pictures now come from
  a web-wide image search (Wikipedia as backup), are pulled straight into the HUD without opening the browser,
  and up to 4 can show side by side ("show me 3 pictures of...", "show me another one"); click one to enlarge.
- **1.6.0** (5 Nov 2026): ChatGPT as a backup brain. When the Claude plan's limit is used up, Jarvis switches to
  ChatGPT (through OpenAI's Codex CLI on your ChatGPT plan) and keeps his memory and the conversation. Say
  "switch to ChatGPT", "use Claude" or "auto mode" to choose. See "ChatGPT as a backup brain" above to set it up.
- **1.5.1** (5 Nov 2026): the floating mini core now matches the HUD's colour.
- **1.5.0** (5 Nov 2026): fresher greetings (around 50, by time of day and weekday, no repeats in a row).
  Close any side panel with its x and ask Jarvis to bring it back ("show the MT5 journal", "show all panels").
  New holographic panel types: line charts, donut charts, progress bars (budgets, goals), lists (agenda,
  reminders, news), live countdowns (timers now show one) and text notes.
- **1.4.1** (5 Nov 2026): fixed panels getting stuck after being moved once.
- **1.4.0** (5 Nov 2026): HUD upgrade.
  - Colour themes: "Jarvis, make the HUD red" (also gold, green, purple, pink, orange, white, teal, blue...).
  - Pictures: "show me a picture of a CLA45 AMG" pulls one from Wikipedia onto the HUD.
  - Drag any panel by its title and resize it from the bottom-right corner. Jarvis remembers where you put
    them; Protocols → Layout → Reset puts them back.
  - A subtle grid, scan sweep and panel corner details.
- **1.3.1** (5 Nov 2026): more time to think when talking. After "Hey Jarvis" he waits up to 8 seconds for you
  to start, and a pause of up to about 1.5 seconds no longer cuts you off mid-sentence. Updates now show up within half an hour without restarting.
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
