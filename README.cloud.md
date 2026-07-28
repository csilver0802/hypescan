
## Browser-based Cloud Deployment (GitHub Codespaces & Replit)

This project can be run in browser-based cloud IDEs. Codespaces is the recommended path (supports Docker Compose). Replit is possible but will run the Python app directly without Docker.

### GitHub Codespaces (recommended)

Steps (no local setup needed):
1. Push your branch to GitHub (already done).
2. Open the repository page in GitHub and click the green "Code" button -> "Open with Codespaces" -> "New codespace".
3. Codespaces will create a container from `.devcontainer/devcontainer.json`. The devcontainer is configured to run `docker compose up --build -d` automatically on start and forward port 8000.
4. After Codespace starts, wait for the app to build and the health server to report:
   - Use the Codespaces Ports tab; Codespaces will expose port 8000 and provide a public HTTPS URL you can open from your phone. The forwarded port link is clickable in the Codespaces UI ("Open in Browser").

Exact command run inside Codespace (automated by devcontainer):
- docker compose up --build -d

Open these URLs (replace with Codespaces forwarded URL):
- https://<codespace-host>/health
- https://<codespace-host>/metrics

Notes:
- Codespaces exposes forwarded ports over an HTTPS public link (only while the Codespace is running). This provides the clickable live URL for your Android phone.
- The devcontainer includes the Docker-in-Docker feature so Docker Compose should work. Build can take a few minutes.

### Replit (alternative quick option)

Replit does not reliably support Docker Compose. A simple way to run the app in Replit is to run the Python process directly.

Steps:
1. Create a new Replit and import this GitHub repository (Import from GitHub).
2. Ensure `.replit` and `start-replit.sh` exist (they are added in this branch).
3. Start the Replit; it runs `start-replit.sh` which installs requirements and runs `python main_runner.py`.
4. Replit will provide a public URL for the running web process; open `/health` and `/metrics` paths on that URL.

Caveats:
- Replit may have outbound network restrictions and process limits; long-lived fetchers may be throttled.
- Replit runs the process directly (no Docker). Use Codespaces for a Docker-accurate environment.

### Ports
- Health & Metrics port: 8000 (METRICS_PORT). The Codespaces or Replit UI will show and forward this port to an HTTPS URL.

### Troubleshooting & Tips
- If Codespaces fails to start Docker Compose automatically, open the Codespace terminal and run:
  docker compose up --build -d
- Use the Codespaces Ports view to find the public URL. Click "Open in Browser" to open the forwarded port.
- If the health endpoint returns errors, check logs:
  docker compose logs -f app

