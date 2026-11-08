#define main cutefish_app_center_program_main
#include "../src/main.cpp"
#undef main
#include "preferences_fixture.h"
#include <cassert>
#include <sys/stat.h>
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
static void policyChecks(const std::filesystem::path& folder){
    auto path=folder/"policy.json";std::filesystem::remove(path);Preferences prefs(path);std::string error;
    assert(prefs.sourceOrder()==Preferences::formats());assert(prefs.rememberChoices());assert(prefs.choices().empty());
    assert(prefs.setOrder({"snap","appimage","flatpak","deb"},error));
    J deb=J::object({{"source","deb"},{"id","browser"},{"search_key","deb-target"}});
    J flatpak=J::object({{"source","flatpak"},{"id","org.example.Browser"},{"scope","user"},{"search_key","flatpak-target"}});
    J snap=J::object({{"source","snap"},{"id","browser"},{"search_key","snap-target"}});
    assert(preferredVariant({deb,flatpak,snap},prefs)==2);
    flatpak.insert("installed",true);assert(preferredVariant({deb,flatpak,snap},prefs)==1);
    assert(preferredVariant({deb,flatpak,snap},prefs,"deb-target")==0);
    assert(preferredVariant({deb,flatpak,snap},prefs,"unavailable-target")==1);
    assert(prefs.setChoice("app:browser","flatpak-target",error));Preferences reopened(path);
    assert(reopened.choices().at("app:browser")=="flatpak-target");assert(reopened.sourceOrder()[0]=="snap");
    struct stat info{};assert(::stat(path.c_str(),&info)==0);assert((info.st_mode&0777)==0600);
    assert(reopened.clearChoices(error));assert(Preferences(path).choices().empty());assert(reopened.sourceOrder()[0]=="snap");
    assert(reopened.setChoice("app:browser","snap-target",error));assert(reopened.setRememberChoices(false,error));
    assert(!Preferences(path).rememberChoices());assert(Preferences(path).choices().empty());
    assert(reopened.setChoice("app:browser","deb-target",error));assert(Preferences(path).choices().empty());
    assert(reopened.reset(error));Preferences otherWindow(path);
    assert(reopened.setOrder({"flatpak","snap","deb","appimage"},error));
    assert(otherWindow.setChoice("app:other","flatpak-target",error));
    assert(Preferences(path).sourceOrder()[0]=="flatpak");assert(Preferences(path).choices().size()==1);
    {std::ofstream file(path);file<<R"({"version":1,"source_order":["snap","snap","unknown"],"future_option":true})";}
    Preferences normalized(path);assert(normalized.sourceOrder()==std::vector<std::string>({"snap","deb","flatpak","appimage"}));
    assert(normalized.setChoice("app:browser","snap-target",error));
    {std::ifstream file(path);auto data=J::parse(std::string{std::istreambuf_iterator<char>(file),{}});assert(data && (*data)["future_option"].toBool());}
    {std::ofstream file(path);file<<"broken JSON";}
    Preferences broken(path);assert(!broken.error().empty());assert(!broken.setOrder({"snap"},error));
    {std::ifstream file(path);std::string bytes{std::istreambuf_iterator<char>(file),{}};assert(bytes=="broken JSON");}
    assert(broken.reset(error));assert(Preferences(path).sourceOrder()==Preferences::formats());
    {std::ofstream file(path);file<<R"({"version":2})";}
    Preferences newer(path);assert(!newer.setRememberChoices(false,error));
    auto blocker=folder/"not-a-directory";{std::ofstream file(blocker);file<<"fixture";}
    Preferences unwritable(blocker/"preferences.json");assert(!unwritable.reset(error));assert(unwritable.sourceOrder()==Preferences::formats());
}
int main(int argc,char** argv){
    isolatePreferences("native_settings");
    auto folder=std::filesystem::absolute("work/settings-fixture");std::filesystem::create_directories(folder);policyChecks(folder);
    auto backend=(std::filesystem::path(__FILE__).parent_path()/"search_fixture.py").string();setenv("CUTEFISH_APP_CENTER_BACKEND",backend.c_str(),1);
    setenv("APP_CENTER_SEARCH_FIXTURE_DIR",folder.c_str(),1);setenv("APP_CENTER_SETTINGS_FIXTURE","1",1);
    ui::Application app(argc,argv,ui::Application::Platform::Headless);
    auto center=std::make_unique<AppCenter>(app,false);center->show();
    auto search=[&]{auto& w=center->window();auto* field=find<ui::SearchField>(w.contentView(),[](auto*){return true;});field->setText("example");field->onAccepted();};
    auto choices=[&]{return find<ui::ComboBox>(center->window().contentView(),[](auto* combo){return combo->items().size()==5 && combo->items()[0].starts_with("Debian");});};
    auto button=[&](const std::string& tip){return find<ui::Button>(center->window().contentView(),[&](auto* b){return b->toolTip()==tip;});};
    auto restart=[&]{center.reset();center=std::make_unique<AppCenter>(app,false);center->show();search();};
    base::Timer poll(&app.loop());int stage=0,ticks=0;
    poll.onTimeout=[&]{
        if(++ticks>300){std::cerr<<"Settings test timeout at stage "<<stage<<"\n";app.quit(1);return;}
        auto& w=center->window();w.grab();auto* root=w.contentView();
        auto ready=[&](const std::string& publisher){return text(root,publisher) && !text(root,"Loading app details…");};
        if(stage==0){
            ui::TestInput::setKeyboardFocus(w,true);ui::TestInput::typeKey(w,',',ui::ControlModifier);
            assert(text(root,"Preferred application formats"));click(w,button("Move Snap up"));stage=1;
        }
        else if(stage==1 && Preferences().sourceOrder()[1]=="snap"){click(w,button("Move Snap up"));stage=2;}
        else if(stage==2 && Preferences().sourceOrder()[0]=="snap"){
            assert(w.grab().savePng("work/settings-fixture/settings-light.png"));ui::Theme::setCurrent(ui::Theme::dark());
            assert(w.grab().savePng("work/settings-fixture/settings-dark.png"));click(w,text(root,"Catalog"));search();stage=3;
        }else if(stage==3 && ready("snap Publisher")){
            assert(choices()->currentIndex()==3);choices()->setCurrentIndex(2);choices()->onActivated(2);stage=4;
        }else if(stage==4 && ready("flatpak Publisher")){
            assert(choices()->currentIndex()==2);assert(Preferences().choices().size()==1);restart();stage=5;
        }else if(stage==5 && ready("flatpak Publisher")){
            assert(choices()->currentIndex()==2);click(w,text(root,"Use Default Source"));stage=6;
        }else if(stage==6 && ready("snap Publisher")){
            assert(Preferences().choices().empty());click(w,text(root,"Settings"));
            auto* toggle=find<ui::Switch>(root,[](auto*){return true;});assert(toggle && toggle->isChecked());click(w,toggle);stage=7;
        }else if(stage==7 && !Preferences().rememberChoices()){
            click(w,text(root,"Catalog"));search();stage=8;
        }else if(stage==8 && ready("snap Publisher")){
            choices()->setCurrentIndex(2);choices()->onActivated(2);stage=9;
        }else if(stage==9 && ready("flatpak Publisher")){
            assert(Preferences().choices().empty());restart();stage=10;
        }else if(stage==10 && ready("snap Publisher")){
            click(w,text(root,"Settings"));click(w,text(root,"Restore Defaults"));stage=11;
        }else if(stage==11 && Preferences().sourceOrder()[0]=="deb"){
            assert(Preferences().rememberChoices());click(w,text(root,"Catalog"));search();stage=12;
        }else if(stage==12 && ready("deb Publisher")){
            std::cout<<"Settings order, exact saved choices across restart, installed-source precedence, fallback, clearing, opt-out, defaults, theme rendering and file failure checks passed.\n";app.quit();
        }
    };
    poll.start(100ms);return app.run();
}
