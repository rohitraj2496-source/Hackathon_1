# Putting Haq on the internet (AWS EC2)

This guide puts Haq on your AWS server so anyone can open it at
**https://44-197-229-105.sslip.io**. Follow the steps in order. You copy commands from the grey boxes and
paste them into the terminal.

- Server: Ubuntu 24.04, t3.small, public IP **44.197.229.105**
- Web address: **44-197-229-105.sslip.io**. sslip.io is a free name that points to that IP, so no domain
  purchase is needed. HTTPS comes free from Let's Encrypt. The microphone only works over HTTPS.

## What visitors get

- **DEMO mode (the default).** Anyone can watch real Haq runs that were recorded earlier. They are replayed
  step by step and labelled "Demo: recorded real run". This costs nothing.
- **LIVE mode.** Checking a new family needs the passcode you set below. Live checks have two limits:
  - **A daily spending limit** (default $1.00 a day). When it runs out, visitors see a friendly message in
    Hindi or English and are sent to the recorded demos.
  - **A limit per visitor** of 2 live checks per hour.
- API keys, internal traces and error details are never sent to the browser.

---

## Before you start: open the web ports in AWS (one time)

In the AWS console go to **EC2 → Instances →** your instance **→ Security → Security groups → Edit inbound
rules**. Make sure these three rules exist:

| Type | Port | Source |
|---|---|---|
| SSH | 22 | My IP |
| HTTP | 80 | Anywhere (0.0.0.0/0) |
| HTTPS | 443 | Anywhere (0.0.0.0/0) |

Port 80 is needed even though the site uses HTTPS: Let's Encrypt uses it to issue the certificate.

## 1. Connect to the server

On your Mac, open **Terminal** and run:

```bash
ssh -i ~/.ssh/haq-rsquare-key.pem ubuntu@44.197.229.105
```

- If it asks "Are you sure you want to continue connecting?", type `yes`.
- If it says the key's permissions are "too open", run `chmod 400 ~/.ssh/haq-rsquare-key.pem` once, then try
  again.

You are connected when the prompt shows something like `ubuntu@ip-…:~$`. **Every command after this runs on
the server.**

## 2. Download the code

```bash
git clone https://github.com/rohitraj2496-source/Hackathon_1.git
cd Hackathon_1
```

## 3. Create the secrets file (`.env`)

The secrets live only on the server, in a file called `.env`. **Never commit `.env` to git, and never paste
it anywhere public.** It is already listed in `.gitignore`, so `git` will not pick it up.

```bash
nano .env
```

Type these four lines, using your own values:

```
ANTHROPIC_API_KEY=sk-ant-...your key...
NEATLOGS_API_KEY=...your neatlogs key...
HAQ_LIVE_PASSCODE=pick-a-passcode-only-you-share
HAQ_DAILY_BUDGET_USD=1.00
```

- To save: press **Ctrl+O**, then **Enter**. To close the editor: press **Ctrl+X**.
- `HAQ_LIVE_PASSCODE`: anyone who wants a live check types this into the website. Choose something hard to
  guess. Visitors get 5 tries per 15 minutes.
- `HAQ_DAILY_BUDGET_USD`: the most the Claude API may spend per day (India date). A live check costs about
  $0.11–0.46.
- Without a `.env`, the site still works in **demo-only** mode.

## 4. Install everything (one command)

```bash
./deploy/setup.sh 44-197-229-105.sslip.io
```

This takes a few minutes. It:

1. installs Python 3.12
2. creates the app's own Python environment and installs its libraries
3. sets Haq up as a background service that starts by itself after a crash or a reboot
4. installs **Caddy**, which gets the HTTPS certificate and forwards visitors to the app

You can run it again at any time: it only changes what is missing.

When it finishes, open **https://44-197-229-105.sslip.io** in Chrome. The very first visit can take about 30
seconds while the certificate is issued.

## 5. Check that it is running

| What you want | Command |
|---|---|
| Is the app running? | `sudo systemctl status haq` (look for **active (running)**; press `q` to leave) |
| The app's recent log lines | `sudo journalctl -u haq -n 50 --no-pager` |
| Watch the log live | `sudo journalctl -u haq -f` (press **Ctrl+C** to stop) |
| Is HTTPS / Caddy running? | `sudo systemctl status caddy` |
| Quick health check | `curl https://44-197-229-105.sslip.io/health` should print `{"status":"ok"}` |
| Restart the app (e.g. after editing `.env`) | `sudo systemctl restart haq` |

## 6. Update the site after you push new code

After you `git push` changes to GitHub, connect to the server (step 1) and run:

```bash
cd ~/Hackathon_1
./deploy/update.sh
```

It downloads the new code, reinstalls libraries only if `requirements.txt` changed, and restarts the app.

---

## ⚠️ Important: do not *stop* the instance before Oct 16

This server's public IP (**44.197.229.105**) is not reserved. If you **stop** the instance in the AWS console
(or with `shutdown`), AWS gives it a **different IP** when it starts again. The web address
`44-197-229-105.sslip.io` would then point nowhere, and the site would be down.

- **Rebooting is fine.** A reboot keeps the IP, and Haq and Caddy start again by themselves.
- If you ever must stop it, attach an **Elastic IP** first, or redo steps 4–6 with the new address (the
  domain becomes `<new-ip-with-dashes>.sslip.io`).

## If something goes wrong

- **The page does not load at all.** Check that ports 80 and 443 are open (see "Before you start"), then run
  `sudo systemctl status caddy`.
- **"Certificate" errors in the browser.** Wait a minute and refresh. Caddy retries automatically. Its log:
  `sudo journalctl -u caddy -n 50 --no-pager`.
- **The page loads but live checks say they are switched off.** `.env` is missing the API key or the
  passcode. Fix `.env`, then run `sudo systemctl restart haq`.
- **Live checks say "used up for today".** The daily limit was reached. It resets at midnight India time. To
  change it, edit `HAQ_DAILY_BUDGET_USD` in `.env` and restart the app.

## What is on the server

| Path | What it is |
|---|---|
| `~/Hackathon_1` | the code (a clone of the public repo) |
| `~/Hackathon_1/.env` | your secrets (owner-only permissions; never committed) |
| `~/Hackathon_1/data/` | families checked live, the cache, and the daily spend counter |
| `/etc/systemd/system/haq.service` | the background service (port 8000, local only) |
| `/etc/caddy/Caddyfile` | the HTTPS settings for the domain |
