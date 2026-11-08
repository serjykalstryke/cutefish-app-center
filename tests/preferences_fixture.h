// SPDX-License-Identifier: BSD-3-Clause
#pragma once
#include <cstdlib>
#include <filesystem>

inline void isolatePreferences(const char* name) {
    auto folder=std::filesystem::absolute("work/test-preferences");std::filesystem::create_directories(folder);
    auto path=(folder/(std::string(name)+".json")).string();std::filesystem::remove(path);
    setenv("CUTEFISH_APP_CENTER_PREFERENCES",path.c_str(),1);
}
