/* Mercurial Server r28 — native DSM application window (Ext JS / SYNO.SDS). */
Ext.namespace("SYNO.SDS.MercurialServer");

SYNO.SDS.MercurialServer.API = "/webman/3rdparty/mercurialserver/api.cgi";

SYNO.SDS.MercurialServer.Instance = Ext.extend(SYNO.SDS.AppInstance, {
    appWindowName: "SYNO.SDS.MercurialServer.Main"
});

SYNO.SDS.MercurialServer.Main = Ext.extend(SYNO.SDS.AppWindow, {
    constructor: function (config) {
        config = config || {};
        this.csrf = "";
        this.sessionToken = "";

        this.statusPanel = new Ext.Panel({
            border: false,
            height: 48,
            bodyStyle: "padding:8px 4px;background:transparent;",
            html: this._statusMarkup("waiting", "Checking server status...")
        });
        var self = this;
        this.storagePath = new Ext.form.TriggerField({
            fieldLabel: "Repository path",
            anchor: "100%",
            editable: false,
            triggerClass: "hg-folder-trigger",
            onTriggerClick: function () { self._chooseStorageFolder(); },
            listeners: {render: function (field) { field.trigger.dom.title = "Choose a repository folder"; }},
            value: "/var/packages/mercurialserver/var/repositories"
        });
        this.storageState = new Ext.form.DisplayField({fieldLabel: "Access", value: ""});
        this.pythonRuntime = new Ext.form.DisplayField({fieldLabel: "Python runtime", value: "Detecting..."});
        this.httpsState = new Ext.form.DisplayField({fieldLabel: "HTTPS", value: "Checking DSM HTTPS..."});
        this.httpsUrl = new Ext.form.TriggerField({
            fieldLabel: "Public address",
            anchor: "100%",
            editable: false,
            triggerClass: "hg-copy-trigger",
            onTriggerClick: function () { self._copyText(this.getValue(), "public address"); },
            listeners: {render: function (field) { field.trigger.dom.title = "Copy public address"; }},
            emptyText: "https://nas.example.com:5001/hg/"
        });
        this.cloneCommand = new Ext.form.TriggerField({
            fieldLabel: "Clone command",
            editable: false,
            anchor: "100%",
            triggerClass: "hg-copy-trigger",
            onTriggerClick: function () { self._copyText(this.getValue(), "clone command"); },
            listeners: {render: function (field) { field.trigger.dom.title = "Copy clone command"; }}
        });
        this.versionPanel = new Ext.Panel({
            border: false,
            height: 24,
            bodyStyle: "padding:6px 2px 0;text-align:right;background:transparent;color:#7b8794;font-size:11px;",
            html: "Version 1.0.0 &middot; Build 31"
        });
        this.startButton = new SYNO.ux.Button({text: "Start", btnStyle: "blue", scope: this, handler: this._start});
        this.stopButton = new SYNO.ux.Button({text: "Stop", scope: this, handler: this._stop});

        var dateSort = function (value) {
            var parsed = new Date(value);
            return isNaN(parsed.getTime()) ? 0 : parsed.getTime();
        };
        this.repoStore = new Ext.data.JsonStore({
            fields: [
                {name: "name", sortType: Ext.data.SortTypes.asUCString},
                {name: "size_bytes", type: "int"},
                {name: "modified_at", sortType: dateSort}
            ],
            data: [],
            sortInfo: {field: "name", direction: "ASC"}
        });
        this.userStore = new Ext.data.JsonStore({
            fields: [
                {name: "username", sortType: Ext.data.SortTypes.asUCString},
                {name: "admin", type: "boolean"},
                {name: "created_at", sortType: dateSort}
            ],
            data: [],
            sortInfo: {field: "username", direction: "ASC"}
        });

        this.repoGrid = new Ext.grid.GridPanel({
            cls: "hg-grid",
            border: true,
            stripeRows: true,
            loadMask: true,
            store: this.repoStore,
            columns: [
                {header: "Repository", dataIndex: "name", sortable: true, width: 300},
                {header: "Size", dataIndex: "size_bytes", sortable: true, renderer: this._bytes, align: "right", width: 100},
                {header: "Last changed", dataIndex: "modified_at", sortable: true, renderer: this._date, width: 190}
            ],
            viewConfig: {
                forceFit: true,
                deferEmptyText: false,
                emptyText: '<div class="hg-empty-state"><div class="hg-empty-title">No repositories yet</div><div>Create a repository above, or place an existing Mercurial repository in the storage folder.</div></div>'
            },
            tbar: [
                new SYNO.ux.Button({text: "Create repository", cls: "hg-toolbar-button hg-toolbar-button-primary", iconCls: "hg-icon hg-icon-repository-add", btnStyle: "blue", scope: this, handler: this._createRepository}),
                new SYNO.ux.Button({text: "Refresh", cls: "hg-toolbar-button", iconCls: "hg-icon hg-icon-refresh", scope: this, handler: this._refresh})
            ]
        });

        this.userGrid = new Ext.grid.GridPanel({
            cls: "hg-grid",
            border: true,
            stripeRows: true,
            loadMask: true,
            store: this.userStore,
            columns: [
                {header: "Username", dataIndex: "username", sortable: true, width: 250},
                {header: "Administrator", dataIndex: "admin", sortable: true, renderer: function (v) { return v ? "Yes" : "No"; }, width: 130},
                {header: "Added", dataIndex: "created_at", sortable: true, renderer: this._date, width: 180}
            ],
            viewConfig: {
                forceFit: true,
                deferEmptyText: false,
                emptyText: '<div class="hg-empty-state"><div class="hg-empty-title">No server users yet</div><div>Add a user to grant authenticated clone, pull, and push access.</div></div>'
            },
            tbar: [
                new SYNO.ux.Button({text: "Add user", cls: "hg-toolbar-button hg-toolbar-button-primary", iconCls: "hg-icon hg-icon-user-add", btnStyle: "blue", scope: this, handler: this._addUser}),
                new SYNO.ux.Button({text: "Change password", cls: "hg-toolbar-button", iconCls: "hg-icon hg-icon-password", scope: this, handler: this._changePassword}),
                new SYNO.ux.Button({text: "Delete", cls: "hg-toolbar-button hg-toolbar-button-danger", iconCls: "hg-icon hg-icon-delete", scope: this, handler: this._deleteUser})
            ]
        });

        this.overview = new Ext.form.FormPanel({
            title: "Overview",
            cls: "hg-overview",
            border: false,
            autoScroll: true,
            labelWidth: 120,
            bodyStyle: "padding:24px; padding-bottom: 8px;",
            items: [
                {xtype: "fieldset", title: "Mercurial service", autoHeight: true, items: [
                    this.statusPanel,
                    this.pythonRuntime,
                    {xtype: "panel", border: false, bodyStyle: "padding-top:10px;", items: [this.startButton, this.stopButton]}
                ]},
                {xtype: "fieldset", title: "Repository storage", autoHeight: true, items: [
                    this.storagePath,
                    this.storageState
                ]},
                {xtype: "fieldset", title: "Secure client access", autoHeight: true, items: [
                    this.httpsState,
                    this.httpsUrl,
                    this.cloneCommand
                ]},
                // this.versionPanel
            ]
        });

        Ext.apply(config, {
            iconCls: "hg-window-icon",
            width: 820,
            height: 680,
            minWidth: 620,
            minHeight: 450,
            maximizable: true,
            minimizable: true,
            resizable: true,
            layout: "fit",
            items: [{
                xtype: "tabpanel",
                cls: "hg-tabs",
                activeTab: 0,
                border: false,
                items: [
                    this.overview,
                    {title: "Repositories", layout: "fit", bodyStyle: "padding:10px;background:#f4f6f8;", items: [this.repoGrid]},
                    {title: "Users", layout: "fit", bodyStyle: "padding:10px;background:#f4f6f8;", items: [this.userGrid]}
                ]
            }],
            buttons: [
                {text: "Refresh", scope: this, handler: this._refresh},
                "->",
                {text: "Close", scope: this, handler: function () { this.close(); }}
            ],
            listeners: {afterrender: {fn: this._bootstrap, scope: this, single: true}}
        });
        SYNO.SDS.MercurialServer.Main.superclass.constructor.call(this, config);
    },

    _statusMarkup: function (state, text) {
        var colors = {running: "#20a05a", stopped: "#d83b3b", error: "#d83b3b", waiting: "#9aa4af"};
        var color = colors[state] || colors.waiting;
        return '<div class="hg-status-line">' +
            '<span class="hg-status-light hg-status-' + state + '" style="display:inline-block;width:16px;height:16px;border-radius:50%;vertical-align:middle;margin-right:12px;background:' + color + ';box-shadow:0 0 0 4px ' + color + '22;"></span>' +
            '<span class="hg-status-text" style="vertical-align:middle;font-size:14px;font-weight:600;">' + Ext.util.Format.htmlEncode(text) + '</span>' +
            '</div>';
    },

    _setStatus: function (state, text) {
        var markup = this._statusMarkup(state, text);
        this.statusPanel.html = markup;
        if (this.statusPanel.rendered && this.statusPanel.body) {
            this.statusPanel.body.update(markup);
        }
    },

    _setVersion: function (version, build) {
        var markup = "Version " + Ext.util.Format.htmlEncode(String(version || "unknown")) +
            " &middot; Build " + Ext.util.Format.htmlEncode(String(build || "unknown"));
        this.versionPanel.html = markup;
        if (this.versionPanel.rendered && this.versionPanel.body) {
            this.versionPanel.body.update(markup);
        }
    },

    _date: function (value) {
        if (!value) { return ""; }
        var parsed = new Date(value);
        return isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
    },

    _bytes: function (value) {
        var bytes = Number(value) || 0;
        var units = ["bytes", "KB", "MB", "GB", "TB"];
        var unit = 0;
        while (bytes >= 1024 && unit < units.length - 1) {
            bytes /= 1024;
            unit += 1;
        }
        if (unit === 0) { return Math.round(bytes) + " " + units[unit]; }
        return (bytes < 10 ? bytes.toFixed(1) : Math.round(bytes)) + " " + units[unit];
    },

    _defaultHttpsBase: function () {
        var hostname = window.location.hostname;
        var port = window.location.port;
        var authority;
        if (hostname.indexOf(":") >= 0) { hostname = "[" + hostname + "]"; }
        if (window.location.protocol !== "https:") { port = "5001"; }
        authority = hostname + (port ? ":" + port : "");
        return "https://" + authority + "/hg/";
    },

    _message: function (title, text) {
        Ext.Msg.alert(title, Ext.util.Format.htmlEncode(text));
    },

    _copyText: function (value, description) {
        var self = this;
        var legacyCopy = function () {
            var input = document.createElement("textarea");
            var copied = false;
            input.value = value || "";
            input.setAttribute("readonly", "readonly");
            input.style.position = "fixed";
            input.style.left = "-10000px";
            document.body.appendChild(input);
            input.select();
            try { copied = document.execCommand("copy"); } catch (e) {}
            document.body.removeChild(input);
            if (!copied) {
                self._message("Mercurial Server", "Could not copy the " + description + ". Select the text and copy it manually.");
            }
        };
        if (!value) { return; }
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(value).catch(legacyCopy);
        } else {
            legacyCopy();
        }
    },

    _request: function (path, method, body, callback, failureCallback) {
        var self = this;
        var headers = {};
        var requestConfig;
        method = method || "GET";
        if (this.csrf && method !== "GET") { headers["X-CSRF-Token"] = this.csrf; }
        if (this.sessionToken) { headers["X-Mercurial-Session"] = this.sessionToken; }
        requestConfig = {
            url: SYNO.SDS.MercurialServer.API + "?path=" + encodeURIComponent(path) + "&_=" + (+new Date()),
            method: method,
            headers: headers,
            timeout: 35000,
            success: function (response) {
                var data;
                try { data = Ext.decode(response.responseText); }
                catch (e) { self._message("Mercurial Server", "The server returned an invalid response."); return; }
                try { callback(data); }
                catch (e2) {
                    self._setStatus("error", "Interface error while reading server status");
                    self._message("Mercurial Server", e2.message || "The interface could not display the server response.");
                }
            },
            failure: function (response) {
                var data = {};
                var errorText;
                try { data = Ext.decode(response.responseText); } catch (e) {}
                if (response.status === 401 && path !== "/api/bootstrap" && path !== "/api/login") {
                    self.csrf = "";
                    self.sessionToken = "";
                    self._bootstrap();
                    return;
                }
                errorText = data.error || (response.status <= 0
                    ? "The request timed out. Check that the Mercurial Server package is running."
                    : "Request failed (" + response.status + ").");
                self._setStatus("error", errorText);
                if (failureCallback) {
                    failureCallback(errorText, response.status);
                } else if (path !== "/api/status" && path !== "/api/bootstrap") {
                    self._message("Mercurial Server", errorText);
                }
            }
        };
        if (body !== null && body !== undefined) { requestConfig.jsonData = body; }
        Ext.Ajax.request(requestConfig);
    },

    _bootstrap: function () {
        var self = this;
        this._setStatus("waiting", "Checking server status...");
        this._request("/api/bootstrap", "GET", null, function (data) {
            self.csrf = data.csrf || "";
            self.sessionToken = data.session || self.sessionToken || "";
            if (data.dsm_authenticated) {
                self._refresh();
            }
            else if (data.setup_required) {
                self._setStatus("stopped", "Initial setup required");
                self._showCredentials(true);
            }
            else if (!data.authenticated) {
                self._setStatus("stopped", "Administrator sign-in required");
                self._showCredentials(false);
            }
            else { self._refresh(); }
        });
    },

    _showCredentials: function (setup) {
        var self = this;
        if (this.authWindow) { try { this.authWindow.close(); } catch (e) {} }
        var username = new Ext.form.TextField({fieldLabel: "Username", allowBlank: false, anchor: "100%"});
        var password = new Ext.form.TextField({fieldLabel: "Password", inputType: "password", allowBlank: false, anchor: "100%"});
        var confirmation = new Ext.form.TextField({fieldLabel: "Confirm password", inputType: "password", allowBlank: false, anchor: "100%", hidden: !setup});
        var submit = function () {
            if (!username.getValue() || !password.getValue()) { self._message("Mercurial Server", "Enter a username and password."); return; }
            if (setup && password.getValue() !== confirmation.getValue()) { self._message("Mercurial Server", "Passwords do not match."); return; }
            self._request(setup ? "/api/setup" : "/api/login", "POST", {
                username: username.getValue(), password: password.getValue()
            }, function (data) {
                self.csrf = data.csrf || "";
                self.sessionToken = data.session || "";
                self.authWindow.close();
                self.authWindow = null;
                self._refresh();
            });
        };
        this.authWindow = new Ext.Window({
            title: setup ? "Set up Mercurial Server" : "Mercurial Server sign in",
            cls: "hg-dialog",
            owner: this,
            modal: true,
            shadow: "drop",
            closable: !setup,
            resizable: false,
            width: 420,
            autoHeight: true,
            layout: "form",
            labelWidth: 120,
            bodyStyle: "padding:20px;background:#f4f5f6;color:#25313b;",
            items: [
                {xtype: "box", autoEl: {tag: "p", html: setup ? "Create the first Mercurial Server administrator." : "Enter a Mercurial Server administrator account."}},
                username, password, confirmation
            ],
            buttons: [new SYNO.ux.Button({text: setup ? "Create administrator" : "Sign in", btnStyle: "blue", handler: submit})],
            listeners: {show: function () { username.focus(true, 200); }}
        });
        password.on("specialkey", function (field, event) { if (event.getKey() === event.ENTER && !setup) { submit(); } });
        confirmation.on("specialkey", function (field, event) { if (event.getKey() === event.ENTER) { submit(); } });
        this.authWindow.show();
    },

    _refresh: function () {
        var self = this;
        this._setStatus("waiting", "Checking server status...");
        this._request("/api/status", "GET", null, function (data) {
            var noServerUsers = !(data.users || []).length;
            self._setStatus(
                data.running ? "running" : "stopped",
                data.running
                    ? (noServerUsers
                        ? "Server running — add a server user before cloning"
                        : "Server running — clone, pull, and push are available")
                    : (data.backend_error ? "Server stopped — " + data.backend_error : "Server stopped — repository traffic is paused")
            );
            self.startButton.setDisabled(!!data.running);
            self.stopButton.setDisabled(!data.running);
            self.storagePath.setValue(data.repo_path || "");
            self.pythonRuntime.setValue(
                "Python " + (data.python_version || "unknown") +
                (data.python_executable ? " — " + Ext.util.Format.htmlEncode(data.python_executable) : "")
            );
            self._setVersion(data.package_version, data.package_build);
            self.storageState.setValue(data.repo_writable ? "The package can read and write this folder." : "Grant the mercurialserver system user read/write permission.");
            var httpsBase = data.https_base_url || self._defaultHttpsBase();
            self.httpsState.setValue(
                data.https_configured
                    ? "Enabled — certificate and TLS are managed by DSM"
                    : "Unavailable"
            );
            self.httpsUrl.setValue(httpsBase);
            self.cloneCommand.setValue("hg clone " + httpsBase + "REPOSITORY");
            self.repoStore.loadData(data.repositories || []);
            self.userStore.loadData(data.users || []);
        });
    },

    _action: function (path, body, successText) {
        var self = this;
        this._request(path, "POST", body || {}, function () {
            if (successText) { self._message("Mercurial Server", successText); }
            self._refresh();
        });
    },

    _start: function () {
        var self = this;
        this._setStatus("waiting", "Starting Mercurial service...");
        this.startButton.setDisabled(true);
        this.stopButton.setDisabled(true);
        this._request("/api/service/start", "POST", {}, function () {
            self._refresh();
        }, function (message) {
            self._setStatus("error", message);
            self.startButton.setDisabled(false);
            self.stopButton.setDisabled(true);
        });
    },

    _stop: function () {
        var self = this;
        this._setStatus("waiting", "Stopping Mercurial service...");
        this.startButton.setDisabled(true);
        this.stopButton.setDisabled(true);
        this._request("/api/service/stop", "POST", {}, function () {
            self._refresh();
        }, function (message) {
            self._setStatus("error", message);
            self.startButton.setDisabled(false);
        });
    },

    _chooseStorageFolder: function () {
        var self = this;
        var currentPath = this.storagePath.getValue() || "/";
        var folderStore = new Ext.data.JsonStore({
            fields: ["name", "path", {name: "writable", type: "boolean"}],
            data: []
        });
        var pathField = new Ext.form.TextField({
            fieldLabel: "Current folder",
            readOnly: true,
            anchor: "100%",
            value: currentPath
        });
        var folderGrid = new Ext.grid.GridPanel({
            cls: "hg-grid hg-folder-grid",
            border: true,
            stripeRows: true,
            store: folderStore,
            height: 270,
            columns: [
                {header: "Folder", dataIndex: "name", sortable: true, width: 300},
                {header: "Access", dataIndex: "writable", sortable: true, width: 100, renderer: function (value) { return value ? "Read/write" : "Read only"; }}
            ],
            viewConfig: {forceFit: true, deferEmptyText: false, emptyText: '<div class="hg-folder-empty">No accessible subfolders</div>'}
        });
        var win;
        var loadFolder = function (path) {
            folderGrid.getEl().mask("Loading folders...");
            self._request("/api/directories", "POST", {path: path}, function (data) {
                currentPath = data.path;
                pathField.setValue(data.path);
                folderStore.loadData(data.directories || []);
                folderStore.sort("name", "ASC");
                win.parentPath = data.parent || null;
                folderGrid.getEl().unmask();
            }, function (message) {
                folderGrid.getEl().unmask();
                self._message("Choose repository folder", message);
            });
        };
        var openSelectedFolder = function () {
            var record = folderGrid.getSelectionModel().getSelected();
            if (record) { loadFolder(record.get("path")); }
        };
        var chooseCurrentFolder = function () {
            var record = folderGrid.getSelectionModel().getSelected();
            var selectedPath = record ? record.get("path") : currentPath;
            self._request("/api/settings/storage", "POST", {repo_path: selectedPath}, function () {
                win.close();
                self._refresh();
            });
        };
        win = new Ext.Window({
            title: "Choose repository folder",
            cls: "hg-dialog hg-folder-dialog",
            owner: this,
            modal: true,
            shadow: "drop",
            resizable: true,
            width: 560,
            height: 480,
            minWidth: 460,
            minHeight: 340,
            layout: "fit",
            items: [{
                xtype: "panel",
                border: false,
                layout: "form",
                labelWidth: 90,
                bodyStyle: "padding:14px;background:#f4f5f6;",
                items: [pathField, folderGrid],
                tbar: [
                    new SYNO.ux.Button({text: "Up", iconCls: "hg-icon hg-icon-folder-up", handler: function () { if (win.parentPath) { loadFolder(win.parentPath); } }}),
                    new SYNO.ux.Button({text: "Open", iconCls: "hg-icon hg-icon-folder", handler: openSelectedFolder}),
                    new SYNO.ux.Button({text: "Refresh", iconCls: "hg-icon hg-icon-refresh", handler: function () { loadFolder(currentPath); }})
                ]
            }],
            buttons: [
                new SYNO.ux.Button({text: "Cancel", handler: function () { win.close(); }}),
                new SYNO.ux.Button({text: "Choose folder", btnStyle: "blue", handler: chooseCurrentFolder})
            ],
            listeners: {show: function () { loadFolder(currentPath); }}
        });
        folderGrid.on("rowdblclick", openSelectedFolder);
        win.show();
    },

    _prompt: function (title, fields, submitText, handler) {
        var win = new Ext.Window({
            title: title,
            cls: "hg-dialog",
            owner: this,
            modal: true,
            shadow: "drop",
            resizable: false,
            width: 420,
            autoHeight: true,
            layout: "form",
            labelWidth: 120,
            bodyStyle: "padding:20px;background:#f4f5f6;color:#25313b;",
            items: fields,
            buttons: [
                new SYNO.ux.Button({text: "Cancel", handler: function () { win.close(); }}),
                new SYNO.ux.Button({text: submitText, btnStyle: "blue", handler: function () { handler(win); }})
            ]
        });
        win.show();
        if (fields.length && fields[0].focus) { fields[0].focus(true, 200); }
        return win;
    },

    _createRepository: function () {
        var self = this;
        var name = new Ext.form.TextField({fieldLabel: "Repository name", allowBlank: false, anchor: "100%"});
        this._prompt("Create repository", [name], "Create", function (win) {
            self._request("/api/repositories", "POST", {name: name.getValue()}, function () { win.close(); self._refresh(); });
        });
    },

    _addUser: function () {
        var self = this;
        var username = new Ext.form.TextField({fieldLabel: "Username", allowBlank: false, anchor: "100%"});
        var password = new Ext.form.TextField({fieldLabel: "Password", inputType: "password", allowBlank: false, anchor: "100%"});
        var admin = new Ext.form.Checkbox({fieldLabel: "Administrator", checked: false});
        this._prompt("Add server user", [username, password, admin], "Add", function (win) {
            self._request("/api/users", "POST", {username: username.getValue(), password: password.getValue(), admin: admin.getValue()}, function () { win.close(); self._refresh(); });
        });
    },

    _selectedUser: function () {
        var selection = this.userGrid.getSelectionModel().getSelected();
        if (!selection) { this._message("Mercurial Server", "Select a user first."); return null; }
        return selection.get("username");
    },

    _changePassword: function () {
        var self = this;
        var username = this._selectedUser();
        if (!username) { return; }
        var password = new Ext.form.TextField({fieldLabel: "New password", inputType: "password", allowBlank: false, anchor: "100%"});
        this._prompt("Change password for " + username, [password], "Save", function (win) {
            self._request("/api/users/" + encodeURIComponent(username) + "/password", "POST", {password: password.getValue()}, function () { win.close(); self._refresh(); });
        });
    },

    _deleteUser: function () {
        var self = this;
        var username = this._selectedUser();
        if (!username) { return; }
        Ext.Msg.confirm("Delete user", "Delete " + Ext.util.Format.htmlEncode(username) + "?", function (answer) {
            if (answer !== "yes") { return; }
            self._request("/api/users/" + encodeURIComponent(username), "DELETE", null, function () { self._refresh(); });
        });
    },

    _logout: function () {
        var self = this;
        this._request("/api/logout", "POST", {}, function () {
            self.csrf = "";
            self.sessionToken = "";
            self._setStatus("stopped", "Administrator sign-in required");
            self._showCredentials(false);
        });
    }
});
