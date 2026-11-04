#define main cutefish_app_center_program_main
#include "../src/main.cpp"
#undef main
#include <cassert>
#include <ui/test_input.h>

template<class T> static T* findView(ui::View* root,std::function<bool(T*)> match){
    if(auto* view=dynamic_cast<T*>(root);view && match(view))return view;
    for(auto& child:root->children())if(auto* found=findView<T>(child.get(),match))return found;
    return nullptr;
}
static ui::Label* text(ui::View* root,const std::string& value){return findView<ui::Label>(root,[&](auto* label){return label->text()==value;});}
static void click(ui::Window& window,ui::View* view){assert(view);window.grab();ui::TestInput::click(window,view->mapToWindow({view->geometry().width/2,view->geometry().height/2}));}
static bool loaded(AppRow* row){return row && findView<ui::IconImage>(row,[](auto* image){return std::filesystem::path(image->name()).is_absolute();});}
int main(int argc,char** argv){
    const std::string mode=argc>1?argv[1]:"";const bool live=mode=="--snap" || mode=="--appimage";
    auto fixture=std::filesystem::absolute("work/icons-fixture");std::filesystem::create_directories(fixture);std::filesystem::create_directories("outputs");
    if(!live){
        auto provider=(std::filesystem::path(__FILE__).parent_path()/"icons_fixture.py").string();setenv("CUTEFISH_APP_CENTER_BACKEND",provider.c_str(),1);
        setenv("APP_CENTER_ICONS_FIXTURE_DIR",fixture.c_str(),1);std::filesystem::remove(fixture/"requests.jsonl");
    }
    ui::Application app(argc,argv,ui::Application::Platform::Headless);AppCenter center(app,false);center.show();auto& window=center.window();window.grab();
    auto search=[&](const std::string& query){auto* field=findView<ui::SearchField>(window.contentView(),[](auto*){return true;});assert(field);field->setText(query);field->onAccepted();};
    if(live){auto* source=findView<ui::ComboBox>(window.contentView(),[](auto* c){return c->items().size()==5;});assert(source);source->setCurrentIndex(mode=="--snap"?3:4);}
    search(live?(mode=="--snap"?"firefox":"obsidian"):"old");
    base::Timer poll(&app.loop());int stage=0,ticks=0;ui::ScrollView* list=nullptr;
    poll.onTimeout=[&]{
        if(++ticks>350){std::cerr<<"Timed out at icon stage "<<stage<<"\n";app.quit(1);return;}
        window.grab();auto* root=window.contentView();
        if(live){
            auto* row=findView<AppRow>(root,[](auto* r){return loaded(r);});
            if(row && ticks>=80 && !text(root,"Loading app details…")){assert(window.grab().savePng(mode=="--snap"?"outputs/app-center-snap-icons.png":"outputs/app-center-appimage-icons.png"));std::cout<<"Live "<<mode<<" catalog list icon rendered.\n";app.quit();}return;
        }
        if(stage==0 && std::filesystem::exists(fixture/"requests.jsonl") && text(root,"old App 0")){
            // Navigate while the icon subprocess is deliberately stalled.
            click(window,text(root,"About"));assert(text(root,"Created by"));stage=1;
        }else if(stage==1){
            click(window,text(root,"Discover"));search("new");stage=2;
        }else if(stage==2 && text(root,"new App 0")){
            auto* first=findView<AppRow>(root,[](auto* r){return text(r,"new App 0");});if(!loaded(first))return;
            assert(!text(root,"old App 0"));
            std::ifstream input(fixture/"requests.jsonl");std::string line;while(std::getline(input,line)){auto keys=J::parse(line);assert(keys && keys->size()<=12);}
            auto* offscreen=findView<AppRow>(root,[](auto* r){return text(r,"new App 30");});assert(offscreen && !loaded(offscreen));
            for(auto* parent=offscreen->parent();parent;parent=parent->parent())if((list=dynamic_cast<ui::ScrollView*>(parent)))break;
            assert(list);auto point=offscreen->mapToWindow({0,0}),origin=list->contentView()->mapToWindow({0,0});
            list->ensureVisible({point.x-origin.x,point.y-origin.y,offscreen->geometry().width,offscreen->geometry().height});stage=3;
        }else if(stage==3){
            auto* offscreen=findView<AppRow>(root,[](auto* r){return text(r,"new App 30");});if(!loaded(offscreen))return;
            assert(window.grab().savePng("work/icons-fixture/lazy-icons.png"));
            std::cout<<"Delayed list artwork, navigation cancellation, batch limits and loading on scroll passed.\n";app.quit();
        }
    };
    poll.start(100ms);return app.run();
}
