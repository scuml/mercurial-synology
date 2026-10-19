# Mercurial Server for Synology DSM

A `noarch` DSM 7.2+ package that hosts Mercurial repositories and gives you a small
native DSM application window for day-to-day administration. It supports Intel and ARM Synology
models because Mercurial runs in its portable pure-Python mode.

The interface provides:

- first-run administrator setup;
- username/password management with PBKDF2-SHA256 password hashing;
- Start and Stop controls for repository traffic;
- repository discovery and one-click repository creation;
- a NAS folder picker for the repository storage path; and
- authenticated HTTPS clone, pull, and push access below `/hg/` using DSM's
  certificate and integrated web server.

## Build

Requirements on the build computer are `curl`, `tar`, and Python 3.9 or newer.
Run:

```sh
./build.sh
```

The finished package is written to:

```text
build/mercurialserver-1.0.0-<build>-noarch.spk
```

The build downloads the pinned Mercurial 7.2.4 source release, verifies its
SHA-256 checksum, includes that source in the package, and does not need the
Synology cross-compilation toolkit. A cached download in `build/cache` is reused.
Each successful build increments the numeric build suffix in `package/INFO` and
keeps the packaged backend and UI version metadata synchronized.

You can also run `make package`, `make test`, or `make clean`.

## Deploy over SSH

Enable SSH in **Control Panel → Terminal & SNMP**, then run this from the build
computer using a DSM administrator account:

```sh
./deploy.sh DSM_ADMIN@192.168.1.8
```

The command builds the package, uploads it over DSM-compatible legacy SCP to a
temporary location, installs or upgrades it with `synopkg`, starts it, checks
package status, and checks the integrated HTTPS address. SSH and `sudo` prompt normally
when passwordless keys are not configured. With no target argument it asks for
the DSM administrator username and connects to `192.168.1.8`. The default SSH
port is 22 and the default DSM HTTPS port is 5001. Override the address or
nonstandard ports like this:

```sh
DEPLOY_NAS=192.168.1.20 DEPLOY_SSH_PORT=2222 DEPLOY_HTTPS_PORT=5443 ./deploy.sh
```

The equivalent Make target is `make deploy TARGET=alice@192.168.1.8`.

For a concise source map and manual edit, test, version, rebuild, and install
workflow, see [docs/README.md](docs/README.md).

## Install and set up

1. Install Synology's **Python 3.12** package from Package Center. Python 3.9,
   3.10, or 3.11 also works when 3.12 is unavailable.
2. In Package Center, choose **Manual Install** and select the generated `.spk`.
3. Start **Mercurial Server**, then open **Mercurial Server** from DSM's main
   menu. It opens as a draggable native DSM window like Synology Git Server;
   it does not launch a URL window.
4. The native app uses the signed-in DSM administrator automatically; it does
   not have a separate Mercurial Server login.
5. Add Mercurial users for clone, pull, and push access, then create repositories.

The initial storage location is Synology's persistent package data directory,
normally `/volumeN/@appdata/mercurialserver/repositories`. Package upgrades do
not remove it.

To use a shared folder such as `/volume1/hg`, grant the internal system user
`mercurialserver` read/write permission in **Control Panel → Shared Folder →
Edit → Permissions → System internal user**. Then click the folder icon beside
**Repository path**, browse to the shared folder, and choose it. The selection
is saved immediately. Existing repositories are recognized by their `.hg` folder.

## Clone and push

Every server user may read and write repositories. For example:

```sh
hg clone https://NAS_ADDRESS:5001/hg/team/project
```

Mercurial prompts for the username and password. For unattended use, configure
Mercurial's `[auth]` section instead of placing passwords directly in URLs. For
example, in the client's user-level `hgrc`:

```ini
[auth]
nas.prefix = https://NAS_ADDRESS:5001/hg/
nas.username = alice
nas.password = use-a-secret-store-when-available
```

## HTTPS and network security

DSM 7.2's package `web-config` resource installs `/hg/` into DSM's built-in
nginx server automatically. TLS and certificate renewal are managed by DSM, so
the certificate assigned to DSM in **Control Panel → Security → Certificate**
is also used for Mercurial. The default clone address is
`https://NAS_ADDRESS:5001/hg/`; a saved public address can override the displayed
clone command when DSM uses a custom HTTPS port or external hostname.

Plain HTTP repository requests are rejected. Expose DSM's HTTPS port, not port
8090.

DSM 7.2 build 64570 or newer is required for this integrated HTTPS mode.

Both the authenticated gateway on `127.0.0.1:8090` and Mercurial backend on
`127.0.0.1:8091` are loopback-only. Remote repository traffic reaches them only
through DSM HTTPS.

Administration uses native DSM controls on the DSM desktop; the internal port
8090 is no longer reachable from the NAS network.

## Persistent files and logs

DSM provides the package's persistent `var` directory. It contains:

- `settings.json` — configuration and salted password hashes (mode `0600`);
- `repositories/` — default repository storage;
- `manager.log` and `manager-console.log` — manager logs;
- `mercurial.log` — Mercurial backend output; and
- generated PID and hgweb configuration files.

Stopping the package in Package Center stops both the admin interface and the
Mercurial backend. The Start/Stop buttons in the interface affect only repository
traffic, leaving administration available.

## Development tests

Preview the native DSM/Ext interface locally with:

```sh
make preview
```

This opens `http://127.0.0.1:4173/ext/`. It runs the real
`src/ui/MercurialServer28.js` with the official Ext JS 3.4.1.1 GPL runtime, a
thin shim for Synology's base window and button classes, and an in-memory mock
of `api.cgi`. Ext itself generates the window, tabs, forms, grids, toolbars,
selection states, masks, and dialogs. Put experiments in
`preview/ext/overrides.css`; it and the real `src/ui/style.css` update in the
browser without refreshing. Move finished overrides into `src/ui/style.css`.

The separate standalone web interface is available with `make preview-web`;
its local overrides live in `preview/overrides.css`.

Run the automated tests with:

```sh
/path/to/python3 -m unittest discover -s tests -v
```

An end-to-end smoke test can be performed by building the package and launching
`src/mercurial_server/server.py` against the bundled `hg` source in
`build/work/payload/vendor/mercurial`.
