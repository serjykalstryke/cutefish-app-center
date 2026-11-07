#!/usr/bin/python3
"""Unprivileged store providers. stdin request -> NDJSON progress + result.

No shell, sudo, root helper or arbitrary executable from a request. Debian
transactions belong to PackageKit and Snap transactions belong to snapd.
"""
from __future__ import annotations
import base64
import concurrent.futures
import contextlib
import configparser
import html
from html.parser import HTMLParser
import ipaddress
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
import unicodedata
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

class AppCenterError(Exception):
    pass

class PackageKitFailure(AppCenterError):
    def __init__(self, message, restarts):
        super().__init__(message)
        self.restarts = restarts

def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)

def progress(text, percent=None):
    emit({"event": "progress", "message": text, "percent": percent})

def run(args, timeout=45):
    try:
        p = subprocess.run(args, capture_output=True, text=True, env=ENV,
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise AppCenterError(f"{args[0]} is not installed.") from None
    except subprocess.TimeoutExpired:
        raise AppCenterError(f"{args[0]} did not respond in time.") from None
    if p.returncode:
        raise AppCenterError((p.stderr or p.stdout or f"{args[0]} failed.").strip()[-4000:])
    return p.stdout

def data_home():
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))

def state_dir():
    p = data_home() / "cutefish-app-center"
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p

@contextlib.contextmanager
def mutation_lock():
    with open(state_dir() / "transaction.lock", "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AppCenterError("Another store transaction is running.") from None
        yield

class PackageKit:
    def __init__(self):
        try:
            from gi.repository import Gio, GLib
            self.Gio, self.GLib = Gio, GLib
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except Exception as e:
            raise AppCenterError("Cannot reach the system package service. Install packagekit and python3-gi. " + str(e)) from None

    def call(self, path, iface, method, signature=None, values=()):
        params = self.GLib.Variant(signature, values) if signature else None
        return self.bus.call_sync(PK_NAME, path, iface, method, params, None,
                                 self.Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION,
                                 120000, None).unpack()

    def transaction(self, method, signature, values, report=None):
        try:
            path = self.call(PK_ROOT, PK_NAME, "CreateTransaction")[0]
        except Exception as e:
            raise AppCenterError("The Debian package service is unavailable. Install packagekit and try again. " + str(e)) from None
        packages, errors, restarts = [], [], []
        finished = [None]
        method_replied = False
        method_error = None
        status = 'unknown'
        last_package = ''
        loop = self.GLib.MainLoop()
        if report:
            import ctypes
            lib = ctypes.CDLL('libpackagekit-glib2.so.18')
            status_name = lib.pk_status_enum_to_string
            status_name.argtypes = [ctypes.c_int]
            status_name.restype = ctypes.c_char_p

        def reply(bus, result, _user):
            nonlocal method_replied, method_error
            try:
                bus.call_finish(result)
            except self.GLib.Error as error:
                method_error = str(error)
            method_replied = True
            if method_error or finished[0] is not None:
                loop.quit()

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
                if method_replied:
                    loop.quit()
        def properties(bus, sender, obj, iface, name, params, user):
            nonlocal status, last_package
            changed = params.unpack()[1]
            n = changed.get("Percentage")
            if report and {'Status', 'Percentage', 'LastPackage'} & changed.keys():
                if 'Status' in changed:
                    status = status_name(changed['Status']).decode()
                if 'LastPackage' in changed:
                    last_package = changed['LastPackage'].partition(';')[0]
                phase, message = debian_progress(status, last_package)
                percent = n if phase in ('downloading', 'applying') and n is not None and 0 <= n <= 100 else None
                report(message, percent, phase)
            elif n is not None and 0 <= n <= 100:
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
            # Dispatch status signals while the method is waiting for its reply.
            self.bus.call(PK_NAME, path, PK_IFACE, method, self.GLib.Variant(signature, values), None,
                          self.Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 120000, None, reply, None)
            loop.run()
            if method_error or errors or finished[0] != 1:
                raise PackageKitFailure("; ".join(errors) or method_error or "The package transaction did not complete.", restarts)
            return packages, restarts
        except AppCenterError:
            raise
        except Exception as e:
            raise AppCenterError(str(e)) from None
        finally:
            for sub in subs:
                self.bus.signal_unsubscribe(sub)

    def resolve(self, package, installed=False):
        if not PACKAGE.fullmatch(package):
            raise AppCenterError("Invalid Debian package name.")
        # Filter bits are 1 << enum, not the enum ordinal.
        name, _, requested_arch = package.partition(":")
        packages, _ = self.transaction("Resolve", "(tas)", ((1 << (2 if installed else 3)) | (1 << 16), [name]))
        wanted_arch = requested_arch or run(["dpkg", "--print-architecture"]).strip()
        packages = [p for p in packages if p["id"].split(";")[2] in (wanted_arch, "all")]
        if not packages:
            raise AppCenterError("The package service could not resolve this package. Refresh software sources and try again.")
        if len(packages) != 1:
            raise AppCenterError("More than one package architecture or version matches. Use the system package tools to select one.")
        return packages[0]["id"]


def debian_progress(status, package):
    if status == 'waiting-for-auth':
        return 'authorization', 'Approve the administrator prompt to continue.'
    if status == 'waiting-for-lock':
        return 'waiting', 'Waiting for the Debian package manager to become available.'
    suffix = f' {package}…' if package else ' packages…'
    if status.startswith('download'):
        return 'downloading', 'Downloading' + suffix
    if status in ('install', 'update', 'remove', 'commit', 'cleanup', 'obsolete', 'run-hook'):
        return 'applying', 'Applying changes to' + suffix
    return 'working', 'Preparing Debian package changes…'


def dpkg_installed():
    out = run(["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${db:Status-Status}\t${binary:Summary}\t${Essential}\t${Protected}\t${Architecture}\n"])
    items = []
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) >= 6 and cols[2] == "installed":
            name, version, _, summary, essential, protected = cols[:6]
            items.append(dict(source="deb", id=name, name=name, version=version,
                              summary=summary, installed=True, scope="system",
                              protected=essential == "yes" or protected == "yes", architecture=cols[6] if len(cols)>6 else name.partition(":")[2], icon="application-x-deb"))
    return items


def search_text(value):
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold()))


# These are vocabulary/category mappings, not lists of preferred applications.
# Available applications and their identities always come from the providers.
SEARCH_CATEGORIES = (
    (("browser", "browsers", "web browser", "web browsers", "internet browser", "internet browsers"),
     ("WebBrowser",), "browser", ("web browser", "internet browser", "browse the web", "browse the world wide web", "access the internet", "browse faster")),
    (("image editor", "image editors", "photo editor", "photo editors", "picture editor", "picture editors"),
     ("ImageProcessing", "RasterGraphics", "VectorGraphics"), "image", ("image editor", "photo editor", "graphics editor", "image editing", "photo editing", "image manipulation")),
    (("text editor", "text editors"), ("TextEditor",), "text editor", ("text editor", "text editing")),
    (("video player", "video players", "media player", "media players"),
     ("Player",), "media player", ("video player", "media player", "play video")),
    (("music player", "music players", "audio player", "audio players"),
     ("Player",), "music player", ("music player", "audio player", "play music")),
    (("development", "ide", "ides", "code editor", "code editors", "programming editor", "programming editors"),
     ("IDE", "Development"), "code editor", ("code editor", "development environment", "programming editor")),
    (("internet",), ("Network",), "internet", ("internet", "web browser", "email", "messaging")),
    (("graphics", "photography"), ("Graphics", "Photography", "RasterGraphics", "VectorGraphics"), "graphics", ("graphics", "image editor", "photo editor", "illustration")),
    (("office", "productivity"), ("Office",), "office", ("office", "spreadsheet", "word processor", "presentation")),
    (("audio video", "audio and video", "multimedia"), ("AudioVideo", "Audio", "Video", "Player"), "media", ("audio", "video", "music", "media")),
    (("game", "games"), ("Game",), "game", ("game", "puzzle", "chess")),
    (("education", "learning"), ("Education",), "education", ("educational", "learning", "teaching")),
    (("utility", "utilities"), ("Utility",), "utility", ("utility", "desktop tool")),
)


def search_intent(query):
    normalized = search_text(query)
    return next((entry for entry in SEARCH_CATEGORIES if normalized in entry[0]), None)


def search_lookup(query):
    intent = search_intent(query)
    return intent[2] if intent else query


def search_score(item, query):
    """Exact names/IDs, then app categories, names/keywords and short summaries.

    Long descriptions help ordinary searches, but never establish category
    membership: an editor mentioning a browser should not become a browser.
    """
    normalized = search_text(query)
    if not normalized:
        return 0
    name = search_text(item.get("name", ""))
    identities = [item.get("id", ""), item.get("app_id", "")]
    if normalized == name or any(query.casefold() == x.casefold() for x in identities if x):
        return 1000 + (5 if item.get("installed") else 0) - (15 if item.get("catalog") else 0)
    words = normalized.split()
    def matches(text):
        return all(word in text for word in words)
    summary = search_text(item.get("summary", ""))
    keywords = search_text(" ".join(item.get("keywords", [])))
    identity = search_text(" ".join(identities))
    description = search_text(item.get("description", ""))
    score = (800 if name.startswith(normalized) else 750 if matches(name) else
             700 if matches(identity) else 650 if matches(keywords) else
             500 if matches(summary) else 350 if matches(" ".join((name, summary, keywords))) else
             200 if matches(description) else 0)
    helper = bool(re.search(r"\b(librar(?:y|ies)|development files|debug symbols|language pack|locali[sz]ation|bindings|plugins?|extensions?|transitional package|module|support for|handling support|integration|connector|wrapper|sandbox|webdriver|headless|daemon|minimal shell)\b", summary))
    helper |= bool(re.search(r"(?:-l10n(?:-|$)|-locale(?:-|$)|-(?:dev|doc|dbg|dbgsym|common|data|config|plugins|utils)$|^(?:webext-|elpa-|node-|python[0-9]?-|ruby-|php-|golang-|gir[0-9]|libjs-|lib.*-perl$))", item.get("id", "")))
    intent = search_intent(query)
    if intent:
        categories = set(item.get("categories", []))
        category_match = bool(categories.intersection(intent[1]))
        # The Player category is shared by audio and video applications.
        if intent[2] == "music player" and "Video" in categories and "Audio" not in categories:
            category_match = False
        purpose = any(phrase in " ".join((name, summary)) for phrase in intent[3])
        if intent[2] == "image" and categories.intersection(("Viewer", "Game", "Office", "Scanning")) and not purpose:
            category_match = False
        if intent[2] == "browser" and not category_match and re.search(r"\b(?:(?:for|in|of|with|using|to) (?:your |the |a )?web browsers?|irc client|web server)\b", summary):
            purpose = False
        if not (category_match or purpose) or (helper and not item.get("desktop_app")):
            return 0
        confidence = 30 if category_match and item.get("desktop_app") else 0
        if purpose or "x-scheme-handler/https" in item.get("mediatypes", []):
            confidence += 10
        score = max(score, 850 + confidence)
        # Browser launchers, bookmark tools, etc. can share WebBrowser metadata.
        if re.search(r"\b(launcher|bookmark|downloader|manager|torrent|installer)\b", name + " " + summary):
            score -= 200
        if re.search(r"\b(text mode|text based|terminal based|non graphical|framebuffer)\b", summary):
            score -= 100
    elif helper and not item.get("desktop_app"):
        score = max(1, score - 300) if score else 0
    if not score:
        return 0
    if re.search(r"\b(nightly|beta|unstable|canary|development build)\b", name):
        score -= 40
    if item.get("catalog"):
        score -= 15
    return score + (5 if item.get("installed") else 0)


def ranked_search(items, query, limit=LIMIT):
    scored = [(search_score(item, query), item) for item in items]
    scored = [(score, item) for score, item in scored if score > 0]
    scored.sort(key=lambda pair: (-pair[0], search_text(pair[1]["name"]),
                pair[1]["source"], pair[1].get("scope", ""), pair[1].get("remote", ""),
                pair[1].get("branch", ""), pair[1].get("arch", ""), pair[1]["id"]))
    return [item for _, item in scored[:limit]]


def application_ids(item):
    """Catalog identity is a browsing hint, never a package transaction target."""
    values = [item.get('app_id', '')] + item.get('desktop_ids', []) + item.get('common_ids', [])
    if item['source'] == 'flatpak':
        values.append(item['id'])
    return {v.casefold().removesuffix('.desktop') for v in values
            if isinstance(v, str) and APPID.fullmatch(v)}


def application_title_aliases(value, legacy_id=False):
    name = search_text(value)
    names = {name}
    # Presentation suffixes do not distinguish a separate application. Edition
    # words (ESR, beta, nightly, etc.) remain part of the name.
    suffixes = (' web browser', ' desktop application', ' desktop client')
    if legacy_id:
        suffixes += (' browser',)
    for suffix in suffixes:
        if name.endswith(suffix) and len(name) > len(suffix):
            names.add(name[:-len(suffix)])
            break
    return {n.replace(' ', '') for n in names if n}


def application_aliases(item):
    name = search_text(item.get('name', ''))
    aliases = application_title_aliases(name)
    if item['source'] in ('deb', 'snap'):
        ident = item['id'].split(':')[0]
        if ident.endswith('-stable'):
            ident = ident[:-7]
        aliases.add(search_text(ident).replace(' ', ''))
    # A descriptive final component (com.brave.Browser) is not a project name.
    generic = {'app', 'application', 'browser', 'desktop', 'client', 'player', 'editor'}
    for ident in application_ids(item):
        parts = ident.split('.')
        token = search_text(parts[-1]).replace(' ', '')
        if len(parts) > 2 and token in generic:
            token = search_text(parts[-2]).replace(' ', '')
        if len(token) >= 4 and any(token == word for word in name.split()):
            aliases.add(token)
    return {a for a in aliases if len(a) >= 3}


def search_variant_key(item):
    return tuple(str(item.get(k, '')) for k in
                 ('source', 'id', 'scope', 'remote', 'branch', 'arch', 'architecture', 'channel', 'path', 'catalog'))


def group_search_results(items, limit=300):
    """Group application presentations; retain every exact installation choice.

    Explicit AppStream/desktop/common IDs join first. Exact name/package aliases
    fill gaps only where they identify one catalog identity unambiguously. Two
    unrelated reverse-DNS identities sharing a title remain separate. No fuzzy
    matching, app-name whitelist, or network lookup is needed per result.
    """
    unique = {}
    for item in items:
        key = search_variant_key(item)
        if key not in unique:
            unique[key] = dict(item)
        elif item.get('installed'):
            unique[key]['installed'] = True
    records = list(unique.values())
    parents = list(range(len(records)))
    def root(n):
        while parents[n] != n:
            parents[n] = parents[parents[n]]
            n = parents[n]
        return n
    def join(a, b):
        a, b = root(a), root(b)
        if a != b:
            parents[max(a, b)] = min(a, b)
    ids = [application_ids(i) for i in records]
    known = {}
    for n, values in enumerate(ids):
        for ident in sorted(values):
            if ident in known:
                join(n, known[ident])
            else:
                known[ident] = n
    aliases, anchored = {}, set()
    for n, item in enumerate(records):
        # A library/helper with no application metadata is still searchable by
        # package name, but must not become an alternative installer for an app.
        if item['source'] == 'deb' and not (item.get('desktop_app') or item.get('is_application')):
            continue
        names = application_aliases(item)
        edition_text = item.get('name', '') + ' ' + (item['id'] if item['source'] in ('deb', 'snap') else '')
        edition = tuple(sorted(set(search_text(edition_text).split()) & {'esr', 'beta', 'nightly', 'unstable', 'canary'}))
        for alias in names:
            aliases.setdefault((edition, alias), set()).add(root(n))
        titles = application_title_aliases(item.get('name', ''))
        legacy_title_match = any(application_title_aliases(ident, legacy_id=True) & titles for ident in ids[n])
        if any(ident.count('.') >= 2 for ident in ids[n]) or (ids[n] and not legacy_title_match):
            anchored.add(root(n))
    # Decide ambiguity against the explicit-ID graph, before weak joins can
    # turn an unknown-name record into a bridge between different applications.
    ambiguous = {alias for alias, roots in aliases.items() if len(roots & anchored) > 1}
    proposals = {}
    for alias, roots in aliases.items():
        if alias in ambiguous:
            continue
        anchors = roots & anchored
        if anchors:
            anchor = next(iter(anchors))
            for candidate in roots - anchors:
                proposals.setdefault(candidate, set()).add(anchor)
    for candidate, anchors in proposals.items():
        if len(anchors) == 1:
            join(candidate, next(iter(anchors)))
    for alias, roots in sorted(aliases.items()):
        if alias in ambiguous or roots & anchored:
            continue
        # Unknown records which also match competing known identities stay
        # independent instead of indirectly connecting those identities.
        safe = [n for n in sorted(roots) if len(proposals.get(n, set())) <= 1]
        if safe:
            for n in safe[1:]:
                a, b = root(safe[0]), root(n)
                a_anchors = {root(x) for x in anchored if root(x) == a}
                b_anchors = {root(x) for x in anchored if root(x) == b}
                if a_anchors and b_anchors and a != b:
                    continue
                join(a, b)
    groups = {}
    for n, item in enumerate(records):
        groups.setdefault(root(n), []).append(item)
    result = []
    for choices in list(groups.values())[:limit]:
        all_ids = set().union(*(application_ids(i) for i in choices))
        canonical = sorted(all_ids, key=lambda value: (value.count('.') < 2, value))
        key = 'app:' + canonical[0] if canonical else 'listing:' + hashlib.sha256(
            json.dumps(sorted(search_variant_key(i) for i in choices)).encode()).hexdigest()
        # Friendly catalog identity is independent of the selected packaging.
        display = min(choices, key=lambda i: (not bool(i.get('desktop_app')), '_' in i['name'],
                      i['name'].islower(), {'flatpak':0, 'deb':1, 'snap':2, 'appimage':3}[i['source']], i['name']))
        art = next((i for i in [display] + choices if i.get('icon') and not i['icon'].startswith('application-x-')), display)
        sources = [name for source, name in [('deb','Debian'),('flatpak','Flatpak'),('snap','Snap'),('appimage','AppImage')]
                   if any(i['source'] == source for i in choices)]
        choices.sort(key=lambda i: (not bool(i.get('installed')), i.get('branch', 'stable') != 'stable',
                     {'deb':0, 'flatpak':1, 'snap':2, 'appimage':3}[i['source']], search_variant_key(i)))
        for item in choices:
            item.update(application_key=key, application_name=display['name'].replace('_', ' '),
                        application_summary=display.get('summary', ''), application_icon=art.get('icon', ''),
                        application_icon_key=art.get('icon_key', ''), application_sources=' · '.join(sources),
                        application_installed=any(i.get('installed') for i in choices),
                        search_key=hashlib.sha256(json.dumps(search_variant_key(item)).encode()).hexdigest())
        result.extend(choices)
    return result, len(groups)


class PlainDescription(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if not self.hidden and tag in ("p", "div", "br", "li", "ul", "ol"):
            self.parts.append("\n" + ("• " if tag == "li" else ""))
    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in ("p", "div", "li"):
            self.parts.append("\n")
    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def description_text(value):
    parser = PlainDescription()
    parser.feed(value[:60000])
    text = "".join(parser.parts)
    text = re.sub(r"\[([^\]\n]+)\]\(https?://[^)]+\)", r"\1", text)
    text = re.sub(r"(?m)^\s*#{1,6}\s+", "", text).replace("**", "").replace("__", "")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n\n".join(line for line in lines if line)[:12000]


def component_text(node, tag):
    elements = node.findall(tag)
    english = (None, "en", "en-US", "en_GB", "en-GB")
    for language in english:
        for element in elements:
            if element.get("{http://www.w3.org/XML/1998/namespace}lang") == language:
                return " ".join(element.itertext()).strip()
    return ""


def component_artwork(node, path):
    result = {}
    for icon in node.findall("icon"):
        name = icon.text or ""
        if icon.get("type") == "cached" and PurePosixPath(name).name == name:
            for resolution in ("128x128", "64x64", "48x48"):
                candidate = path.parent / "icons" / resolution / name
                if candidate.is_file():
                    result["icon"] = str(candidate)
                    break
        if icon.get("type") == "remote" and name.startswith("https://"):
            result["icon_url"] = name
    shots = []
    for shot in sorted(node.findall("screenshots/screenshot"), key=lambda e: e.get("type") != "default"):
        images = [image for image in shot.findall("image") if (image.text or "").startswith("https://")]
        # Prefer a medium thumbnail over a multi-megabyte original image.
        def image_size(image):
            try:
                return abs(int(image.get("width", "100000")) - 752)
            except ValueError:
                return 100000
        if images:
            chosen = min(images, key=image_size)
            shots.append(dict(url=chosen.text, caption=component_text(shot, "caption")[:500]))
    result["screenshot_urls"] = shots[:3]
    return result


def appstream_components(paths):
    """Read desktop application metadata only. Never load add-ons as apps."""
    result = []
    for path in sorted(set(paths)):
        try:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rb") as f:
                for _, node in ET.iterparse(f, events=("end",)):
                    if node.tag != "component":
                        continue
                    if node.get("type") in ("desktop-application", "desktop"):
                        def text(tag):
                            return component_text(node, tag)
                        descriptions = [e for e in node.findall("description") if not e.attrib]
                        description = description_text(ET.tostring(descriptions[0], encoding="unicode")) if descriptions else ""
                        result.append(dict(name=text("name"), summary=text("summary"),
                            description=description, app_id=node.findtext("id", ""),
                            publisher=text("developer/name") or text("developer_name"),
                            license=node.findtext("project_license", ""),
                            homepage=next((e.text for e in node.findall("url") if e.get("type") == "homepage"), ""),
                            desktop_ids=[e.text for e in node.findall("launchable") if e.get("type") == "desktop-id" and e.text],
                            pkgname=node.findtext("pkgname", ""),
                            flatpak_ref=next((e.text for e in node.findall("bundle") if e.get("type") == "flatpak"), ""),
                            version=next((e.get("version", "") for e in node.findall("releases/release")), ""),
                            categories=[e.text for e in node.findall("categories/category") if e.text],
                            keywords=[e.text for group in node.findall("keywords") if not group.attrib
                                      for e in group.findall("keyword") if e.text and not e.attrib],
                            mediatypes=[e.text for e in node.findall("provides/mediatype") if e.text],
                            desktop_app=True,
                            icon=next((e.text for e in node.findall("icon") if e.get("type") == "stock" and e.text), "application-x-executable")))
                        result[-1].update(component_artwork(node, path))
                    node.clear()
        except (OSError, ET.ParseError):
            continue
    return result


def distribution_appstream(pool=None):
    """Use libappstream's OS catalog and icon cache, including Debian DEP-11.

    Flatpak metadata and installed desktop files are deliberately excluded:
    Debian records must retain their own repository/package identity.
    """
    try:
        import gi
        gi.require_version('AppStream', '1.0')
        from gi.repository import AppStream as As, GLib
    except (ImportError, ValueError):
        return {}
    try:
        if pool is None:
            pool = As.Pool()
            pool.set_locale('C')
            pool.set_flags(As.PoolFlags.LOAD_OS_CATALOG)
            pool.load(None)
        result = {}
        components = pool.get_components_by_kind(As.ComponentKind.DESKTOP_APP).as_array()
        for component in sorted(components, key=lambda c: c.get_id() or ''):
            packages = [name for name in component.get_pkgnames() if PACKAGE.fullmatch(name)]
            if not packages:
                continue
            developer = component.get_developer()
            launchable = component.get_launchable(As.LaunchableKind.DESKTOP_ID)
            provided = component.get_provided_for_kind(As.ProvidedKind.MEDIATYPE)
            item = dict(name=component.get_name() or '', summary=component.get_summary() or '',
                        description=description_text(component.get_description() or ''),
                        app_id=component.get_id(), publisher=developer.get_name() if developer else '',
                        license=component.get_project_license() or '',
                        homepage=component.get_url(As.UrlKind.HOMEPAGE) or '',
                        desktop_ids=launchable.get_entries() if launchable else [],
                        categories=component.get_categories(), keywords=component.get_keywords(),
                        mediatypes=provided.get_items() if provided else [], desktop_app=True,
                        icon='application-x-deb', screenshot_urls=[])
            # A stock theme icon often exists only after the app is installed.
            # Repository cache files work before installation and offline.
            icons = sorted(component.get_icons(), key=lambda i: (
                abs(i.get_width() * i.get_scale() - 128), i.get_name() or ''))
            for icon in icons:
                filename = icon.get_filename()
                if icon.get_kind() in (As.IconKind.CACHED, As.IconKind.LOCAL) and filename and Path(filename).is_file():
                    item['icon'] = filename
                    break
            else:
                stock = next((i.get_name() for i in icons if i.get_kind() == As.IconKind.STOCK and i.get_name()), '')
                if stock:
                    item['icon'] = stock
            remote = next((i.get_url() for i in icons if i.get_kind() == As.IconKind.REMOTE
                           and (i.get_url() or '').startswith('https://')), '')
            if remote and not Path(item['icon']).is_absolute():
                item['icon_url'] = remote
            for shot in sorted(component.get_screenshots_all(), key=lambda x: x.get_kind() != As.ScreenshotKind.DEFAULT):
                images = [i for i in shot.get_images() if (i.get_url() or '').startswith('https://')]
                if images:
                    image = min(images, key=lambda i: abs((i.get_width() or 100000) - 752))
                    item['screenshot_urls'].append(dict(url=image.get_url(), caption=(shot.get_caption() or '')[:500]))
                if len(item['screenshot_urls']) == 3:
                    break
            for package in packages:
                result.setdefault(package, item)
        return result
    except GLib.Error:
        # Missing or incomplete metadata must not break APT package management.
        return {}


def appstream():
    """Read distribution metadata if present; APT summaries remain a fallback."""
    metadata = distribution_appstream()
    if metadata:
        return metadata
    paths = []
    for directory in ("/var/lib/swcatalog/xml", "/var/cache/swcatalog/xml", "/usr/share/swcatalog/xml", "/var/cache/app-info/xmls"):
        paths += list(Path(directory).glob("*.xml*"))
    return {item["pkgname"]: {k: v for k, v in item.items() if k not in ("pkgname", "flatpak_ref", "version")}
            for item in appstream_components(paths)
            if PACKAGE.fullmatch(item["pkgname"])}


def flatpak_appstream(scope, arch):
    root = (Path(os.environ.get("FLATPAK_USER_DIR", data_home() / "flatpak")) if scope == "user"
            else Path(os.environ.get("FLATPAK_SYSTEM_DIR", "/var/lib/flatpak")))
    result = {}
    for directory in (root / "appstream").glob("*/" + arch + "/active"):
        path = directory / "appstream.xml"
        if not path.is_file():
            path = directory / "appstream.xml.gz"
        remote = directory.parent.parent.name
        for item in appstream_components([path]):
            parts = item["flatpak_ref"].split("/")
            if len(parts) == 4 and parts[0] == "app" and parts[2] == arch:
                result[(parts[1], arch, parts[3], remote)] = item
    return result


def deb_search(query):
    if len(query) < 2:
        return []
    # Search summaries as well as names; escape each literal term for APT's regex.
    out = run(["apt-cache", "search", "--"] + [re.escape(w) for w in search_lookup(query).split()], timeout=30)
    installed = {x["id"].split(":")[0]: x for x in dpkg_installed()}
    metadata = appstream()
    candidates = {}
    for line in out.splitlines():
        name, sep, summary = line.partition(" - ")
        if not sep or not PACKAGE.fullmatch(name):
            continue
        candidates[name] = summary
    # Category/name/keyword matches need not occur in a Debian package name or
    # its short summary. Join them to packages actually offered by this system.
    matches = {pkg for pkg, meta in metadata.items() if search_score(dict(meta, id=pkg), query)}
    if matches:
        available = set(run(["apt-cache", "pkgnames"]).splitlines())
        candidates.update({pkg: metadata[pkg]["summary"] for pkg in matches & available})
    items = []
    for name, summary in candidates.items():
        item = dict(source="deb", id=name, name=name, summary=summary, scope="system",
                    installed=name in installed, version=installed.get(name, {}).get("version", ""), icon="application-x-deb")
        item.update({k: v for k, v in metadata.get(name, {}).items() if v or k != "version"})
        items.append(item)
    missing = [i for i in items if i['installed'] and not i.get('desktop_app')]
    if missing:
        launchers = debian_desktop_packages()
        for item in missing:
            item.update(launchers.get(item['id'], {}))
    return ranked_search(items, query)

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
            raise AppCenterError(payload.get("result", {}).get("message", "Snap service request failed."))
        return payload
    except AppCenterError:
        raise
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise AppCenterError("Cannot reach snapd: " + str(e)) from None
    finally:
        conn.close()

def snap_items(query=None, updates=False, limit=LIMIT):
    if query is not None:
        path = "/v2/find?" + urllib.parse.urlencode({"q": search_lookup(query)})
    elif updates:
        path = "/v2/find?select=refresh"
    else:
        path = "/v2/snaps"
    data = snap_api(path)["result"]
    installed_records = {x['name']: x for x in (snap_api('/v2/snaps')['result'] if query is not None or updates else data)}
    installed = set(installed_records)
    items = [dict(source="snap", id=x["name"], name=x.get("title") or x["name"],
                 summary=x.get("summary", ""), version=x.get("version", ""),
                 description=x.get("description", "")[:4000],
                 installed=x["name"] in installed or (query is None and not updates),
                 scope="system", channel=x.get("channel", "stable"),
                 confinement=x.get("confinement", "strict"), snap_type=x.get("type", "app"), revision=str(x.get("revision", "")), icon="application-x-executable")
             for x in data if query is None or x.get("type", "app") == "app"]
    items = ranked_search(items, query) if query is not None else items[:limit] if limit else items
    for item in items:
        item['installed_revision'] = str(installed_records.get(item['id'], {}).get('revision', ''))
        item['installed_version'] = installed_records.get(item['id'], {}).get('version', '')
    records = {x['name']: x for x in data}
    for item in items:
        common = records[item['id']].get('common-ids', [])
        item['common_ids'] = [v for v in common if isinstance(v, str) and APPID.fullmatch(v)] if isinstance(common, list) else []
    return [catalog_icon(item, snap_artwork_locator(records[item['id']], installed_records.get(item['id']))) for item in items]


def flatpak_items(query=None, updates=False):
    if not shutil.which("flatpak"):
        raise AppCenterError("Flatpak is not installed. Install flatpak and configure a remote such as Flathub.")
    items = []
    for scope in ("user", "system"):
        if query is not None:
            args = ["search", "--columns=application,name,description,version,branch,remotes", "--", search_lookup(query)]
        elif updates:
            args = ["remote-ls", "--updates", "--app", "--columns=application,name,description,version,branch,origin,arch"]
        else:
            args = ["list", "--app", "--columns=application,name,description,version,branch,origin,arch"]
        out = run(["flatpak", "--" + scope] + args, timeout=90)
        installed = set()
        native_arch = ""
        metadata = {}
        scope_items = {}
        if query is not None:
            native_arch = run(["flatpak", "--default-arch"]).strip()
            installed = {tuple(line.split("\t")) for line in run(["flatpak", "--" + scope, "list", "--app", "--columns=application,branch,origin,arch"]).splitlines()}
            # Search includes add-ons and runtimes, which cannot be installed as
            # app/ refs. Keep only exact application refs advertised by a remote.
            app_refs = {tuple(line.split("\t")) for line in run([
                "flatpak", "--" + scope, "remote-ls", "--app", "--cached",
                "--columns=application,arch,branch,origin"]).splitlines()}
            metadata = flatpak_appstream(scope, native_arch)
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
                item = dict(source="flatpak", id=appid, name=name, summary=summary,
                                  version=version, branch=branch, remote=remote, scope=scope,
                                  arch=cols[6] if len(cols) > 6 else native_arch,
                                  installed=query is None or (appid, branch, remote, native_arch) in installed, icon="application-x-executable")
                key = (appid, item["arch"], branch, remote)
                # Keep CLI display/version fields; supplement with search metadata.
                item.update({k: v for k, v in metadata.get(key, {}).items()
                             if k not in ("name", "summary", "version")})
                scope_items[key] = item
        if query is not None:
            for key, meta in metadata.items():
                if key in scope_items or key not in app_refs:
                    continue
                appid, arch, branch, remote = key
                item = dict(meta, source="flatpak", id=appid, scope=scope, remote=remote,
                            arch=arch, branch=branch, installed=(appid, branch, remote, arch) in installed)
                if search_score(item, query):
                    scope_items[key] = item
        items.extend(scope_items.values())
    return ranked_search(items, query) if query is not None else items[:LIMIT]


def flatpak_permissions(metadata):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read_string(metadata)
    except configparser.Error as e:
        raise AppCenterError("Could not read this Flatpak's access metadata: " + str(e)) from None
    if "Application" not in parser:
        raise AppCenterError("This result is a Flatpak runtime or extension, not an application.")
    sections = []
    for name in ("Context", "Session Bus Policy", "System Bus Policy"):
        if parser.has_section(name):
            sections.append(name + ":\n" + "\n".join(k + "=" + v for k, v in parser.items(name)))
    return "\n\n".join(sections) or "No additional static access declarations were reported. Runtime portal requests may still occur."


APPIMAGE_FEED = "https://appimage.github.io/feed.json"
CATALOG_MAX_BYTES = 12 * 1024 * 1024

def appimage_feed():
    cache_dir = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "cutefish-app-center"
    cache = cache_dir / "appimage-feed.json"
    try:
        if cache.is_file() and time.time() - cache.stat().st_mtime < 86400:
            data = json.loads(cache.read_text())
            if isinstance(data.get("items"), list):
                return data["items"]
    except (OSError, ValueError, AttributeError):
        pass
    try:
        req = urllib.request.Request(APPIMAGE_FEED, headers={"User-Agent": "CutefishAppCenter/0.3.3"})
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read(CATALOG_MAX_BYTES + 1)
        if len(raw) > CATALOG_MAX_BYTES:
            raise AppCenterError("The AppImage catalog exceeded its size limit.")
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise AppCenterError("The AppImage catalog has an unsupported format.")
    except (OSError, ValueError) as e:
        raise AppCenterError("Could not load the AppImage catalog. Imported files are still available under Installed. " + str(e)) from None
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
    result, artwork = [], {}
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
        result.append(dict(source="appimage", id=hashlib.sha256(name.encode()).hexdigest(),
                           name=name, summary=summary[:1500], scope="catalog", installed=False,
                           categories=[x for x in (entry.get("categories") or []) if isinstance(x, str)],
                           catalog=True, icon="application-x-executable",
                           catalog_url="https://appimage.github.io/" + urllib.parse.quote(name, safe="") + "/"))
        artwork[result[-1]['id']] = appimage_artwork_locator(entry)
    return [catalog_icon(item, artwork[item['id']]) for item in ranked_search(result, query)]


def appimage_catalog_link(target):
    # Reconstruct a known catalog URL, never pass arbitrary URI schemes to a launcher.
    name = target.get("name", "")
    if (not isinstance(name, str) or not name or len(name) > 300 or
            hashlib.sha256(name.encode()).hexdigest() != target.get("id")):
        raise AppCenterError("Invalid AppImage catalog entry.")
    return "https://appimage.github.io/" + urllib.parse.quote(name, safe="") + "/"


def appimage_items():
    migrate_legacy_library()
    result = []
    for p in (data_home() / "cutefish-app-center/appimages").glob("*/metadata.json"):
        try:
            item = json.loads(p.read_text())
            if item.get("id") == p.parent.name and re.fullmatch(r"[a-f0-9]{64}", item["id"]):
                if item.get('metadata_version', 0) < APPIMAGE_METADATA_VERSION:
                    try:
                        item = refresh_appimage_metadata(item['id'])
                    except (AppCenterError, OSError):
                        pass
                result.append(item)
        except (OSError, ValueError, KeyError):
            continue
    return result


def inspect_local(filename):
    path = Path(filename).expanduser().resolve(strict=True)
    if not path.is_file():
        raise AppCenterError("Choose a regular local file.")
    if path.suffix.lower() == ".deb":
        fields = run(["dpkg-deb", "--show", "--showformat=${Package}\t${Version}\t${Architecture}\t${Description}\n", str(path)]).split("\t", 3)
        if len(fields) != 4 or not PACKAGE.fullmatch(fields[0]):
            raise AppCenterError("This file is not a valid Debian package.")
        return dict(source="deb", id=fields[0], name=fields[0], version=fields[1],
                    architecture=fields[2], summary=fields[3].strip(), scope="system", path=str(path),
                    sha256=file_hash(path), installed=False, icon="application-x-deb")
    with path.open("rb") as f:
        header = f.read(11)
    if header[:4] != b"\x7fELF" or header[8:11] not in (b"AI\x01", b"AI\x02"):
        raise AppCenterError("Choose a valid .deb or AppImage file. This file does not have an AppImage header.")
    return dict(source="appimage", id=file_hash(path), name=path.stem,
                summary="Local AppImage • publisher not verified • updates managed by its publisher",
                path=str(path), scope="user", installed=False, icon="application-x-executable")


def file_hash(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def validate_target(target):
    source = target.get("source")
    if source not in ("deb", "flatpak", "snap", "appimage"):
        raise AppCenterError("Unknown software source.")
    ident = target.get("id", "")
    pattern = PACKAGE if source == "deb" else APPID
    if not pattern.fullmatch(ident):
        raise AppCenterError("Invalid software identifier.")
    if source == "flatpak":
        if target.get("scope") not in ("user", "system"):
            raise AppCenterError("Choose a Flatpak installation scope.")
        for field in ("branch", "remote"):
            if not APPID.fullmatch(target.get(field, "")):
                raise AppCenterError("Invalid Flatpak " + field)
        if target.get("arch") and not APPID.fullmatch(target["arch"]):
            raise AppCenterError("Invalid Flatpak architecture.")
    if source == "appimage" and not re.fullmatch(r"[a-f0-9]{64}", ident):
        raise AppCenterError("Invalid AppImage identifier.")


def pk_args(target, action, flags):
    pk = PackageKit()
    if target.get("path"):
        if action != "install":
            raise AppCenterError("Local packages can only be installed from a file.")
        checked = inspect_local(target["path"])
        if checked["source"] != "deb" or checked["sha256"] != target.get("sha256"):
            raise AppCenterError("The local package changed. Open it again before installing.")
        return pk, "InstallFiles", "(tas)", (flags & ~2, [checked["path"]])
    if action == "update":
        matches = [package['id'] for package, _ in debian_update_candidates(pk)
                   if package['id'] == target.get('package_id') and package.get('info') != 'blocked']
        if len(matches) != 1:
            raise AppCenterError("This update changed or is no longer available. Reload updates and try again.")
        pid = matches[0]
    else:
        pid = pk.resolve(target["id"], installed=action == "remove")
    if action == "remove":
        return pk, "RemovePackages", "(tasbb)", (flags, [pid], True, False)
    return pk, "UpdatePackages" if action == "update" else "InstallPackages", "(tas)", (flags, [pid])


def plan(target, action):
    validate_target(target)
    if action not in ("install", "remove", "update"):
        raise AppCenterError("Unsupported software operation.")
    changes = []
    note = ""
    source = target["source"]
    flatpak_group = None
    if source == "deb":
        pk, method, signature, args = pk_args(target, action, 4 | 2)
        changes, _ = pk.transaction(method, signature, args)
        if action == 'update' and not changes:
            raise AppCenterError('Debian prepared no changes for this update. Check for updates again.')
        protected = {i["id"].split(":")[0] for i in dpkg_installed() if i["protected"]}
        if any(c["info"] in ("remove", "removing", "obsolete", "obsoleting") and c["id"].split(";")[0] in protected for c in changes):
            raise AppCenterError("This operation would remove an essential or protected system package.")
        if target.get("path"):
            note = "Local Debian packages can run installation scripts with administrator access. Only install files from a publisher you trust. Dependencies will be resolved by the system package service."
        else:
            note = "The system package service will request administrator authorization if needed."
    elif source == "flatpak":
        ref = flatpak_ref(target)
        if target.get('ref_kind') == 'runtime' and action != 'update':
            raise AppCenterError('Shared Flatpak runtimes can be updated here. Flatpak manages their removal.')
        if action == "install":
            metadata = run(["flatpak", "--" + target["scope"], "remote-info", "--show-metadata", "--", target["remote"], ref])
            permissions = flatpak_permissions(metadata)
            note = "Flatpak may install shared runtimes and extensions. Application access declared by the publisher:\n" + permissions
        else:
            note = "Application data is kept when removing a Flatpak. Shared runtimes may also be updated."
        changes = [{"info": action, "id": ref, "summary": target.get("name", target["id"])}]
        if action == 'update':
            selected = dict(target, arch=target.get('arch') or run(['flatpak', '--default-arch']).strip())
            available = management_flatpaks(updates=True, scopes=(target['scope'],))
            candidate = next((i for i in available if software_key(i)==software_key(selected)), None)
            if candidate is None:
                raise AppCenterError('This Flatpak no longer has an available update. Check for updates again.')
            flatpak_group = flatpak_update_group(target['scope'], [dict(ref=ref)])
            if flatpak_group is None:
                raise AppCenterError('No Flatpak changes remain to apply.')
            changes, note = flatpak_group['changes'], flatpak_group['note']
    elif source == "snap":
        path = "/v2/snaps/" + urllib.parse.quote(target["id"], safe="")
        if action == "install":
            found = snap_api("/v2/find?" + urllib.parse.urlencode({"name": target["id"]}))["result"]
            if len(found) != 1:
                raise AppCenterError("Snap is no longer available.")
            confinement = found[0].get("confinement", "strict")
        else:
            record = snap_api(path)["result"]
            if action == 'remove' and record.get('type') in ('base', 'core', 'os', 'snapd', 'kernel', 'gadget'):
                raise AppCenterError('This is a protected Snap system component.')
            confinement = record.get("confinement", "strict")
        if confinement == "devmode":
            raise AppCenterError("Developer mode snaps are not supported by this version.")
        target = dict(target, confinement=confinement)
        note = ("Classic confinement: this app has broad access to your files and system, similar to a native application." if confinement == "classic" else "This snap uses strict confinement.")
        note += " Snapd manages shared bases, dependencies, automatic refreshes and removal snapshots."
        changes = [{"info": action, "id": target["id"], "summary": target.get("name", target["id"])}]
    else:
        if action == "update":
            raise AppCenterError("This AppImage has no store-managed update source. Download a new version from its publisher and import it.")
        if action == "install":
            checked = inspect_local(target.get("path", ""))
            if checked["source"] != "appimage" or checked["id"] != target["id"]:
                raise AppCenterError("The AppImage changed. Open it again.")
            note = "The publisher is not verified. AppImages can access your files. Importing copies the file into your store library and adds a menu entry. It will not run the application."
        else:
            note = "Removes the store's copy and menu entry. The original download and application data are kept."
        changes = [{"info": action, "id": target["id"], "summary": target.get("name", target["id"])}]
    result = dict(target=target, action=action, changes=sorted(changes, key=lambda x: (x["id"], x["info"])), note=note)
    if flatpak_group is not None:
        result['flatpak_group'] = flatpak_group
    result["fingerprint"] = fingerprint(result)
    return result


def fingerprint(plan_data):
    # Summaries and display labels are not transaction identity.
    payload = dict(target=plan_data["target"], action=plan_data["action"],
                   changes=[(c["id"], c["info"], c.get('remote', ''), c.get('commit', '')) for c in plan_data["changes"]], note=plan_data["note"],
                   transaction_targets=plan_data.get('flatpak_group', {}).get('targets', []))
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def flatpak_ref(target):
    arch = target.get("arch") or run(["flatpak", "--default-arch"]).strip()
    if not APPID.fullmatch(arch):
        raise AppCenterError("Invalid Flatpak architecture.")
    kind = target.get('ref_kind', 'app')
    if kind not in ('app', 'runtime'):
        raise AppCenterError('Invalid Flatpak reference kind.')
    return kind + "/" + target["id"] + "/" + arch + "/" + target["branch"]


def stream_command(args):
    try:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, env=ENV, stdin=subprocess.DEVNULL)
    except OSError as e:
        raise AppCenterError(str(e)) from None
    tail = []
    for line in process.stdout:
        text = line.strip()
        if text:
            tail.append(text)
            tail = tail[-30:]
            progress(text)
    if process.wait():
        raise AppCenterError("\n".join(tail))


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
        raise AppCenterError('Install squashfs-tools and util-linux to read AppImage artwork.')
    args = ['prlimit', '--fsize=' + str(limit + 1), '--as=536870912', '--cpu=10', '--',
            'unsquashfs', '-processors', '1', '-data-queue', '8', '-frag-queue', '8',
            '-no-progress', '-o', str(offset)] + options + [str(path)] + list(members)
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(args, stdout=output, stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL, env=ENV, timeout=15)
        except subprocess.TimeoutExpired:
            raise AppCenterError('Reading AppImage metadata timed out.') from None
        if result.returncode:
            raise AppCenterError('The embedded metadata could not be read within its limits.')
        output.seek(0)
        data = output.read(limit + 1)
        if len(data) > limit:
            raise AppCenterError('The embedded metadata exceeded its size limit.')
        return data


def archive_member(path):
    value = PurePosixPath(path)
    return (bool(path) and not value.is_absolute() and '..' not in value.parts and
            not any(ord(c) < 32 for c in path) and len(path) < 1024)


def metadata_text(value, length=512):
    # Desktop Entry escapes are separate from INI parsing.
    value = re.sub(r'\\([sntr\\])', lambda m: {'s': ' ', 'n': ' ', 't': ' ', 'r': ' ', '\\': '\\'}[m[1]], value)
    return ' '.join(re.sub(r'[\x00-\x1f\x7f]', ' ', value).split())[:length]


def svg_local_references(value):
    # Gradients/filters in inline CSS can contain several local references.
    # External resources, imports and escaped CSS URLs are not supported.
    if '@import' in value.lower() or '\\' in value:
        return False
    remaining = re.sub(r"url\(\s*(?:#[\w.-]+|'#[\w.-]+'|\"#[\w.-]+\")\s*\)", '', value, flags=re.I)
    return re.search(r'url\s*\(', remaining, re.I) is None


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
                    if not value.startswith('data:image/png;base64,') or len(value) > 2 * 1024 * 1024:
                        return None
                    try:
                        embedded = base64.b64decode(''.join(value.partition(',')[2].split()), validate=True)
                        if not embedded.startswith(b'\x89PNG\r\n\x1a\n') or icon_format(embedded) != 'png':
                            return None
                    except ValueError:
                        return None
                if not svg_local_references(value):
                    return None
            if node.tag.rsplit('}', 1)[-1] == 'style' and not svg_local_references(node.text or ''):
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
            except (AppCenterError, UnicodeError, configparser.Error, KeyError):
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
            except (AppCenterError, OSError, EOFError):
                continue
        if artwork is None:
            fields['metadata_note'] = 'No supported embedded icon was found; a generic icon is used.'
    except (AppCenterError, OSError, ValueError, struct.error):
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
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.cutefish-app-center-')
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
        raise AppCenterError('Invalid AppImage identifier.')
    with mutation_lock():
        dest = state_dir() / 'appimages' / ident
        if dest.is_symlink() or not dest.is_dir():
            raise AppCenterError('This AppImage is not in the managed library.')
        archive = dest / 'application.AppImage'
        if archive.is_symlink() or file_hash(archive) != ident:
            raise AppCenterError('The managed AppImage changed. Import the downloaded file again.')
        old = json.loads((dest / 'metadata.json').read_text())
        meta = appimage_details(old, archive, dest, dest)
        launcher = data_home() / 'applications' / ('org.cutefish.AppCenter.AppImage-' + ident + '.desktop')
        atomic_file(launcher, appimage_launcher(meta), 0o644)
        atomic_file(dest / 'metadata.json', json.dumps(meta))
        return meta


def import_appimage(target):
    migrate_legacy_library()
    checked = inspect_local(target["path"])
    if checked["id"] != target["id"]:
        raise AppCenterError("The AppImage changed. Open it again.")
    root = state_dir() / "appimages"
    root.mkdir(exist_ok=True)
    dest = root / target["id"]
    if dest.exists():
        raise AppCenterError("This AppImage is already imported.")
    staging = Path(tempfile.mkdtemp(prefix=".import-", dir=root))
    launcher = data_home() / "applications" / ("org.cutefish.AppCenter.AppImage-" + target["id"] + ".desktop")
    committed = False
    try:
        shutil.copyfile(checked["path"], staging / "application.AppImage")
        if file_hash(staging / "application.AppImage") != target["id"]:
            raise AppCenterError("The file changed while being copied.")
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
            raise AppCenterError("The software or dependency plan changed. Review the operation again.")
        target, action = current["target"], current["action"]
        source = target["source"]
        restarts = []
        if source == "deb":
            pk, method, sig, args = pk_args(target, action, 2)
            _, restarts = pk.transaction(method, sig, args)
            if action == 'update':
                verify_debian_updates(args[1])
        elif source == "flatpak":
            if action == 'update':
                group = current['flatpak_group']
                flatpak_update_group(target['scope'], group['targets'], approved=group)
            else:
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
                    raise AppCenterError("Invalid change identifier from snapd.")
                while True:
                    change = snap_api("/v2/changes/" + change_id)["result"]
                    tasks = change.get("tasks", [])
                    progress(change.get("summary", "Working with Snap…"))
                    if change.get("ready"):
                        if change.get("err") or change.get("status") != "Done":
                            raise AppCenterError(change.get("err", "Snap transaction did not complete."))
                        break
                    time.sleep(0.7)
        elif action == "install":
            import_appimage(target)
        else:
            dest = state_dir() / "appimages" / target["id"]
            if dest.is_symlink():
                raise AppCenterError("Invalid managed AppImage directory.")
            if not dest.is_dir():
                raise AppCenterError("This AppImage is no longer in the store library.")
            (data_home() / "applications" / ("org.cutefish.AppCenter.AppImage-" + target["id"] + ".desktop")).unlink(missing_ok=True)
            shutil.rmtree(dest)
        restart, notice = restart_notice(restarts)
        return {"message": "Operation completed." + (' ' + notice if notice else ''), "restart": restart}


def inventory_provider(source, mode, query):
    if source == "deb":
        if mode == "search":
            return deb_search(query)
        if mode == "updates":
            return management_provider('deb', updates=True)
        metadata = appstream()
        return [dict(x, **metadata.get(x["id"].split(":")[0], {})) for x in dpkg_installed()]
    if source == "flatpak":
        return flatpak_items(query if mode == "search" else None, mode == "updates")
    if source == "snap":
        return snap_items(query if mode == "search" else None, mode == "updates")
    if mode == "updates":
        return []
    if mode == "search":
        local = ranked_search(appimage_items(), query)
        return local + appimage_catalog(query)
    return appimage_items()


def software_key(item):
    source = item['source']
    if source == 'deb':
        name, _, suffix = item['id'].partition(':')
        return json.dumps([source, name, item.get('architecture') or suffix or 'native'], separators=(',', ':'))
    if source == 'flatpak':
        return json.dumps([source, item['scope'], item.get('ref_kind', 'app'), item['id'], item.get('arch', ''), item['branch'], item['remote']], separators=(',', ':'))
    return json.dumps([source, item.get('scope', 'system'), item['id']], separators=(',', ':'))


def debian_installations():
    installed = {}
    for item in dpkg_installed():
        installed.setdefault(item['id'].split(':')[0], []).append(item)
    return installed


def debian_package_installation(package_id, installed):
    fields = package_id.split(';')
    if len(fields) != 4 or not PACKAGE.fullmatch(fields[0]) or not fields[1] or not fields[2]:
        return None
    name, _, arch, _ = fields
    records = installed.get(name.split(':')[0], [])
    exact = next((item for item in records if item['architecture'] == arch), None)
    if exact is None and len(records) == 1 and 'all' in (arch, records[0]['architecture']):
        # A package may switch between architecture-specific and Architecture: all.
        return records[0]
    return exact


def debian_version_compare(left, operator, right):
    result = subprocess.run(['dpkg', '--compare-versions', left, operator, right],
                            capture_output=True, timeout=5, env=ENV)
    if result.returncode not in (0, 1):
        raise AppCenterError('Could not compare Debian package versions.')
    return result.returncode == 0


def debian_update_candidates(pk):
    packages, _ = pk.transaction('GetUpdates', '(t)', (0,))
    installed = debian_installations()
    for package in packages:
        item = debian_package_installation(package['id'], installed)
        if item is None:
            continue
        version = package['id'].split(';')[1]
        # A repository can contain a separate build with the same version.
        # Update All operates on upgrades, so only show newer Debian versions.
        if version != item['version'] and debian_version_compare(version, 'gt', item['version']):
            yield package, item


def verify_debian_updates(package_ids):
    installed = debian_installations()
    missing = []
    for package_id in package_ids:
        item = debian_package_installation(package_id, installed)
        name, expected, arch, _ = package_id.split(';')
        if item is None or (item['version'] != expected and not debian_version_compare(item['version'], 'ge', expected)):
            missing.append(f'{name} ({arch}, expected {expected})')
    if missing:
        names = ', '.join(missing[:5])
        if len(missing) > 5:
            names += f' and {len(missing) - 5} more'
        raise AppCenterError(f'Debian did not install the reviewed versions for {names}. Check for updates again.')


def management_sources():
    result = ['deb']
    if shutil.which('flatpak'):
        result.append('flatpak')
    if shutil.which('snap') or Path('/run/snapd.socket').exists():
        result.append('snap')
    return result


def desktop_record(path):
    if not visible_desktop(path):
        return None
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(path, encoding='utf-8')
        entry = parser['Desktop Entry']
        return dict(name=metadata_text(entry['Name']), summary=metadata_text(entry.get('Comment', '')),
                    icon=metadata_text(entry.get('Icon', 'application-x-executable'), 1024),
                    desktop_ids=[Path(path).name], desktop_app=True, is_application=True, snap_instance=entry.get('X-SnapInstanceName', ''))
    except (OSError, KeyError, configparser.Error, UnicodeError):
        return None


def debian_desktop_packages():
    """Join visible launchers to package owners in one dpkg query; never run Exec."""
    result = {}
    try:
        ownership = run(['dpkg-query', '--search', '/usr/share/applications/*.desktop'])
    except AppCenterError:
        return result
    for line in ownership.splitlines():
        owners, separator, filename = line.rpartition(': ')
        path = PurePosixPath(filename)
        if not separator or path.parent != PurePosixPath('/usr/share/applications') or path.suffix != '.desktop':
            continue
        record = desktop_record(filename)
        if record:
            for package in owners.split(', '):
                if PACKAGE.fullmatch(package):
                    result.setdefault(package, record)
    return result


def flatpak_api(scope):
    try:
        import gi
        gi.require_version('Flatpak', '1.0')
        from gi.repository import Flatpak, GLib
        installation = Flatpak.Installation.new_user(None) if scope == 'user' else Flatpak.Installation.new_system(None)
        return Flatpak, GLib, installation
    except (ImportError, ValueError) as error:
        raise AppCenterError('Flatpak management needs gir1.2-flatpak-1.0. ' + str(error)) from None


def management_flatpaks(updates=False, refresh=False, scopes=('user', 'system')):
    items = []
    for scope in scopes:
        F, GLib, installation = flatpak_api(scope)
        try:
            if refresh:
                for remote in installation.list_remotes(None):
                    if not remote.get_disabled():
                        installation.update_remote_sync(remote.get_name(), None)
            refs = installation.list_installed_refs_for_update(None) if updates else installation.list_installed_refs(None)
            metadata = {}
            for ref in refs:
                kind = 'app' if ref.get_kind() == F.RefKind.APP else 'runtime'
                ident, arch, branch, remote = ref.get_name(), ref.get_arch(), ref.get_branch(), ref.get_origin()
                if not all(APPID.fullmatch(x or '') for x in (ident, arch, branch, remote)):
                    continue
                if kind == 'app' and arch not in metadata:
                    metadata[arch] = flatpak_appstream(scope, arch)
                item = dict(source='flatpak', id=ident, scope=scope, ref_kind=kind, arch=arch, branch=branch,
                            remote=remote, installed=True, version=ref.get_appdata_version() or '',
                            installed_version=ref.get_appdata_version() or '', name=ref.get_appdata_name() or ident,
                            icon='application-x-executable', summary='Shared Flatpak runtime' if kind == 'runtime' else '',
                            is_application=kind == 'app', installed_commit=ref.get_commit())
                item.update({k: v for k, v in metadata.get(arch, {}).get((ident, arch, branch, remote), {}).items()
                             if k not in ('version', 'name')})
                if updates:
                    item.update(update_available=True, update_version=metadata.get(arch, {}).get((ident, arch, branch, remote), {}).get('version', ''))
                item['install_key'] = software_key(item)
                items.append(item)
        except GLib.Error as error:
            raise AppCenterError(str(error)) from None
    return items


def management_provider(source, updates=False, refresh=False):
    if source == 'flatpak':
        return management_flatpaks(updates, refresh)
    if source == 'deb':
        if updates:
            pk = PackageKit()
            if refresh:
                pk.transaction('RefreshCache', '(b)', (True,))
            metadata = appstream()
            result = []
            for package, installed in debian_update_candidates(pk):
                name, version, _, _ = package['id'].split(';')
                item = dict(installed, **metadata.get(name.split(':')[0], {}))
                item.update(package_id=package['id'], version=version, installed_version=installed['version'],
                            update_version=version, update_available=True, update_blocked=package.get('info') == 'blocked')
                item['is_application'] = bool(item.get('desktop_app'))
                item['install_key'] = software_key(item)
                result.append(item)
            return result
        metadata, desktops = appstream(), debian_desktop_packages()
        items = dpkg_installed()
        for item in items:
            item.update({k: v for k, v in metadata.get(item['id'].split(':')[0], {}).items() if k != 'version'})
            desktop = desktops.get(item['id']) or desktops.get(item['id'].split(':')[0])
            if desktop:
                for key, value in desktop.items():
                    if not item.get('desktop_app') or not item.get(key):
                        item[key] = value
            item['is_application'] = bool(item.get('desktop_app') or desktop)
            item['installed_version'] = item['version']
            item['install_key'] = software_key(item)
        return items
    if source == 'snap':
        items = snap_items(updates=updates, limit=None)
        # Installed exports are positive GUI-app evidence, unlike snap type=app
        # alone, which also covers command-line services and daemon packages.
        desktops = {}
        for path in sorted(Path('/var/lib/snapd/desktop/applications').glob('*.desktop')):
            desktop = desktop_record(str(path))
            if desktop:
                instance = desktop.get('snap_instance') or next((i['id'] for i in sorted(items, key=lambda x:-len(x['id'])) if path.stem.startswith(i['id']+'_')), '')
                if instance:
                    desktops.setdefault(instance, desktop)
        for item in items:
            desktop = desktops.get(item['id'])
            item['is_application'] = item.get('snap_type') == 'app' and bool(desktop)
            item['protected'] = item.get('snap_type') in ('base', 'core', 'os', 'snapd', 'kernel', 'gadget')
            if desktop and item['icon'].startswith('application-x-'):
                item['icon'] = desktop['icon']
            if updates:
                item.update(update_available=True, update_version=item.get('version', ''))
            else:
                item['installed_version'] = item.get('version', '')
            item['install_key'] = software_key(item)
        return items
    items = appimage_items()
    return [dict(item, is_application=True, installed_version=item.get('version', ''), install_key=software_key(item)) for item in items]


def management_inventory(request=None, updates=False):
    request = request or {}
    sources = management_sources() + ([] if updates else ['appimage'])
    items, warnings = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        pending = {executor.submit(management_provider, source, updates, request.get('refresh', False)): source for source in sources}
        for future in concurrent.futures.as_completed(pending):
            try:
                items.extend(future.result())
            except Exception as error:
                warnings.append(pending[future] + ': ' + str(error))
    items.sort(key=lambda i: (i.get('name', i['id']).casefold(), i['install_key']))
    return dict(items=items, warnings=sorted(warnings), complete=not warnings,
                update_count=sum(not item.get('update_blocked') for item in items) if updates else 0)


def changes_identity(changes):
    return sorted((c['info'], c['id'], c.get('remote', ''), c.get('commit', '')) for c in changes)


def update_plan_fingerprint(plan_data):
    # Review labels and download estimates do not determine transaction identity.
    payload = [dict(source=g['source'], scope=g.get('scope', 'system'), targets=g['targets'],
                    changes=changes_identity(g['changes'])) for g in plan_data['groups']]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def check_protected_changes(changes):
    removed = {c['id'].split(';')[0].split(':')[0] for c in changes if c['info'] in ('remove', 'removing', 'obsolete', 'obsoleting')}
    if removed:
        protected = {i['id'].split(':')[0] for i in dpkg_installed() if i.get('protected')}
        if removed & protected:
            raise AppCenterError('These updates would remove an essential or protected system package.')


def debian_update_group(items):
    ids = sorted({i['package_id'] for i in items if not i.get('update_blocked')})
    if not ids:
        return None
    changes, _ = PackageKit().transaction('UpdatePackages', '(tas)', (6, ids))
    if not changes:
        raise AppCenterError('Debian prepared no changes for these updates. Check for updates again.')
    check_protected_changes(changes)
    labels = {i['package_id']: i for i in items}
    for change in changes:
        fields = change['id'].split(';')
        if len(fields) == 4:
            change.update(name=labels.get(change['id'], {}).get('name', fields[0]), version=fields[1])
    return dict(source='deb', scope='system', name='Debian system', targets=ids, changes=changes,
                note='Includes application and system-package updates. Debian resolves and previews required dependency changes.')


def flatpak_operations(transaction):
    result = []
    for operation in transaction.get_operations():
        kind = int(operation.get_operation_type())
        if kind not in (0, 1, 2, 3):
            raise AppCenterError('Unsupported Flatpak update operation.')
        result.append(dict(info={0:'install', 1:'update', 2:'install', 3:'remove'}[kind], id=operation.get_ref(),
                           name=operation.get_ref().split('/')[1], remote=operation.get_remote() or '',
                           commit=operation.get_commit() or '', download_size=operation.get_download_size()))
    return sorted(result, key=lambda c: (c['id'], c['info']))


def flatpak_update_group(scope, targets, approved=None, report=None):
    F, GLib, installation = flatpak_api(scope)
    old_umask = os.umask(0o022)
    state = dict(ready=False, changes=[], error='')
    try:
        tx = F.Transaction.new_for_installation(installation, None)
        tx.set_no_interaction(approved is None)
        tx.add_default_dependency_sources()
        tx.connect('add-new-remote', lambda *_: False)
        tx.connect('choose-remote-for-ref', lambda _tx, _for, _runtime, remotes: 0 if len(remotes)==1 else -1)
        tx.connect('webflow-start', lambda *_: False)
        tx.connect('basic-auth-start', lambda *_: False)
        for target in targets:
            # Resolve the remote commit through the transaction. An installed
            # ref's latest commit may only describe its local repository.
            # The ready callbacks compare exact resolved commits before apply.
            tx.add_update(target['ref'], None, None)
        def ready(transaction):
            try:
                state['changes'] = flatpak_operations(transaction)
                state['ready'] = True
                if approved is not None and changes_identity(state['changes']) != changes_identity(approved['changes']):
                    state['error'] = 'Flatpak dependencies changed. Review all updates again.'
                    return False
                return approved is not None
            except Exception as error:
                state['error'] = str(error)
                return False
        tx.connect('ready-pre-auth', ready)
        # Recheck after authorization as well, before any download/deployment.
        tx.connect('ready', ready)
        def new_operation(_transaction, operation, status):
            ref = operation.get_ref().split('/')[1]
            def changed(p):
                text = p.get_status() or 'Updating ' + ref + '…'
                percent = None if p.get_is_estimating() else p.get_progress()
                if report:
                    report(f'{ref}: {text}', percent)
                else:
                    progress(text, percent)
            status.connect('changed', changed)
            changed(status)
        if approved is not None:
            tx.connect('new-operation', new_operation)
            tx.connect('operation-error', lambda _tx, _op, error, _details: state.update(error=str(error)) or False)
        try:
            tx.run(None)
        except GLib.Error as error:
            if approved is not None or not state['ready']:
                raise AppCenterError(state['error'] or str(error)) from None
        if state['error']:
            raise AppCenterError(state['error'])
        if approved is not None:
            return
        operations = {c['id']: c for c in state['changes']}
        resolved = [dict(ref=t['ref'], commit=operations.get(t['ref'], {}).get('commit') or t.get('commit', '')) for t in targets]
        if not state['changes']:
            return None
        return dict(source='flatpak', scope=scope, name='Flatpak · ' + scope, targets=resolved,
                    changes=state['changes'], note='Includes the listed applications, runtimes and required related components. New software sources are not added.')
    except GLib.Error as error:
        raise AppCenterError(str(error)) from None
    finally:
        os.umask(old_umask)


def snap_update_group(items):
    if not items:
        return None
    targets = sorted([dict(name=i['id'], revision=i.get('revision', ''), installed_revision=i.get('installed_revision', '')) for i in items], key=lambda t:t['name'])
    return dict(source='snap', scope='system', name='Snap system', targets=targets,
                changes=[dict(info='update', id=i['id'], name=i['name'], version=i.get('version', '')) for i in items],
                note='Updates the listed snaps. Snapd resolves any required supporting components when the refresh starts.')


def prepare_all_updates():
    inventory = management_inventory(updates=True)
    if not inventory['complete']:
        raise AppCenterError('Could not check every configured update source. No updates have been applied.\n' + '\n'.join(inventory['warnings']))
    items = [i for i in inventory['items'] if not i.get('update_blocked')]
    if len(items) > 10000:
        raise AppCenterError('Too many updates for one review. Use the system package tools to complete these updates.')
    groups = []
    deb = debian_update_group([i for i in items if i['source']=='deb'])
    if deb:
        groups.append(deb)
    for scope in ('system', 'user'):
        refs = [dict(ref=flatpak_ref(i)) for i in items if i['source']=='flatpak' and i['scope']==scope]
        if refs:
            group = flatpak_update_group(scope, refs)
            if group:
                groups.append(group)
    snap = snap_update_group([i for i in items if i['source']=='snap'])
    if snap:
        groups.append(snap)
    result = dict(groups=groups, count=sum(len(g['targets']) for g in groups),
                  blocked_count=sum(bool(i.get('update_blocked')) for i in inventory['items']),
                  note='Update All covers every configured source, including system packages and runtimes, regardless of the current list filters. AppImages must be updated from their publishers.')
    result['fingerprint'] = update_plan_fingerprint(result)
    return result


def restart_notice(restarts):
    names = set()
    for value in restarts:
        if isinstance(value, str):
            names.add(value)
        else:
            import ctypes
            lib = ctypes.CDLL('libpackagekit-glib2.so.18')
            fn = lib.pk_restart_enum_to_string
            fn.argtypes = [ctypes.c_int]
            fn.restype = ctypes.c_char_p
            names.add((fn(value) or b'unknown').decode())
    if names & {'system', 'security-system'}:
        return True, 'A system restart is required.'
    if names & {'session', 'security-session'}:
        return True, 'Sign out and back in to complete these updates.'
    if 'application' in names:
        return False, 'Restart updated applications to use their new versions.'
    return False, ''


def wait_snap_update(reply, report=None):
    if reply.get('type') != 'async':
        return
    change_id = str(reply.get('change', ''))
    if not change_id.isdigit():
        raise AppCenterError('Invalid Snap update response.')
    while True:
        change = snap_api('/v2/changes/' + change_id)['result']
        if change.get('ready'):
            if change.get('err') or change.get('status') != 'Done':
                raise AppCenterError(change.get('err') or 'Snap updates did not complete.')
            return
        task = next((task for task in change.get('tasks', []) if task.get('status') == 'Doing'), {})
        text = task.get('summary') or change.get('summary', 'Updating software…')
        counts = task.get('progress') or {}
        done, total = counts.get('done'), counts.get('total')
        percent = 100 * done / total if isinstance(done, int) and isinstance(total, int) and 0 <= done <= total and total > 1 else None
        if report:
            report(text, percent, 'downloading' if task.get('kind', '').startswith('download') else 'working')
        else:
            progress('Snap: ' + text, percent)
        time.sleep(0.7)


def apply_all_updates(approved):
    if not isinstance(approved, dict) or not re.fullmatch(r'[a-f0-9]{64}', str(approved.get('fingerprint', ''))):
        raise AppCenterError('Review all updates before applying them.')
    with mutation_lock():
        progress('Checking the reviewed updates…')
        current = prepare_all_updates()
        if current['fingerprint'] != approved['fingerprint']:
            raise AppCenterError('Available updates or dependencies changed. Review all updates again; nothing has been applied.')
        completed, errors, pending, restarts = [], [], [], []
        def notify(index, state, message='', percent=None, phase=''):
            emit(dict(event='update_progress', index=index, state=state, message=message, percent=percent, phase=phase))

        for index, group in enumerate(current['groups']):
            last_report = None
            def report(message, percent=None, phase='working'):
                nonlocal last_report
                current_report = (message, percent, phase)
                if current_report != last_report:
                    notify(index, 'running', *current_report)
                    last_report = current_report

            report('Checking the changes for this source…', phase='checking')
            try:
                if group['source'] == 'deb':
                    # Re-simulate immediately before modification, preserving exact package IDs.
                    changes, _ = PackageKit().transaction('UpdatePackages', '(tas)', (6, group['targets']))
                    check_protected_changes(changes)
                    if changes_identity(changes) != changes_identity(group['changes']):
                        raise AppCenterError('Debian dependency changes no longer match the review.')
                    _, restart = PackageKit().transaction('UpdatePackages', '(tas)', (2, group['targets']), report=report)
                    restarts.extend(restart)
                    verify_debian_updates(group['targets'])
                elif group['source'] == 'flatpak':
                    flatpak_update_group(group['scope'], group['targets'], approved=group, report=report)
                else:
                    latest = snap_update_group(management_provider('snap', updates=True))
                    if not latest or latest['targets'] != group['targets']:
                        raise AppCenterError('Snap updates changed. Review all updates again.')
                    report('Starting the Snap refresh. Approve any administrator prompt.', phase='working')
                    reply = snap_api('/v2/snaps', dict(action='refresh', snaps=[t['name'] for t in group['targets']]))
                    wait_snap_update(reply, report=report)
                completed.append(group['name'])
                notify(index, 'completed')
            except Exception as error:
                if isinstance(error, PackageKitFailure):
                    restarts.extend(error.restarts)
                errors.append(group['name'] + ': ' + str(error))
                pending = [g['name'] for g in current['groups'][index+1:]]
                notify(index, 'failed', str(error))
                for later in range(index + 1, len(current['groups'])):
                    notify(later, 'skipped')
                break
        message = ('No installable updates. Held or blocked updates were left unchanged.' if current['blocked_count'] else 'No updates are available.') if not current['groups'] else 'Updates completed.'
        if errors:
            message = ('Completed: ' + ', '.join(completed) + '.\n' if completed else '') + 'Some updates could not be completed.\n' + '\n'.join(errors)
            if pending:
                message += '\nNot attempted: ' + ', '.join(pending) + '.'
            message += '\nCompleted changes are kept. Check for updates before retrying.'
        restart, notice = restart_notice(restarts)
        if notice:
            message += '\n' + notice
        return dict(message=message, completed=completed, errors=errors, pending=pending,
                    restart=restart, restart_notice=notice)


def listing(request):
    mode = request.get("mode", "installed")
    if mode not in ("search", "installed", "updates"):
        raise AppCenterError("Unknown store view.")
    query = request.get("query", "").strip()[:200]
    if request.get("source", "all") not in ("all", "deb", "flatpak", "snap", "appimage"):
        raise AppCenterError("Unknown software source.")
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
    if mode == "search":
        items = ranked_search(items, query, limit=300 * len(sources))
        items, total = group_search_results(items)
        return dict(items=items, warnings=sorted(warnings), total=total,
                    message='Showing up to 300 applications. Search to narrow the list.' if total > 300 else '')
    else:
        items.sort(key=lambda x: (x["name"].casefold(), x["source"], x.get("scope", "")))
    # Filtering installed packages is local and does not invoke a package solver.
    if mode == "installed" and query:
        items = [x for x in items if query.casefold() in (x["name"] + " " + x.get("summary", "")).casefold()]
    return {"items": items[:300], "warnings": sorted(warnings), "total": len(items),
            "message": "Showing up to 300 entries. Search to narrow the list." if len(items) > 300 else ""}


# Details are read-only. Only launch_installed starts an application, after a
# fresh installation/launcher check; no command from a catalog is executed.
def cache_home():
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'cutefish-app-center'


def public_https(url, resolve=False):
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in (None, 443) or any(ord(c) < 33 for c in url)):
            return False
        host = parsed.hostname.rstrip('.').lower()
        if host == 'localhost' or host.endswith(('.localhost', '.local')):
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            if resolve:
                addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                    return False
        return True
    except (ValueError, OSError, TypeError):
        return False


class ArtworkRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public_https(newurl, resolve=True):
            raise AppCenterError('The artwork URL is not a public HTTPS address.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def artwork_format(raw):
    basic = icon_format(raw)
    if basic:
        return basic
    # JPEG dimensions are in a Start Of Frame segment; never decode to inspect.
    if raw.startswith(b'\xff\xd8'):
        offset = 2
        while offset + 4 <= len(raw):
            if raw[offset] != 255:
                break
            marker = raw[offset + 1]
            offset += 2
            if marker in (0xD8, 0xD9) or marker == 0:
                continue
            length = int.from_bytes(raw[offset:offset + 2], 'big')
            if length < 2 or offset + length > len(raw):
                break
            if marker in (0xC0, 0xC1, 0xC2) and length >= 7:
                height, width = struct.unpack_from('>HH', raw, offset + 3)
                return 'jpg' if 0 < width <= 4096 and 0 < height <= 4096 else None
            offset += length
    if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP' and len(raw) >= 30:
        width = height = 0
        if raw[12:16] == b'VP8X':
            width = int.from_bytes(raw[24:27], 'little') + 1
            height = int.from_bytes(raw[27:30], 'little') + 1
        elif raw[12:16] == b'VP8 ' and raw[23:26] == b'\x9d\x01\x2a':
            width, height = (v & 0x3fff for v in struct.unpack_from('<HH', raw, 26))
        elif raw[12:16] == b'VP8L' and raw[20] == 0x2f:
            bits = int.from_bytes(raw[21:25], 'little')
            width, height = (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
        return 'webp' if 0 < width <= 4096 and 0 < height <= 4096 else None
    return None


def artwork_cache_entry(key):
    """Return usable cached artwork without network access, plus freshness."""
    for suffix in ('png', 'jpg', 'webp', 'svg'):
        path = cache_home() / 'artwork' / (key + '.' + suffix)
        try:
            if path.is_file() and not path.is_symlink():
                return str(path), time.time() - path.stat().st_mtime < 7 * 86400
        except OSError:
            pass
    return '', False


def store_artwork(key, raw, stale=''):
    if len(raw) > 6 * 1024 * 1024:
        return stale
    if raw.startswith(b'\x1f\x8b'):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                raw = compressed.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024 or icon_format(raw) != 'svg':
                return stale
        except (OSError, EOFError, ValueError):
            return stale
    suffix = artwork_format(raw)
    if not suffix:
        return stale
    directory = cache_home() / 'artwork'
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (key + '.' + suffix)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix='.artwork-')
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(raw)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return str(destination)



def cached_artwork(url):
    if not public_https(url):
        return ''
    key = hashlib.sha256(url.encode()).hexdigest()
    stale, fresh = artwork_cache_entry(key)
    if fresh:
        return stale
    if not public_https(url, resolve=True):
        return stale
    request = urllib.request.Request(url, headers={'User-Agent': 'CutefishAppCenter/0.3.3'})
    try:
        with urllib.request.build_opener(ArtworkRedirect()).open(request, timeout=6) as response:
            raw = response.read(6 * 1024 * 1024 + 1)
        return store_artwork(key, raw, stale)
    except (OSError, ValueError, AppCenterError):
        return stale


def icon_locator_key(locator):
    if locator.get('kind') == 'https' and isinstance(locator.get('url'), str) and public_https(locator['url']):
        return hashlib.sha256(locator['url'].encode()).hexdigest()
    if (locator.get('kind') == 'snap' and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}', locator.get('name', ''))
            and re.fullmatch(r'[a-zA-Z0-9-]{1,40}', str(locator.get('revision', '')))):
        return hashlib.sha256(('snap-icon:' + locator['name'] + ':' + str(locator['revision'])).encode()).hexdigest()
    return ''


def catalog_icon(item, locator):
    """Register only provider-derived locators. A list request never downloads icons."""
    key = icon_locator_key(locator)
    if not key:
        return item
    cached, _ = artwork_cache_entry(key)
    if cached:
        item['icon'] = cached
    try:
        registry = cache_home() / 'icon-sources'
        registry.mkdir(parents=True, exist_ok=True)
        path = registry / (key + '.json')
        if not path.is_file():
            atomic_file(path, json.dumps(locator))
        item['icon_key'] = key
    except OSError:
        pass
    return item


def snap_artwork_locator(record, installed=None):
    local = installed or record
    name = local.get('name', '')
    if local.get('icon') == '/v2/icons/' + name + '/icon':
        return dict(kind='snap', name=name, revision=str(local.get('revision', '')))
    urls = [m.get('url') for m in record.get('media') or [] if isinstance(m, dict) and m.get('type') == 'icon']
    urls.append(record.get('icon'))
    return next((dict(kind='https', url=url) for url in urls if isinstance(url, str) and public_https(url)), {})


def appimage_artwork_locator(entry):
    icons = entry.get('icons') or []
    if not isinstance(icons, list):
        return {}
    for icon in icons:
        if isinstance(icon, str):
            url = urllib.parse.urljoin('https://appimage.github.io/database/', icon)
            if public_https(url):
                return dict(kind='https', url=url)
    return {}


def load_catalog_icon(key):
    if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}', key):
        return ''
    stale, fresh = artwork_cache_entry(key)
    if fresh:
        return stale
    try:
        path = cache_home() / 'icon-sources' / (key + '.json')
        if path.is_symlink() or path.stat().st_size > 4096:
            return stale
        locator = json.loads(path.read_text())
        if not isinstance(locator, dict) or icon_locator_key(locator) != key:
            return stale
        if locator['kind'] == 'https':
            return cached_artwork(locator['url'])
        conn = SnapHTTP('localhost', timeout=6)
        try:
            conn.request('GET', '/v2/icons/' + locator['name'] + '/icon')
            response = conn.getresponse()
            if response.status != 200:
                return stale
            return store_artwork(key, response.read(6 * 1024 * 1024 + 1), stale)
        finally:
            conn.close()
    except (OSError, ValueError, TypeError, AppCenterError, http.client.HTTPException):
        return stale


def list_icons(request):
    keys = request.get('keys')
    if (not isinstance(keys, list) or len(keys) > 16 or
            any(not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}', key) for key in keys)):
        raise AppCenterError('Invalid icon request.')
    # Individual completions let a slow source leave the other rows responsive.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        pending = {executor.submit(load_catalog_icon, key): key for key in dict.fromkeys(keys)}
        for future in concurrent.futures.as_completed(pending):
            try:
                path = future.result()
                if path:
                    emit(dict(event='icon', key=pending[future], path=path))
            except (OSError, ValueError, AppCenterError):
                pass
    return {}


def detail_artwork(item, metadata):
    item['screenshots'] = []
    jobs = []
    if metadata.get('icon_url'):
        jobs.append(('icon', metadata['icon_url'], ''))
    for shot in metadata.get('screenshot_urls', [])[:3]:
        jobs.append(('screenshot', shot['url'], shot.get('caption', '')))
    if not jobs:
        return
    # Preserve gallery order even if downloads finish in a different order.
    def load(job):
        try:
            return cached_artwork(job[1])
        except (OSError, ValueError, AppCenterError):
            return ''
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for job, path in zip(jobs, executor.map(load, jobs)):
            if path and job[0] == 'icon':
                item['icon'] = path
            elif path:
                item['screenshots'].append(dict(path=path, caption=job[2]))
    if any(job[0] == 'screenshot' for job in jobs) and not item['screenshots']:
        item['artwork_note'] = 'Screenshots are unavailable right now.'


def deb_fields(text):
    result, key = {}, ''
    for line in text.splitlines():
        if line.startswith((' ', '\t')) and key:
            result[key] += '\n' + ('' if line.strip() == '.' else line[1:])
        elif ': ' in line:
            key, value = line.split(': ', 1)
            result[key] = value
        elif not line:
            break
    return result


def deb_installed(ident):
    try:
        value = run(['dpkg-query', '--show', '--showformat=${db:Status-Status}\t${Version}\n', '--', ident]).strip().split('\t')
        return value[1] if len(value) == 2 and value[0] == 'installed' else ''
    except AppCenterError:
        return ''


def visible_desktop(path):
    try:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read(path, encoding='utf-8')
        entry = parser['Desktop Entry']
        if (entry.get('Type') != 'Application' or entry.get('Hidden', '').lower() == 'true'
                or entry.get('NoDisplay', '').lower() == 'true' or not entry.get('Name')
                or not (entry.get('Exec') or entry.get('DBusActivatable', '').lower() == 'true')):
            return False
        return True
    except (OSError, KeyError, configparser.Error, UnicodeError):
        return False


def flatpak_installed(target):
    arch = target.get('arch') or run(['flatpak', '--default-arch']).strip()
    text = run(['flatpak', '--' + target['scope'], 'list', '--runtime' if target.get('ref_kind') == 'runtime' else '--app', '--columns=application,branch,origin,arch,version'])
    for line in text.splitlines():
        fields = line.split('\t')
        if len(fields) >= 4 and tuple(fields[:4]) == (target['id'], target['branch'], target['remote'], arch):
            return dict(arch=arch, version=fields[4] if len(fields) > 4 else '')
    return None


def launch_spec(target):
    validate_target(target)
    source, ident = target['source'], target['id']
    if target.get('catalog'):
        return None
    if source == 'flatpak':
        if target.get('ref_kind') == 'runtime':
            return None
        installed = flatpak_installed(target)
        return dict(kind='flatpak', **installed) if installed is not None else None
    if source == 'deb':
        if target.get('path') or not deb_installed(ident):
            return None
        files = run(['dpkg-query', '--listfiles', '--', ident]).splitlines()
        candidates = sorted(p for p in files if p.startswith('/usr/share/applications/') and p.endswith('.desktop'))
    elif source == 'snap':
        try:
            installed = snap_api('/v2/snaps/' + urllib.parse.quote(ident, safe=''))['result']
        except AppCenterError:
            return None
        if installed.get('status') not in ('active', 'installed'):
            return None
        candidates = sorted(str(p) for p in Path('/var/lib/snapd/desktop/applications').glob(ident + '_*.desktop'))
    else:
        if not re.fullmatch(r'[a-f0-9]{64}', ident):
            return None
        image = state_dir() / 'appimages' / ident / 'application.AppImage'
        if not image.is_file() or image.is_symlink():
            return None
        candidates = [str(data_home() / 'applications' / ('org.cutefish.AppCenter.AppImage-' + ident + '.desktop'))]
    candidates = [p for p in candidates if visible_desktop(p)]
    return dict(kind='desktop', path=candidates[0]) if candidates else None


def launch_desktop(path):
    from gi.repository import Gio
    entry = Gio.DesktopAppInfo.new_from_filename(path)
    if entry is None or not entry.launch([], None):
        raise AppCenterError('The application launcher could not be started.')


def launch_installed(target):
    spec = launch_spec(target)
    if spec is None:
        raise AppCenterError('This installation has no available application launcher. Reload the store and try again.')
    if spec['kind'] == 'flatpak':
        subprocess.Popen(['flatpak', '--' + target['scope'], 'run', '--arch=' + spec['arch'],
                          '--branch=' + target['branch'], target['id']], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        launch_desktop(spec['path'])
    return {'message': 'Launch requested.'}


def app_details(target, artwork=True):
    validate_target(target)
    item = dict(target)
    # Display data is re-read from the selected source, never used as launch
    # instructions or as caller-supplied remote artwork URLs.
    for key in ('icon_key', 'screenshots', 'icon_url', 'screenshot_urls', 'can_open', 'homepage', 'publisher', 'license', 'publisher_verified'):
        item.pop(key, None)
    metadata = {}
    source, ident = target['source'], target['id']
    warnings = []
    if source == 'deb':
        if target.get('path'):
            fields = deb_fields(run(['dpkg-deb', '--field', target['path']]))
        else:
            fields = deb_fields(run(['apt-cache', 'show', '--no-all-versions', '--', ident]))
        metadata = appstream().get(ident.split(':')[0], {})
        description = fields.get('Description-en', fields.get('Description', ''))
        summary, _, body = description.partition('\n')
        item.update(summary=summary or item.get('summary', ''), description=body or summary,
                    version=fields.get('Version', item.get('version', '')), maintainer=fields.get('Maintainer', ''),
                    homepage=fields.get('Homepage', ''), architecture=fields.get('Architecture', ''))
        item.update({k: v for k, v in metadata.items() if v and (k != 'version' or not item['version'])})
        installed_version = deb_installed(ident) if not target.get('path') else ''
        item.update(installed=bool(installed_version), installed_version=installed_version)
    elif source == 'flatpak':
        arch = target.get('arch') or run(['flatpak', '--default-arch']).strip()
        metadata = flatpak_appstream(target['scope'], arch).get((ident, arch, target['branch'], target['remote']), {})
        item.update({k: v for k, v in metadata.items() if v})
        installed = flatpak_installed(dict(target, arch=arch))
        item.update(installed=installed is not None, installed_version=installed['version'] if installed else '', arch=arch)
        if not metadata:
            warnings.append('The local catalog has no additional details for this app.')
    elif source == 'snap':
        installed = None
        try:
            installed = snap_api('/v2/snaps/' + urllib.parse.quote(ident, safe=''))['result']
        except AppCenterError:
            pass
        try:
            records = snap_api('/v2/find?' + urllib.parse.urlencode({'name': ident}))['result']
            info = next((r for r in records if r.get('name') == ident), installed or {})
        except AppCenterError:
            info = installed or {}
            warnings.append('Store details are unavailable; showing installed information.')
        publisher = info.get('publisher') or {}
        media = info.get('media') or []
        catalog_icon(item, snap_artwork_locator(info, installed))
        metadata = dict(screenshot_urls=[dict(url=m['url'], caption='') for m in media if m.get('type') == 'screenshot' and m.get('url')][:3])
        item.update(name=info.get('title') or info.get('name') or item.get('name', ident), summary=info.get('summary', ''),
                    description=description_text(info.get('description', '')), version=info.get('version', ''),
                    publisher=publisher.get('display-name') or publisher.get('username', ''),
                    publisher_verified=publisher.get('validation') == 'verified', license=info.get('license', ''),
                    homepage=info.get('website', ''), installed=bool(installed),
                    installed_version=(installed or {}).get('version', ''), confinement=info.get('confinement', 'strict'))
    elif target.get('catalog'):
        entry = next((e for e in appimage_feed() if isinstance(e, dict) and isinstance(e.get('name'), str)
                      and hashlib.sha256(e['name'].encode()).hexdigest() == ident), None)
        if entry is None:
            raise AppCenterError('This AppImage catalog entry is no longer available.')
        base_url = 'https://appimage.github.io/database/'
        icons = entry.get('icons') or []
        shots = entry.get('screenshots') or []
        catalog_icon(item, appimage_artwork_locator(entry))
        metadata = dict(screenshot_urls=[dict(url=urllib.parse.urljoin(base_url, u), caption='') for u in shots if isinstance(u, str)][:3])
        authors = [a.get('name', '') for a in entry.get('authors') or [] if isinstance(a, dict)]
        item.update(name=entry['name'], description=description_text(entry.get('description') or ''),
                    catalog_author=', '.join(a for a in authors if a), installed=False)
    else:
        records = [i for i in appimage_items() if i['id'] == ident]
        if records:
            item.update(records[0])
            item['description'] = item.get('summary', '')
        else:
            # A file currently being reviewed is not installed or launchable.
            item['installed'] = False
            item['description'] = item.get('summary', '')
    try:
        launcher = launch_spec(item)
        item['can_open'] = bool(launcher)
        if launcher and launcher['kind'] == 'desktop':
            desktop = configparser.ConfigParser(interpolation=None, strict=False)
            desktop.read(launcher['path'], encoding='utf-8')
            entry = desktop['Desktop Entry']
            if source == 'deb' and not item.get('desktop_app'):
                item['name'] = metadata_text(entry.get('Name', item.get('name', ident)))
            if not item.get('icon') or item.get('icon', '').startswith('application-x-'):
                item['icon'] = metadata_text(entry.get('Icon', 'application-x-executable'), 1024)
    except (OSError, AppCenterError, KeyError, configparser.Error, UnicodeError):
        item['can_open'] = False
    if not public_https(item.get('homepage', '')):
        item.pop('homepage', None)
    if artwork:
        if source == 'snap' or target.get('catalog'):
            path = load_catalog_icon(item.get('icon_key', ''))
            if path:
                item['icon'] = path
        detail_artwork(item, metadata)
    item['details_loaded'] = True
    return {'item': item, 'warnings': warnings}


# Editorial choices are separate from search ranking. Every displayed entry
# must join an app currently advertised by a configured local catalog.
FEATURED_APPS = (
    ('Firefox', 'firefox', ('org.mozilla.firefox',), ('firefox-esr', 'firefox')),
    ('LibreOffice', 'libreoffice', ('org.libreoffice.LibreOffice',), ('libreoffice',)),
    ('VLC', 'vlc', ('org.videolan.VLC',), ('vlc',)),
    ('GIMP', 'gimp', ('org.gimp.GIMP',), ('gimp',)),
    ('Krita', 'krita', ('org.kde.krita',), ('krita',)),
    ('Inkscape', 'inkscape', ('org.inkscape.Inkscape',), ('inkscape',)),
)


def discover_apps():
    candidates, warnings = [], []
    if shutil.which('flatpak'):
        try:
            arch = run(['flatpak', '--default-arch']).strip()
            wanted = {appid.casefold() for _, _, ids, _ in FEATURED_APPS for appid in ids}
            for scope in ('user', 'system'):
                metadata = flatpak_appstream(scope, arch)
                refs = {tuple(line.split('\t')) for line in run([
                    'flatpak', '--' + scope, 'remote-ls', '--app', '--cached',
                    '--columns=application,arch,branch,origin']).splitlines()}
                for key, meta in metadata.items():
                    appid, ref_arch, branch, remote = key
                    if key in refs and appid.casefold() in wanted and branch == 'stable':
                        candidates.append(dict(meta, source='flatpak', id=appid, scope=scope,
                                               remote=remote, arch=ref_arch, branch=branch))
        except AppCenterError as error:
            warnings.append('Flatpak: ' + str(error))
    packages = sorted({name for _, _, _, names in FEATURED_APPS for name in names})
    try:
        pattern = '^(' + '|'.join(re.escape(name) for name in packages) + ')$'
        output = run(['apt-cache', 'search', '--names-only', '--', pattern], timeout=30)
        metadata = appstream()
        for line in output.splitlines():
            name, separator, summary = line.partition(' - ')
            if separator and name in packages:
                item = dict(source='deb', id=name, name=name, summary=summary,
                            scope='system', icon='application-x-deb')
                item.update(metadata.get(name, {}))
                candidates.append(item)
    except AppCenterError as error:
        warnings.append('Debian: ' + str(error))
    result = []
    for title, query, appids, packages in FEATURED_APPS:
        matches = [item for item in candidates if
                   (item['source'] == 'flatpak' and item['id'].casefold() in {x.casefold() for x in appids}) or
                   (item['source'] == 'deb' and item['id'] in packages)]
        if not matches:
            continue
        # Rich catalog metadata first; lexical identity only breaks ties.
        matches.sort(key=lambda i: (not bool(i.get('desktop_app')), i['source'], i.get('scope', ''), i.get('remote', ''), i['id']))
        result.append(dict(matches[0], feature_name=title, query=query))
    return {'items': result, 'warnings': warnings}


_MIGRATING = set()


def migrate_legacy_library():
    """Move validated Store imports and retarget only its generated launchers.

    Source downloads are never moved. The procedure can resume after a process
    stops between the directory move and the atomic metadata/launcher writes.
    """
    root = state_dir()
    if str(root) in _MIGRATING:
        return
    legacy = data_home() / 'cutefish-store'
    applications = data_home() / 'applications'
    old_launchers = list(applications.glob('org.cutefish.Store.AppImage-*.desktop'))
    old_library = legacy / 'appimages'
    if not old_library.exists() and not old_launchers:
        return
    if old_library.is_symlink():
        raise AppCenterError('The older AppImage library is a symbolic link and cannot be migrated automatically.')
    _MIGRATING.add(str(root))
    try:
        with open(root / 'migration.lock', 'a') as migration:
            fcntl.flock(migration, fcntl.LOCK_EX)
            legacy.mkdir(parents=True, exist_ok=True)
            with open(legacy / 'transaction.lock', 'a') as previous, mutation_lock():
                try:
                    fcntl.flock(previous, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise AppCenterError('Finish the operation in Cutefish Store before migrating its AppImage library.') from None
                library = root / 'appimages'
                library.mkdir(exist_ok=True)
                if library.is_symlink():
                    raise AppCenterError('The application library is a symbolic link.')
                entries = {p.name: p for p in old_library.glob('*') if re.fullmatch(r'[a-f0-9]{64}', p.name)}
                # Include moved entries whose launcher rewrite was interrupted.
                for launcher in old_launchers:
                    ident = launcher.name.removeprefix('org.cutefish.Store.AppImage-').removesuffix('.desktop')
                    if re.fullmatch(r'[a-f0-9]{64}', ident) and ident not in entries:
                        entries[ident] = library / ident
                for ident, source in entries.items():
                    if source.is_symlink() or not source.is_dir():
                        raise AppCenterError('An older AppImage import has an invalid directory.')
                    archive = source / 'application.AppImage'
                    if archive.is_symlink() or file_hash(archive) != ident:
                        raise AppCenterError('An older AppImage import changed. Its original file has been preserved.')
                    original = json.loads((source / 'metadata.json').read_text())
                    if original.get('id') != ident:
                        raise AppCenterError('An older AppImage import has invalid metadata.')
                    destination = library / ident
                    duplicate = False
                    if source != destination:
                        if destination.exists():
                            if destination.is_symlink() or (destination / 'application.AppImage').is_symlink() or file_hash(destination / 'application.AppImage') != ident:
                                raise AppCenterError('A different file occupies the new AppImage library entry.')
                            original = json.loads((destination / 'metadata.json').read_text())
                            if original.get('id') != ident:
                                raise AppCenterError('The new AppImage library entry has invalid metadata.')
                            duplicate = True
                        else:
                            source.rename(destination)
                    meta = dict(original, source='appimage', installed=True, scope='user',
                                path=str(destination / 'application.AppImage'))
                    icon = Path(original.get('icon', ''))
                    if icon.is_absolute():
                        try:
                            try:
                                relative = icon.relative_to(legacy / 'appimages' / ident)
                            except ValueError:
                                relative = icon.relative_to(destination)
                            if relative.name != str(relative):
                                raise ValueError('Invalid icon path')
                            meta['icon'] = str(destination / relative) if (destination / relative).is_file() else 'application-x-executable'
                        except ValueError:
                            meta['icon'] = 'application-x-executable'
                    meta.setdefault('icon', 'application-x-executable')
                    new_launcher = applications / ('org.cutefish.AppCenter.AppImage-' + ident + '.desktop')
                    atomic_file(new_launcher, appimage_launcher(meta), 0o644)
                    atomic_file(destination / 'metadata.json', json.dumps(meta))
                    (applications / ('org.cutefish.Store.AppImage-' + ident + '.desktop')).unlink(missing_ok=True)
                    if duplicate:
                        source.rename(old_library / ('.migrated-' + ident))
    finally:
        _MIGRATING.discard(str(root))


def dispatch(request):
    migrate_legacy_library()
    op = request.get("op")
    if op == "icons":
        return list_icons(request)
    if op == 'plan_all_updates':
        return {'plan': prepare_all_updates()}
    if op == 'apply_all_updates':
        return apply_all_updates(request.get('plan'))
    if op == 'library':
        return management_inventory(request)
    if op == 'update_inventory':
        return management_inventory(request, updates=True)
    if op == "details":
        return app_details(request["target"])
    if op == "launch":
        return launch_installed(request["target"])
    if op == "discover":
        return discover_apps()
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
    raise AppCenterError("Unknown store operation.")


def main():
    try:
        request = json.loads(sys.stdin.readline(8 * 1024 * 1024))
        emit(dict(event="result", ok=True, **dispatch(request)))
    except Exception as e:
        emit({"event": "result", "ok": False, "error": str(e)})
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
