// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <algorithm>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <string>
#include <vector>
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#include <base/json.h>
#include <base/paths.h>

class Preferences {
    using Json = cutefish::base::json::Value;
public:
    explicit Preferences(std::filesystem::path path=defaultPath()):m_path(std::move(path)) {
        readCurrent(m_data,m_error);
    }
    static std::filesystem::path defaultPath() {
        if(const char* path=std::getenv("CUTEFISH_APP_CENTER_PREFERENCES");path && *path)return path;
        std::filesystem::path config=cutefish::base::paths::configHome();
        if(const char* path=std::getenv("XDG_CONFIG_HOME");path && std::filesystem::path(path).is_absolute())config=path;
        return config/"cutefish-app-center/preferences.json";
    }
    static const std::vector<std::string>& formats() {
        static const std::vector<std::string> names={"deb","flatpak","snap","appimage"};return names;
    }
    std::vector<std::string> sourceOrder() const {
        std::vector<std::string> order;
        for(const auto& value:m_data["source_order"].toArray()){
            auto name=value.toString();
            if(std::find(formats().begin(),formats().end(),name)!=formats().end() && std::find(order.begin(),order.end(),name)==order.end())order.push_back(name);
        }
        for(const auto& name:formats())if(std::find(order.begin(),order.end(),name)==order.end())order.push_back(name);
        return order;
    }
    bool rememberChoices() const {return m_data["remember_choices"].toBool(true);}
    std::map<std::string,std::string> choices() const {
        std::map<std::string,std::string> result;
        if(rememberChoices())for(const auto& [app,value]:m_data["application_choices"].toObject())
            if(!app.empty() && app.size()<=1024 && value.isString() && !value.toString().empty() && value.toString().size()<=4096)result[app]=value.toString();
        return result;
    }
    const std::string& error() const {return m_error;}
    bool setOrder(const std::vector<std::string>& order,std::string& error) {
        return save([&](Json& next){Json::Array values;for(const auto& name:order)values.emplace_back(name);next.insert("source_order",values);},error);
    }
    bool setRememberChoices(bool remember,std::string& error) {
        return save([&](Json& next){next.insert("remember_choices",remember);if(!remember)next.insert("application_choices",Json::object());},error);
    }
    bool setChoice(const std::string& app,const std::string& variant,std::string& error) {
        error.clear();if(!rememberChoices())return true;
        return save([&](Json& next){
            if(!next["remember_choices"].toBool(true))return;
            auto saved=next["application_choices"];if(!saved.isObject())saved=Json::object();
            saved.insert(app,variant);next.insert("application_choices",saved);
        },error);
    }
    bool forgetChoice(const std::string& app,std::string& error) {
        return save([&](Json& next){
            auto saved=Json::object();for(const auto& [key,value]:next["application_choices"].toObject())if(key!=app)saved.insert(key,value);
            next.insert("application_choices",saved);
        },error);
    }
    bool clearChoices(std::string& error) {
        return save([](Json& next){next.insert("application_choices",Json::object());},error);
    }
    bool reset(std::string& error) {return save([](Json& next){next=Json::object();},error,true);}
private:
    bool readCurrent(Json& data,std::string& error) const {
        std::error_code ec;
        if(!std::filesystem::exists(m_path,ec) && !ec){data=Json::object();return true;}
        if(!ec && std::filesystem::file_size(m_path,ec)<=1024*1024 && !ec){
            std::ifstream file(m_path);
            auto value=Json::parse(std::string{std::istreambuf_iterator<char>(file),{}});
            if(file && value && value->isObject() && (*value)["version"].toDouble()==1){data=*value;return true;}
        }
        error="Preferences could not be read. Reset them below to save changes.";return false;
    }
    bool save(const std::function<void(Json&)>& change,std::string& error,bool repair=false) {
        error.clear();
        if(!m_error.empty() && !repair){error=m_error;return false;}
        std::error_code ec;auto parent=m_path.parent_path();
        if(!parent.empty())std::filesystem::create_directories(parent,ec);
        if(ec){error="Could not save preferences: "+ec.message();return false;}
        struct Lock {int fd;~Lock(){if(fd>=0)::close(fd);}} lock{::open((m_path.string()+".lock").c_str(),O_CREAT|O_RDWR|O_CLOEXEC|O_NOFOLLOW,0600)};
        if(lock.fd<0){error="Could not save preferences: "+std::string(std::strerror(errno));return false;}
        int acquired;do{acquired=::flock(lock.fd,LOCK_EX);}while(acquired<0 && errno==EINTR);
        if(acquired<0){error="Could not save preferences: "+std::string(std::strerror(errno));return false;}
        // Apply only this change to the latest document under the lock, so two
        // open windows cannot discard each other's unrelated preferences.
        Json next=Json::object();
        if(!repair && !readCurrent(next,error)){m_error=error;return false;}
        change(next);next.insert("version",1);
        auto bytes=next.serialize(false)+"\n";
        if(bytes.size()>1024*1024){error="Could not save preferences: too many saved application choices.";return false;}
        std::string temporary=m_path.string()+".XXXXXX";
        std::vector<char> name(temporary.begin(),temporary.end());name.push_back('\0');
        int fd=mkstemp(name.data());
        if(fd<0){error="Could not save preferences: "+std::string(std::strerror(errno));return false;}
        // Write beside the destination and rename only after the complete file
        // reaches disk. Readers always see one complete, private JSON document.
        size_t offset=0;int failure=0;
        while(offset<bytes.size()){
            auto written=::write(fd,bytes.data()+offset,bytes.size()-offset);
            if(written<0 && errno==EINTR)continue;
            if(written<=0){failure=written<0?errno:EIO;break;}offset+=static_cast<size_t>(written);
        }
        if(!failure && fsync(fd)<0)failure=errno;
        if(::close(fd)<0 && !failure)failure=errno;
        if(!failure && ::rename(name.data(),m_path.c_str())<0)failure=errno;
        if(failure){::unlink(name.data());error="Could not save preferences: "+std::string(std::strerror(failure));return false;}
        m_data=std::move(next);m_error.clear();return true;
    }
    std::filesystem::path m_path;
    Json m_data=Json::object();
    std::string m_error;
};
