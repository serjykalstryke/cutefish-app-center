#!/usr/bin/python3
"""Unprivileged store providers. stdin request -> NDJSON progress + result.

No shell, sudo, root helper or arbitrary executable from a request. Debian
transactions belong to PackageKit and Snap transactions belong to snapd.
"""
from __future__ import annotations
import concurrent.futures
import contextlib
import configparser
import html
import fcntl
import gzip
import hashlib
import http.client
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import subprocess
import struct
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

LIMIT = 100
ENV = dict(os.environ, LC_ALL="C.UTF-8", LANG="C.UTF-8")
PACKAGE = re.compile(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?\Z")
APPID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
PK_NAME = "org.freedesktop.PackageKit"
PK_ROOT = "/org/freedesktop/PackageKit"
PK_IFACE = PK_NAME + ".Transaction"
def pk_info(info):
    # Resolve against the installed library: PackageKit 2 changed enum ordinals.
    import ctypes
    lib = ctypes.CDLL("libpackagekit-glib2.so.18")
    fn = lib.pk_info_enum_to_string
    fn.argtypes = [ctypes.c_int]
    fn.restype = ctypes.c_char_p
    return fn(info).decode("utf-8")

class StoreError(Exception):
    pass

def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)

def progress(text, percent=None):
    emit({"event": "progress", "message": text, "percent": percent})

def run(args, timeout=45):
    try:
        p = subprocess.run(args, capture_output=True, text=True, env=ENV,
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise StoreError(f"{args[0]} is not installed.") from None
    except subprocess.TimeoutExpired:
        raise StoreError(f"{args[0]} did not respond in time.") from None
    if p.returncode:
        raise StoreError((p.stderr or p.stdout or f"{args[0]} failed.").strip()[-4000:])
    return p.stdout

def data_home():
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))

def state_dir():
    p = data_home() / "cutefish-store"
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p

@contextlib.contextmanager
def mutation_lock():
    with open(state_dir() / "transaction.lock", "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StoreError("Another store transaction is running.") from None
        yield

class PackageKit:
    def __init__(self):
        try:
            from gi.repository import Gio, GLib
            self.Gio, self.GLib = Gio, GLib
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except Exception as e:
            raise StoreError("Cannot reach the system package service. Install packagekit and python3-gi. " + str(e)) from None

    def call(self, path, iface, method, signature=None, values=()):
        params = self.GLib.Variant(signature, values) if signature else None
        return self.bus.call_sync(PK_NAME, path, iface, method, params, None,
                                 self.Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION,
                                 120000, None).unpack()

    def transaction(self, method, signature, values):
        try:
            path = self.call(PK_ROOT, PK_NAME, "CreateTransaction")[0]
        except Exception as e:
            raise StoreError("The Debian package service is unavailable. Install packagekit and try again. " + str(e)) from None
        packages, errors, restarts = [], [], []
        finished = [None]
        loop = self.GLib.MainLoop()
        def signal(bus, sender, obj, iface, name, params, user):
            args = params.unpack()
            if name == "Package":
                info, pid, summary = args
                packages.append({"info": pk_info(info), "id": pid, "summary": summary})
            elif name == "ErrorCode":
                errors.append(args[1])
            elif name == "RequireRestart":
                restarts.append(args[0])
            elif name in ("EulaRequired", "RepoSignatureRequired", "MediaChangeRequired"):
                errors.append("The package service requires an additional license, signing key or installation medium. Use the system package tools to resolve it.")
            elif name == "Finished":
                finished[0] = args[0]
                loop.quit()
        def properties(bus, sender, obj, iface, name, params, user):
            changed = params.unpack()[1]
            n = changed.get("Percentage")
            if n is not None and 0 <= n <= 100:
                progress("Working with Debian packages…", n)
        subs = [self.bus.signal_subscribe(PK_NAME, PK_IFACE, None, path, None,
                                         self.Gio.DBusSignalFlags.NONE, signal, None),
                self.bus.signal_subscribe(PK_NAME, "org.freedesktop.DBus.Properties", "PropertiesChanged", path, None,
                                         self.Gio.DBusSignalFlags.NONE, properties, None)]
        try:
            # Debian 13 uses as; newer PackageKit also supports a{sv} hints.
            xml = self.call(path, "org.freedesktop.DBus.Introspectable", "Introspect")[0]
            root = ET.fromstring(xml)
            node = root.find("./interface[@name='" + PK_IFACE + "']/method[@name='SetHints']/arg")
            if node is not None and node.get("type") == "a{sv}":
                self.call(path, PK_IFACE, "SetHints", "(a{sv})", ({"interactive": self.GLib.Variant("b", True)},))
            else:
                self.call(path, PK_IFACE, "SetHints", "(as)", (["interactive=true", "background=false"],))
            self.call(path, PK_IFACE, method, signature, values)
            if finished[0] is None:
                loop.run()
            if errors or finished[0] != 1:
                raise StoreError("; ".join(errors) or "The package transaction did not complete.")
            return packages, restarts
        except StoreError:
            raise
        except Exception as e:
            raise StoreError(str(e)) from None
        finally:
            for sub in subs:
                self.bus.signal_unsubscribe(sub)

    def resolve(self, package, installed=False):
        if not PACKAGE.fullmatch(package):
            raise StoreError("Invalid Debian package name.")
        # Filter bits are 1 << enum, not the enum ordinal.
        name, _, requested_arch = package.partition(":")
        packages, _ = self.transaction("Resolve", "(tas)", ((1 << (2 if installed else 3)) | (1 << 16), [name]))
        wanted_arch = requested_arch or run(["dpkg", "--print-architecture"]).strip()
        packages = [p for p in packages if p["id"].split(";")[2] in (wanted_arch, "all")]
        if not packages:
            raise StoreError("The package service could not resolve this package. Refresh software sources and try again.")
        if len(packages) != 1:
            raise StoreError("More than one package architecture or version matches. Use the system package tools to select one.")
        return packages[0]["id"]


def dpkg_installed():
    out = run(["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${db:Status-Status}\t${binary:Summary}\t${Essential}\t${Protected}\n"])
    items = []
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) >= 6 and cols[2] == "installed":
            name, version, _, summary, essential, protected = cols[:6]
            items.append(dict(source="deb", id=name, name=name, version=version,
                              summary=summary, installed=True, scope="system",
                              protected=essential == "yes" or protected == "yes", icon="application-x-deb"))
    return items


def appstream():
    """Read distribution metadata if present; fall back to honest package search."""
    result = {}
    paths = []
    for directory in ("/var/lib/swcatalog/xml", "/var/cache/swcatalog/xml", "/var/cache/app-info/xmls"):
        paths += list(Path(directory).glob("*.xml*"))
    for path in paths:
        try:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rb") as f:
                for _, node in ET.iterparse(f, events=("end",)):
                    if node.tag != "component":
                        continue
                    if node.get("type") == "desktop-application":
                        pkg = node.findtext("pkgname")
                        if pkg and PACKAGE.fullmatch(pkg):
                            def plain(tag):
                                elements = node.findall(tag)
                                return next((e.text for e in elements if not e.attrib and e.text), "")
                            icon = next((e.text for e in node.findall("icon") if e.get("type") == "stock"), "application-x-deb")
                            result[pkg] = {"name": plain("name") or pkg,
                                           "summary": plain("summary"), "icon": icon,
                                           "app_id": node.findtext("id", "")}
                    node.clear()
        except (OSError, ET.ParseError):
            continue
    return result


def deb_search(query):
    if len(query) < 2:
        return []
    # apt-cache search treats its argument as a regular expression.
    out = run(["apt-cache", "search", "--names-only", "--", re.escape(query)], timeout=30)
    installed = {x["id"].split(":")[0]: x for x in dpkg_installed()}
    metadata = appstream()
    items = []
    for line in out.splitlines()[:LIMIT]:
        name, sep, summary = line.partition(" - ")
        if not sep or not PACKAGE.fullmatch(name):
            continue
        item = dict(source="deb", id=name, name=name, summary=summary, scope="system",
                    installed=name in installed, version=installed.get(name, {}).get("version", ""), icon="application-x-deb")
        item.update(metadata.get(name, {}))
        items.append(item)
    return items

class SnapHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/run/snapd.socket")

def snap_api(path, body=None):
    conn = SnapHTTP("localhost", timeout=120)
    try:
        headers = {"X-Allow-Interaction": "true"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body)
        conn.request("POST" if body is not None else "GET", path, body=data, headers=headers)
        response = conn.getresponse()
        payload = json.loads(response.read())
        if response.status >= 400 or payload.get("type") == "error":
            raise StoreError(payload.get("result", {}).get("message", "Snap service request failed."))
        return payload
    except StoreError:
        raise
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise StoreError("Cannot reach snapd: " + str(e)) from None
    finally:
        conn.close()

def snap_items(query=None, updates=False):
    if query is not None:
        path = "/v2/find?" + urllib.parse.urlencode({"q": query})
    elif updates:
        path = "/v2/find?select=refresh"
    else:
        path = "/v2/snaps"
    data = snap_api(path)["result"]
    installed = {x["name"] for x in snap_api("/v2/snaps")["result"]} if query is not None or updates else set()
    return [dict(source="snap", id=x["name"], name=x.get("title") or x["name"],
                 summary=x.get("summary", ""), version=x.get("version", ""),
                 installed=x["name"] in installed or (query is None and not updates),
                 scope="system", channel=x.get("channel", "stable"),
                 confinement=x.get("confinement", "strict"), icon="application-x-executable") for x in data[:LIMIT]]


def flatpak_items(query=None, updates=False):
    if not shutil.which("flatpak"):
        raise StoreError("Flatpak is not installed. Install flatpak and configure a remote such as Flathub.")
    items = []
    for scope in ("user", "system"):
        if query is not None:
            args = ["search", "--columns=application,name,description,version,branch,remotes", "--", query]
        elif updates:
            args = ["remote-ls", "--updates", "--app", "--columns=application,name,description,version,branch,origin,arch"]
        else:
            args = ["list", "--app", "--columns=application,name,description,version,branch,origin,arch"]
        out = run(["flatpak", "--" + scope] + args, timeout=90)
        installed = set()
        native_arch = ""
        if query is not None:
            native_arch = run(["flatpak", "--default-arch"]).strip()
            installed = {tuple(line.split("\t")) for line in run(["flatpak", "--" + scope, "list", "--app", "--columns=application,branch,origin,arch"]).splitlines()}
            # Search includes add-ons and runtimes, which cannot be installed as
            # app/ refs. Keep only exact application refs advertised by a remote.
            app_refs = {tuple(line.split("\t")) for line in run([
                "flatpak", "--" + scope, "remote-ls", "--app", "--cached",
                "--columns=application,arch,branch,origin"]).splitlines()}
        for line in out.splitlines():
            cols = line.split("\t")
            if len(cols) < 6 or not APPID.fullmatch(cols[0]):
                continue
            appid, name, summary, version, branch, remotes = cols[:6]
            # Search may report multiple remotes; preserve each choice.
            for remote in remotes.split(","):
                remote = remote.strip()
                if not APPID.fullmatch(remote) or not APPID.fullmatch(branch):
                    continue
                if query is not None and (appid, native_arch, branch, remote) not in app_refs:
                    continue
                items.append(dict(source="flatpak", id=appid, name=name, summary=summary,
                                  version=version, branch=branch, remote=remote, scope=scope,
                                  arch=cols[6] if len(cols) > 6 else native_arch,
                                  installed=query is None or (appid, branch, remote, native_arch) in installed, icon="application-x-executable"))
    return items[:LIMIT]


def flatpak_permissions(metadata):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read_string(metadata)
    except configparser.Error as e:
        raise StoreError("Could not read this Flatpak's access metadata: " + str(e)) from None
    if "Application" not in parser:
        raise StoreError("This result is a Flatpak runtime or extension, not an application.")
    sections = []
    for name in ("Context", "Session Bus Policy", "System Bus Policy"):
        if parser.has_section(name):
            sections.append(name + ":\n" + "\n".join(k + "=" + v for k, v in parser.items(name)))
    return "\n\n".join(sections) or "No additional static access declarations were reported. Runtime portal requests may still occur."


APPIMAGE_FEED = "https://appimage.github.io/feed.json"
CATALOG_MAX_BYTES = 12 * 1024 * 1024

def appimage_feed():
    cache_dir = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "cutefish-store"
    cache = cache_dir / "appimage-feed.json"
    try:
        if cache.is_file() and time.time() - cache.stat().st_mtime < 86400:
            data = json.loads(cache.read_text())
            if isinstance(data.get("items"), list):
                return data["items"]
    except (OSError, ValueError, AttributeError):
        pass
    try:
        req = urllib.request.Request(APPIMAGE_FEED, headers={"User-Agent": "CutefishStore/0.1.2"})
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read(CATALOG_MAX_BYTES + 1)
        if len(raw) > CATALOG_MAX_BYTES:
            raise StoreError("The AppImage catalog exceeded its size limit.")
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise StoreError("The AppImage catalog has an unsupported format.")
    except (OSError, ValueError) as e:
        raise StoreError("Could not load the AppImage catalog. Imported files are still available under Installed. " + str(e)) from None
    # Cache failure must not hide a successful search.
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=cache_dir, prefix=".catalog-")
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(raw)
            os.replace(temporary, cache)
        finally:
            Path(temporary).unlink(missing_ok=True)
    except OSError:
        pass
    return data["items"]


def appimage_catalog(query):
    words = query.casefold().split()
    result = []
    for entry in appimage_feed():
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name or len(name) > 300:
            continue
        description = entry.get("description") or ""
        if not isinstance(description, str):
            description = ""
        summary = html.unescape(re.sub(r"<[^>]*>", " ", description))
        summary = " ".join(summary.split())
        if not all(w in (name + " " + summary).casefold() for w in words):
            continue
        result.append(dict(source="appimage", id=hashlib.sha256(name.encode()).hexdigest(),
                           name=name, summary=summary[:1500], scope="catalog", installed=False,
                           catalog=True, icon="application-x-executable",
                           catalog_url="https://appimage.github.io/" + urllib.parse.quote(name, safe="") + "/"))
    result.sort(key=lambda x: (not all(w in x["name"].casefold() for w in words), x["name"].casefold()))
    return result[:LIMIT]


def appimage_catalog_link(target):
    # Reconstruct a known catalog URL, never pass arbitrary URI schemes to a launcher.
    name = target.get("name", "")
    if (not isinstance(name, str) or not name or len(name) > 300 or
            hashlib.sha256(name.encode()).hexdigest() != target.get("id")):
        raise StoreError("Invalid AppImage catalog entry.")
    return "https://appimage.github.io/" + urllib.parse.quote(name, safe="") + "/"


def appimage_items():
    result = []
    for p in (data_home() / "cutefish-store/appimages").glob("*/metadata.json"):
        try:
            item = json.loads(p.read_text())
            if item.get("id") == p.parent.name and re.fullmatch(r"[a-f0-9]{64}", item["id"]):
                if item.get('metadata_version', 0) < APPIMAGE_METADATA_VERSION:
                    try:
                        item = refresh_appimage_metadata(item['id'])
                    except (StoreError, OSError):
                        pass
                result.append(item)
        except (OSError, ValueError, KeyError):
            continue
    return result


def inspect_local(filename):
    path = Path(filename).expanduser().resolve(strict=True)
    if not path.is_file():
        raise StoreError("Choose a regular local file.")
    if path.suffix.lower() == ".deb":
        fields = run(["dpkg-deb", "--show", "--showformat=${Package}\t${Version}\t${Architecture}\t${Description}\n", str(path)]).split("\t", 3)
        if len(fields) != 4 or not PACKAGE.fullmatch(fields[0]):
            raise StoreError("This file is not a valid Debian package.")
        return dict(source="deb", id=fields[0], name=fields[0], version=fields[1],
                    architecture=fields[2], summary=fields[3].strip(), scope="system", path=str(path),
                    sha256=file_hash(path), installed=False, icon="application-x-deb")
    with path.open("rb") as f:
        header = f.read(11)
    if header[:4] != b"\x7fELF" or header[8:11] not in (b"AI\x01", b"AI\x02"):
        raise StoreError("Choose a valid .deb or AppImage file. This file does not have an AppImage header.")
    return dict(source="appimage", id=file_hash(path), name=path.stem,
                summary="Local AppImage • publisher not verified • updates managed by its publisher",
                path=str(path), scope="user", installed=False, icon="application-x-executable")


def file_hash(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def validate_target(target):
    source = target.get("source")
    if source not in ("deb", "flatpak", "snap", "appimage"):
        raise StoreError("Unknown software source.")
    ident = target.get("id", "")
    pattern = PACKAGE if source == "deb" else APPID
    if not pattern.fullmatch(ident):
        raise StoreError("Invalid software identifier.")
    if source == "flatpak":
        if target.get("scope") not in ("user", "system"):
            raise StoreError("Choose a Flatpak installation scope.")
        for field in ("branch", "remote"):
            if not APPID.fullmatch(target.get(field, "")):
                raise StoreError("Invalid Flatpak " + field)
        if target.get("arch") and not APPID.fullmatch(target["arch"]):
            raise StoreError("Invalid Flatpak architecture.")
    if source == "appimage" and not re.fullmatch(r"[a-f0-9]{64}", ident):
        raise StoreError("Invalid AppImage identifier.")


def pk_args(target, action, flags):
    pk = PackageKit()
    if target.get("path"):
        if action != "install":
            raise StoreError("Local packages can only be installed from a file.")
        checked = inspect_local(target["path"])
        if checked["source"] != "deb" or checked["sha256"] != target.get("sha256"):
            raise StoreError("The local package changed. Open it again before installing.")
        return pk, "InstallFiles", "(tas)", (flags & ~2, [checked["path"]])
    if action == "update":
        available, _ = pk.transaction("GetUpdates", "(t)", (0,))
        matches = [p["id"] for p in available if p["id"] == target.get("package_id")]
        if len(matches) != 1:
            raise StoreError("This update changed or is no longer available. Reload updates and try again.")
        pid = matches[0]
    else:
        pid = pk.resolve(target["id"], installed=action == "remove")
    if action == "remove":
        return pk, "RemovePackages", "(tasbb)", (flags, [pid], True, False)
    return pk, "UpdatePackages" if action == "update" else "InstallPackages", "(tas)", (flags, [pid])


def plan(target, action):
    validate_target(target)
    if action not in ("install", "remove", "update"):
        raise StoreError("Unsupported software operation.")
    changes = []
    note = ""
    source = target["source"]
    if source == "deb":
        pk, method, signature, args = pk_args(target, action, 4 | 2)
        changes, _ = pk.transaction(method, signature, args)
        protected = {i["id"].split(":")[0] for i in dpkg_installed() if i["protected"]}
        if any(c["info"] in ("remove", "removing", "obsolete", "obsoleting") and c["id"].split(";")[0] in protected for c in changes):
            raise StoreError("This operation would remove an essential or protected system package.")
        if target.get("path"):
            note = "Local Debian packages can run installation scripts with administrator access. Only install files from a publisher you trust. Dependencies will be resolved by the system package service."
        else:
            note = "The system package service will request administrator authorization if needed."
    elif source == "flatpak":
        ref = flatpak_ref(target)
        if action == "install":
            metadata = run(["flatpak", "--" + target["scope"], "remote-info", "--show-metadata", "--", target["remote"], ref])
            permissions = flatpak_permissions(metadata)
            note = "Flatpak may install shared runtimes and extensions. Application access declared by the publisher:\n" + permissions
        else:
            note = "Application data is kept when removing a Flatpak. Shared runtimes may also be updated."
        changes = [{"info": action, "id": ref, "summary": target.get("name", target["id"])}]
    elif source == "snap":
        path = "/v2/snaps/" + urllib.parse.quote(target["id"], safe="")
        if action == "install":
            found = snap_api("/v2/find?" + urllib.parse.urlencode({"name": target["id"]}))["result"]
            if len(found) != 1:
                raise StoreError("Snap is no longer available.")
            confinement = found[0].get("confinement", "strict")
        else:
            confinement = snap_api(path)["result"].get("confinement", "strict")
        if confinement == "devmode":
            raise StoreError("Developer mode snaps are not supported by this version.")
        target = dict(target, confinement=confinement)
        note = ("Classic confinement: this app has broad access to your files and system, similar to a native application." if confinement == "classic" else "This snap uses strict confinement.")
        note += " Snapd manages shared bases, dependencies, automatic refreshes and removal snapshots."
        changes = [{"info": action, "id": target["id"], "summary": target.get("name", target["id"])}]
    else:
        if action == "update":
            raise StoreError("This AppImage has no store-managed update source. Download a new version from its publisher and import it.")
        if action == "install":
            checked = inspect_local(target.get("path", ""))
            if checked["source"] != "appimage" or checked["id"] != target["id"]:
                raise StoreError("The AppImage changed. Open it again.")
            note = "The publisher is not verified. AppImages can access your files. Importing copies the file into your store library and adds a menu entry. It will not run the application."
        else:
            note = "Removes the store's copy and menu entry. The original download and application data are kept."
        changes = [{"info": action, "id": target["id"], "summary": target.get("name", target["id"])}]
    result = dict(target=target, action=action, changes=sorted(changes, key=lambda x: (x["id"], x["info"])), note=note)
    result["fingerprint"] = fingerprint(result)
    return result


def fingerprint(plan_data):
    # Summaries and display labels are not transaction identity.
    payload = dict(target=plan_data["target"], action=plan_data["action"],
                   changes=[(c["id"], c["info"]) for c in plan_data["changes"]], note=plan_data["note"])
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def flatpak_ref(target):
    arch = target.get("arch") or run(["flatpak", "--default-arch"]).strip()
    if not APPID.fullmatch(arch):
        raise StoreError("Invalid Flatpak architecture.")
    return "app/" + target["id"] + "/" + arch + "/" + target["branch"]


def stream_command(args):
    try:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, env=ENV, stdin=subprocess.DEVNULL)
    except OSError as e:
        raise StoreError(str(e)) from None
    tail = []
    for line in process.stdout:
        text = line.strip()
        if text:
            tail.append(text)
            tail = tail[-30:]
            progress(text)
    if process.wait():
        raise StoreError("\n".join(tail))


def desktop_quote(path):
    # Desktop Entry Exec quoting, including its separate string escape layer.
    escaped = str(path).replace("%", "%%")
    escaped = re.sub(r'([\\"`$])', r'\\\1', escaped)
    return '"' + escaped.replace("\\", "\\\\") + '"'


APPIMAGE_METADATA_VERSION = 1
ICON_MAX_BYTES = 4 * 1024 * 1024


def squashfs_offset(path):
    """Locate a bounded type-2 payload without running its ELF runtime."""
    size = path.stat().st_size
    with path.open('rb') as stream:
        header = stream.read(16 * 1024 * 1024)
    if header[:4] != b'\x7fELF' or header[8:11] != b'AI\x02':
        return None
    start = 0
    while True:
        offset = header.find(b'hsqs', start)
        if offset < 0:
            return None
        if offset + 96 <= len(header):
            block = struct.unpack_from('<I', header, offset + 12)[0]
            block_log = struct.unpack_from('<H', header, offset + 22)[0]
            major = struct.unpack_from('<H', header, offset + 28)[0]
            used = struct.unpack_from('<Q', header, offset + 40)[0]
            if (major == 4 and 4096 <= block <= 1048576 and
                    block_log <= 20 and block == 1 << block_log and
                    96 <= used <= size - offset):
                return offset
        start = offset + 4


def archive_output(path, offset, options, members=(), limit=65536):
    """Read bounded metadata through the archive tool, never the AppImage."""
    if not shutil.which('unsquashfs') or not shutil.which('prlimit'):
        raise StoreError('Install squashfs-tools and util-linux to read AppImage artwork.')
    args = ['prlimit', '--fsize=' + str(limit + 1), '--as=536870912', '--cpu=10', '--',
            'unsquashfs', '-processors', '1', '-data-queue', '8', '-frag-queue', '8',
            '-no-progress', '-o', str(offset)] + options + [str(path)] + list(members)
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(args, stdout=output, stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL, env=ENV, timeout=15)
        except subprocess.TimeoutExpired:
            raise StoreError('Reading AppImage metadata timed out.') from None
        if result.returncode:
            raise StoreError('The embedded metadata could not be read within its limits.')
        output.seek(0)
        data = output.read(limit + 1)
        if len(data) > limit:
            raise StoreError('The embedded metadata exceeded its size limit.')
        return data


def archive_member(path):
    value = PurePosixPath(path)
    return (bool(path) and not value.is_absolute() and '..' not in value.parts and
            not any(ord(c) < 32 for c in path) and len(path) < 1024)


def metadata_text(value, length=512):
    # Desktop Entry escapes are separate from INI parsing.
    value = re.sub(r'\\([sntr\\])', lambda m: {'s': ' ', 'n': ' ', 't': ' ', 'r': ' ', '\\': '\\'}[m[1]], value)
    return ' '.join(re.sub(r'[\x00-\x1f\x7f]', ' ', value).split())[:length]


def icon_format(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
        width, height = struct.unpack_from('>II', data, 16)
        return 'png' if 0 < width <= 4096 and 0 < height <= 4096 else None
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        return None
    try:
        root = ET.fromstring(data)
        if root.tag.rsplit('}', 1)[-1] != 'svg':
            return None
        for node in root.iter():
            if node.tag.rsplit('}', 1)[-1] in ('script', 'foreignObject'):
                return None
            for key, value in node.attrib.items():
                if key.rsplit('}', 1)[-1] == 'href' and not value.startswith('#'):
                    return None
                if 'url(' in value and not re.fullmatch(r'url\(\s*#[\w.-]+\s*\)', value):
                    return None
            if node.tag.rsplit('}', 1)[-1] == 'style' and ('url(' in (node.text or '') or '@import' in (node.text or '')):
                return None
        return 'svg'
    except (ET.ParseError, ValueError):
        return None


def embedded_appimage_metadata(path):
    fields, artwork, suffix = {}, None, None
    try:
        offset = squashfs_offset(path)
        if offset is None:
            return {'metadata_note': 'Embedded details are unavailable for this AppImage format.'}, None, None
        listing = archive_output(path, offset, ['-ls', '-max-depth', '1'], limit=128 * 1024).decode('utf-8', 'replace')
        desktops = sorted(line[len('squashfs-root/'):] for line in listing.splitlines()
                          if line.startswith('squashfs-root/') and line.endswith('.desktop')
                          and '/' not in line[len('squashfs-root/'):])[:16]
        icon_name = ''
        for desktop in desktops:
            if not archive_member(desktop):
                continue
            try:
                raw = archive_output(path, offset, ['-cat', '-no-wildcards'], [desktop])
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                parser.optionxform = str
                parser.read_string(raw.decode('utf-8-sig'))
                entry = parser['Desktop Entry']
                if entry.get('Type', 'Application') != 'Application' or not entry.get('Name'):
                    continue
                fields['name'] = metadata_text(entry['Name'])
                if entry.get('Comment'):
                    fields['summary'] = metadata_text(entry['Comment'], 1500)
                if entry.get('StartupWMClass'):
                    fields['startup_wm_class'] = metadata_text(entry['StartupWMClass'])
                fields['categories'] = [x for x in entry.get('Categories', '').split(';') if re.fullmatch(r'[A-Za-z0-9]+', x)][:32]
                if entry.get('X-AppImage-Version'):
                    fields['version'] = metadata_text(entry['X-AppImage-Version'])
                icon_name = entry.get('Icon', '')
                break
            except (StoreError, UnicodeError, configparser.Error, KeyError):
                continue
        candidates = []
        if archive_member(icon_name):
            candidates += [icon_name] if icon_name.endswith(('.png', '.svg', '.svgz')) else [icon_name + ext for ext in ('.png', '.svg', '.svgz')]
        candidates.append('.DirIcon')
        for member in dict.fromkeys(candidates):
            try:
                data = archive_output(path, offset, ['-cat', '-no-wildcards'], [member], limit=ICON_MAX_BYTES)
                if data.startswith(b'\x1f\x8b'):
                    with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
                        data = compressed.read(ICON_MAX_BYTES + 1)
                if len(data) <= ICON_MAX_BYTES and (suffix := icon_format(data)):
                    artwork = data
                    break
            except (StoreError, OSError, EOFError):
                continue
        if artwork is None:
            fields['metadata_note'] = 'No supported embedded icon was found; a generic icon is used.'
    except (StoreError, OSError, ValueError, struct.error):
        fields['metadata_note'] = 'Embedded details could not be read; a generic icon is used.'
    return fields, artwork, suffix


def desktop_value(value):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', str(value)).replace('\\', '\\\\')


def appimage_launcher(meta):
    lines = ['[Desktop Entry]', 'Type=Application', 'Name=' + desktop_value(meta['name']),
             'Exec=' + desktop_quote(meta['path']), 'Icon=' + desktop_value(meta['icon']),
             'Terminal=false', 'Categories=' + ';'.join(meta.get('categories') or ['Utility']) + ';']
    if meta.get('summary'):
        lines.append('Comment=' + desktop_value(meta['summary']))
    if meta.get('startup_wm_class'):
        lines.append('StartupWMClass=' + desktop_value(meta['startup_wm_class']))
    return '\n'.join(lines) + '\n'


def atomic_file(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.cutefish-store-')
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data if isinstance(data, bytes) else data.encode())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def appimage_details(meta, archive, output_dir, final_dir):
    fields, artwork, suffix = embedded_appimage_metadata(archive)
    result = dict(meta, **fields, icon='application-x-executable', metadata_version=APPIMAGE_METADATA_VERSION)
    if artwork is not None:
        icon_name = 'icon.' + suffix
        atomic_file(output_dir / icon_name, artwork, 0o644)
        result['icon'] = str(final_dir / icon_name)
    return result


def refresh_appimage_metadata(ident):
    if not re.fullmatch(r'[a-f0-9]{64}', ident):
        raise StoreError('Invalid AppImage identifier.')
    with mutation_lock():
        dest = state_dir() / 'appimages' / ident
        if dest.is_symlink() or not dest.is_dir():
            raise StoreError('This AppImage is not in the managed library.')
        archive = dest / 'application.AppImage'
        if archive.is_symlink() or file_hash(archive) != ident:
            raise StoreError('The managed AppImage changed. Import the downloaded file again.')
        old = json.loads((dest / 'metadata.json').read_text())
        meta = appimage_details(old, archive, dest, dest)
        launcher = data_home() / 'applications' / ('org.cutefish.Store.AppImage-' + ident + '.desktop')
        atomic_file(launcher, appimage_launcher(meta), 0o644)
        atomic_file(dest / 'metadata.json', json.dumps(meta))
        return meta


def import_appimage(target):
    checked = inspect_local(target["path"])
    if checked["id"] != target["id"]:
        raise StoreError("The AppImage changed. Open it again.")
    root = state_dir() / "appimages"
    root.mkdir(exist_ok=True)
    dest = root / target["id"]
    if dest.exists():
        raise StoreError("This AppImage is already imported.")
    staging = Path(tempfile.mkdtemp(prefix=".import-", dir=root))
    launcher = data_home() / "applications" / ("org.cutefish.Store.AppImage-" + target["id"] + ".desktop")
    committed = False
    try:
        shutil.copyfile(checked["path"], staging / "application.AppImage")
        if file_hash(staging / "application.AppImage") != target["id"]:
            raise StoreError("The file changed while being copied.")
        (staging / "application.AppImage").chmod(0o755)
        meta = dict(checked, installed=True, path=str(dest / "application.AppImage"))
        meta = appimage_details(meta, staging / 'application.AppImage', staging, dest)
        (staging / "metadata.json").write_text(json.dumps(meta))
        staging.rename(dest)
        committed = True
        atomic_file(launcher, appimage_launcher(meta), 0o644)
    except Exception:
        if committed:
            shutil.rmtree(dest)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def apply(approved):
    with mutation_lock():
        current = plan(approved["target"], approved["action"])
        if current["fingerprint"] != approved.get("fingerprint"):
            raise StoreError("The software or dependency plan changed. Review the operation again.")
        target, action = current["target"], current["action"]
        source = target["source"]
        restarts = []
        if source == "deb":
            pk, method, sig, args = pk_args(target, action, 2)
            _, restarts = pk.transaction(method, sig, args)
        elif source == "flatpak":
            args = ["flatpak", "--" + target["scope"], {"remove": "uninstall"}.get(action, action), "--assumeyes", "--noninteractive"]
            args += ["--", target["remote"], flatpak_ref(target)] if action == "install" else ["--", flatpak_ref(target)]
            stream_command(args)
        elif source == "snap":
            body = {"action": {"update": "refresh"}.get(action, action)}
            if action == "install":
                body["channel"] = "stable"
                if target.get("confinement") == "classic":
                    body["classic"] = True
            reply = snap_api("/v2/snaps/" + urllib.parse.quote(target["id"], safe=""), body)
            if reply.get("type") == "async":
                change_id = str(reply["change"])
                if not change_id.isdigit():
                    raise StoreError("Invalid change identifier from snapd.")
                while True:
                    change = snap_api("/v2/changes/" + change_id)["result"]
                    tasks = change.get("tasks", [])
                    progress(change.get("summary", "Working with Snap…"))
                    if change.get("ready"):
                        if change.get("err") or change.get("status") != "Done":
                            raise StoreError(change.get("err", "Snap transaction did not complete."))
                        break
                    time.sleep(0.7)
        elif action == "install":
            import_appimage(target)
        else:
            dest = state_dir() / "appimages" / target["id"]
            if dest.is_symlink():
                raise StoreError("Invalid managed AppImage directory.")
            if not dest.is_dir():
                raise StoreError("This AppImage is no longer in the store library.")
            (data_home() / "applications" / ("org.cutefish.Store.AppImage-" + target["id"] + ".desktop")).unlink(missing_ok=True)
            shutil.rmtree(dest)
        return {"message": "Operation completed." + (" A session or system restart is required." if restarts else ""), "restart": bool(restarts)}


def inventory_provider(source, mode, query):
    if source == "deb":
        if mode == "search":
            return deb_search(query)
        if mode == "updates":
            packages, _ = PackageKit().transaction("GetUpdates", "(t)", (0,))
            return [dict(source="deb", id=x["id"].split(";")[0], package_id=x["id"], name=x["id"].split(";")[0], version=x["id"].split(";")[1], summary=x["summary"], installed=True, scope="system", icon="application-x-deb") for x in packages]
        metadata = appstream()
        return [dict(x, **metadata.get(x["id"].split(":")[0], {})) for x in dpkg_installed()]
    if source == "flatpak":
        return flatpak_items(query if mode == "search" else None, mode == "updates")
    if source == "snap":
        return snap_items(query if mode == "search" else None, mode == "updates")
    if mode == "updates":
        return []
    if mode == "search":
        local = [x for x in appimage_items() if query.casefold() in x["name"].casefold()]
        return local + appimage_catalog(query)
    return appimage_items()


def listing(request):
    mode = request.get("mode", "installed")
    if mode not in ("search", "installed", "updates"):
        raise StoreError("Unknown store view.")
    query = request.get("query", "").strip()[:200]
    if request.get("source", "all") not in ("all", "deb", "flatpak", "snap", "appimage"):
        raise StoreError("Unknown software source.")
    sources = [request["source"]] if request.get("source", "all") != "all" else ["deb", "flatpak", "snap", "appimage"]
    items, warnings = [], []
    if mode == "search" and len(query) < 2:
        return {"items": [], "warnings": [], "message": "Type at least two characters to search your configured sources."}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(inventory_provider, s, mode, query): s for s in sources}
        for future in concurrent.futures.as_completed(futures):
            source = futures[future]
            try:
                items.extend(future.result())
            except Exception as e:
                warnings.append(source + ": " + str(e))
    items.sort(key=lambda x: (x["name"].casefold(), x["source"], x.get("scope", "")))
    total = len(items)
    # Filtering installed packages is local and does not invoke a package solver.
    if mode == "installed" and query:
        items = [x for x in items if query.casefold() in (x["name"] + " " + x.get("summary", "")).casefold()]
    return {"items": items[:300], "warnings": warnings, "total": total,
            "message": "Showing up to 300 entries. Search to narrow the list." if len(items) > 300 else ""}


def dispatch(request):
    op = request.get("op")
    if op == "list":
        return listing(request)
    if op == "refresh_appimage_metadata":
        return {"item": refresh_appimage_metadata(request["id"]), "message": "AppImage details refreshed."}
    if op == "catalog_link":
        return {"url": appimage_catalog_link(request["target"])}
    if op == "inspect":
        return {"item": inspect_local(request["path"])}
    if op == "plan":
        return {"plan": plan(request["target"], request["action"])}
    if op == "apply":
        return apply(request["plan"])
    if op == "refresh_flatpak":
        for scope in ("user", "system"):
            if run(["flatpak", "--" + scope, "remotes", "--columns=name"]).strip():
                stream_command(["flatpak", "--" + scope, "update", "--appstream", "--noninteractive"])
        return {"message": "Flatpak catalog metadata refreshed."}
    if op == "refresh":
        PackageKit().transaction("RefreshCache", "(b)", (True,))
        return {"message": "Debian package metadata refreshed."}
    raise StoreError("Unknown store operation.")


def main():
    try:
        request = json.loads(sys.stdin.readline(1024 * 1024))
        emit(dict(event="result", ok=True, **dispatch(request)))
    except Exception as e:
        emit({"event": "result", "ok": False, "error": str(e)})
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
