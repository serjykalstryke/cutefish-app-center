#define main cutefish_app_center_program_main
#include "../src/main.cpp"
#undef main
#include "preferences_fixture.h"
#include <cassert>
#include <ui/test_input.h>

template<class T> static T* find(ui::View* root,std::function<bool(T*)> match){
    if(auto* v=dynamic_cast<T*>(root);v && match(v))return v;
    for(auto& child:root->children())if(auto* v=find<T>(child.get(),match))return v;
    return nullptr;
}
static ui::Label* text(ui::View* root,const std::string& value){return find<ui::Label>(root,[&](auto* l){return l->text()==value;});}
static void click(ui::Window& window,ui::View* view){
    assert(view);for(auto* parent=view->parent();parent;parent=parent->parent())if(auto* scroll=dynamic_cast<ui::ScrollView*>(parent)){
        auto point=view->mapToWindow({0,0}),origin=scroll->contentView()->mapToWindow({0,0});
        scroll->ensureVisible({point.x-origin.x,point.y-origin.y,view->geometry().width,view->geometry().height});
    }
    window.grab();ui::TestInput::click(window,view->mapToWindow({view->geometry().width/2,view->geometry().height/2}));
}
static J record(const std::filesystem::path& file){std::ifstream stream(file);return *J::parse(std::string{std::istreambuf_iterator<char>(stream),{}});}
int main(int argc,char** argv){
    isolatePreferences("native_sources");
    auto folder=std::filesystem::absolute("work/sources-fixture");std::filesystem::create_directories(folder);
    for(auto file:{"source-state.json","source-plan.json","source-apply.json","software-plan.json"})std::filesystem::remove(folder/file);
    auto backend=(std::filesystem::path(__FILE__).parent_path()/"sources_fixture.py").string();setenv("CUTEFISH_APP_CENTER_BACKEND",backend.c_str(),1);setenv("APP_CENTER_SOURCES_FIXTURE_DIR",folder.c_str(),1);
    ui::Application app(argc,argv,ui::Application::Platform::Headless);AppCenter store(app,false);store.show();auto& w=store.window();
    base::Timer poll(&app.loop());int stage=0,ticks=0;
    auto dialog=[&](const std::string& button)->ui::Window*{for(auto* win:app.windows())if(win!=&w && text(win->contentView(),button))return win;return nullptr;};
    poll.onTimeout=[&]{
        if(++ticks>300){std::cerr<<"Sources test timeout at stage "<<stage<<"\n";app.quit(1);return;}w.grab();auto* root=w.contentView();
        if(stage==0){
            ui::TestInput::setKeyboardFocus(w,true);ui::TestInput::typeKey(w,',',ui::ControlModifier);
            auto* sections=find<ui::SegmentedControl>(root,[](auto*){return true;});assert(sections);sections->setCurrentIndex(1);sections->onCurrentChanged(1);stage=1;
        }else if(stage==1 && text(root,"Debian main")){
            assert(text(root,"Flathub · system"));assert(w.grab().savePng("work/sources-fixture/sources-light.png"));ui::Theme::setCurrent(ui::Theme::dark());assert(w.grab().savePng("work/sources-fixture/sources-dark.png"));
            click(w,text(root,"Disable"));stage=2;
        }else if(stage==2 && dialog("Apply Source Change")){
            assert(str(record(folder/"source-plan.json")["target"],"id")=="debian-main");assert(!std::filesystem::exists(folder/"source-apply.json"));
            auto* d=dialog("Apply Source Change");click(*d,text(d->contentView(),"Apply Source Change"));stage=3;
        }else if(stage==3 && text(root,"Disabled")){
            assert(std::filesystem::exists(folder/"source-apply.json"));click(w,text(root,"Add Flatpak Source…"));stage=4;
        }else if(stage==4 && dialog("Review Source")){
            auto* d=dialog("Review Source");auto* presets=find<ui::ComboBox>(d->contentView(),[](auto* c){return c->items().size()==3;});assert(presets);presets->setCurrentIndex(1);presets->onActivated(1);click(*d,text(d->contentView(),"Review Source"));stage=5;
        }else if(stage==5 && dialog("Apply Source Change")){
            auto target=record(folder/"source-plan.json")["target"];assert(str(target,"id")=="flathub-beta");assert(str(target,"scope")=="user");assert(str(target,"repository_url")=="https://flathub.org/beta-repo/flathub-beta.flatpakrepo");
            auto* d=dialog("Apply Source Change");click(*d,text(d->contentView(),"Cancel"));stage=51;
        }else if(stage==51){click(w,text(root,"Install Snap Support"));stage=6;
        }else if(stage==6 && dialog("Install")){
            auto target=record(folder/"software-plan.json")["target"];assert(str(target,"source")=="deb" && str(target,"id")=="snapd");
            auto* d=dialog("Install");click(*d,text(d->contentView(),"Cancel"));stage=61;
        }else if(stage==61){click(w,text(root,"Catalog"));auto* search=find<ui::SearchField>(root,[](auto*){return true;});search->setText("example");search->onAccepted();stage=7;
        }else if(stage==7 && text(root,"Fixture Publisher")){
            auto* channels=find<ui::ComboBox>(root,[](auto* c){return c->toolTip()=="Choose a published Snap track and release channel";});assert(channels && channels->currentIndex()==0);channels->setCurrentIndex(1);channels->onActivated(1);stage=8;
        }else if(stage==8 && text(root,"Change Channel")){
            assert(text(root,"Currently tracking latest/stable"));click(w,text(root,"Change Channel"));stage=9;
        }else if(stage==9 && dialog("Change Channel")){
            auto request=record(folder/"software-plan.json");assert(str(request,"action")=="switch-channel");assert(str(request["target"],"requested_channel")=="latest/beta");
            std::cout<<"Source inventory, scopes, review before mutation, Flatpak preset, missing-provider setup and exact Snap channel review passed.\n";app.quit();
        }
    };poll.start(100ms);return app.run();
}
