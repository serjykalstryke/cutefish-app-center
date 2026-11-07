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
#include <cctype>

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
#define APP_CENTER_VERSION "0.3.3"
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
static std::string sourceChoiceName(const J& item) {
    auto name=sourceName(item);
    if(str(item,"source")=="flatpak"){
        if(!str(item,"branch").empty())name+=" · "+str(item,"branch");
    }else if(str(item,"source")=="snap"){
        if(!str(item,"channel").empty())name+=" · "+str(item,"channel");
    }
    return name+(item["catalog"].toBool()?" · Download":item["installed"].toBool()?" · Installed":" · Available");
}
static std::string variantKey(const J& item) {
    if(!str(item,"search_key").empty())return str(item,"search_key");
    std::string key;
    for(auto field:{"source","id","scope","remote","branch","arch","architecture","channel","path"})key+=str(item,field)+"\n";
    return key;
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

class UpdateOperation : public ui::DialogWindow {
public:
    UpdateOperation(ui::Window* parent,const J& plan)
        : ui::DialogWindow(parent,"Software updates",620) {
        setCloseVisible(false);
        window()->onCloseRequested=[this]{if(!m_running)close();};
        auto* content=setContent<ui::Column>();
        content->setSpacing(14);content->setMargins(ui::Margins::all(20));
        m_heading=label(content,"Applying updates",22,700,true);
        m_summary=label(content,"Checking the reviewed updates…",13,400,true);
        m_scroll=content->addChild<ui::ScrollView>();size(m_scroll,-1,270,true);
        auto* sources=m_scroll->setContent<ui::Column>();sources->setSpacing(10);
        for(const auto& group:plan["groups"].toArray()){
            auto* card=sources->addChild<Panel>();card->setMargins(ui::Margins::all(12));card->setSpacing(6);
            size(card,-1,-1,true);
            label(card,str(group,"name"),15,650,true);
            auto* status=label(card,"Queued",12,550,true);
            auto* detail=label(card,"",12,400,true);detail->setVisible(false);
            auto* bar=card->addChild<ui::ProgressBar>();size(bar,-1,6,true);bar->setVisible(false);
            m_rows.push_back({card,status,detail,bar,"queued"});
        }
        m_notice=label(content,"",13,550,true);m_notice->setMaximumLineCount(5);m_notice->setVisible(false);
        auto* buttons=content->addChild<ui::Row>();size(buttons,-1,-1,true);buttons->addStretch();
        m_close=buttons->addChild<ui::DialogButton>("Close",true);m_close->setEnabled(false);
        m_close->onClicked=[this]{if(!m_running)close();};
    }

    void update(const J& event) {
        if(!m_running || !event["index"].isNumber())return;
        auto index=event["index"].toDouble();
        if(index<0 || index>=m_rows.size())return;
        auto& row=m_rows[static_cast<size_t>(index)];
        const auto state=str(event,"state");
        const bool active=state=="running";
        if(!active && state!="completed" && state!="failed" && state!="skipped")return;
        if(active && row.state=="queued")m_scroll->ensureVisible(row.card->geometry());
        row.state=state;
        auto status=statusText(state,str(event,"phase"));
        auto percent=event["percent"].toDouble();
        const bool measured=event["percent"].isNumber() && percent>=0 && percent<=100;
        if(active && measured)status+=" · "+std::to_string(static_cast<int>(percent))+"%";
        row.status->setText(status);
        auto detail=str(event,"message");
        row.detail->setText(detail);row.detail->setVisible(!detail.empty());
        row.bar->setVisible(active);row.bar->setIndeterminate(active && !measured);
        if(active && measured)row.bar->setValue(percent/100.);
        m_summary->setText(completionCount());
    }

    void finish(const J& result) {
        const bool hasErrors=result["errors"].size()>0;
        m_heading->setText(hasErrors?"Updates need attention":"Updates completed");
        m_summary->setText(completionCount()+(hasErrors?". Check for updates before retrying.":"."));
        finishWithNotice(str(result,"restart_notice"));
    }

    void fail(const std::string& error,bool reported) {
        m_heading->setText("Updates need attention");
        const bool started=std::any_of(m_rows.begin(),m_rows.end(),[](const Row& row){return row.state!="queued";});
        for(auto& row:m_rows)if(row.state=="queued" || row.state=="running"){
            row.status->setText(reported && !started?"Not attempted":"Outcome unknown");
            row.detail->setVisible(false);
            row.bar->setVisible(false);row.bar->setIndeterminate(false);
        }
        m_summary->setText(completionCount()+". Check for updates before retrying.");
        finishWithNotice(error);
    }

private:
    static std::string statusText(std::string_view state,std::string_view phase) {
        if(state=="completed")return "Completed";
        if(state=="failed")return "Needs attention";
        if(state=="skipped")return "Not attempted";
        if(phase=="authorization")return "Waiting for authentication";
        if(phase=="waiting")return "Waiting for package manager";
        if(phase=="downloading")return "Downloading";
        if(phase=="applying")return "Applying changes";
        if(phase=="checking")return "Checking changes";
        return "Working";
    }
    struct Row {
        Panel* card;
        ui::Label* status;
        ui::Label* detail;
        ui::ProgressBar* bar;
        std::string state;
    };
    std::string completionCount() const {
        const auto done=std::count_if(m_rows.begin(),m_rows.end(),[](const Row& row){return row.state=="completed";});
        return std::to_string(done)+" of "+std::to_string(m_rows.size())+(m_rows.size()==1?" source completed":" sources completed");
    }
    void finishWithNotice(const std::string& text) {
        m_running=false;
        m_notice->setText(text);m_notice->setToolTip(text);m_notice->setVisible(!text.empty());
        m_close->setEnabled(true);
    }
    bool m_running=true;
    std::vector<Row> m_rows;
    ui::ScrollView* m_scroll;
    ui::Label *m_heading,*m_summary,*m_notice;
    ui::DialogButton* m_close;
};

class AppRow : public ui::Button {
public:
    explicit AppRow(const J& item): ui::Button("") {
        auto* row=addChild<ui::Row>(); m_row=row;
        row->setSpacing(12); row->setMargins({12,10,12,10});
        m_icon=row->addChild<ui::IconImage>(str(item,"icon"),40);
        m_icon->setFallbackName("application-x-executable"); size(m_icon,40,40);
        auto* text=row->addChild<ui::Column>(); size(text,-1,-1,true); text->setSpacing(4);
        auto* heading=text->addChild<ui::Row>();heading->setSpacing(8);size(heading,-1,-1,true);
        auto* title=label(heading,str(item,"name"),15,600);title->setMaximumLineCount(1);
        if(item["update_available"].toBool()){
            auto* badge=label(heading,item["update_blocked"].toBool()?"Held":"Update",10,650);size(badge,48,-1);badge->setColor(ui::Theme::current().highlight);
        }
        else if(item["application_installed"].toBool()){
            auto* badge=label(heading,"Installed",10,550);size(badge,60,-1);badge->setColor(ui::ColorId::DisabledText);
        }
        auto subtitle=str(item,"application_sources").empty()?sourceName(item):str(item,"application_sources");
        if(item["management"].toBool()){
            auto version=str(item,"installed_version");if(!version.empty())subtitle+=" · "+version;
            auto available=str(item,"update_version");if(!available.empty() && available!=version)subtitle+=" → "+available;
        }
        auto* sub=label(text,subtitle,11); sub->setColor(ui::ColorId::DisabledText);
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
        for(const auto& entry:std::vector<std::vector<std::string>>{{"Discover","discover","view-grid"},{"Installed","installed","applications-other"},{"Install from File","files","document-open"}}){
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
        m_search->onTextEdited=[this]{if(m_page!="installed"){m_page="discover";m_mode="search";}m_debounce.start(450ms);};
        m_search->onAccepted=[this]{m_debounce.stop();refresh();};
        m_source=controls->addChild<ui::ComboBox>(std::vector<std::string>{"All sources","Debian","Flatpak","Snap","AppImage"});
        m_source->setCurrentIndex(0); size(m_source,150,36);
        m_source->onActivated=[this](int){refresh();};
        m_reload=controls->addChild<ui::Button>("Reload"); m_reload->onClicked=[this]{reloadView();};
        m_managementControls=main->addChild<ui::Column>();m_managementControls->setSpacing(10);size(m_managementControls,-1,-1,true);
        m_updateSummary=label(m_managementControls,"Checking for updates…",13,550,true);
        auto* management=m_managementControls->addChild<ui::Row>();management->setSpacing(10);size(management,-1,36,true);
        m_softwareView=management->addChild<ui::ComboBox>(std::vector<std::string>{"Applications","All software"});m_softwareView->setCurrentIndex(0);size(m_softwareView,160,36);
        m_softwareView->onActivated=[this](int){showLibrary();};
        m_updateFilter=management->addChild<ui::ComboBox>(std::vector<std::string>{"All installed","Updates only"});m_updateFilter->setCurrentIndex(0);size(m_updateFilter,150,36);
        m_updateFilter->onActivated=[this](int){showLibrary();};management->addStretch();
        m_updateAll=management->addChild<ui::DialogButton>("Update All",true);m_updateAll->setEnabled(false);m_updateAll->onClicked=[this]{prepareAllUpdates();};
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
    ~AppCenter(){cancelDetails();cancelDiscover();cancelIcons();cancelUpdateCheck();m_app.setMainMenu(nullptr);}
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
        m_softwareView->setEnabled(!value);m_updateFilter->setEnabled(!value);
        m_updateAll->setEnabled(!value && m_updatesLoaded && m_updatesComplete && m_updateCount>0);
        if(!value && m_libraryRenderPending){m_libraryRenderPending=false;m_app.loop().post([this]{if(!m_busy && m_page=="installed")showLibrary();});}
        m_list->setEnabled(!value);
        m_detail->setEnabled(!value);
    }
    void request(const J& data, std::function<void(const J&)> done, bool mutating=false,
                 std::function<void(const J&)> onEvent={},
                 std::function<void(const std::string&,bool)> onError={}) {
        if(m_preview || m_busy) return;
        cancelDetails();cancelIcons();
        if(mutating){cancelDiscover();cancelUpdateCheck();m_featuredLoaded=false;m_libraryLoaded=false;m_updatesLoaded=false;}
        m_debounce.stop(); busy(true,mutating);m_status->setText(mutating?"Applying software changes…":"Loading…");
        m_process=std::make_unique<base::Process>(&m_app.loop());
        m_process->setStandardInput(data.serialize()+"\n");
        m_buffer.clear();
        m_process->onStandardOutput=[this,onEvent](std::string_view bytes) {
            m_buffer.append(bytes);
            size_t e;
            while((e=m_buffer.find('\n'))!=std::string::npos) {
                auto line=m_buffer.substr(0,e);m_buffer.erase(0,e+1);
                auto item=J::parse(line);
                if(item && str(*item,"event")=="progress") {
                    auto text=str(*item,"message");
                    auto newline=text.find('\n'); if(newline!=std::string::npos)text.resize(newline);
                    m_status->setText(text);
                    const bool measured=(*item)["percent"].isNumber();
                    m_bar->setIndeterminate(!measured);
                    if(measured)m_bar->setValue((*item)["percent"].toDouble()/100.);
                }
                if(item && onEvent && str(*item,"event")=="update_progress")onEvent(*item);
            }
        };
        m_process->onFinished=[this,done,onError](int, bool) {
            std::string output=m_process->standardOutput();
            std::string errors=m_process->standardError();
            m_app.loop().post([this,output,errors,done,onError] {
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
                    if(onError)onError(error,str(result,"event")=="result");
                    else message("Software operation",error);
                    return;
                }
                m_status->setText(str(result,"message").empty()?"Ready":str(result,"message"));
                done(result);
            });
        };
        std::string backend=APP_CENTER_BACKEND;
        if(const char* env=std::getenv("CUTEFISH_APP_CENTER_BACKEND"))backend=env;
        if(!m_process->start("/usr/bin/python3",{backend})) {
            busy(false);m_status->setText("Could not start the store backend.");
            if(onError)onError("Could not start the software service.",true);
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
        cancelDetails();m_userSelected=false;if(page!="installed")cancelUpdateCheck();m_page=page;m_mode=page=="installed"?"installed":"search";
        m_search->setText("");m_source->setCurrentIndex(0);m_reviewedFile.clear();refresh();
    }
    void updateNavigation() {
        for(size_t i=0;i<m_nav.size();i++)m_nav[i]->setSelected(m_navPages[i]==m_page);
    }
    void reloadView() {
        if(m_busy)return;
        if(m_page=="installed"){m_updatesLoaded=false;loadLibrary(true);return;}
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
        const bool catalogPage=m_page=="discover" || m_page=="installed";
        m_controls->setVisible(catalogPage);m_metadataControls->setVisible(false);m_managementControls->setVisible(m_page=="installed");
        m_reload->setText(m_page=="installed"?"Check for Updates":"Reload");
        m_title->setText(m_page=="files"?"Install from File":m_page=="about"?"About":m_page=="installed"?"Installed":"Discover");
        m_subtitle->setVisible(m_page!="about" && !(m_page=="discover" && m_search->text().size()<2));
        if(m_page=="files"){m_subtitle->setText("Review a .deb or AppImage before installing.");filePage();return;}
        if(m_page=="about"){aboutPage();return;}
        if(m_page=="discover" && m_search->text().size()<2){landing();loadDiscover();return;}
        m_subtitle->setText(m_page=="discover"?"Find apps across your configured software sources.":"Manage installed apps and keep all software up to date.");
        if(m_page=="installed"){
            m_source->setVisible(true);m_reload->setVisible(true);m_footer->setVisible(true);
            if(!m_libraryLoaded)loadLibrary();else{showLibrary();if(!m_updatesLoaded && !m_updateProcess)startUpdateCheck();}
            return;
        }
        m_source->setVisible(true);m_reload->setVisible(true);m_footer->setVisible(true);
        static const std::vector<std::string> sources={"all","deb","flatpak","snap","appimage"};
        request(J::object({{"op","list"},{"mode",m_mode},{"query",m_search->text()},{"source",sources.at(std::max(0,m_source->currentIndex()))}}),[this](const J& result){populate(result);});
    }
    void cancelUpdateCheck() {
        ++m_updateGeneration;
        if(m_updateProcess){m_updateProcess->onFinished={};m_updateProcess->onStandardOutput={};m_updateProcess.reset();}
    }
    void loadLibrary(bool check=false) {
        if(m_busy)return;
        cancelUpdateCheck();m_updateItems.clear();m_updateWarnings.clear();m_updatesLoaded=false;m_updatesComplete=false;
        request(J::object({{"op","library"}}),[this,check](const J& result){
            m_libraryItems=result["items"].toArray();m_libraryWarnings=result["warnings"].toArray();m_libraryLoaded=true;
            showLibrary();startUpdateCheck(check);
        });
    }
    void startUpdateCheck(bool fresh=false) {
        cancelUpdateCheck();m_updatesLoaded=false;m_updatesComplete=false;
        const auto generation=m_updateGeneration;
        m_updateSummary->setText(fresh?"Refreshing sources and checking for updates…":"Checking for updates…");m_updateAll->setEnabled(false);
        m_updateProcess=std::make_unique<base::Process>(&m_app.loop());
        m_updateProcess->setStandardInput(J::object({{"op","update_inventory"},{"refresh",fresh}}).serialize()+"\n");
        m_updateProcess->onFinished=[this,generation](int,bool){
            auto output=m_updateProcess->standardOutput();
            m_app.loop().post([this,generation,output]{
                if(generation!=m_updateGeneration)return;
                m_updateProcess.reset();m_updatesLoaded=true;J result;
                size_t pos=0;while(pos<output.size()){
                    auto end=output.find('\n',pos);if(end==std::string::npos)end=output.size();
                    auto value=J::parse(output.substr(pos,end-pos));if(value && str(*value,"event")=="result")result=*value;pos=end+1;
                }
                m_updateItems=result["items"].toArray();m_updateWarnings=result["warnings"].toArray();
                m_updatesComplete=result["ok"].toBool() && result["complete"].toBool();
                if(!result["ok"].toBool())m_updateWarnings.push_back(str(result,"error").empty()?"Update checking did not complete. Try Check for Updates.":str(result,"error"));
                if(m_page=="installed"){
                    if(!m_busy)showLibrary();else m_libraryRenderPending=true;
                }
            });
        };
        std::string backend=APP_CENTER_BACKEND;if(const char* path=std::getenv("CUTEFISH_APP_CENTER_BACKEND"))backend=path;
        if(!m_updateProcess->start("/usr/bin/python3",{backend})){
            m_updateProcess.reset();m_updatesLoaded=true;m_updateWarnings={"Could not start update checking."};showLibrary();
        }
    }
    void showLibrary() {
        if(m_page!="installed" || !m_libraryLoaded)return;
        std::map<std::string,J> records;
        for(auto item:m_libraryItems){item.insert("management",true);item.insert("update_available",false);records[str(item,"install_key")]=item;}
        for(const auto& update:m_updateItems){
            const auto key=str(update,"install_key");
            if(!records.contains(key)){auto item=update;item.insert("management",true);records[key]=item;}
            auto& item=records[key];
            for(auto field:{"package_id","update_available","update_blocked","update_version","revision","installed_revision"})
                if(!update[field].isNull())item.insert(field,update[field]);
        }
        size_t eligible=0,appUpdates=0,blocked=0;
        for(const auto& update:m_updateItems){
            if(update["update_blocked"].toBool()){++blocked;continue;}
            ++eligible;auto it=records.find(str(update,"install_key"));
            if(it!=records.end() && it->second["is_application"].toBool())++appUpdates;
        }
        m_updateCount=eligible;
        auto summary=!m_updatesLoaded?"Checking for updates…":!m_updatesComplete?"Some update sources are unavailable":eligible==0?(blocked?"No installable updates available":"No updates available"):std::to_string(eligible)+" updates available · "+std::to_string(appUpdates)+" applications · "+std::to_string(eligible-appUpdates)+" system components";
        if(blocked)summary+=" · "+std::to_string(blocked)+" held or blocked";
        if(m_restartRequired)summary+=" · Restart required";
        m_updateSummary->setText(summary);
        m_updateAll->setText(eligible?"Update All ("+std::to_string(eligible)+")":"Update All");
        m_updateAll->setEnabled(!m_busy && m_updatesLoaded && m_updatesComplete && eligible>0);
        m_updateAll->setToolTip("Review updates for all software and sources, including system packages and runtimes hidden by the current filters.");
        static const std::vector<std::string> sources={"all","deb","flatpak","snap","appimage"};
        const auto source=sources.at(std::max(0,m_source->currentIndex()));
        auto lower=[](std::string value){std::transform(value.begin(),value.end(),value.begin(),[](unsigned char c){return char(std::tolower(c));});return value;};
        const auto query=lower(m_search->text());J::Array visible;
        size_t hidden=0;
        for(auto& [key,item]:records){
            if(source!="all" && str(item,"source")!=source)continue;
            if(m_softwareView->currentIndex()==0 && !item["is_application"].toBool()){++hidden;continue;}
            if(m_updateFilter->currentIndex()==1 && !item["update_available"].toBool())continue;
            if(!query.empty() && lower(str(item,"name")+" "+str(item,"id")+" "+str(item,"summary")).find(query)==std::string::npos)continue;
            visible.push_back(item);
        }
        std::stable_sort(visible.begin(),visible.end(),[&](const J& a,const J& b){
            if(a["update_available"].toBool()!=b["update_available"].toBool())return a["update_available"].toBool();
            return std::make_pair(lower(str(a,"name")),str(a,"install_key"))<std::make_pair(lower(str(b,"name")),str(b,"install_key"));
        });
        auto warnings=m_libraryWarnings;warnings.insert(warnings.end(),m_updateWarnings.begin(),m_updateWarnings.end());
        std::string note=hidden?std::to_string(hidden)+" system components available under All software.":"";
        populate(J::object({{"items",visible},{"warnings",warnings},{"message",note}}));
    }
    void prepareAllUpdates() {
        if(m_busy || !m_updatesLoaded || !m_updatesComplete || m_updateCount==0)return;
        request(J::object({{"op","plan_all_updates"}}),[this](const J& result){
            J plan=result["plan"];
            if(plan["groups"].size()==0){message("Software updates","No updates remain to apply.");m_libraryLoaded=false;refresh();return;}
            m_review=std::make_unique<ui::DialogWindow>(&m_window,"Review all software updates",690);
            auto* content=m_review->setContent<ui::Column>();content->setSpacing(14);content->setMargins(ui::Margins::all(20));
            label(content,"Update all software",22,700,true);
            label(content,str(plan,"note"),12,400,true);
            auto* scroll=content->addChild<ui::ScrollView>();size(scroll,-1,380,true);
            auto* changes=scroll->setContent<ui::Column>();changes->setSpacing(10);
            for(const auto& group:plan["groups"].toArray()){
                label(changes,str(group,"name"),16,650,true);label(changes,str(group,"note"),11,400,true);
                for(const auto& change:group["changes"].toArray()){
                    auto name=str(change,"name");if(name.empty())name=str(change,"id");
                    auto version=str(change,"version");label(changes,str(change,"info")+"  "+name+(version.empty()?"":" → "+version),12,400,true);
                    if(str(change,"id")!=name)label(changes,str(change,"id"),11,400,true);
                }
            }
            if(plan["blocked_count"].toDouble()>0)label(changes,"Held or blocked updates are left unchanged.",12,400,true);
            auto* buttons=content->addChild<ui::Row>();buttons->setSpacing(12);buttons->addStretch();
            auto* cancel=buttons->addChild<ui::Button>("Cancel");cancel->onClicked=[this]{m_review->close();};
            auto* confirm=buttons->addChild<ui::DialogButton>("Apply Updates",true);
            confirm->onClicked=[this,plan]{
                m_review->close();
                m_app.loop().post([this,plan]{applyAllUpdates(plan);});
            };
            m_review->show();
        });
    }
    void applyAllUpdates(const J& plan) {
        if(m_busy)return;
        m_updateOperation=std::make_unique<UpdateOperation>(&m_window,plan);
        m_updateOperation->onClosed=[this]{
            m_libraryLoaded=false;m_updatesLoaded=false;m_variants.clear();refresh();
        };
        m_updateOperation->show();
        request(J::object({{"op","apply_all_updates"},{"plan",plan}}),[this](const J& result){
            m_restartRequired=m_restartRequired || result["restart"].toBool();
            m_updateOperation->finish(result);
        },true,[this](const J& event){m_updateOperation->update(event);},
        [this](const std::string& error,bool reported){m_updateOperation->fail(error,reported);});
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
        if(m_page=="installed")return str(item,"install_key");
        if(!str(item,"application_key").empty())return str(item,"application_key");
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
        std::string priorKey;J priorDetails;
        if(m_page=="installed" && m_userSelected && m_selectedVariant<m_variants.size()){priorKey=str(m_variants[m_selectedVariant],"install_key");priorDetails=m_variants[m_selectedVariant];}
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
            label(empty,m_page=="installed"?(m_updateFilter->currentIndex()==1?"No updates in this view":"No applications in this view"):"No results",21,650,true);
            label(empty,"Check the source messages below, or try another search.",13,400,true);
            detailEmpty();m_detail->setVisible(false);
        }
        size_t selected=0;bool ordinary=false;
        for(size_t i=0;i<m_groups.size();i++) {
            if(m_page=="installed"){
                bool pending=m_groups[i][0]["update_available"].toBool();
                if(i==0 && pending)label(col,"Updates available",14,650);
                if(!pending && !ordinary){label(col,"Installed",14,650);ordinary=true;}
                if(str(m_groups[i][0],"install_key")==priorKey){
                    selected=i;
                    if(priorDetails["details_loaded"].toBool()){
                        for(auto field:{"update_available","update_blocked","update_version","package_id","installed_version"})
                            if(!m_groups[i][0][field].isNull())priorDetails.insert(field,m_groups[i][0][field]);
                        m_groups[i][0]=priorDetails;
                    }
                }
            }
            auto presentation=m_groups[i][0];
            if(m_page!="installed" && !str(presentation,"application_key").empty()){
                presentation.insert("name",presentation["application_name"]);
                if(!str(presentation,"application_icon").empty())presentation.insert("icon",presentation["application_icon"]);
            }
            auto* row=col->addChild<AppRow>(presentation);
            if(m_groups[i].size()>1)row->setToolTip(std::to_string(m_groups[i].size())+" source or installation choices");
            row->onClicked=[this,i]{if(m_page=="installed")m_userSelected=true;select(i);};m_rows.push_back(row);
        }
        std::string warnings;
        for(const auto& w:result["warnings"].toArray()){if(!warnings.empty())warnings+="\n";warnings+=w.toString();}
        m_warnings->setVisible(!warnings.empty());m_warnings->setText(warnings);m_warnings->setToolTip(warnings);
        auto count=std::to_string(m_groups.size())+(m_mode=="search"?" results · best matches first":" entries");
        if(!warnings.empty())count+=" · some sources unavailable";
        if(!str(result,"message").empty())count+=" · "+str(result,"message");
        m_status->setText(count);
        if(!m_groups.empty())select(selected);
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
            for(auto& variant:m_groups[i]){
                if(str(variant,"icon_key")==key)variant.insert("icon",path);
                if(str(variant,"application_icon_key")==key)variant.insert("application_icon",path);
            }
            auto rowKey=str(m_groups[i][0],"application_icon_key");if(rowKey.empty())rowKey=str(m_groups[i][0],"icon_key");
            if(i<m_rows.size() && rowKey==key)m_rows[i]->setIcon(path);
        }
        for(auto& variant:m_variants){
            if(str(variant,"icon_key")==key)variant.insert("icon",path);
            if(str(variant,"application_icon_key")==key)variant.insert("application_icon",path);
        }
    }
    void loadVisibleIcons() {
        if(m_preview || m_busy || m_iconProcess || m_rows.empty() || !m_list->isVisible())return;
        const auto top=m_list->mapToWindow({0,0}).y;
        const auto bottom=top+m_list->geometry().height;
        J::Array keys;
        for(size_t i=0;i<m_rows.size() && keys.size()<12;i++){
            auto* row=m_rows[i];const auto y=row->mapToWindow({0,0}).y;
            if(y+row->geometry().height<top-80 || y>bottom+80)continue;
            auto key=str(m_groups[i][0],"application_icon_key");if(key.empty())key=str(m_groups[i][0],"icon_key");
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
        m_variants=m_groups[i];m_activeApplication=groupKey(m_variants[0]);size_t selected=0;
        if(m_page!="installed" && m_sourceChoices.contains(m_activeApplication)){
            for(size_t n=0;n<m_variants.size();n++)if(variantKey(m_variants[n])==m_sourceChoices[m_activeApplication]){selected=n;break;}
        }
        details(selected);
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
        for(const auto& entry:std::vector<std::pair<std::string,std::string>>{{"Discover","discover"},{"Installed","installed"},{"Install from File","files"}}){view->addItem(entry.first,[this,page=entry.second]{navigate(page);});}
        view->addSeparator();
        auto search=[this]{if(m_busy)return;if(m_page=="files" || m_page=="about")navigate("discover");m_search->setFocus();};
        auto find=view->addItem("Search",search);view->setItemKeyEquivalent(find,"f",ui::ControlModifier);m_window.addShortcut(ui::ControlModifier,'f',search);
        auto reload=view->addItem("Reload",[this]{reloadView();});view->setItemKeyEquivalent(reload,"r",ui::ControlModifier);m_window.addShortcut(ui::ControlModifier,'r',[this]{reloadView();});
        auto* software=m_mainMenu->addSubmenu("Software");
        software->addItem("Check for Updates",[this]{if(!m_busy){if(m_page!="installed")navigate("installed");reloadView();}});
        auto all=software->addItem("Update All",[this]{prepareAllUpdates();});
        software->onAboutToShow=[this,software,all]{software->setItemEnabled(all,m_page=="installed" && !m_busy && m_updatesLoaded && m_updatesComplete && m_updateCount>0);};
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
        const bool unified=m_page!="installed" && !str(item,"application_name").empty();
        label(title,unified?str(item,"application_name"):str(item,"name"),23,700,true);
        auto* status=label(title,item["catalog"].toBool()?"AppImage download":item["installed"].toBool()?"Installed":item["application_installed"].toBool()?"Installed from another source":"Available",11,500);status->setColor(ui::ColorId::DisabledText);
        auto summary=unified?str(item,"application_summary"):str(item,"summary");
        if(!summary.empty())label(panel,summary,13,400,true);
        if(!str(item,"publisher").empty())label(panel,str(item,"publisher")+(item["publisher_verified"].toBool()?" · Verified Snap publisher":""),12,550,true);
        label(panel,"Software source",11,650);
        if(m_variants.size()>1) {
            std::vector<std::string> names;std::map<std::string,int> duplicates;
            for(auto& v:m_variants){names.push_back(sourceChoiceName(v));++duplicates[names.back()];}
            for(size_t n=0;n<names.size();n++)if(duplicates[names[n]]>1){
                auto arch=str(m_variants[n],"arch");if(arch.empty())arch=str(m_variants[n],"architecture");
                names[n]+=" · "+str(m_variants[n],"id")+(arch.empty()?"":" · "+arch);
            }
            auto* variants=panel->addChild<ui::ComboBox>(names);size(variants,-1,36,true);variants->setCurrentIndex(int(index));
            variants->setToolTip("Choose the software source for this application. Actions apply only to the selected source.");
            variants->onActivated=[this](int n){
                if(n<0 || size_t(n)>=m_variants.size())return;
                m_sourceChoices[m_activeApplication]=variantKey(m_variants[n]);
                m_app.loop().post([this,n]{details(n);});
            };
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
            std::string action=installed?(item["update_available"].toBool()?"update":"remove"):"install";
            std::string text=action=="remove"?"Remove":action=="update"?"Update":str(item,"source")=="appimage"?"Import AppImage":"Install";
            auto* button=actions->addChild<ui::DialogButton>(text,!item["can_open"].toBool());size(button,-1,40,true);
            button->setDestructive(action=="remove");button->setEnabled(!m_preview && !(action=="remove" && (item["protected"].toBool() || str(item,"ref_kind")=="runtime")) && !(action=="update" && item["update_blocked"].toBool()));button->onClicked=[this,item,action]{prepare(item,action);};
            if(installed && action=="update"){
                auto* remove=actions->addChild<ui::Button>("Remove");size(remove,-1,40,true);remove->setEnabled(!m_preview && !item["protected"].toBool() && str(item,"ref_kind")!="runtime");
                remove->onClicked=[this,item]{prepare(item,"remove");};
            }
            if(item["update_blocked"].toBool())label(panel,"This update is held or blocked by the system package service.",12,500,true);
            if(str(item,"ref_kind")=="runtime")label(panel,"Shared runtime — removal is managed by Flatpak.",12,400,true);
            if(item["protected"].toBool())label(panel,str(item,"source")=="deb"?"Protected system package":"Protected system component",12,600,true);
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
            auto value=std::string(field)=="version" && !str(item,"update_version").empty()?str(item,"update_version"):str(item,field);if(value.empty())continue;
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
                    m_restartRequired=m_restartRequired || result["restart"].toBool();
                    m_libraryLoaded=false;m_updatesLoaded=false;m_variants.clear();detailEmpty();refresh();
                },true);
            };
            m_review->show();
        });
    }
    ui::Application& m_app;
    bool m_preview=false,m_busy=false,m_mutating=false;
    std::string m_mode="search",m_page="discover",m_buffer,m_displayName,m_author,m_brandIcon,m_distribution,m_projectUrl,m_reviewedFile;
    J::Array m_libraryItems,m_libraryWarnings,m_updateItems,m_updateWarnings;
    bool m_libraryLoaded=false,m_updatesLoaded=false,m_updatesComplete=false,m_libraryRenderPending=false,m_restartRequired=false,m_userSelected=false;
    size_t m_updateCount=0;unsigned long m_updateGeneration=0;
    ui::Column* m_managementControls;
    ui::Label* m_updateSummary;
    ui::ComboBox *m_softwareView,*m_updateFilter;
    ui::DialogButton* m_updateAll;
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
    std::string m_activeApplication;
    std::map<std::string,std::string> m_sourceChoices;
    std::unique_ptr<base::Process> m_process,m_detailProcess,m_discoverProcess,m_iconProcess,m_updateProcess;
    base::Timer m_debounce,m_iconDebounce;
    std::unique_ptr<ui::FileChooser> m_chooser;
    std::unique_ptr<UpdateOperation> m_updateOperation;
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
