// SPDX-License-Identifier: BSD-3-Clause
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <map>
#include <memory>
#include <string>
#include <vector>
#include <cstdlib>

#include <base/event_loop.h>
#include <base/json.h>
#include <base/process.h>
#include <base/timer.h>
#include <base/url.h>
#include <ui/application.h>
#include <ui/button.h>
#include <ui/combo_box.h>
#include <ui/dialog_window.h>
#include <ui/file_chooser.h>
#include <ui/file_drop_area.h>
#include <ui/icon_image.h>
#include <ui/label.h>
#include <ui/layout.h>
#include <ui/painter.h>
#include <ui/progress_bar.h>
#include <ui/scroll_view.h>
#include <ui/search_field.h>
#include <ui/theme.h>
#include <ui/window.h>
#include <ui/window_header.h>

namespace ui = cutefish::ui;
namespace base = cutefish::base;
using J = base::json::Value;
using namespace std::chrono_literals;

#ifndef STORE_BACKEND
#define STORE_BACKEND "/usr/libexec/cutefish-store/store_backend.py"
#endif
#ifndef STORE_BRANDING_FILE
#define STORE_BRANDING_FILE "/usr/share/cutefish-store/branding.json"
#endif

static J branding() {
    std::string path=STORE_BRANDING_FILE;
    if(const char* overridePath=std::getenv("CUTEFISH_STORE_BRANDING"))path=overridePath;
    std::ifstream file(path);
    if(!file)return J::object();
    std::string text{std::istreambuf_iterator<char>(file),{}};
    auto parsed=J::parse(text);
    return parsed && parsed->isObject()?*parsed:J::object();
}

static void size(ui::View* v, double w=-1, double h=-1, bool fw=false, bool fh=false) {
    ui::LayoutHints hints;
    hints.preferredWidth=w; hints.preferredHeight=h;
    hints.fillWidth=fw; hints.fillHeight=fh;
    v->setLayoutHints(hints);
}
static ui::Label* label(ui::View* p, const std::string& text, double font=13, int weight=400, bool wrap=false) {
    auto* l=p->addChild<ui::Label>(text);
    l->setFontSize(font); l->setWeight(weight); l->setWrap(wrap);
    size(l,-1,-1,true);
    return l;
}
static std::string str(const J& v, std::string_view key) { return v[key].toString(); }
static std::string sourceName(const J& item) {
    auto s=str(item,"source");
    if(s=="deb") return "Debian · system";
    if(s=="flatpak") return "Flatpak · " + str(item,"remote") + " · " + str(item,"scope");
    if(s=="snap") return "Snap · system";
    return item["catalog"].toBool() ? "AppImage · community catalog" : "AppImage · personal library";
}
class Panel : public ui::Column {
public:
    explicit Panel(bool accent=false): m_accent(accent) { setMargins(ui::Margins::all(20)); setSpacing(12); }
protected:
    void paint(ui::Painter& p) override {
        p.fillRoundedRect(localRect(),16,m_accent ? ui::Theme::current().highlight.withAlpha(.10) : ui::Theme::current().secondBackground);
    }
private: bool m_accent;
};
class AppRow : public ui::Button {
public:
    explicit AppRow(const J& item): ui::Button("") {
        auto* row=addChild<ui::Row>(); m_row=row;
        row->setSpacing(12); row->setMargins({12,10,12,10});
        auto* icon=row->addChild<ui::IconImage>(str(item,"icon"),40);
        icon->setFallbackName("application-x-executable"); size(icon,40,40);
        auto* text=row->addChild<ui::Column>(); size(text,-1,-1,true); text->setSpacing(4);
        label(text,str(item,"name"),15,600);
        auto* sub=label(text,sourceName(item),11); sub->setColor(ui::ColorId::DisabledText);
        size(this,-1,72,true);
    }
    void selected(bool selected) { m_selected=selected; requestPaint(); }
protected:
    void layout() override { ui::Button::layout(); m_row->setGeometry(localRect()); }
    void paint(ui::Painter& p) override {
        ui::Button::paint(p);
        if(m_selected) p.strokeRoundedRect(localRect().adjusted(1,1,-1,-1),10,ui::Theme::current().highlight,2);
    }
private: ui::Row* m_row; bool m_selected=false;
};

class Store {
public:
    Store(ui::Application& app, bool preview): m_app(app), m_preview(preview), m_debounce(&app.loop()) {
        auto brand=branding();
        const auto displayName=brand["display_name"].toString("Cutefish Store");
        m_window.setTitle(displayName); m_window.setMinimumSize({900,680}); m_window.resize({1120,800});
        m_window.setRestoreId("main");
        m_window.onCloseRequested=[this] {
            if(m_mutating) { m_status->setText("Please wait for the software operation to finish before closing the store."); return; }
            m_app.quit();
        };
        auto drop=std::make_unique<ui::FileDropArea>();
        drop->filter=[](const std::string& url){ return base::url::isLocalFile(url); };
        drop->onDropped=[this](const std::vector<std::string>& urls){
            if(!m_busy && !urls.empty()) if(auto p=base::url::toLocalFile(urls.front())) inspect(*p);
        };
        auto* root=drop->addChild<ui::Column>();
        auto* header=root->addChild<ui::WindowHeader>(48);
        header->setButtonsCentered(true); size(header,-1,48,true);
        auto* h=header->setContent<ui::Row>(); h->setMargins({20,7,16,7}); h->setSpacing(12);
        auto* title=label(h,displayName,14,600); size(title,-1,-1,true);
        m_open=h->addChild<ui::Button>("Open file…"); m_open->onClicked=[this]{chooseFile();};
        auto* body=root->addChild<ui::Row>(); size(body,-1,-1,true,true);
        auto* sidebar=body->addChild<Panel>(); size(sidebar,192,-1,false,true);
        sidebar->setMargins({16,24,16,18}); sidebar->setSpacing(12);
        auto* mark=sidebar->addChild<ui::IconImage>(brand["icon"].toString("org.cutefish.Store"),56); size(mark,56,56);
        label(sidebar,"Your software,\nin one place.",17,650,true);
        auto* intro=label(sidebar,brand["tagline"].toString("Made for Cutefish"),11); intro->setColor(ui::ColorId::DisabledText);
        for(auto name:{"Discover","Installed","Updates"}) {
            auto* b=sidebar->addChild<ui::Button>(name); size(b,-1,38,true);
            std::string mode=std::string(name)=="Discover"?"search":std::string(name)=="Installed"?"installed":"updates";
            b->onClicked=[this,mode]{m_mode=mode; m_search->setText(""); refresh();};
            m_nav.push_back(b);
        }
        sidebar->addStretch();
        label(sidebar,"LOCAL FILES",10,650);
        label(sidebar,"Open or drop a .deb or AppImage to review it.",12,400,true);
        label(sidebar,brand["distribution_label"].toString("Debian 13"),11);
        auto* main=body->addChild<ui::Column>(); size(main,-1,-1,true,true);
        main->setMargins({26,18,26,18}); main->setSpacing(14);
        m_title=label(main,"Discover",28,700);
        m_subtitle=label(main,"Find apps across your configured software sources.",13);
        m_subtitle->setColor(ui::ColorId::DisabledText);
        auto* controls=main->addChild<ui::Row>(); controls->setSpacing(12); size(controls,-1,38,true);
        m_search=controls->addChild<ui::SearchField>("Search apps and packages"); size(m_search,-1,38,true);
        m_search->onTextEdited=[this]{m_debounce.start(450ms);};
        m_search->onAccepted=[this]{m_debounce.stop();refresh();};
        m_source=controls->addChild<ui::ComboBox>(std::vector<std::string>{"All sources","Debian","Flatpak","Snap","AppImage"});
        m_source->setCurrentIndex(0); size(m_source,150,36);
        m_source->onActivated=[this](int){refresh();};
        m_reload=controls->addChild<ui::Button>("Reload"); m_reload->onClicked=[this]{refresh();};
        auto* workspace=main->addChild<ui::Row>(); workspace->setSpacing(18); size(workspace,-1,-1,true,true);
        m_list=workspace->addChild<ui::ScrollView>(); size(m_list,-1,-1,true,true);
        m_detail=workspace->addChild<ui::ScrollView>(); size(m_detail,338,-1,false,true);
        m_warnings=label(main,"",11,400,true); m_warnings->setMaximumLineCount(3); m_warnings->setColor(ui::ColorId::DisabledText); m_warnings->setVisible(false);
        auto* footer=main->addChild<ui::Row>(); footer->setSpacing(12); size(footer,-1,28,true);
        m_status=label(footer,"Ready",11); size(m_status,-1,-1,true);
        m_bar=footer->addChild<ui::ProgressBar>(); size(m_bar,110,6); m_bar->setVisible(false);
        auto* metadata=main->addChild<ui::Row>();metadata->setSpacing(12);size(metadata,-1,-1,true);
        m_refresh=metadata->addChild<ui::Button>("Refresh Debian catalog");
        m_flatpakRefresh=metadata->addChild<ui::Button>("Refresh Flatpak catalog");
        m_flatpakRefresh->onClicked=[this]{request(J::object({{"op","refresh_flatpak"}}),[this](const J&){refresh();},true);};
        m_refresh->setToolTip("Ask the system package service to download the latest repository metadata.");
        m_refresh->onClicked=[this]{request(J::object({{"op","refresh"}}),[this](const J&){refresh();},true);};
        m_debounce.setSingleShot(true); m_debounce.onTimeout=[this]{if(!m_busy)refresh();};
        m_window.setContentView(std::move(drop));
        landing(); detailEmpty();
        if(m_preview) {
            m_mode="search";
            J::Array items;
            items.push_back(J::object({{"source","deb"},{"id","gimp"},{"app_id","org.gimp.GIMP"},{"name","GNU Image Manipulation Program"},{"summary","Create and edit images with a complete set of professional tools."},{"version","3.0"},{"scope","system"},{"icon","gimp"},{"installed",false}}));
            items.push_back(J::object({{"source","flatpak"},{"id","org.gimp.GIMP"},{"name","GNU Image Manipulation Program"},{"summary","Create and edit images with a complete set of professional tools."},{"version","3.0"},{"remote","flathub"},{"branch","stable"},{"scope","user"},{"icon","gimp"},{"installed",false}}));
            items.push_back(J::object({{"source","deb"},{"id","vlc"},{"name","VLC media player"},{"summary","Play your music and videos."},{"scope","system"},{"icon","vlc"},{"installed",true}}));
            items.push_back(J::object({{"source","snap"},{"id","firefox"},{"name","Firefox"},{"summary","Browse the web."},{"scope","system"},{"icon","firefox"},{"installed",false}}));
            populate(J::object({{"items",J(items)}}));
            m_status->setText("Design preview · sample entries · software operations disabled");
        }
    }
    void show(){m_window.show();}
    ui::Window& window(){return m_window;}
    void open(const std::string& path){inspect(path);}
private:
    void busy(bool value, bool mutating=false) {
        m_busy=value; m_mutating=value && mutating;
        m_bar->setVisible(value); m_bar->setIndeterminate(value);
        for(auto* b:m_nav) b->setEnabled(!value);
        m_search->setEnabled(!value);m_source->setEnabled(!value);m_reload->setEnabled(!value);
        m_open->setEnabled(!value);m_refresh->setEnabled(!value);m_flatpakRefresh->setEnabled(!value);
        m_detail->setEnabled(!value);
    }
    void request(const J& data, std::function<void(const J&)> done, bool mutating=false) {
        if(m_preview || m_busy) return;
        m_debounce.stop(); busy(true,mutating);m_status->setText(mutating?"Applying software changes…":"Loading…");
        m_process=std::make_unique<base::Process>(&m_app.loop());
        m_process->setStandardInput(data.serialize()+"\n");
        m_buffer.clear();
        m_process->onStandardOutput=[this](std::string_view bytes) {
            m_buffer.append(bytes);
            size_t e;
            while((e=m_buffer.find('\n'))!=std::string::npos) {
                auto line=m_buffer.substr(0,e);m_buffer.erase(0,e+1);
                auto item=J::parse(line);
                if(item && str(*item,"event")=="progress") {
                    auto text=str(*item,"message");
                    auto newline=text.find('\n'); if(newline!=std::string::npos)text.resize(newline);
                    m_status->setText(text);
                    if((*item)["percent"].isNumber()){m_bar->setIndeterminate(false);m_bar->setValue((*item)["percent"].toDouble()/100.);}
                }
            }
        };
        m_process->onFinished=[this,done](int, bool) {
            std::string output=m_process->standardOutput();
            std::string errors=m_process->standardError();
            m_app.loop().post([this,output,errors,done] {
                m_process.reset(); busy(false);
                J result;
                size_t pos=0;
                while(pos<output.size()) {
                    auto end=output.find('\n',pos); if(end==std::string::npos)end=output.size();
                    auto value=J::parse(output.substr(pos,end-pos));
                    if(value && str(*value,"event")=="result")result=*value;
                    pos=end+1;
                }
                if(!result["ok"].toBool()) {
                    std::string error=str(result,"error");
                    if(error.empty())error=errors.empty()?"The software service stopped without returning a result.":errors;
                    m_status->setText("Could not complete the request.");
                    message("Software operation",error);return;
                }
                m_status->setText(str(result,"message").empty()?"Ready":str(result,"message"));
                done(result);
            });
        };
        std::string backend=STORE_BACKEND;
        if(const char* env=std::getenv("CUTEFISH_STORE_BACKEND"))backend=env;
        if(!m_process->start("/usr/bin/python3",{backend})) {
            busy(false);m_status->setText("Could not start the store backend.");
        }
    }
    void message(const std::string& title, const std::string& text) {
        m_message=std::make_unique<ui::ConfirmDialog>(&m_window,title,text);
        m_message->setConfirmText("Close");m_message->setCancelVisible(false);m_message->show();
    }
    void chooseFile() {
        m_chooser=std::make_unique<ui::FileChooser>(&m_window);
        m_chooser->setTitle("Open software package");
        m_chooser->setAcceptLabel("Review");
        m_chooser->setFilters({{"Software packages",{"*.deb","*.AppImage","*.appimage"},{}},{"All files",{"*"},{}}});
        m_chooser->onAccepted=[this](const std::vector<std::string>& paths,const std::string&){if(!paths.empty())inspect(paths.front());};
        m_chooser->open();
    }
    void inspect(std::string path) {
        if(auto local=base::url::toLocalFile(path))path=*local;
        request(J::object({{"op","inspect"},{"path",path}}),[this](const J& result){
            m_variants={result["item"]};details(0);
            m_status->setText("Review the file, then choose Install or Import.");
        });
    }
    void refresh() {
        if(m_busy)return;
        m_title->setText(m_mode=="search"?"Discover":m_mode=="installed"?"Installed":"Updates");
        m_subtitle->setText(m_mode=="search"?"Find apps across your configured software sources.":m_mode=="installed"?"Manage apps, packages, and your AppImage library.":"Available updates from sources that responded.");
        if(m_mode=="search" && m_search->text().size()<2){landing();detailEmpty();return;}
        static const std::vector<std::string> sources={"all","deb","flatpak","snap","appimage"};
        request(J::object({{"op","list"},{"mode",m_mode},{"query",m_search->text()},{"source",sources.at(std::max(0,m_source->currentIndex()))}}),[this](const J& result){populate(result);});
    }
    void landing() {
        m_groups.clear();m_rows.clear();m_warnings->setVisible(false);
        auto* col=m_list->setContent<ui::Column>(); col->setSpacing(18);
        auto* hero=col->addChild<Panel>(true); size(hero,-1,-1,true);hero->setSpacing(12);
        label(hero,"A home for your apps",23,700,true);
        label(hero,"Debian, Flatpak, Snap, and AppImage.\nChoose the source that works for you.",14,400,true);
        label(col,"Start exploring",17,650);
        for(auto term:{"Web browsers","Creativity","Media players","Development"}){
            auto* b=col->addChild<ui::Button>(term);size(b,-1,44,true);
            std::string query=std::string(term)=="Web browsers"?"firefox":std::string(term)=="Creativity"?"gimp":std::string(term)=="Media players"?"vlc":"editor";
            b->onClicked=[this,query]{m_search->setText(query);refresh();};
        }
        label(col,"AppImages",16,650);
        label(col,"Download from a publisher you trust, then open the file here to add it to your library.",12,400,true);
    }
    void detailEmpty() {
        auto* panel=m_detail->setContent<Panel>();
        label(panel,"Choose your source",20,650,true);
        label(panel,"Search for software or select an installed app to see its version, installation scope, and available actions.",13,400,true);
        label(panel,"Local installation",15,650);
        label(panel,"Downloaded .deb files get a dependency review. Imported AppImages get their own menu entry.",13,400,true);
    }
    std::string groupKey(const J& item) {
        std::string id=str(item,"app_id");
        if(id.empty() && str(item,"source")=="flatpak")id=str(item,"id");
        if(!id.empty()) {
            if(id.ends_with(".desktop"))id.resize(id.size()-8);
            return "app:"+id;
        }
        return str(item,"source")+":"+str(item,"id");
    }
    void populate(const J& result) {
        m_groups.clear();m_rows.clear();
        std::map<std::string,size_t> keys;
        for(auto& item:result["items"].toArray()) {
            auto key=groupKey(item);
            if(!keys.contains(key)){keys[key]=m_groups.size();m_groups.push_back({});}
            m_groups[keys[key]].push_back(item);
        }
        auto* col=m_list->setContent<ui::Column>(); col->setSpacing(7);
        if(m_groups.empty()) {
            auto* empty=col->addChild<Panel>();
            label(empty,m_mode=="updates"?"No updates reported":"No results",21,650,true);
            label(empty,"Check the source messages below, or try another search.",13,400,true);
            detailEmpty();
        }
        for(size_t i=0;i<m_groups.size();i++) {
            auto* row=col->addChild<AppRow>(m_groups[i][0]);
            if(m_groups[i].size()>1)row->setToolTip(std::to_string(m_groups[i].size())+" source or installation choices");
            row->onClicked=[this,i]{select(i);};m_rows.push_back(row);
        }
        std::string warnings;
        for(const auto& w:result["warnings"].toArray()){if(!warnings.empty())warnings+="\n";warnings+=w.toString();}
        m_warnings->setVisible(!warnings.empty());m_warnings->setText(warnings);m_warnings->setToolTip(warnings);
        auto count=std::to_string(m_groups.size())+" entries";
        if(!warnings.empty())count+=" · some sources unavailable";
        if(!str(result,"message").empty())count+=" · "+str(result,"message");
        m_status->setText(count);
        if(!m_groups.empty())select(0);
    }
    void select(size_t i) {
        for(size_t n=0;n<m_rows.size();n++)m_rows[n]->selected(n==i);
        m_variants=m_groups[i];details(0);
    }
    void details(size_t index) {
        if(index>=m_variants.size())return;
        J item=m_variants[index];
        auto* panel=m_detail->setContent<Panel>();
        auto* icon=panel->addChild<ui::IconImage>(str(item,"icon"),64);icon->setFallbackName("application-x-executable");size(icon,64,64);
        label(panel,str(item,"name"),23,700,true);
        label(panel,str(item,"summary"),13,400,true);
        label(panel,"SOURCE",10,650);
        if(m_variants.size()>1) {
            std::vector<std::string> names;for(auto& v:m_variants)names.push_back(sourceName(v));
            auto* variants=panel->addChild<ui::ComboBox>(names);size(variants,-1,36,true);
            variants->setCurrentIndex(int(index));
            variants->onActivated=[this](int n){m_app.loop().post([this,n]{details(n);});};
        } else label(panel,sourceName(item),13,550,true);
        if(!str(item,"version").empty())label(panel,"Version  "+str(item,"version"),12,400,true);
        if(!str(item,"branch").empty())label(panel,"Branch  "+str(item,"branch"),12);
        label(panel,"Identifier  "+str(item,"id"),11,400,true);
        if(!str(item,"path").empty())label(panel,"File  "+str(item,"path"),11,400,true);
        if(item["catalog"].toBool()) {
            label(panel,"Community catalog listing. Availability and publisher trust vary. Open the download page, download an AppImage, then use Open file to import it.",12,400,true);
            auto* download=panel->addChild<ui::DialogButton>("Open download page…",true);size(download,-1,38,true);
            download->setEnabled(!m_preview);
            download->onClicked=[this,item]{
                request(J::object({{"op","catalog_link"},{"target",item}}),[this](const J& result){
                    auto url=str(result,"url");
                    if(url.starts_with("https://appimage.github.io/")) {
                        if(base::Process::startDetached("/usr/bin/xdg-open",{url})<0)
                            message("Download page","Could not open your web browser.");
                    }
                });
            };
            return;
        }
        bool installed=item["installed"].toBool();
        std::string action=installed?(m_mode=="updates"?"update":"remove"):"install";
        std::string text=action=="remove"?"Remove":action=="update"?"Update":str(item,"source")=="appimage"?"Import AppImage":"Install";
        if(str(item,"source")=="deb" && installed)label(panel,"Debian inventory includes system packages. Review dependency changes carefully.",11,400,true);
        auto* button=panel->addChild<ui::DialogButton>(text,true);size(button,-1,38,true);
        button->setDestructive(action=="remove");button->setEnabled(!m_preview && !item["protected"].toBool());
        button->onClicked=[this,item,action]{prepare(item,action);};
        if(item["protected"].toBool())label(panel,"Protected system package",12,600,true);
        if(str(item,"source")=="appimage")label(panel,"Update support varies by publisher. This version manages imported files and menu entries.",11,400,true);
        if(str(item,"source")=="snap")label(panel,"Snapd also handles automatic updates for installed snaps.",11,400,true);
    }
    void prepare(const J& item,const std::string& action) {
        request(J::object({{"op","plan"},{"target",item},{"action",action}}),[this](const J& result){
            J plan=result["plan"];
            m_review=std::make_unique<ui::DialogWindow>(&m_window,"Review software changes",620);
            auto* content=m_review->setContent<ui::Column>();content->setSpacing(14);content->setMargins(ui::Margins::all(20));
            label(content,str(plan["target"],"name"),21,700,true);
            auto* scroll=content->addChild<ui::ScrollView>();size(scroll,-1,340,true);
            auto* changes=scroll->setContent<ui::Column>();changes->setSpacing(10);
            label(changes,str(plan,"note"),12,400,true);
            label(changes,"Changes",14,650);
            for(auto& c:plan["changes"].toArray())label(changes,str(c,"info")+"  "+str(c,"id"),12,400,true);
            if(plan["changes"].size()==0)label(changes,"No dependency changes were reported.",12,400,true);
            auto* actions=content->addChild<ui::Row>();actions->setSpacing(12);actions->addStretch();
            auto* cancel=actions->addChild<ui::Button>("Cancel");cancel->onClicked=[this]{m_review->close();};
            auto action=str(plan,"action");
            auto* confirm=actions->addChild<ui::DialogButton>(action=="remove"?"Remove":action=="update"?"Update":"Install",true);
            confirm->setDestructive(action=="remove");
            confirm->onClicked=[this,plan]{
                m_review->close();
                request(J::object({{"op","apply"},{"plan",plan}}),[this](const J& result){
                    auto text=str(result,"message");
                    m_status->setText(text);message("Software changes complete",text);
                    m_variants.clear();detailEmpty();refresh();
                },true);
            };
            m_review->show();
        });
    }
    ui::Application& m_app;
    bool m_preview=false,m_busy=false,m_mutating=false;
    std::string m_mode="search",m_buffer;
    ui::Window m_window;
    ui::Label *m_title,*m_subtitle,*m_status,*m_warnings;
    ui::SearchField* m_search;
    ui::ComboBox* m_source;
    ui::Button *m_open,*m_reload,*m_refresh,*m_flatpakRefresh;
    ui::ProgressBar* m_bar;
    ui::ScrollView *m_list,*m_detail;
    std::vector<ui::Button*> m_nav;
    std::vector<AppRow*> m_rows;
    std::vector<std::vector<J>> m_groups;
    std::vector<J> m_variants;
    std::unique_ptr<base::Process> m_process;
    base::Timer m_debounce;
    std::unique_ptr<ui::FileChooser> m_chooser;
    std::unique_ptr<ui::ConfirmDialog> m_message;
    std::unique_ptr<ui::DialogWindow> m_review;
};

int main(int argc,char** argv) {
    bool preview=false;std::string screenshot,path;
    for(int i=1;i<argc;i++) {
        std::string arg=argv[i];
        if(arg=="--preview")preview=true;
        else if(arg=="--screenshot" && i+1<argc){screenshot=argv[++i];preview=true;}
        else if(arg=="--help") {std::cout<<"cutefish-store [FILE.deb|FILE.AppImage] [--preview] [--screenshot PATH]\n";return 0;}
        else if(path.empty())path=arg;
    }
    ui::Application app(argc,argv,screenshot.empty()?ui::Application::Platform::Wayland:ui::Application::Platform::Headless);
    app.setApplicationId("org.cutefish.Store");
    Store store(app,preview);store.show();
    if(!screenshot.empty())return store.window().grab().savePng(screenshot)?0:1;
    if(!path.empty())app.loop().post([&]{store.open(path);});
    return app.run();
}
