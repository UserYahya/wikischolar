# Deploying WikiScholar on an Azure VM (Docker + Caddy + Cloudflare)

This setup puts the whole stack on one Ubuntu VM (tested for an Azure **D2s_v5**, 2 vCPU / 8 GB):

```
Visitor ──HTTPS──▶ Cloudflare (CDN, DDoS, Turnstile) ──HTTPS──▶ Azure VM :443
                                                                  └─ Caddy ─▶ web (gunicorn) ─┬─▶ PostgreSQL 16
                                                                              worker (send_queued) ┴─▶ Redis (rate limits)
```

| File | Purpose |
|---|---|
| `docker-compose.prod.yml` | Production stack. Only Caddy publishes ports; Postgres is tuned for 8 GB |
| `deploy/Caddyfile` | TLS with the Cloudflare Origin certificate, passes the real visitor IP to the app |
| `deploy/.env.production.example` | Template for `/opt/wikischolar/.env` |
| `deploy/pg_backup.sh` | Daily `pg_dump`, then a verified upload to Amazon S3 |
| `deploy/certs/` | Origin certificate and key, on the server only (git-ignored) |

Throughout, `dc` is short for `docker compose -f docker-compose.prod.yml`, run from `/opt/wikischolar`. Add it once on the VM:
`echo "alias dc='cd /opt/wikischolar && docker compose -f docker-compose.prod.yml'" >> ~/.bashrc && source ~/.bashrc`

---

## A. Azure portal

1. **Network security group** (VM → Networking), inbound rules:
   - `22/tcp`: source **My IP address** only.
   - `80,443/tcp`: source = Cloudflare's IP ranges (paste the IPv4 list from <https://www.cloudflare.com/ips-v4>, comma-separated, into one rule).
   - Delete any rule that allows 80/443/8000/5432 from `Any`.
2. **Static public IP**: VM → Networking → the public IP → Configuration → *Static*.
3. **Budget alert**: Cost Management → Budgets → about $150/month, with an email at 80% and 100%. Exceeding the grant moves the subscription to pay-as-you-go.
4. Optional: VM → Disks → resize the OS disk to **64 GB Premium SSD** (holds the database, images and 3 days of local backups).

## B. Cloudflare (dashboard for `wikischolar.bd`)

5. **DNS**: `A  register  <VM public IP>`, **Proxied** (orange cloud).
6. **SSL/TLS → Overview**: mode **Full (strict)**.
7. **SSL/TLS → Origin Server → Create Certificate**, hostname `register.wikischolar.bd`, 15 years, PEM. Keep the *certificate* and *private key* open for step 12 (the key is shown only once).
8. **Turnstile → Add widget**: domain `register.wikischolar.bd`, Managed mode. Copy the site key and secret key into `.env` (step 12). This keeps bots from triggering OTP emails and sign-in attempts.

## C. Prepare the VM

SSH in: `ssh -i ~/.ssh/wikischolar-reg-azure.pem azureuser@<VM IP>`

9. Install OS updates and tools:
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo apt install -y unattended-upgrades git unzip curl
   sudo timedatectl set-timezone Asia/Dhaka
   # AWS CLI v2 (installs to /usr/local/bin/aws)
   curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
   unzip -q /tmp/awscliv2.zip -d /tmp && sudo /tmp/aws/install && aws --version
   ```
10. Install Docker with log rotation, so container logs can't fill the disk:
    ```bash
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker $USER
    echo '{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"3"}}' | sudo tee /etc/docker/daemon.json
    sudo systemctl restart docker
    exit   # log back in so the docker group applies
    ```
11. Get the code. The repo is private, so give the VM a **read-only deploy key**:
    ```bash
    ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N "" -C "wikischolar-vm"
    cat ~/.ssh/github_deploy.pub   # a repo admin adds this: GitHub repo → Settings → Deploy keys → Add (leave "write" unticked)
    printf 'Host github.com\n  IdentityFile ~/.ssh/github_deploy\n' >> ~/.ssh/config
    sudo mkdir -p /opt/wikischolar && sudo chown $USER: /opt/wikischolar
    git clone git@github.com:UserYahya/wikischolar.git /opt/wikischolar
    ```
12. Add the secrets and certificate:
    ```bash
    cd /opt/wikischolar
    cp deploy/.env.production.example .env && chmod 600 .env
    python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # → DJANGO_SECRET_KEY
    openssl rand -hex 32                                           # → DB_PASSWORD
    openssl rand -hex 24                                           # → NOTIFY_WEBHOOK_TOKEN
    nano .env   # fill in all "change-me" values, SMTP/Brevo, Turnstile keys, DJANGO_ALLOWED_HOSTS
    nano deploy/certs/origin.pem   # paste the Cloudflare origin certificate
    nano deploy/certs/origin.key   # paste the private key
    chmod 600 deploy/certs/*
    ```
    For `WS_CREDENTIALS_KEY`, generate it inside the container after step 13 (`dc run --rm web python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`), put it in `.env`, then run `dc up -d`. Or leave it empty and the key is derived from `DJANGO_SECRET_KEY`.

    > **Save `.env` in a password manager now.** `DJANGO_SECRET_KEY` / `WS_CREDENTIALS_KEY` decrypt the email/SMS passwords stored in the database. A database backup restored without them loses those passwords.

## D. Launch

13. Start the stack:
    ```bash
    dc up -d --build      # builds the app; migrate + seed_reference run on every start
    dc ps                 # db and redis "healthy", web/worker/caddy "Up"
    dc logs -f web        # Ctrl+C to leave
    ```
14. Run the pre-flight check: `dc exec web python manage.py check_host`. Every line should be **OK**.
15. Create the first admin: `dc exec web python manage.py create_super_admin --email you@wikimedia.org.bd --name "Your Name"` (it prompts for the password, minimum 12 characters).
16. Test the site: open <https://register.wikischolar.bd>, run a full test registration (the OTP email must arrive), then sign in at `/dashboard/`.

## E. Daily backups to Amazon S3

17. In the AWS console:
    - **S3 → Create bucket** (e.g. `wikischolar-db-backups`, region `ap-south-1`): Block *all* public access ON, default encryption SSE-S3.
    - Bucket → Management → **Lifecycle rule**: prefix `postgres/`, expire current versions after **30 days**.
    - **IAM → Users → Create user** `wikischolar-backup` (no console access) with this inline policy, then create an access key:
      ```json
      {"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:PutObject",
        "Resource":"arn:aws:s3:::wikischolar-db-backups/postgres/*"}]}
      ```
      The key can only upload, so if the VM is compromised it can't read or delete old backups.
18. On the VM:
    ```bash
    aws configure                 # the backup user's key, region ap-south-1
    sudo mkdir -p /opt/backup && sudo chown $USER: /opt/backup
    cp /opt/wikischolar/deploy/pg_backup.sh /opt/backup/ && chmod 700 /opt/backup/pg_backup.sh
    nano /opt/backup/pg_backup.sh # set S3_URI, and HC_URL (step 19)
    /opt/backup/pg_backup.sh      # must print "backup OK"; check the file appears in S3
    sudo touch /var/log/pg_backup.log && sudo chown $USER: /var/log/pg_backup.log
    (crontab -l 2>/dev/null; echo '0 3 * * * /opt/backup/pg_backup.sh >> /var/log/pg_backup.log 2>&1') | crontab -
    ```
19. **Alerting**: create a free check at <https://healthchecks.io> (period 1 day, grace 2 hours) and paste its URL into `HC_URL`. You get an email if a nightly backup fails or doesn't run.
20. **Test a restore** now, and again every quarter:
    ```bash
    F=$(ls -t /opt/backup/files/*.dump | head -1)
    dc exec -T db createdb -U wikischolar restore_test
    dc exec -T db pg_restore --no-owner -U wikischolar -d restore_test < "$F"
    dc exec -T db psql -U wikischolar -d restore_test -c "select count(*) from districts;"
    dc exec -T db dropdb -U wikischolar restore_test
    ```
    To recover production from S3: download the dump with an admin AWS account, `dc stop web worker`, restore into a fresh database, point `DB_NAME` at it (or rename the databases), then `dc up -d`.

## F. Updates and day-to-day operations

- **Deploy an update**: `cd /opt/wikischolar && git pull && dc up -d --build`. collectstatic, migrate and seed run automatically. Downtime is a few seconds.
- **Logs**: `dc logs -f web`, `dc logs -f caddy`, `dc logs worker`. Slow SQL (over 500 ms) is logged in `dc logs db`.
- **Slowest queries**:
  ```bash
  dc exec db psql -U wikischolar -d wikischolar -c "create extension if not exists pg_stat_statements;"
  dc exec db psql -U wikischolar -d wikischolar -c "select calls, round(mean_exec_time) ms, left(query,80) from pg_stat_statements order by total_exec_time desc limit 10;"
  ```
- **Monitoring**: Azure portal → VM → Alerts. Add alerts for *Percentage CPU > 80% for 10 min* and *Available Memory Bytes < 1 GB*.
- **Before launch day**, load-test with [k6](https://k6.io) against `/` and `/api/reference/…`. The app rate-limits per IP (e.g. 300 API calls / 5 min), so a test from one machine gets throttled. Raise `RATE_LIMITS` temporarily on a staging copy, or test the uncached pages only.
- **If the server is too slow**: resize the VM to D4s_v5 (Azure portal → Size, about 2 minutes downtime), then raise gunicorn `--workers` to 5 and Postgres `shared_buffers`/`effective_cache_size` to 4GB/10GB in `docker-compose.prod.yml`.
- **Cloudflare IP list changes** (rare): update the NSG rule and `trusted_proxies` in `deploy/Caddyfile`, then `dc restart caddy`.

## Verification checklist

- [ ] `check_host` prints only OK.
- [ ] `curl -sI https://register.wikischolar.bd` shows `200`, `strict-transport-security` and `cf-ray`.
- [ ] From your own computer, `curl -m 5 http://<VM IP>:8000` and `curl -m 5 -k https://<VM IP>` both fail (the VM accepts only Cloudflare).
- [ ] Dashboard → Audit log shows **your** public IP for your sign-in (not a 172.x Docker or Cloudflare address).
- [ ] Page source references hashed static files (`public.<hash>.css`).
- [ ] A backup file is in S3, the healthchecks.io check is green, and the restore test worked.
- [ ] `.env` is saved in a password manager.
