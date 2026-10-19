# Editing and rebuilding Mercurial Server

## Requirements

- macOS or another Unix-like system
- Python 3.9 or newer
- `curl` and `tar`
- Internet access on the first build; later builds reuse `build/cache/`

Run commands from the repository root.

## Where to make changes

| Area | Files |
| --- | --- |
| Native DSM window | `src/ui/MercurialServer28.js`, `src/ui/style.css` |
| DSM and package icons | `src/ui/images/` |
| Crisp 18px field icons | `tools/make_field_icons.py` |
| Standalone web interface | `src/www/index.html`, `src/www/app.js`, `src/www/styles.css` |
| Server, API, authentication, and repository logic | `src/mercurial_server/server.py` |
| DSM package metadata | `package/INFO` |
| Install and service lifecycle | `package/scripts/` |
| DSM nginx integration | `src/nginx/`, `package/conf/` |
| Tests | `tests/test_server.py` |

Do not edit files under `build/`; that directory is regenerated.

The DSM application icon uses the checked-in files named
`src/ui/images/mercurialserver-neon-{size}.png`. Required sizes are 16, 24, 32, 48,
64, 72, and 256 pixels. The editable high-resolution source is
`src/ui/images/mercurialserver-neon-master.png`. The 64px and 256px files also
become the package icons.
Regenerate the 18px copy and folder controls after editing their pixel drawings with:

```sh
python3 tools/make_field_icons.py src/ui/images
```

## Check changes

Run the automated tests:

```sh
make test
```

To select a specific Python interpreter:

```sh
make test PYTHON=/usr/bin/python3
```

After changing the native UI JavaScript, also run:

```sh
node --check src/ui/MercurialServer28.js
```

## Preview the native UI

DSM provides proprietary `SYNO.SDS` base classes around Ext JS. The local
preview supplies only those small base-class shims and mock API data, then runs
the real application source against the official Ext JS 3.4.1.1 renderer:

```sh
make preview
```

It opens `http://127.0.0.1:4173/ext/`. Ext generates the actual application
window, tabs, forms, grids, toolbars, selection states, masks, and dialogs from
`src/ui/MercurialServer28.js`. Edit either `src/ui/style.css` or the local-only
`preview/ext/overrides.css`; style changes appear without a refresh. Move rules
from the override file into `src/ui/style.css` when they are ready.

For the exact Synology base-theme rendering, deploy the package to a NAS:

```sh
./deploy.sh DSM_ADMIN@NAS_ADDRESS
```

Open Mercurial Server from the DSM desktop after installation. When a UI
revision changes, rebuilding increments the package build automatically; this
prevents DSM from reusing cached package assets.

## Rebuild the package

```sh
./build.sh
```

The completed package is written to:

```text
build/mercurialserver-1.0.0-<build>-noarch.spk
```

The build verifies the pinned Mercurial source archive, assembles the payload,
copies the UI icons, and creates the SPK. To force a completely fresh build:

```sh
make clean
./build.sh
```

## Install on DSM

For a manual install, open **Package Center**, choose **Manual Install**, and
select the generated `.spk` file.

To build, upload, install, and verify over SSH in one command:

```sh
./deploy.sh DSM_ADMIN@NAS_ADDRESS
```

DSM may prompt for the administrator password. The target NAS needs Python 3.9
or newer installed from Package Center.

## Changing the version

Each successful `./build.sh` run increments the numeric suffix in
`package/INFO`, applies it to the packaged backend and UI, and includes it in
the SPK filename. Failed builds leave the stored build number unchanged.

To change the semantic version, edit the version in `package/INFO` while
retaining a numeric suffix, such as `1.1.0-29`. The next build will use
`1.1.0-30`.
