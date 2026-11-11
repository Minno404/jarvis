# J.A.R.V.I.S.

**Version 1.75.1** (shown at the bottom right of the HUD)

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

- **1.75.1**: Shift calendar: full width on the phone, shorter labels (9a, 10p), and days off from the roster shown as BOD, Rest or Off. Rosters now save their days off as well as the shifts.
- **1.75.0**: Shift calendar: 'bring up my work shifts' shows a month calendar up to the end of your latest roster; tap a day to give it a shift, mark it off or add a note. 'What am I doing this week?' shows this week in one row. Voice: an Emotion slider in Settings > Voice for every voice (pace, pitch and pauses follow the words), and 14 more adult voices. Roleplay characters can have their own voice and speed.
- **1.74.0** (11 Nov 2026): rosters read exactly. A grid roster PDF (one row per person, one column per day, cells like
  "3SHTQ / 22:00 - 29:30 / 7:30") is read by position, so each shift lands on the right day: hours past 24 become the
  next morning, the paid hours are kept, and days off (BOD, leave, rest, Not Avail.) are skipped. Works for the
  Gmail roster and for a PDF sent through the + button (PDFs can now be attached). On the phone, the clock panel
  can't be squashed any more (that cut its title off) and the boot-up lines no longer sit over the chat.
- **1.73.6** (11 Nov 2026): a roleplay panel only shows in incognito ("roleplay" outside incognito says to go
  incognito first). The phone's "On this phone" sound choice is now always visible in Settings, Voice (it was inside
  the Kokoro options, hidden when the online voice is picked).
- **1.73.5** (11 Nov 2026): "check rosters", "check my roster", "get my roster" or "check my email for my roster" makes
  Jarvis look in Gmail now, load the newest roster's shifts and say how many (or that it's already loaded).
- **1.73.4** (11 Nov 2026): Settings, Voice, "On this phone" (phone only, remembered on that phone): play alongside
  YouTube and music (the Silent switch mutes him), lower them while he talks (try it in Silent), or take over like a
  music app (heard in Silent, pauses the rest, shows the lock-screen player). Holo mode always takes over.
- **1.73.3** (11 Nov 2026): on the phone, outside holo mode, Jarvis's sound mixes with whatever is playing (YouTube,
  music) instead of pausing it. Holo mode still takes over the audio so he's heard properly.
- **1.73.2** (11 Nov 2026): the phone no longer zooms in and shifts the page when he taps the message box (or any
  other box): iPhones zoom on text boxes under 16px, so on touch screens they're 16px.
- **1.73.1** (11 Nov 2026): roster email on a day he picks, no alerts. Settings, Roster email, "Check on": on that
  weekday (from 9 am, once) Jarvis looks for a roster email he hasn't loaded yet; if there is one, he loads the shifts
  and says how many came in. "Get my roster" still works any time.
- **1.73.0** (11 Nov 2026): the roster from Gmail. Settings, Roster email: his Gmail, a Google app password (read
  only, kept on the PC, never sent to an AI), the address the roster comes from and his name on it. Every 2 hours Jarvis
  checks for a new roster email and says when one arrives; "get my roster" downloads the newest (PDF, Excel, CSV or
  pictures; files kept in rosters/), finds his name's shifts and saves them. Gmail is read through IMAP, read-only.
- **1.72.0** (11 Nov 2026): work shifts. Send a photo or screenshot of the roster ("here's my roster") and Jarvis
  reads it and saves every shift (date, start, end, where); a new roster replaces the old one for its dates. "Bring up
  my work shifts", "my roster" or "when do I work next?" shows the next two weeks as a panel (with hours) instantly,
  no AI needed. Shifts are kept in shifts.json on the PC.
- **1.71.3** (11 Nov 2026): on the phone, a panel he asks for ("roleplay", "show the MT5 journal") scrolls into view,
  since phone panels stack below the chat.
- **1.71.2** (11 Nov 2026): "roleplay", "roleplay mode" or "show the roleplay" opens a roleplay add-on's panel straight
  away (no AI involved, so it can't be mistaken for opening an app); "close roleplay" closes it.
- **1.71.1** (11 Nov 2026): "show the …" / "close the …" opens or closes a panel only on the screen he asked from:
  asked on the phone (the roleplay panel, say), it doesn't appear on the PC, and the other way round.
- **1.71.0** (11 Nov 2026): a pin button next to each panel's close button (on the PC). A pinned panel can't be
  dragged or resized. Pinned in its side column, it stays in the column. Pinned somewhere he moved it, it keeps its
  distance from the nearest window edges (left/right/centre, top/bottom/middle), so when the window is enlarged it
  stays beside the panels around it instead of drifting across. Click the pin again to unpin.
- **1.70.7** (11 Nov 2026): security fix. Other websites open in his browser could send commands to Jarvis at
  127.0.0.1:8765 (Jarvis fully trusts requests from this PC), or reach it through a domain pointed at 127.0.0.1.
  Every request now has to come from Jarvis's own page or a program on the PC: the Host must be this PC, a
  Tailscale name or localhost, a browser's Origin must match it, and the browser must not mark it cross-site.
- **1.70.6** (11 Nov 2026): "MT5", "MetaTrader" and "open MT5" always mean the plain MetaTrader 5 app. Jarvis no longer
  asks which broker terminal (FTMO, Purple Trading, EightCap, VantageFX) to open.
- **1.70.5** (11 Nov 2026): thicker core rings (about 1.6 times as wide).
- **1.70.4** (11 Nov 2026): the core as an armillary sphere. The four inner rings are gimbals, each at its own
  inclination and turning about the vertical at its own pace, all centred on the heart; the two outer rings and the
  dial stay square to the viewer as the frame. Listening folds the gimbals flat; thinking spins them faster.
- **1.70.3** (11 Nov 2026): the rings face you (Saturn from above) and drift freely again, each in its own small
  lean and wobble, but always centred on the heart, never pushed back behind it.
- **1.70.2** (11 Nov 2026): the core's ring plane faces the viewer, like Saturn seen from above its pole, and still
  turns with the core as it sways or follows the mouse.
- **1.70.1** (11 Nov 2026): Saturn-style core. All the rings and the outer dial lie in one plane through the heart,
  tilted toward the viewer, and turn with the core as it sways or follows the mouse (flatter while listening, steeper
  while thinking). The camera sits further back, so the outer ring no longer gets cut off at the edges.
- **1.70.0** (11 Nov 2026): focus while playing. With the roleplay panel open, a D&D session on (Dungeon Master
  persona) or incognito mode, the trading autopilot keeps trading but its panel doesn't pop up, and its announcements
  (trades, break-even, limits) and other routine ones are held, then told in one go when he's done. Add-on panels
  report being open with POST /api/focus.
- **1.69.1** (11 Nov 2026): the plain MetaTrader 5, never a broker's copy. With both "MetaTrader 5" and a broker's
  own (like "EightCap MetaTrader 5") installed, opening MT5, the autopilot, trades and live data all use the plain one,
  and "stop trading" closes only that one. Start Menu shortcuts with the same name prefer the one in its own folder.
- **1.69.0** (11 Nov 2026): uses far less of the Claude plan.
  - Everyday requests (apps, weather, timers, the TV) go to Claude Haiku; trading, writing, explaining, planning,
    photos and long messages go to Sonnet; making a blueprint to Fable. Settings, Brain, "Claude model" switches to
    "Always Sonnet".
  - The brain's instructions carry only the first sentence of each tool's description (the full one is a tool_help
    call away), except the tools where the rules matter every time (money, deleting, power): about 31% shorter.
  - Local AI model choices add Liquid LFM3 1.7B: small, fast on the processor and strong at using tools.
- **1.68.1** (11 Nov 2026): custom add-on panels can call their own add-on's functions (POST /api/custom_call; only
  custom/*.py FUNCS, never the core tools). See CUSTOM.md.
- **1.68.0** (11 Nov 2026): incognito mode and REA.
  - "Go incognito": nothing is logged, learned or remembered, the chat starts fresh, and a badge shows at the top.
    "Leave incognito" (or click the badge) ends it, starts fresh again, and deletes the brains' saved copies of those
    chats (Claude Code's and Codex's session files on this PC). Restarting Jarvis ends it too.
  - Settings, Brain, "Incognito model": an Ollama model of his choosing that answers incognito chats on this PC
    (downloaded when saved). Claude and ChatGPT keep their own rules in incognito.
  - "Install REA": installs REA (Reverse Engineer Anything, morluto/rea) with npm; coding and PC jobs then get its
    tools for looking inside apps, game files (Unity, Godot), programs and databases. Needs Node.js 22.23+.
- **1.67.0** (11 Nov 2026): skills for Jarvis's background jobs (jobskills/, loaded by Claude Code with
  --plugin-dir; chat isn't affected, so it costs no extra tokens per message). Coding jobs: Ponytail (the least code
  that works, from DietrichGebert/ponytail), systematic debugging and checking before saying "done" (from
  obra/superpowers), Impeccable for front-end design (pbakaus/impeccable). PC jobs: Word, Excel, PowerPoint, PDF and
  web app testing (anthropics/skills). Each folder keeps its MIT or Apache 2.0 licence.
- **1.66.0** (11 Nov 2026): void mode. The HUD floats inside a huge empty sphere: its lines curve away on every side,
  brightest level with the core and fading to black above and below, turning a little as the mouse moves and
  drifting slowly. A light pool behind the core, dust at three distances, and panels hanging in the space with
  shadows falling away under them. Every background style sits inside the sphere. Settings, Background, Depth
  switches between "Void sphere" (default) and "Standard floor" (the 1.65 look); the choice is saved. On phones the
  sphere holds still.
- **1.65.0** (11 Nov 2026): a more 3D core and a deeper HUD (designed with Claude Fable 5.2). The core is a lit
  sphere in a turning wire shell, with banded rings at their own tilts and depths that spread apart as Jarvis talks,
  fog on their far side, and a slight lean toward the mouse. Behind it: a dot field, a perspective floor grid and a
  vignette that shift at different rates as the mouse moves. Panels float: a lit top edge, a shadow and glow under
  them, and a slow 3-pixel hover (off on phones and with reduced motion).
- **1.64.1** (11 Nov 2026): Fable only makes blueprints. Asking for a blueprint or for more detail on a part uses
  Fable; handling one that's up (enlarge, pull it apart, rotate, close, save) and everything else uses Sonnet. The
  10-minute window after a blueprint is gone.
- **1.64.0** (11 Nov 2026): blueprints think with Claude Fable 5.2. Asking for a blueprint, pulling it apart, more
  detail, and anything said within 10 minutes of the last blueprint goes to Fable; everything else stays on Sonnet.
  If his plan can't use Fable, Jarvis notes it and does blueprints on Sonnet. (Change with JARVIS_BLUEPRINT_MODEL.)
- **1.63.0** (11 Nov 2026): the autopilot opens MetaTrader 5 itself. "Make me money" opens MT5 minimised when it's
  closed and waits for it to log in; if MT5 gets closed while the autopilot runs, it opens it again. "Stop trading"
  (or the Stop button) closes MT5. Stops and targets stay on the broker's server. The autopilot stopping itself (at
  the daily loss limit, say) leaves MT5 open. Jarvis remembers where MT5 is installed each time it runs.
- **1.62.2** (11 Nov 2026): split mode on the phone. Triple-tap the core to split it into Claude (pros) and
  ChatGPT (cons), triple-tap either one to merge back with that one as the brain. The two cores fill the phone's width.
- **1.62.1** (11 Nov 2026): the phone always opens Jarvis's secure Tailscale link, where its microphone works.
  Opening the plain Tailscale address (http://...:8765) sends the phone straight to the https one, and the Pair
  phone QR code only offers the secure link.
- **1.62.0** (11 Nov 2026): phone panels stay. Panels that come up on the phone are still there the next time the
  app opens, until closed with their x. The trading autopilot's panel sits at the bottom of the phone's panels
  whenever the autopilot is running (and can stop or start it from there), and isn't there when it's off. The MT5
  journal records each trade's account number and shows only the account MT5 is logged into: log into another
  account and the journal switches to that account's trades (empty for a new one). Switching back brings the old
  ones back.
- **1.61.0** (11 Nov 2026): autopilot quiet hours. From 04:00 to 10:30 every day, and from Saturday 04:00 to
  Monday 10:30, the autopilot doesn't look at charts or ask the brains, even when it's on. Trades already open are
  still managed (break-even). Change the times in Settings, Trading, "Quiet hours" (this PC's clock).
- **1.60.2** (10 Nov 2026): faster, reliable restarts. Restarting (from the phone, the tray, an update) starts the
  new Jarvis directly, skipping Jarvis.bat's component checks, which took several seconds and could hang forever on an
  install. The new copy waits for the old one to close, then opens the port. jarvis.log shows how many seconds
  each start took. The phone keeps a copy of the page, so opening Jarvis mid-restart shows it (not a white
  screen) and it reloads as soon as Jarvis answers. Panels sent right after a restart now reach an open page.
- **1.60.1** (10 Nov 2026): the trading autopilot asks ChatGPT first on every check, and only asks Claude to
  confirm when ChatGPT sees a trade. Most checks end at "no trade", so Claude's plan limit is barely touched.
- **1.60.0** (10 Nov 2026): token usage panel, shown only when asked ("token usage", "how many tokens have I got
  left?", "how many more tasks can you do?", "what does the autopilot use?"). Every brain call (chat, jobs, the
  trading autopilot) is logged with its tokens. The panel shows each brain's tokens today, ChatGPT's 5-hour and
  weekly limits (read from Codex's own session files), Claude's limit when Claude Code reports it, DeepSeek's
  balance, about how many more messages and jobs fit, and what the autopilot uses per check, per day and as a share
  of ChatGPT's 5-hour limit.
- **1.59.3** (10 Nov 2026): a frozen Jarvis no longer blocks a new one. Opening Jarvis while another copy is
  running replaces it if that copy is an older version, its window has frozen (its page stopped checking in for 30
  seconds), or it has stopped answering but still holds Jarvis's port (it's ended: only a Jarvis, or a program
  Jarvis started, is ever ended). What happened goes in takeover.log. Before, a frozen Jarvis kept every new copy
  from starting until it was ended in Task Manager.
- **1.59.2** (10 Nov 2026): update Jarvis from your phone. The Update button works on the phone too (it used to work
  on the PC only), and you can say "update yourself" or "install the update" from either: Jarvis installs the latest
  version, restarts on the PC, and the page reloads by itself once he's back on the new version.
- **1.59.1** (10 Nov 2026): long answers no longer drop on the phone ("I have lost contact with the server"): while
  the brain thinks, Jarvis sends a small keep-alive every 10 seconds, because phones and Tailscale cut a silent
  connection after about a minute (and that also stopped the brain mid-answer). The autopilot card says what the
  brains decided in plain words ("both brains see no clear setup right now", or that they disagree) with the reason.
- **1.59.0** (10 Nov 2026): trading with the screens off. While the autopilot runs, the PC can't fall asleep (a
  sleeping PC can't trade) but the screens can turn off: "screens off", and "goodnight" turns the screens off instead
  of sleeping while it's trading. A Test trade button (on the autopilot card and in Settings > Trading, or say "test
  trade"): on a demo account it opens the smallest buy with a stop and target, closes it 5 seconds later, and shows
  each step, or what's wrong (MT5 not open, Algo Trading off, a read-only login, market closed). The autopilot now
  checks Algo Trading is on before it starts.
- **1.58.0** (10 Nov 2026): a Trading section in Settings: account size (what % limits are taken of), the size you
  want per trade (% or $ risked, or fixed lots), a daily loss limit, an equity floor, a daily profit target, max lots,
  max risk a trade, the autopilot's trades a day, minimum reward:risk and symbols. Every trade (yours through Jarvis
  and the autopilot's) is checked against them: none that could take today's loss past the limit, or equity below
  the floor if every open stop were hit (trades without a stop block it). If equity ever reaches the floor, Jarvis
  closes his own trades, stops the autopilot and tells you (your own manual trades are left alone). The autopilot
  stops for the day at the profit target or the loss limit.
- **1.57.0** (10 Nov 2026): trading on MT5. Trades you ask for ("buy 0.1 gold, stop 2310, target 2350", "move my
  stop to break-even", "close my gold trade") come up as a ticket on the HUD with the chart and the entry, stop and
  take-profit lines and the dollar risk; nothing is sent until you click Confirm (voice can't), and a stop loss is
  required. The trading autopilot ("make me money", "stop trading"): every 15 minutes it reads the M15, H1 and H4
  charts, your account, the news calendar and how you trade (from your journal), asks Claude and ChatGPT separately
  (DeepSeek stands in if one is out), and trades only when both pick the same symbol and direction, with the wider
  stop and nearer target, at least 1.5 reward to risk. Its limits: 0.5% risk a trade, a 2% daily loss limit (then it
  stops for the day), 3 trades a day, one trade open at a time, nothing within 30 minutes of high-impact news, and
  break-even at 1R. Demo accounts only, until you switch real money on (separately for your own trades and for the
  autopilot) with a click on a HUD card. Limits are changed by voice ("set my risk per trade to 1%").
- **1.56.2** (9 Nov 2026): "Test ChatGPT coding" now tests with exactly the instructions a real project job gets,
  so it catches the same problems a real job would hit.
- **1.56.1** (9 Nov 2026): ChatGPT coding jobs work. ChatGPT (Codex) reads and edits files by running shell
  commands, so the "you can't run commands" rule written for Claude's coding jobs stopped it reading anything ("No
  file-reading tool is available"). ChatGPT project jobs are now told to use the shell inside the project folder (read,
  search, edit, run the project's own tests), still nothing outside it.
- **1.56.0** (9 Nov 2026): the disk doctor ("disk doctor", "what's filling my drive?", "free up space"). In about
  half a minute Jarvis measures every drive, the biggest folders and files, and what can be cleared safely: temp files,
  crash dumps, browser, graphics shader and developer caches, Windows Update downloads, old installers in Downloads
  (to the Recycle Bin, so they can be restored), his own old pictures and the Recycle Bin. A panel shows it all with
  tick boxes and a Clear button; nothing is removed until you choose. Files in use are skipped, links are never
  followed, and your own files are never touched.
- **1.55.1** (9 Nov 2026): "Test ChatGPT coding": Jarvis checks whether ChatGPT can really do coding and PC jobs on
  this PC. He looks for an add-on in custom/ that replaces how jobs run, or a sandbox setting (on Windows, Codex's
  sandbox is what says "blocked" or "Access denied"), then has ChatGPT create a file and run a command in a scratch
  folder, and tells you exactly what's in the way.
- **1.55.0** (9 Nov 2026): fixes from a mate's maintenance notes and Jarvis's own log. When the brain you picked
  runs out of allowance (Claude's monthly spend limit), Jarvis says so and another brain answers, and he knows when
  it resets ("resets Nov 10, 12:30pm") instead of retrying it every message. Errors say what went wrong, not just
  "RuntimeError". ChatGPT no longer fails with "thread-store conflict" when two messages overlap (it starts a fresh
  conversation instead of fighting over the busy one). Background jobs that couldn't do their work (blocked,
  denied, missing access) are marked stuck instead of done, and ChatGPT project jobs are no longer told they can
  run commands while being told they can't. Jarvis.exe opened directly no longer crashes: it finds its Python by
  itself and starts Jarvis. Quieter log: no tracebacks when the HUD stops a reply or a voice clip early.
- **1.54.1** (8 Nov 2026): click any panel's title to enlarge it (the blueprint opens in 3D), click it again to shrink
  it; dragging the title still moves the panel. Fixed enlarged panels' videos not restarting.
- **1.54.0** (8 Nov 2026): the 3D blueprint has tools: Measure (click two points, get the real distance in mm), a
  Slice slider that cuts it open from the front, and Save STL / Save GLB ("export it for 3D printing"): real size in
  mm, saved to Documents\Jarvis models, ready for a slicer, Blender or Godot. The local AI hands jobs and photos to
  an online brain (it keeps the chat), and falls back to itself when offline. Talk over Jarvis to cut in, no name
  needed: he tells your voice from his own echo by loudness and by the words. Old personal values were scrubbed from
  the project's history.
- **1.53.0** (8 Nov 2026): every part wears a real photo. While researching the parts, Jarvis finds a photo of
  each one (the real board, screen, speaker...), cuts it out from its background and puts it on that part in 3D,
  sized to the part; the details card shows it too. After drawing, Jarvis is told the blueprint isn't finished until
  every part has been built in detail, and each detail step names the next part to do.
- **1.52.0** (8 Nov 2026): blueprints for anything. The model's outer shape is traced from your photo (a guitar, a
  shoe, a drill), with the photo cut to that outline and its background removed. Any part can be built from pieces
  (blocks, rounded blocks, cylinders, tubes, cones, balls, rings and wedges, up to 80 per part, sizes in mm), and
  Jarvis refines the parts one by one after the first drawing (blueprint_detail), so the HUD fills in detail as he
  goes. Up to 40 parts per blueprint. Big things are drawn as sections: double-click one and press "Open it up"
  (or say "pull the engine apart") for a new 1:1 blueprint of just that section. Send a second photo of the back and
  the back looks real too. Things with nothing online are drawn from how that kind of thing is usually built.
- **1.51.0** (8 Nov 2026): 1:1 scale blueprints. Every part needs its real size in mm, and every part must fit
  inside the object's walls. If one doesn't (a 40 mm deep battery box in a 32 mm deep Game Boy), the blueprint is sent
  back once for Jarvis to look up the real sizes and redraw. Labels show the real sizes ("Main board · 80×110×1.6 mm",
  "1:1 90×148×32 mm"). A part that's still too big is shrunk evenly, keeping its shape.
- **1.50.1** (8 Nov 2026): a closed-up 3D blueprint shows only the outside (the photo front and the back),
  like the real thing; the insides appear when you pull it apart. Every part is sized and placed to fit inside the
  object, so nothing pokes through the shell.
- **1.50.0** (8 Nov 2026): the 3D blueprint looks like the real thing. The photo you showed (straightened if it
  was held at an angle) goes on the front of the model. Part names only show when you hover over a part or select it.
  Click a part to select it, drag to move it, then drag it again to turn it. Non-round objects no longer get watch
  parts (a bezel and lugs, a 12:00 display).
- **1.49.0** (8 Nov 2026): 3D blueprint parts you can actually see. Parts are solid and lit (key and rim
  lights) instead of faint wireframe. Dials are printed (minute track, numbers, subdial scales, brand), circuit boards
  have traces, coin cells, chips, keypads and displays have markings. Tapered hands with lume, a bezel, drilled lugs, a
  knurled crown, gear hubs, balance rim screws, bracelet pins and screw slots and threads. The camera fits the parts,
  and labels are dark pills that stay readable at any zoom.
- **1.48.0** (8 Nov 2026): replica-quality blueprints. Jarvis works out the object's category and a well-documented
  equivalent with the same insides (a tie-in or fashion watch has a stock movement), researches the insides on
  that, then researches every component one by one for its real size before drawing anything. The 3D view builds
  proper parts: toothed gears with spoke windows, dials with indices and subdials, hands, domed crystals, coin
  cells, quartz crystals, stepper motors, cases with lugs, rotors, balance wheels with their hairspring, pushers,
  crowns, bracelet links, keypads, chips, speakers, displays, plates with screw holes. Research pictures must
  actually mention the object (no more film stills or crystals for "quartz").
- **1.47.3** (8 Nov 2026): blueprints no longer get "refused permission". Claude wrapped long tool arguments full of
  apostrophes in $(...) or heredocs, which Jarvis's permission rule refuses; he now always sends them in plain
  single quotes, with apostrophes written as ’ (tested against Claude Code's own permission check). Research
  pictures are product photos plus exploded-view diagrams of that kind of thing (no more Minecraft builds).
- **1.47.1** (8 Nov 2026): blueprints from a photo you send: attach one (Photo button, paste, or drag it onto the
  window, on the PC or your phone) and say "blueprint this" or "pull it apart"; no camera needed. Every screen traces
  the same photo, so a blueprint asked for on the phone draws properly on the PC too.
- **1.47.0** (8 Nov 2026): blueprints from research. After identifying what you're holding (brand and model if he can
  read them), Jarvis researches it before drawing: iFixit teardowns (the real components in the order they come
  out), web pages on its teardown, exploded view, specifications and how it works (with the measurements pulled
  out), and reference pictures, shown live in a Research panel. The blueprint is drawn from that: real sizes in mm
  (the 3D model to scale), the parts in their real order, a Dossier button with how it works and the sources.
- **1.46.2** (7 Nov 2026): panels you'd moved no longer reopen as a speck in the top-left corner (closing one saved its
  0 x 0 size as its spot); the bad saved spots are cleared, so they open normally again.
- **1.46.1** (7 Nov 2026): fixes "I can't reach my brain right now, sir. FileNotFoundError": Jarvis's instructions
  for Claude had grown past Windows' 32,767-character command-line limit, so they're now passed in a file.
- **1.46.0** (7 Nov 2026): run a simulation. "Simulate saving $50 a week for a year", "compare $50, $100 and $150 a
  week", "what if I pay $200 more a month off the car loan?": the projection plays out on the HUD like a suit
  simulation (up to 3 scenarios, a scan line, the numbers ticking up), then the results: totals, when a goal is
  reached, when a loan is paid off and the interest. The maths is exact (simulate.py); the brain only fills in the
  numbers, and can use your spending report for real ones.
- **1.45.4** (7 Nov 2026): double-click a blueprint component (in 3D, or in the pulled-apart drawing) for a details
  card: what it is, quick questions (what it does, what it's made of, how it works, what goes wrong, replacement
  cost) or ask your own; Jarvis answers in the card and out loud. "Put it back" returns a part you've moved.
- **1.45.3** (7 Nov 2026): better hearing: short commands Whisper mishears ("swap brand", "DeskV", "holo mod") snap to
  the real command, a command followed by chatter ("shrink. Yeah, you're right") just does the command, and he asks
  "did you say...?" far less often. Blueprints are more accurate: Jarvis looks the object up online (teardowns,
  parts diagrams) first, and the 3D view uses its real shape (a watch is a disc) with the parts stacked in their real
  order, pulled apart front to back.
- **1.45.2** (7 Nov 2026): resize the window from any edge or corner like a normal window: hover an edge and it lights
  up with a resize arrow, then drag. (Not while maximised, same as Windows.)
- **1.45.1** (7 Nov 2026): the blueprint in 3D. Enlarge it (or press its 3D button) and the shell and every component
  become 3D shapes: drag empty space to turn it any way, drag a part to move it, right-drag (or Shift-drag) a part
  to spin it any way, scroll to zoom, double-click to reset. "Pull it apart" and "put it back together" work in 3D.
- **1.45.0** (7 Nov 2026): blueprint mode. Hold something up to the desk camera and say "blueprint this": Jarvis works
  out what it is and draws it on blueprint paper, traced from the photo, with labelled features, a size estimate and
  a title block. "Pull it apart" flies the components typically inside it out into labelled columns around the
  outline; "put it back together" closes it up. Saying "pull it apart" first does both.
- **1.44.0** (7 Nov 2026): the hologram workshop. "Show me the model player" finds a .glb/.gltf/.obj/.stl/.fbx in your
  projects, Desktop, Documents or Downloads and shows it as a glowing wireframe hologram over a grid, with a scanning
  plane. Drag to turn, scroll to zoom, double-click to reset; with gesture control on, move your hand to turn it and
  pinch to zoom. Drop a model file on the panel to load it. "Hologram workshop" opens it empty.
- **1.43.0** (7 Nov 2026): hand-off to your phone. Walk away from the PC with Jarvis open on your phone and it picks up
  the last few exchanges and the panels from the last 15 minutes ("Picked up from your PC"); opening the phone after
  leaving does the same. While you're away, anything Jarvis would have said (reminders, a finished job) is said on
  the phone straight away instead of being held for when you're back.
- **1.42.0** (7 Nov 2026): Where I left off: Jarvis notes what you have open (every 10 minutes, when you step away,
  and before the PC sleeps). Back after 3+ hours, or the next morning, he shows it and offers "reopen them".
  "Where was I?" any time. Finish this: with a half-written email, form or message on screen, say "finish this":
  he reads the screen, drafts the missing part in your voice and shows it; "type it" types it where your cursor is
  (new lines as Shift+Enter, never presses Send).
- **1.41.0** (7 Nov 2026): the window drags like a normal Windows window. Drag the strip along the top: push the
  mouse into the top of the screen and "Release to maximise" shows (left or right edge: fill that half). Dragging a
  maximised window brings it back to its normal size under the mouse.
- **1.40.3** (7 Nov 2026): shrinking an enlarged panel you'd moved now puts it back at its own size (it used to
  remember the full-screen size); a full-window size saved by that bug is cleared.
- **1.40.2** (7 Nov 2026): desk view's object labels grow with the panel, so they're readable when it's big.
- **1.40.1** (7 Nov 2026): the desk view panel moves and resizes like the others (drag its title, corner to resize),
  and reopens where you left it.
- **1.40.0** (7 Nov 2026): two buttons above the mini core. "-" tucks it away until you next minimise Jarvis (or tray >
  Mini core). The microphone mutes Jarvis: he ignores the mic completely, even "Hey Jarvis", until you click it
  again (also tray > Mute, or type "stop listening" / "unmute"). Mute is remembered when Jarvis restarts.
- **1.39.0** (7 Nov 2026): talk to Jarvis from your phone. A Mic button (and a mic under the core in holo mode)
  records until you stop talking; the PC turns it into text with the same speech recognition as "Hey Jarvis".
  Phones only allow the microphone on secure pages, so Jarvis sets up Tailscale's secure link
  (https://<your PC>.<tailnet>.ts.net, only your own devices can open it); it's listed first in Pair phone.
- **1.38.0** (7 Nov 2026): desk camera extras. "Room scan" / "what's on my desk?" describes what the camera sees.
  Inventory mode: while desk view is open Jarvis remembers what he sees ("where did I leave my phone?").
  "Gesture control": open palm play/pause, peace sign next song, thumbs up/down volume, fist stops him talking,
  pointing up asks what you're holding. Workout spotter: "count my squats" (push-ups, curls, jumping jacks) counts
  every rep out loud; "I'm done" for the total. "Morning radio" / "Jarvis FM": your morning brief as a radio show
  with a jingle and a soft music bed. Also "volume up", "quieter", "louder".
- **1.37.0** (7 Nov 2026): holo mode on the PC ("holo mode", or Protocols > Holo mode): just the core, floating over a
  projector glow, with what he says written underneath; Escape or "exit holo mode" leaves. Settings > Voice >
  Volume (0 to 150%). "Desk view" opens your webcam in a panel with live object labels; "what am I holding?" sends
  a snapshot to the brain (with the labels, so even brains that can't see get a hint).
- **1.36.0** (7 Nov 2026): "Enlarge ..." (or expand, maximise, full screen): the panel you name fills the HUD, bigger,
  with Jarvis's core in the corner like the spending report. If nothing on screen matches, Jarvis opens it first
  ("enlarge the weather"). "Shrink", the × or Escape go back.
- **1.35.0** (7 Nov 2026): DeepSeek as a brain (Settings > Brain: paste your key from platform.deepseek.com). It
  runs through Claude Code on DeepSeek's servers, so his tools, coding and PC jobs all work, for a fraction of a cent
  a message; in automatic mode it steps in after Claude and ChatGPT. "Switch to DeepSeek" makes it the brain. Also
  Settings > Brain > Local AI model: Tiny (Qwen3 1.7B), Small, Medium or Large, downloaded when you pick it.
- **1.34.2** (7 Nov 2026): Jarvis starts in online mode every time ("offline mode" switches to the local AI). His
  voice no longer changes mid-reply when the online voice hiccups (it tries again first), and he stops remarking on
  the time unless you ask.
- **1.34.1** (7 Nov 2026): RAM mode also gets its smaller model when Jarvis starts already in RAM mode.
- **1.34.0** (7 Nov 2026): timestamps on messages, and Jarvis's replies show how long they took. The local AI is
  quicker: its instructions are a third of the length, RAM mode runs the smaller Qwen3 4B (downloaded in the
  background when you switch) with a smaller memory window, and the model is loaded and has read its instructions
  before your first question (at start-up and when you switch).
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
  - Pictures: "show me a picture of ..." pulls one from Wikipedia onto the HUD.
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
