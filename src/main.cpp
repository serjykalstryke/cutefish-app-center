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
#include <set>
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
#include <ui/image_view.h>
#include <ui/label.h>
#include <ui/layout.h>
#include <ui/menu.h>
#include <ui/event.h>
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

#ifndef APP_CENTER_BACKEND
#define APP_CENTER_BACKEND "/usr/libexec/cutefish-app-center/app_center_backend.py"
#endif
#ifndef APP_CENTER_BRANDING_FILE
#define APP_CENTER_BRANDING_FILE "/usr/share/cutefish-app-center/branding.json"
#endif
#ifndef APP_CENTER_VERSION
#define APP_CENTER_VERSION "0.2.2"
#endif

static J branding() {
    std::string path=APP_CENTER_BRANDING_FILE;
    if(const char* overridePath=std::getenv("CUTEFISH_APP_CENTER_BRANDING"))path=overridePath;
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
    explicit Panel(bool accent=false,double radius=16): m_accent(accent),m_radius(radius) { setMargins(ui::Margins::all(20)); setSpacing(12); }
protected:
    void paint(ui::Painter& p) override {
        auto color=m_accent ? ui::Theme::current().highlight.withAlpha(.10) : ui::Theme::current().secondBackground;
        if(m_radius>0)p.fillRoundedRect(localRect(),m_radius,color);else p.fillRect(localRect(),color);
    }
private: bool m_accent;double m_radius;
};
class AppRow : public ui::Button {
public:
    explicit AppRow(const J& item): ui::Button("") {
        auto* row=addChild<ui::Row>(); m_row=row;
        row->setSpacing(12); row->setMargins({12,10,12,10});
        m_icon=row->addChild<ui::IconImage>(str(item,"icon"),40);
        m_icon->setFallbackName("application-x-executable"); size(m_icon,40,40);
        auto* text=row->addChild<ui::Column>(); size(text,-1,-1,true); text->setSpacing(4);
        label(text,str(item,"name"),15,600);
        auto* sub=label(text,sourceName(item),11); sub->setColor(ui::ColorId::DisabledText);
        size(this,-1,72,true);
    }
    void selected(bool selected) { m_selected=selected; requestPaint(); }
    void setIcon(const std::string& path) { m_icon->setName(path); }
protected:
    void layout() override { ui::Button::layout(); m_row->setGeometry(localRect()); }
    void paint(ui::Painter& p) override {
        ui::Button::paint(p);
        if(m_selected) p.strokeRoundedRect(localRect().adjusted(1,1,-1,-1),10,ui::Theme::current().highlight,2);
    }
private: ui::Row* m_row; ui::IconImage* m_icon; bool m_selected=false;
};

class NavigationItem : public ui::Button {
public:
    NavigationItem(const std::string& text,const std::string& icon):ui::Button(""){
        m_content=addChild<ui::Row>();m_content->setSpacing(10);m_content->setMargins({12,9,12,9});
        auto* glyph=m_content->addChild<ui::IconImage>(icon,20);glyph->setFallbackName("applications-other");size(glyph,20,20);
        label(m_content,text,13,500);size(this,-1,42,true);
    }
    void setSelected(bool selected){m_selected=selected;requestPaint();}
protected:
    void layout() override {m_content->setGeometry(localRect());}
    void paint(ui::Painter& p) override {
        if(m_selected)p.fillRoundedRect(localRect(),9,ui::Theme::current().highlight.withAlpha(.16));
        else if(m_hot)p.fillRoundedRect(localRect(),9,ui::Theme::current().text.withAlpha(.05));
        if(hasVisibleFocus())p.strokeRoundedRect(localRect().adjusted(1,1,-1,-1),9,ui::Theme::current().highlight,1.5);
    }
    void pointerEnter() override {ui::Button::pointerEnter();m_hot=true;requestPaint();}
    void pointerLeave() override {ui::Button::pointerLeave();m_hot=false;requestPaint();}
private:ui::Row* m_content;bool m_selected=false,m_hot=false;
};
class CategoryTile : public ui::Button {
public:
    CategoryTile(const std::string& name,const std::string& description,const std::string& icon):ui::Button(""){
        m_content=addChild<ui::Row>();m_content->setMargins({16,15,16,15});m_content->setSpacing(12);
        auto* glyph=m_content->addChild<ui::IconImage>(icon,32);glyph->setFallbackName("applications-other");size(glyph,32,32);
        auto* text=m_content->addChild<ui::Column>();text->setSpacing(4);size(text,-1,-1,true);
        label(text,name,14,600);auto* descriptionLabel=label(text,description,11,400,true);descriptionLabel->setColor(ui::ColorId::DisabledText);descriptionLabel->setMaximumLineCount(2);
        size(this,-1,86,true);
    }
protected:
    void layout() override {m_content->setGeometry(localRect());}
    void paint(ui::Painter& p) override {
        p.fillRoundedRect(localRect(),12,ui::Theme::current().secondBackground);
        if(m_hot)p.fillRoundedRect(localRect(),12,ui::Theme::current().highlight.withAlpha(.06));
        if(hasVisibleFocus())p.strokeRoundedRect(localRect().adjusted(1,1,-1,-1),12,ui::Theme::current().highlight,1.5);
    }
    void pointerEnter() override {ui::Button::pointerEnter();m_hot=true;requestPaint();}
    void pointerLeave() override {ui::Button::pointerLeave();m_hot=false;requestPaint();}
private:ui::Row* m_content;bool m_hot=false;
};
class FeaturedCard : public ui::Button {
public:
    explicit FeaturedCard(const J& item):ui::Button(""){
        m_content=addChild<ui::Column>();m_content->setMargins(ui::Margins::all(18));m_content->setSpacing(12);
        auto* heading=m_content->addChild<ui::Row>();heading->setSpacing(12);size(heading,-1,48,true);
        auto* icon=heading->addChild<ui::IconImage>(str(item,"icon"),48);icon->setFallbackName("application-x-executable");size(icon,48,48);
        auto* name=label(heading,str(item,"feature_name"),17,650,true);name->setMaximumLineCount(2);size(name,-1,-1,true);
        auto* summary=label(m_content,str(item,"summary"),12,400,true);summary->setMaximumLineCount(2);
        m_content->addStretch();
        auto* source=label(m_content,sourceName(item),10);source->setColor(ui::ColorId::DisabledText);
        auto* action=label(m_content,"View details →",12,600);action->setColor(ui::Theme::current().highlight);
        setToolTip(str(item,"summary"));size(this,-1,204,true);
    }
protected:
    void layout() override {m_content->setGeometry(localRect());}
    void paint(ui::Painter& p) override {
        p.fillRoundedRect(localRect(),14,ui::Theme::current().secondBackground);
        if(m_hot)p.fillRoundedRect(localRect(),14,ui::Theme::current().highlight.withAlpha(.05));
        if(m_hot || hasVisibleFocus())p.strokeRoundedRect(localRect().adjusted(1,1,-1,-1),14,ui::Theme::current().highlight.withAlpha(.5),1.5);
    }
    void pointerEnter() override {ui::Button::pointerEnter();m_hot=true;requestPaint();}
    void pointerLeave() override {ui::Button::pointerLeave();m_hot=false;requestPaint();}
private:ui::Column* m_content;bool m_hot=false;
};
class DropPanel : public Panel {
public:
    DropPanel():Panel(false,14){}
    void setActive(bool active){m_active=active;requestPaint();}
protected:
    void paint(ui::Painter& p) override {
        Panel::paint(p);
        if(m_active)p.fillRoundedRect(localRect(),14,ui::Theme::current().highlight.withAlpha(.08));
        p.strokeRoundedRect(localRect().adjusted(1,1,-1,-1),14,m_active?ui::Theme::current().highlight:ui::Theme::current().disabledText.withAlpha(.3),m_active?2:1);
    }
private:bool m_active=false;
};

class AppCenter {
public:
    AppCenter(ui::Application& app, bool preview): m_app(app), m_preview(preview), m_debounce(&app.loop()), m_iconDebounce(&app.loop()) {
        auto brand=branding();
        const auto displayName=brand["display_name"].toString("Cutefish App Center");
        m_displayName=displayName;
        m_author=brand["author"].toString("David Stinnett");m_brandIcon=brand["icon"].toString("org.cutefish.AppCenter");
        m_distribution=brand["distribution_label"].toString("Debian 13");m_projectUrl=brand["project_url"].toString("https://github.com/serjykalstryke/cutefish-app-center");
        m_window.setTitle(displayName); m_window.setMinimumSize({1000,700}); m_window.resize({1200,850});
        m_window.setRestoreId("main");
        m_window.onCloseRequested=[this] {
            if(m_mutating) { m_status->setText("Please wait for the software operation to finish before closing the store."); return; }
            m_app.quit();
        };
        auto drop=std::make_unique<ui::FileDropArea>();
        drop->filter=[](const std::string& url){ return base::url::isLocalFile(url); };
        drop->onContainsDragChanged=[this,area=drop.get()]{if(m_dropZone)m_dropZone->setActive(area->containsDrag());};
        drop->onDropped=[this](const std::vector<std::string>& urls){
            if(!m_busy && !urls.empty()) if(auto p=base::url::toLocalFile(urls.front())) inspect(*p);
        };
        auto* body=drop->addChild<ui::Row>(); size(body,-1,-1,true,true);
        auto* sideSurface=body->addChild<Panel>(false,0); size(sideSurface,192,-1,false,true);
        sideSurface->setMargins(ui::Margins::all(0));
        auto* windowControls=sideSurface->addChild<ui::WindowHeader>(48);
        windowControls->setButtonsCentered(true);windowControls->setButtonMargin(14);size(windowControls,-1,48,true);
        auto* sidebar=sideSurface->addChild<ui::Column>();size(sidebar,-1,-1,true,true);
        sidebar->setMargins({16,10,16,18});sidebar->setSpacing(12);
        auto* brandRow=sidebar->addChild<ui::Row>();brandRow->setSpacing(10);size(brandRow,-1,54,true);
        auto* mark=brandRow->addChild<ui::IconImage>(brand["icon"].toString("org.cutefish.AppCenter"),36);size(mark,36,36);
        label(brandRow,brand["sidebar_name"].toString("App Center"),16,650,true);
        size(sidebar->addChild<ui::View>(),-1,8);
        for(const auto& entry:std::vector<std::vector<std::string>>{{"Discover","discover","view-grid"},{"Installed","installed","applications-other"},{"Updates","updates","system-software-update"},{"Install from File","files","document-open"}}){
            auto* button=sidebar->addChild<NavigationItem>(entry[0],entry[2]);
            button->onClicked=[this,page=entry[1]]{navigate(page);};m_nav.push_back(button);m_navPages.push_back(entry[1]);
        }
        sidebar->addStretch();
        auto* about=sidebar->addChild<NavigationItem>("About","help-about");about->onClicked=[this]{navigate("about");};m_nav.push_back(about);m_navPages.push_back("about");
        auto* main=body->addChild<ui::Column>(); size(main,-1,-1,true,true);
        main->setMargins({26,0,26,18}); main->setSpacing(14);
        auto* header=main->addChild<ui::WindowHeader>(38);size(header,-1,38,true);
        header->setCloseVisible(false);header->setMinimizeVisible(false);header->setMaximizeVisible(false);

        m_title=label(main,"Discover",28,700);
        m_subtitle=label(main,"Find apps across your configured software sources.",13);
        m_subtitle->setColor(ui::ColorId::DisabledText);
        auto* controls=main->addChild<ui::Row>();m_controls=controls; controls->setSpacing(12); size(controls,-1,38,true);
        m_search=controls->addChild<ui::SearchField>("Search apps"); size(m_search,-1,38,true);
        m_search->onTextEdited=[this]{if(m_page!="installed" && m_page!="updates"){m_page="discover";m_mode="search";}m_debounce.start(450ms);};
        m_search->onAccepted=[this]{m_debounce.stop();refresh();};
        m_source=controls->addChild<ui::ComboBox>(std::vector<std::string>{"All sources","Debian","Flatpak","Snap","AppImage"});
        m_source->setCurrentIndex(0); size(m_source,150,36);
        m_source->onActivated=[this](int){refresh();};
        m_reload=controls->addChild<ui::Button>("Reload"); m_reload->onClicked=[this]{reloadView();};
        auto* workspace=main->addChild<ui::Row>(); workspace->setSpacing(18); size(workspace,-1,-1,true,true);
        m_list=workspace->addChild<ui::ScrollView>(); size(m_list,-1,-1,true,true);
        m_list->onScrolled=[this]{m_iconDebounce.start(80ms);};
        m_detail=workspace->addChild<ui::ScrollView>(); size(m_detail,412,-1,false,true);
        m_warnings=label(main,"",11,400,true); m_warnings->setMaximumLineCount(3); m_warnings->setColor(ui::ColorId::DisabledText); m_warnings->setVisible(false);
        auto* footer=main->addChild<ui::Row>();m_footer=footer; footer->setSpacing(12); size(footer,-1,28,true);
        m_status=label(footer,"Ready",11); size(m_status,-1,-1,true);
        m_bar=footer->addChild<ui::ProgressBar>(); size(m_bar,110,6); m_bar->setVisible(false);
        auto* metadata=main->addChild<ui::Row>();m_metadataControls=metadata;metadata->setSpacing(12);size(metadata,-1,-1,true);
        m_refresh=metadata->addChild<ui::Button>("Refresh Debian catalog");
        m_flatpakRefresh=metadata->addChild<ui::Button>("Refresh Flatpak catalog");
        m_flatpakRefresh->onClicked=[this]{request(J::object({{"op","refresh_flatpak"}}),[this](const J&){refresh();},true);};
        m_refresh->setToolTip("Ask the system package service to download the latest repository metadata.");
        m_refresh->onClicked=[this]{request(J::object({{"op","refresh"}}),[this](const J&){refresh();},true);};
        m_debounce.setSingleShot(true); m_debounce.onTimeout=[this]{if(!m_busy)refresh();};
        m_iconDebounce.setSingleShot(true);m_iconDebounce.onTimeout=[this]{loadVisibleIcons();};
        m_window.setContentView(std::move(drop));
        setupMenu();
        navigate("discover");
        if(m_preview) {
            m_featured=J::Array{
                J::object({{"source","flatpak"},{"remote","flathub"},{"scope","system"},{"feature_name","Firefox"},{"name","Firefox"},{"query","firefox"},{"summary","Browse the web with a fast, private browser."},{"icon","firefox"}}),
                J::object({{"source","deb"},{"scope","system"},{"feature_name","LibreOffice"},{"name","LibreOffice"},{"query","libreoffice"},{"summary","Documents, spreadsheets and presentations."},{"icon","libreoffice-startcenter"}}),
                J::object({{"source","flatpak"},{"remote","flathub"},{"scope","system"},{"feature_name","VLC"},{"name","VLC"},{"query","vlc"},{"summary","Play your music and videos."},{"icon","vlc"}})};
            m_featuredLoaded=true;landing();
        }
    }
    ~AppCenter(){cancelDetails();cancelDiscover();m_app.setMainMenu(nullptr);}
    void show(){m_window.show();}
    ui::Window& window(){return m_window;}
    void open(const std::string& path){inspect(path);}
private:
    void busy(bool value, bool mutating=false) {
        m_busy=value; m_mutating=value && mutating;
        m_bar->setVisible(value); m_bar->setIndeterminate(value);
        for(auto* b:m_nav) b->setEnabled(!value);
        m_search->setEnabled(!value);m_source->setEnabled(!value);m_reload->setEnabled(!value);
        m_refresh->setEnabled(!value);m_flatpakRefresh->setEnabled(!value);
        if(value)m_footer->setVisible(true);
        m_list->setEnabled(!value);
        m_detail->setEnabled(!value);
    }
    void request(const J& data, std::function<void(const J&)> done, bool mutating=false) {
        if(m_preview || m_busy) return;
        cancelDetails();cancelIcons();
        if(mutating){cancelDiscover();m_featuredLoaded=false;}
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
        std::string backend=APP_CENTER_BACKEND;
        if(const char* env=std::getenv("CUTEFISH_APP_CENTER_BACKEND"))backend=env;
        if(!m_process->start("/usr/bin/python3",{backend})) {
            busy(false);m_status->setText("Could not start the store backend.");
        }
    }
    void message(const std::string& title, const std::string& text) {
        m_message=std::make_unique<ui::ConfirmDialog>(&m_window,title,text);
        m_message->setConfirmText("Close");m_message->setCancelVisible(false);m_message->show();
    }
    void chooseFile() {
        if(m_page!="files")navigate("files");
        m_chooser=std::make_unique<ui::FileChooser>(&m_window);
        m_chooser->setTitle("Open software package");
        m_chooser->setAcceptLabel("Review");
        m_chooser->setFilters({{"Software packages",{"*.deb","*.AppImage","*.appimage"},{}},{"All files",{"*"},{}}});
        m_chooser->onAccepted=[this](const std::vector<std::string>& paths,const std::string&){if(!paths.empty())inspect(paths.front());};
        m_chooser->open();
    }
    void inspect(std::string path) {
        if(m_page!="files")navigate("files");
        if(auto local=base::url::toLocalFile(path))path=*local;
        m_reviewedFile=std::filesystem::path(path).filename().string();
        request(J::object({{"op","inspect"},{"path",path}}),[this](const J& result){
            filePage();m_detail->setVisible(true);m_footer->setVisible(true);
            m_variants={result["item"]};details(0);
            m_status->setText("Review the file, then choose Install or Import.");
        });
    }
    void navigate(const std::string& page) {
        if(m_busy)return;
        cancelDetails();m_page=page;m_mode=page=="installed"?"installed":page=="updates"?"updates":"search";
        m_search->setText("");m_source->setCurrentIndex(0);m_reviewedFile.clear();refresh();
    }
    void updateNavigation() {
        for(size_t i=0;i<m_nav.size();i++)m_nav[i]->setSelected(m_navPages[i]==m_page);
    }
    void reloadView() {
        if(m_busy)return;
        cancelDiscover();m_featuredLoaded=false;refresh();
    }
    void resetPage() {
        cancelDetails();cancelIcons();m_variants.clear();m_groups.clear();m_rows.clear();m_selectedVariant=0;m_dropZone=nullptr;
        m_detail->setContent<ui::Column>();
        m_detail->setVisible(false);m_warnings->setVisible(false);m_footer->setVisible(false);
    }
    void refresh() {
        if(m_busy)return;
        updateNavigation();
        const bool catalogPage=m_page=="discover" || m_page=="installed" || m_page=="updates";
        m_controls->setVisible(catalogPage);m_metadataControls->setVisible(m_page=="updates");
        m_title->setText(m_page=="files"?"Install from File":m_page=="about"?"About":m_page=="installed"?"Installed":m_page=="updates"?"Updates":"Discover");
        m_subtitle->setVisible(m_page!="about" && !(m_page=="discover" && m_search->text().size()<2));
        if(m_page=="files"){m_subtitle->setText("Review a .deb or AppImage before installing.");filePage();return;}
        if(m_page=="about"){aboutPage();return;}
        if(m_page=="discover" && m_search->text().size()<2){landing();loadDiscover();return;}
        m_subtitle->setText(m_page=="discover"?"Find apps across your configured software sources.":m_page=="installed"?"Manage installed applications and packages.":"Available updates from your software sources.");
        m_source->setVisible(true);m_reload->setVisible(true);m_footer->setVisible(true);
        static const std::vector<std::string> sources={"all","deb","flatpak","snap","appimage"};
        request(J::object({{"op","list"},{"mode",m_mode},{"query",m_search->text()},{"source",sources.at(std::max(0,m_source->currentIndex()))}}),[this](const J& result){populate(result);});
    }
    void searchFor(const std::string& query) {
        if(m_busy)return;
        m_page="discover";m_mode="search";m_search->setText(query);m_source->setCurrentIndex(0);refresh();
    }
    void cancelDiscover() {
        ++m_discoverGeneration;
        if(m_discoverProcess){m_discoverProcess->onFinished={};m_discoverProcess.reset();}
    }
    void loadDiscover() {
        if(m_preview || m_featuredLoaded || m_discoverProcess)return;
        const auto generation=++m_discoverGeneration;
        m_discoverProcess=std::make_unique<base::Process>(&m_app.loop());
        m_discoverProcess->setStandardInput(J::object({{"op","discover"}}).serialize()+"\n");
        m_discoverProcess->onFinished=[this,generation](int,bool){
            auto output=m_discoverProcess->standardOutput();
            m_app.loop().post([this,generation,output]{
                if(generation!=m_discoverGeneration)return;
                m_discoverProcess.reset();m_featuredLoaded=true;
                size_t pos=0;while(pos<output.size()){
                    auto end=output.find('\n',pos);if(end==std::string::npos)end=output.size();
                    auto result=J::parse(output.substr(pos,end-pos));if(result && str(*result,"event")=="result" && (*result)["ok"].toBool())m_featured=(*result)["items"].toArray();pos=end+1;
                }
                if(m_page=="discover" && m_search->text().size()<2 && !m_busy)landing();
            });
        };
        std::string backend=APP_CENTER_BACKEND;if(const char* path=std::getenv("CUTEFISH_APP_CENTER_BACKEND"))backend=path;
        if(!m_discoverProcess->start("/usr/bin/python3",{backend})){
            m_discoverProcess.reset();m_featuredLoaded=true;landing();
        }
    }
    void landing() {
        resetPage();m_source->setVisible(false);m_reload->setVisible(false);
        auto* content=m_list->setContent<ui::Column>();content->setSpacing(22);content->setMargins({0,4,0,18});
        auto* heading=content->addChild<ui::Row>();heading->setSpacing(10);size(heading,-1,-1,true);
        size(label(heading,"Featured apps",19,650),-1,-1,true);
        const size_t pages=std::max(size_t(1),(m_featured.size()+2)/3);m_featuredPage=std::min(m_featuredPage,pages-1);
        if(!m_featured.empty()){
            auto* previous=heading->addChild<ui::Button>("‹");size(previous,32,30);previous->setToolTip("Previous featured apps");previous->setEnabled(m_featuredPage>0);
            size(label(heading,std::to_string(m_featuredPage+1)+" / "+std::to_string(pages),11),42,-1);
            auto* next=heading->addChild<ui::Button>("›");size(next,32,30);next->setToolTip("Next featured apps");next->setEnabled(m_featuredPage+1<pages);
            previous->onClicked=[this]{m_app.loop().post([this]{if(m_featuredPage>0)--m_featuredPage;landing();});};
            next->onClicked=[this]{m_app.loop().post([this]{++m_featuredPage;landing();});};
            auto* cards=content->addChild<ui::Row>();cards->setSpacing(14);size(cards,-1,204,true);
            const size_t start=m_featuredPage*3;
            for(size_t i=start;i<std::min(start+3,m_featured.size());i++){
                auto* card=cards->addChild<FeaturedCard>(m_featured[i]);const auto query=str(m_featured[i],"query");
                card->onClicked=[this,query]{m_app.loop().post([this,query]{searchFor(query);});};
            }
        } else {
            auto* empty=content->addChild<Panel>();size(empty,-1,150,true);
            label(empty,m_featuredLoaded?"No featured apps available":"Loading featured apps…",15,550,true);
            if(m_featuredLoaded){label(empty,"Search your configured sources or explore a category below.",12,400,true);}
        }
        label(content,"Explore categories",19,650);
        auto* categories=content->addChild<ui::Grid>(3);categories->setColumnSpacing(12);categories->setRowSpacing(12);size(categories,-1,-1,true);
        for(const auto& category:std::vector<std::vector<std::string>>{
            {"Internet","Browsers, mail and chat","applications-internet","internet"},
            {"Graphics","Images, illustration and design","applications-graphics","graphics"},
            {"Office","Documents and productivity","applications-office","office"},
            {"Audio & Video","Music, players and editing","applications-multimedia","audio video"},
            {"Development","Editors and developer tools","applications-development","development"},
            {"Games","Puzzles, strategy and more","applications-games","games"},
            {"Education","Learning and reference","applications-education","education"},
            {"Utilities","Useful everyday tools","applications-utilities","utilities"}}){
            auto* tile=categories->addChild<CategoryTile>(category[0],category[1],category[2]);auto query=category[3];
            tile->onClicked=[this,query]{m_app.loop().post([this,query]{searchFor(query);});};
        }
    }
    void filePage() {
        resetPage();
        auto* content=m_list->setContent<ui::Column>();content->setSpacing(18);content->setMargins({0,12,0,18});
        m_dropZone=content->addChild<DropPanel>();m_dropZone->setSpacing(16);m_dropZone->setMargins(ui::Margins::all(30));size(m_dropZone,-1,310,true);
        auto* icon=m_dropZone->addChild<ui::IconImage>("document-open",56);size(icon,56,56);
        label(m_dropZone,"Drop a package here",23,650,true);
        label(m_dropZone,"Debian packages (.deb) and AppImages",13,400,true);
        auto* row=m_dropZone->addChild<ui::Row>();size(row,-1,-1,true);
        auto* choose=row->addChild<ui::DialogButton>("Choose File…",true);size(choose,160,40);choose->setEnabled(!m_preview);choose->onClicked=[this]{chooseFile();};
        if(!m_reviewedFile.empty()){
            auto* selected=content->addChild<Panel>();label(selected,"Selected file",11,550);label(selected,m_reviewedFile,14,600,true);
        }
        label(content,"You’ll review the file and software changes before anything is installed.",12,400,true);
    }
    void aboutPage() {
        resetPage();
        auto* content=m_list->setContent<ui::Column>();content->setMargins({0,12,0,18});content->setSpacing(18);
        auto* panel=content->addChild<Panel>();panel->setMargins(ui::Margins::all(28));panel->setSpacing(22);size(panel,-1,-1,true);
        auto* hero=panel->addChild<ui::Row>();hero->setSpacing(20);size(hero,-1,-1,true);
        auto* icon=hero->addChild<ui::IconImage>(m_brandIcon,80);icon->setFallbackName("system-software-install");size(icon,80,80);
        auto* title=hero->addChild<ui::Column>();title->setSpacing(8);size(title,-1,-1,true);
        label(title,m_displayName,26,700,true);label(title,std::string("Version ")+APP_CENTER_VERSION,13,400,true);
        label(panel,"A software manager for the Cutefish desktop.",15,400,true);
        auto* author=panel->addChild<ui::Column>();author->setSpacing(6);
        label(author,"Created by",11,500);label(author,m_author,18,650,true);
        label(panel,"Developed for Cutefish and NordOS. This is an independent community project.",13,400,true);
        auto* facts=panel->addChild<ui::Column>();facts->setSpacing(10);
        label(facts,"License  BSD-3-Clause",12,400,true);label(facts,"System  "+m_distribution,12,400,true);
        auto* links=panel->addChild<ui::Row>();links->setSpacing(12);size(links,-1,-1,true);
        auto* source=links->addChild<ui::Button>("View Source ↗");source->setEnabled(!m_preview);source->onClicked=[this]{openWebsite(m_projectUrl);};
        auto* issue=links->addChild<ui::Button>("Report an Issue ↗");issue->setEnabled(!m_preview);issue->onClicked=[this]{openWebsite(m_projectUrl+"/issues");};
    }
    void detailEmpty() {
        cancelDetails();m_variants.clear();m_selectedVariant=0;
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
        cancelIcons();
        m_detail->setVisible(true);m_footer->setVisible(true);
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
            detailEmpty();m_detail->setVisible(false);
        }
        for(size_t i=0;i<m_groups.size();i++) {
            auto* row=col->addChild<AppRow>(m_groups[i][0]);
            if(m_groups[i].size()>1)row->setToolTip(std::to_string(m_groups[i].size())+" source or installation choices");
            row->onClicked=[this,i]{select(i);};m_rows.push_back(row);
        }
        std::string warnings;
        for(const auto& w:result["warnings"].toArray()){if(!warnings.empty())warnings+="\n";warnings+=w.toString();}
        m_warnings->setVisible(!warnings.empty());m_warnings->setText(warnings);m_warnings->setToolTip(warnings);
        auto count=std::to_string(m_groups.size())+(m_mode=="search"?" results · best matches first":" entries");
        if(!warnings.empty())count+=" · some sources unavailable";
        if(!str(result,"message").empty())count+=" · "+str(result,"message");
        m_status->setText(count);
        if(!m_groups.empty())select(0);
        m_iconDebounce.start(1ms);
    }
    void cancelIcons() {
        ++m_iconGeneration;m_iconDebounce.stop();m_iconAttempted.clear();
        if(m_iconProcess){m_iconProcess->onStandardOutput={};m_iconProcess->onFinished={};m_iconProcess.reset();}
        m_iconBuffer.clear();
    }
    void applyListIcon(const std::string& key,const std::string& path) {
        if(key.empty() || !std::filesystem::path(path).is_absolute())return;
        for(size_t i=0;i<m_groups.size();i++){
            for(auto& variant:m_groups[i])if(str(variant,"icon_key")==key)variant.insert("icon",path);
            if(i<m_rows.size() && str(m_groups[i][0],"icon_key")==key)m_rows[i]->setIcon(path);
        }
        for(auto& variant:m_variants)if(str(variant,"icon_key")==key)variant.insert("icon",path);
    }
    void loadVisibleIcons() {
        if(m_preview || m_busy || m_iconProcess || m_rows.empty() || !m_list->isVisible())return;
        const auto top=m_list->mapToWindow({0,0}).y;
        const auto bottom=top+m_list->geometry().height;
        J::Array keys;
        for(size_t i=0;i<m_rows.size() && keys.size()<12;i++){
            auto* row=m_rows[i];const auto y=row->mapToWindow({0,0}).y;
            if(y+row->geometry().height<top-80 || y>bottom+80)continue;
            auto key=str(m_groups[i][0],"icon_key");
            if(!key.empty() && m_iconAttempted.insert(key).second)keys.push_back(key);
        }
        if(keys.empty())return;
        const auto generation=m_iconGeneration;m_iconBuffer.clear();
        m_iconProcess=std::make_unique<base::Process>(&m_app.loop());
        m_iconProcess->setStandardInput(J::object({{"op","icons"},{"keys",keys}}).serialize()+"\n");
        m_iconProcess->onStandardOutput=[this,generation](std::string_view bytes){
            if(generation!=m_iconGeneration)return;
            m_iconBuffer.append(bytes);size_t end;
            while((end=m_iconBuffer.find('\n'))!=std::string::npos){
                auto event=J::parse(m_iconBuffer.substr(0,end));m_iconBuffer.erase(0,end+1);
                if(event && str(*event,"event")=="icon"){
                    const auto key=str(*event,"key"),path=str(*event,"path");
                    m_app.loop().post([this,generation,key,path]{if(generation==m_iconGeneration)applyListIcon(key,path);});
                }
            }
        };
        m_iconProcess->onFinished=[this,generation](int,bool){
            m_app.loop().post([this,generation]{
                if(generation!=m_iconGeneration)return;
                m_iconProcess.reset();m_iconDebounce.start(80ms);
            });
        };
        std::string backend=APP_CENTER_BACKEND;if(const char* path=std::getenv("CUTEFISH_APP_CENTER_BACKEND"))backend=path;
        if(!m_iconProcess->start("/usr/bin/python3",{backend}))m_iconProcess.reset();
    }
    void select(size_t i) {
        for(size_t n=0;n<m_rows.size();n++)m_rows[n]->selected(n==i);
        m_variants=m_groups[i];details(0);
    }
    void cancelDetails() {
        ++m_detailGeneration;
        if(m_detailProcess){m_detailProcess->onFinished={};m_detailProcess.reset();}
    }
    void setupMenu() {
        m_mainMenu=std::make_unique<ui::Menu>();
        auto* application=m_mainMenu->addSubmenu(m_displayName);application->setRole(ui::MenuRole::Application);
        application->addItem("About "+m_displayName,[this]{navigate("about");});
        application->addSeparator();
        auto quit=[this]{if(m_mutating)message("Software operation","Please wait for the software operation to finish before quitting.");else m_app.quit();};
        auto q=application->addItem("Quit "+m_displayName,quit);application->setItemKeyEquivalent(q,"q",ui::ControlModifier);
        m_window.addShortcut(ui::ControlModifier,'q',quit);
        auto* file=m_mainMenu->addSubmenu("File");
        auto open=file->addItem("Open File…",[this]{if(!m_busy)chooseFile();});file->setItemKeyEquivalent(open,"o",ui::ControlModifier);
        m_window.addShortcut(ui::ControlModifier,'o',[this]{if(!m_busy)chooseFile();});
        auto launch=file->addItem("Open Selected App",[this]{
            if(!m_busy && m_selectedVariant<m_variants.size() && m_variants[m_selectedVariant]["can_open"].toBool())launchApp(m_variants[m_selectedVariant]);
        });
        file->onAboutToShow=[this,file,open,launch]{file->setItemEnabled(open,!m_busy && !m_preview);file->setItemEnabled(launch,!m_busy && !m_preview && m_selectedVariant<m_variants.size() && m_variants[m_selectedVariant]["can_open"].toBool());};
        auto* view=m_mainMenu->addSubmenu("View");
        for(const auto& entry:std::vector<std::pair<std::string,std::string>>{{"Discover","discover"},{"Installed","installed"},{"Updates","updates"},{"Install from File","files"}}){view->addItem(entry.first,[this,page=entry.second]{navigate(page);});}
        view->addSeparator();
        auto search=[this]{if(m_busy)return;if(m_page=="files" || m_page=="about")navigate("discover");m_search->setFocus();};
        auto find=view->addItem("Search",search);view->setItemKeyEquivalent(find,"f",ui::ControlModifier);m_window.addShortcut(ui::ControlModifier,'f',search);
        auto reload=view->addItem("Reload",[this]{reloadView();});view->setItemKeyEquivalent(reload,"r",ui::ControlModifier);m_window.addShortcut(ui::ControlModifier,'r',[this]{reloadView();});
        auto* software=m_mainMenu->addSubmenu("Software");
        software->addItem("Refresh Debian Catalog",[this]{if(!m_busy)request(J::object({{"op","refresh"}}),[this](const J&){refresh();},true);});
        software->addItem("Refresh Flatpak Catalog",[this]{if(!m_busy)request(J::object({{"op","refresh_flatpak"}}),[this](const J&){refresh();},true);});
        auto* help=m_mainMenu->addSubmenu("Help");help->setRole(ui::MenuRole::Help);
        help->addItem("Build Instructions and Help",[this]{openWebsite("https://github.com/serjykalstryke/cutefish-app-center#build-from-source-on-debian-13");});
        m_app.setMainMenu(m_mainMenu.get());
    }
    void openWebsite(const std::string& url) {
        if(url.starts_with("https://") && base::Process::startDetached("/usr/bin/xdg-open",{url})<0)
            message("Open website","Could not open your web browser.");
    }
    void launchApp(const J& item) {
        request(J::object({{"op","launch"},{"target",item}}),[this](const J& result){m_status->setText(str(result,"message"));});
    }
    void details(size_t index) {
        if(index>=m_variants.size())return;
        cancelDetails();m_selectedVariant=index;
        renderDetails(index);
        if(m_preview || m_variants[index]["details_loaded"].toBool())return;
        const auto generation=m_detailGeneration;
        m_detailProcess=std::make_unique<base::Process>(&m_app.loop());
        m_detailProcess->setStandardInput(J::object({{"op","details"},{"target",m_variants[index]}}).serialize()+"\n");
        m_detailProcess->onFinished=[this,index,generation](int,bool){
            auto output=m_detailProcess->standardOutput();
            m_app.loop().post([this,index,generation,output]{
                if(generation!=m_detailGeneration || index>=m_variants.size())return;
                m_detailProcess.reset();J result;
                size_t pos=0;while(pos<output.size()){
                    auto end=output.find('\n',pos);if(end==std::string::npos)end=output.size();
                    auto value=J::parse(output.substr(pos,end-pos));if(value && str(*value,"event")=="result")result=*value;pos=end+1;
                }
                if(result["ok"].toBool()) {
                    m_variants[index]=result["item"];
                    applyListIcon(str(m_variants[index],"icon_key"),str(m_variants[index],"icon"));
                    if(result["warnings"].size())m_variants[index].insert("details_note",result["warnings"][0]);
                } else {
                    m_variants[index].insert("details_loaded",true);
                    m_variants[index].insert("details_note","Additional details are unavailable. You can still review the software operation.");
                }
                renderDetails(index);
            });
        };
        std::string backend=APP_CENTER_BACKEND;if(const char* path=std::getenv("CUTEFISH_APP_CENTER_BACKEND"))backend=path;
        if(!m_detailProcess->start("/usr/bin/python3",{backend})){
            m_detailProcess.reset();m_variants[index].insert("details_loaded",true);m_variants[index].insert("details_note","Additional details could not be loaded.");renderDetails(index);
        }
    }
    void screenshotDialog(const J& shot,const std::string& name) {
        m_imageViewer=std::make_unique<ui::DialogWindow>(&m_window,name+" — Screenshot",900);
        auto* content=m_imageViewer->setContent<ui::Column>();content->setMargins(ui::Margins::all(18));content->setSpacing(12);
        auto* image=content->addChild<ui::ImageView>(str(shot,"path"));image->setFillMode(ui::ImageView::FillMode::PreserveAspectFit);size(image,-1,450,true);
        if(!str(shot,"caption").empty())label(content,str(shot,"caption"),12,400,true);
        auto* close=content->addChild<ui::Button>("Close");close->onClicked=[this]{m_imageViewer->close();};
        m_imageViewer->show();
    }
    void gallery(ui::Column* panel,const J& item) {
        label(panel,"Screenshots",16,650);
        auto shots=item["screenshots"].toArray();
        if(shots.empty()){
            auto* missing=label(panel,str(item,"artwork_note").empty()?"Screenshots are not provided by this source.":str(item,"artwork_note"),12,400,true);
            missing->setColor(ui::ColorId::DisabledText);return;
        }
        auto* image=panel->addChild<ui::ImageView>(str(shots[0],"path"));
        image->setFillMode(ui::ImageView::FillMode::PreserveAspectFit);image->setCornerRadius(10);size(image,-1,205,true);
        auto* caption=label(panel,str(shots[0],"caption"),11,400,true);caption->setMaximumLineCount(3);
        auto* controls=panel->addChild<ui::Row>();controls->setSpacing(8);size(controls,-1,-1,true);
        auto current=std::make_shared<size_t>(0);
        auto* previous=controls->addChild<ui::Button>("‹");previous->setToolTip("Previous screenshot");
        auto* count=label(controls,"1 / "+std::to_string(shots.size()),11);size(count,-1,-1,true);
        auto* next=controls->addChild<ui::Button>("›");next->setToolTip("Next screenshot");
        previous->setEnabled(shots.size()>1);next->setEnabled(shots.size()>1);
        auto update=[image,caption,count,current,shots]{image->setSource(str(shots[*current],"path"));caption->setText(str(shots[*current],"caption"));count->setText(std::to_string(*current+1)+" / "+std::to_string(shots.size()));};
        previous->onClicked=[current,shots,update]{*current=(*current+shots.size()-1)%shots.size();update();};
        next->onClicked=[current,shots,update]{*current=(*current+1)%shots.size();update();};
        auto* enlarge=controls->addChild<ui::Button>("Enlarge…");enlarge->onClicked=[this,current,shots,item]{screenshotDialog(shots[*current],str(item,"name"));};
    }
    void renderDetails(size_t index) {
        if(index>=m_variants.size())return;
        J item=m_variants[index];
        auto* panel=m_detail->setContent<Panel>();panel->setSpacing(14);
        auto* identity=panel->addChild<ui::Row>();identity->setSpacing(14);size(identity,-1,-1,true);
        auto* icon=identity->addChild<ui::IconImage>(str(item,"icon"),64);icon->setFallbackName("application-x-executable");size(icon,64,64);
        auto* title=identity->addChild<ui::Column>();title->setSpacing(5);size(title,-1,-1,true);
        label(title,str(item,"name"),23,700,true);
        auto* status=label(title,item["catalog"].toBool()?"AppImage download":item["installed"].toBool()?"Installed":"Available",11,500);status->setColor(ui::ColorId::DisabledText);
        if(!str(item,"summary").empty())label(panel,str(item,"summary"),13,400,true);
        if(!str(item,"publisher").empty())label(panel,str(item,"publisher")+(item["publisher_verified"].toBool()?" · Verified Snap publisher":""),12,550,true);
        label(panel,"Software source",11,650);
        if(m_variants.size()>1) {
            std::vector<std::string> names;for(auto& v:m_variants){auto name=sourceName(v);if(!str(v,"branch").empty())name+=" · "+str(v,"branch");names.push_back(name);}
            auto* variants=panel->addChild<ui::ComboBox>(names);size(variants,-1,36,true);variants->setCurrentIndex(int(index));
            variants->onActivated=[this](int n){m_app.loop().post([this,n]{details(n);});};
        } else label(panel,sourceName(item),13,550,true);
        if(item["catalog"].toBool()) {
            auto* download=panel->addChild<ui::DialogButton>("Open download page…",true);size(download,-1,40,true);download->setEnabled(!m_preview);
            download->onClicked=[this,item]{request(J::object({{"op","catalog_link"},{"target",item}}),[this](const J& result){openWebsite(str(result,"url"));});};
            label(panel,"Download an AppImage from its publisher, then open it here to import it.",12,400,true);
        } else {
            auto* actions=panel->addChild<ui::Row>();actions->setSpacing(10);size(actions,-1,40,true);
            if(item["can_open"].toBool()) {
                auto* open=actions->addChild<ui::DialogButton>("Open",true);size(open,-1,40,true);open->setEnabled(!m_preview);open->onClicked=[this,item]{launchApp(item);};
            }
            bool installed=item["installed"].toBool();
            std::string action=installed?(m_mode=="updates"?"update":"remove"):"install";
            std::string text=action=="remove"?"Remove":action=="update"?"Update":str(item,"source")=="appimage"?"Import AppImage":"Install";
            auto* button=actions->addChild<ui::DialogButton>(text,!item["can_open"].toBool());size(button,-1,40,true);
            button->setDestructive(action=="remove");button->setEnabled(!m_preview && !item["protected"].toBool());button->onClicked=[this,item,action]{prepare(item,action);};
            if(item["protected"].toBool())label(panel,"Protected system package",12,600,true);
        }
        if(!item["details_loaded"].toBool() && !m_preview){label(panel,"Loading app details…",12,400,true);return;}
        if(!str(item,"details_note").empty())label(panel,str(item,"details_note"),12,400,true);
        gallery(panel,item);
        label(panel,"About",16,650);
        auto description=str(item,"description");if(description.empty())description=str(item,"summary");
        label(panel,description.empty()?"No additional description is provided by this source.":description,13,400,true);
        if(!str(item,"homepage").empty()){
            auto* website=panel->addChild<ui::Button>("Project website ↗");website->setEnabled(!m_preview);website->onClicked=[this,item]{openWebsite(str(item,"homepage"));};
        }
        label(panel,"Details",16,650);
        for(auto field:{"installed_version","version","branch","arch","architecture","license","maintainer","catalog_author","confinement"}){
            auto value=str(item,field);if(value.empty())continue;
            std::string name=std::string(field)=="installed_version"?"Installed version":std::string(field)=="version"?"Available version":std::string(field)=="branch"?"Branch":std::string(field)=="license"?"License":std::string(field)=="maintainer"?"Package maintainer":std::string(field)=="catalog_author"?"Catalog author":std::string(field)=="confinement"?"Confinement":"Architecture";
            if(std::string(field)=="version" && value==str(item,"installed_version"))continue;
            label(panel,name+"  "+value,12,400,true);
        }
        auto* identifier=label(panel,"Identifier  "+str(item,"id"),11,400,true);identifier->setToolTip(str(item,"id"));
        if(!str(item,"path").empty())label(panel,"File  "+std::filesystem::path(str(item,"path")).filename().string(),11,400,true);
        if(str(item,"source")=="appimage")label(panel,"AppImage downloads and updates are managed by the publisher.",11,400,true);
        if(str(item,"source")=="snap")label(panel,"Snapd manages automatic updates for installed snaps.",11,400,true);
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
    std::string m_mode="search",m_page="discover",m_buffer,m_displayName,m_author,m_brandIcon,m_distribution,m_projectUrl,m_reviewedFile;
    J::Array m_featured;bool m_featuredLoaded=false;size_t m_featuredPage=0;
    unsigned long m_discoverGeneration=0;
    size_t m_selectedVariant=0;
    unsigned long m_detailGeneration=0,m_iconGeneration=0;
    std::set<std::string> m_iconAttempted;
    std::string m_iconBuffer;
    std::unique_ptr<ui::Menu> m_mainMenu;
    ui::Window m_window;
    ui::Label *m_title,*m_subtitle,*m_status,*m_warnings;
    ui::SearchField* m_search;
    ui::ComboBox* m_source;
    ui::Button *m_reload,*m_refresh,*m_flatpakRefresh;
    ui::Row *m_controls,*m_footer,*m_metadataControls;
    DropPanel* m_dropZone=nullptr;
    ui::ProgressBar* m_bar;
    ui::ScrollView *m_list,*m_detail;
    std::vector<NavigationItem*> m_nav;
    std::vector<std::string> m_navPages;
    std::vector<AppRow*> m_rows;
    std::vector<std::vector<J>> m_groups;
    std::vector<J> m_variants;
    std::unique_ptr<base::Process> m_process,m_detailProcess,m_discoverProcess,m_iconProcess;
    base::Timer m_debounce,m_iconDebounce;
    std::unique_ptr<ui::FileChooser> m_chooser;
    std::unique_ptr<ui::ConfirmDialog> m_message;
    std::unique_ptr<ui::DialogWindow> m_review,m_imageViewer;
};

int main(int argc,char** argv) {
    bool preview=false;std::string screenshot,path;
    for(int i=1;i<argc;i++) {
        std::string arg=argv[i];
        if(arg=="--preview")preview=true;
        else if(arg=="--screenshot" && i+1<argc){screenshot=argv[++i];preview=true;}
        else if(arg=="--help") {std::cout<<"cutefish-app-center [FILE.deb|FILE.AppImage] [--preview] [--screenshot PATH]\n";return 0;}
        else if(path.empty())path=arg;
    }
    ui::Application app(argc,argv,screenshot.empty()?ui::Application::Platform::Wayland:ui::Application::Platform::Headless);
    app.setApplicationId("org.cutefish.AppCenter");
    AppCenter store(app,preview);store.show();
    if(!screenshot.empty())return store.window().grab().savePng(screenshot)?0:1;
    if(!path.empty())app.loop().post([&]{store.open(path);});
    return app.run();
}
