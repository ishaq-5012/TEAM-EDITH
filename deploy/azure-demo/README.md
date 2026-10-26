# SIH evaluator cloud demo: two HTTPS links on one Azure for Students VM

This stack runs the existing VerifyFlow and institution portal with the current evaluator data. It is a **time-limited SIH demonstration**, not the production stack in `docs/DEPLOYMENT.md`: VerifyFlow uses SQLite and inline processing so it fits a small student VM and preserves the synthetic registry connector. Put only fictional evaluator documents on this host. The VM must stay running, but the developer laptop can be off.

## What the two links will be

Choose two free DuckDNS names and point both at the VM's public IP:

- `https://<verifyflow-name>.duckdns.org` — VerifyFlow (SPA and `/api` on the same origin)
- `https://<portal-name>.duckdns.org` — institutional portal

Caddy obtains and renews the HTTPS certificates. No ports other than 22 (SSH), 80 and 443 need to be public. The API and portal only listen on the internal Docker network.

## 1. Azure Portal buttons

1. Azure top search: **Virtual machines** → **Virtual machines** → **Create** → **Azure virtual machine**.
2. **Basics**: subscription **Azure for Students**; **Resource group → Create new** `sih-demo-rg`; VM name `sih-demo`; choose a nearby region with an available 4 GiB or larger Linux VM; image **Ubuntu Server 24.04 LTS**; architecture **x64** for the least image compatibility risk. The student offer's free 1 GiB sizes are too small for this full stack. A 4 GiB choice uses the student credit: inspect Azure's estimate before creating it.
3. **Administrator account**: **SSH public key → Generate new key pair**. Keep the downloaded private key on your computer; never upload or share it.
4. **Inbound ports**: SSH (22), HTTP (80), HTTPS (443). Limit SSH source to your IP after creation in the network security group.
5. **Disks**: standard SSD; don't add optional paid disks. **Networking**: keep a public IPv4 address; choose static allocation if offered, because the two domain records need a stable IP.
6. **Review + create**: confirm subscription, size, disk, networking and estimated credit use. **Create**. Note the VM's **Public IP address** from its Overview page.

The offer has $100 credit and can stop when the credit is consumed or the offer expires. VM, OS disk, public IP and traffic can use credit. Check **Education → Overview → Available credits** periodically.

## 2. Two domain names

At `https://www.duckdns.org/`, sign in, type a unique subdomain in **sub domain**, click **add domain**, and set the **current ip** to the Azure VM public IP. Repeat for the other name. Give DNS a few minutes to update. Both names must resolve to the same VM IP before Caddy can obtain HTTPS certificates.

## 3. Install Docker and clone the source on the VM

From Windows PowerShell on your computer (substitute the downloaded key path and VM IP):

```powershell
ssh -i C:\path\to\sih-demo_key.pem azureuser@<VM_PUBLIC_IP>
```

On the VM, install Docker Engine and the Compose plugin using Docker's [official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/). Then:

```bash
sudo docker compose version
git clone https://github.com/ishaq-5012/TEAM-EDITH.git
cd TEAM-EDITH
```

If the GitHub repository is private, authenticate Git first. Only clone the repository you control.

## 4. Prepare and transfer the private configuration and data

On your **Windows laptop**, in a PowerShell window opened in `E:\sih 2`, run:

```powershell
& .\deploy\azure-demo\prepare-env.ps1 -VerifyFlowDomain '<verifyflow-name>.duckdns.org' -PortalDomain '<portal-name>.duckdns.org'
py -3.11 .\deploy\azure-demo\export_demo.py
```

`prepare-env.ps1` reads the current local intake secret, portal secret, and optional AI provider settings. It writes one private `deploy/azure-demo/.env` with the selected HTTPS origin. `export_demo.py` uses SQLite's backup API and packages the databases, uploads, trust roots and evaluator quick-fill accounts. Neither output is tracked by Git. Pause new local uploads while exporting so copied files and the database snapshot describe the same state.

Then, still on your laptop, transfer these two files over SSH (replace key and IP):

```powershell
scp -i C:\path\to\sih-demo_key.pem .\deploy\azure-demo\.env azureuser@<VM_PUBLIC_IP>:~/TEAM-EDITH/deploy/azure-demo/.env
scp -i C:\path\to\sih-demo_key.pem .\deploy\azure-demo\demo-data.tar.gz azureuser@<VM_PUBLIC_IP>:~/TEAM-EDITH/demo-data.tar.gz
```

Do not paste the contents of `.env`, the archive, or your private key in chat or GitHub.

## 5. Start both apps

On the VM, from `~/TEAM-EDITH`:

```bash
tar -xzf demo-data.tar.gz
rm demo-data.tar.gz
sudo chown -R 10001:10001 backend/var
chmod 600 deploy/azure-demo/.env
sudo docker compose -f deploy/azure-demo/compose.yml --env-file deploy/azure-demo/.env up -d --build
sudo docker compose -f deploy/azure-demo/compose.yml --env-file deploy/azure-demo/.env ps
```

Wait for `migrate` to complete and `api`, `portal`, `web` to show running. Caddy needs both DNS records and inbound 80/443 before it can issue certificates. The first Docker build can take several minutes.

## 6. Verify the two links

On a different network or in a private browser window:

1. Open `https://<verifyflow-name>.duckdns.org/login`. Check **Admin**, **Reviewer**, **Compliance Manager**, **Auditor** auto-fill buttons, then sign in with a demo role.
2. Open `https://<portal-name>.duckdns.org/login`. Check institution quick-fill, sign in, open an application and upload/submit a document.
3. Confirm the submission appears in VerifyFlow, then exercise reviewer → compliance manager → auditor flow.
4. On the VM, check `curl -fsS https://<verifyflow-name>.duckdns.org/api/v1/health/ready` and `curl -fsS https://<portal-name>.duckdns.org/health`.

If a link fails, inspect `sudo docker compose -f deploy/azure-demo/compose.yml --env-file deploy/azure-demo/.env logs --tail=100 web api portal`. Logs are diagnostic data; do not post secrets or document contents.

## Known limits

- This deploy package has not yet been built on an Azure VM. Run the two browser checks above before sharing either link with evaluators.
- SQLite on a single VM is suitable for a small SIH demo; use the PostgreSQL production stack in `docs/DEPLOYMENT.md` for a real multiuser service.
- Local data changes made after `export_demo.py` are not automatically copied to the VM. After cutover, upload through the public portal.
- Keep a backup of **both** `backend/var` and `mock-aicte-portal/var` on the VM. The GitHub repository does not contain the databases, documents or evaluator passwords.
