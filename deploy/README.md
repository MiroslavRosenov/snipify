# Deployment

Pushing to `main` triggers [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml),
which SSHes into the Ubuntu server, pulls the latest commit, syncs dependencies,
and restarts the `snipify` systemd service.

This is a **one-time** server setup. After it's done, deploys are automatic.

## 1. Create a deploy user

The app directory doubles as the user's home, so the user owns everything under it.

```bash
sudo adduser --system --group --home /usr/snipify --shell /bin/bash snipify
# If /usr/snipify already exists, just fix ownership:
sudo chown -R snipify:snipify /usr/snipify
```

## 2. Install uv for the deploy user

```bash
sudo -u snipify -i
curl -LsSf https://astral.sh/uv/install.sh | sh   # installs to ~/.local/bin/uv
exit
```

## 3. Clone the repo

Clone into the home dir (it must be empty; move the cloned `.git` in if `adduser`
already populated it with skeleton files):

```bash
sudo -u snipify git clone https://github.com/<you>/url-shortener.git /usr/snipify
```

## 4. Create the `.env` file

Create `/usr/snipify/.env` (owned by `snipify`) with production values — see the
[main README](../README.md#3-configure-environment) for all keys. At minimum:

```dotenv
ENVIRONMENT=production
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/snipify
SECRET_KEY=<openssl rand -hex 32>
ALGORITHM=HS256
```

This file is git-ignored, so deploys (`git reset --hard`) never overwrite it.

## 5. Apply the database schema (once)

```bash
psql "postgresql://user:pass@localhost:5432/snipify" -f /usr/snipify/schema.sql
```

> The workflow does **not** run migrations automatically — `schema.sql` contains a
> non-idempotent `CREATE TYPE`. Apply schema changes manually when they happen.

## 6. Install the systemd service

```bash
sudo cp /usr/snipify/deploy/snipify.service /etc/systemd/system/snipify.service
sudo systemctl daemon-reload
sudo systemctl enable --now snipify
sudo systemctl status snipify
```

The app listens on `127.0.0.1:8000` (Uvicorn's default). Put nginx/Caddy in front
of it as a reverse proxy for TLS and public access.

## 7. Let the deploy user restart the service without a password

The workflow runs `sudo systemctl restart snipify`. Grant exactly that, nothing more:

```bash
echo 'snipify ALL=(root) NOPASSWD: /usr/bin/systemctl restart snipify, /usr/bin/systemctl is-active snipify' \
  | sudo tee /etc/sudoers.d/snipify
sudo chmod 440 /etc/sudoers.d/snipify
```

## 8. Add an SSH deploy key

On the server, authorize a key GitHub Actions will use:

```bash
sudo -u snipify ssh-keygen -t ed25519 -f /usr/snipify/.ssh/deploy -N ""
sudo -u snipify bash -c 'cat /usr/snipify/.ssh/deploy.pub >> /usr/snipify/.ssh/authorized_keys'
sudo -u snipify cat /usr/snipify/.ssh/deploy   # private key -> GitHub secret
```

## 9. Add GitHub repository secrets

In **Settings → Secrets and variables → Actions**, add:

| Secret            | Value                                              |
| ----------------- | -------------------------------------------------- |
| `DEPLOY_HOST`     | Server IP or hostname                              |
| `DEPLOY_USER`     | `snipify`                                           |
| `DEPLOY_SSH_KEY`  | The **private** key from step 8                    |
| `DEPLOY_PORT`     | SSH port (optional; defaults to `22` if unset)     |

That's it. Push to `main`, or run the workflow manually from the **Actions** tab.
