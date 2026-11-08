// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <string>
#include <utility>
#include <ui/icon.h>

// Symbolic interface artwork uses the toolkit's live text palette. Application
// logos remain full-color IconImages and are never recolored by these glyphs.
inline void registerInterfaceIcons() {
    const std::string start = R"(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">)";
    const std::pair<const char*, const char*> glyphs[] = {
        {"app-center-internet", R"(<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18M5 6.5h14M5 17.5h14"/>)"},
        {"app-center-graphics", R"(<path d="m13 4 7 7M4 20l4-1 13-13a2.1 2.1 0 0 0-3-3L5 16zM5 16l3 3"/>)"},
        {"app-center-office", R"(<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5M9 12h6M9 16h6"/>)"},
        {"app-center-media", R"(<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 8 6 4-6 4z"/>)"},
        {"app-center-development", R"(<path d="m7 6-5 6 5 6M17 6l5 6-5 6M14 3l-4 18"/>)"},
        {"app-center-games", R"(<path d="M8 7h8c2 0 3 1 3.5 3l1.5 7c.5 3-2 4-4 2l-3-3h-4l-3 3c-2 2-4.5 1-4-2L4.5 10C5 8 6 7 8 7zM8 10v4M6 12h4M15 11h.01M18 13h.01"/>)"},
        {"app-center-education", R"(<path d="M12 5C8 2 4 3 2 4v15c3-1 6-1 10 1 4-2 7-2 10-1V4c-2-1-6-2-10 1zM12 5v15M5 7c1.5-.3 3 0 4 .5M5 11c1.5-.3 3 0 4 .5M15 7.5c1-.5 2.5-.8 4-.5M15 11.5c1-.5 2.5-.8 4-.5"/>)"},
        {"app-center-utilities", R"(<path d="M14 4a6 6 0 0 0-7 7l-4 4a2.8 2.8 0 0 0 4 4l4-4a6 6 0 0 0 7-7l-4 4-3-3 4-4z"/>)"},
    };
    for (const auto& [name, paths] : glyphs)
        cutefish::ui::Icon::registerGlyph(name, start + paths + "</svg>");
}
