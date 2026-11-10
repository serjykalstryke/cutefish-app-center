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
    assert(view);window.grab();for(auto* parent=view->parent();parent;parent=parent->parent())if(auto* scroll=dynamic_cast<ui::ScrollView*>(parent)){
        auto point=view->mapToWindow({0,0}),origin=scroll->contentView()->mapToWindow({0,0});scroll->ensureVisible({point.x-origin.x,point.y-origin.y,view->geometry().width,view->geometry().height});
    }
    window.grab();ui::TestInput::click(window,view->mapToWindow({view->geometry().width/2,view->geometry().height/2}));
}
int main(int argc,char** argv){
    isolatePreferences("native_releases");auto folder=std::filesystem::absolute("work/releases-fixture");std::filesystem::create_directories(folder);std::filesystem::remove(folder/"debian-plan.json");
    auto backend=(std::filesystem::path(__FILE__).parent_path()/"releases_fixture.py").string();setenv("CUTEFISH_APP_CENTER_BACKEND",backend.c_str(),1);setenv("APP_CENTER_RELEASES_FIXTURE_DIR",folder.c_str(),1);
    ui::Application app(argc,argv,ui::Application::Platform::Headless);auto center=std::make_unique<AppCenter>(app,false);center->show();
    auto settings=[&]{click(center->window(),text(center->window().contentView(),"Settings"));auto* sections=find<ui::SegmentedControl>(center->window().contentView(),[](auto*){return true;});sections->setCurrentIndex(1);sections->onCurrentChanged(1);};
    auto combo=[&](const std::string& tip){return find<ui::ComboBox>(center->window().contentView(),[&](auto* v){return v->toolTip()==tip;});};
    auto search=[&]{click(center->window(),text(center->window().contentView(),"Catalog"));auto* field=find<ui::SearchField>(center->window().contentView(),[](auto*){return true;});field->setText("example");field->onAccepted();};
    base::Timer poll(&app.loop());int stage=0,ticks=0;
    poll.onTimeout=[&]{
        if(++ticks>300){std::cerr<<"Release UI timeout at stage "<<stage<<"\n";app.quit(1);return;}auto& w=center->window();w.grab();auto* root=w.contentView();
        if(stage==0){settings();stage=1;}
        else if(stage==1 && text(root,"https://dl.flathub.org/repo/")){
            assert(!text(root,"https://dl.flathub.org/beta-repo/"));auto* release=combo("Flatpak catalog release");assert(release && release->currentIndex()==0);release->setCurrentIndex(1);release->onActivated(1);stage=2;
        }else if(stage==2 && text(root,"https://dl.flathub.org/beta-repo/")){
            assert(!text(root,"https://dl.flathub.org/repo/"));assert(Preferences().catalogRelease("flatpak")=="beta");auto* snap=combo("Snap catalog release");snap->setCurrentIndex(1);snap->onActivated(1);stage=3;
        }else if(stage==3 && Preferences().catalogRelease("snap")=="beta"){
            assert(w.grab().savePng("work/releases-fixture/releases-light.png"));ui::Theme::setCurrent(ui::Theme::dark());assert(w.grab().savePng("work/releases-fixture/releases-dark.png"));
            auto* release=combo("Debian operating-system release");assert(release && release->currentIndex()==0);release->setCurrentIndex(2);release->onActivated(2);assert(release->currentIndex()==0);stage=4;
        }else if(stage==4){
            for(auto* dialog:app.windows())if(dialog!=&w && text(dialog->contentView(),"Switch Debian Sources")){
                assert(text(dialog->contentView(),"Use Debian Testing"));assert(text(dialog->contentView(),"/etc/apt/sources.list.d/debian.sources"));click(*dialog,text(dialog->contentView(),"Cancel"));stage=5;break;
            }
        }else if(stage==5){search();stage=6;}
        else if(stage==6 && text(root,"Fixture Publisher")){
            assert(text(root,"Selected beta release"));auto* variants=find<ui::ComboBox>(root,[](auto* v){return v->items().size()==2 && v->items()[0].starts_with("Flatpak");});assert(variants);assert(variants->items()[0].find("beta")!=std::string::npos);assert(variants->items()[1].find("beta")!=std::string::npos);
            center.reset();center=std::make_unique<AppCenter>(app,false);center->show();search();stage=7;
        }else if(stage==7 && text(root,"Fixture Publisher")){
            assert(text(root,"Selected beta release"));assert(Preferences().catalogRelease("snap")=="beta");settings();stage=8;
        }else if(stage==8 && text(root,"https://dl.flathub.org/beta-repo/")){
            auto* release=combo("Flatpak catalog release");release->setCurrentIndex(0);release->onActivated(0);stage=9;
        }else if(stage==9 && text(root,"https://dl.flathub.org/repo/")){
            auto* snap=combo("Snap catalog release");snap->setCurrentIndex(0);snap->onActivated(0);stage=10;
        }else if(stage==10 && Preferences().catalogRelease("snap")=="stable"){search();stage=11;}
        else if(stage==11 && text(root,"Fixture Publisher")){
            assert(text(root,"Selected stable release"));std::cout<<"Stable/beta controls, collapsed Flathub rows, persisted catalog choices, exclusive search variants and canceled Debian release review passed.\n";app.quit();
        }
    };poll.start(100ms);return app.run();
}
